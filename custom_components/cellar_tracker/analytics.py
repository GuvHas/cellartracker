"""Drink-window analytics and the Location/Bin index.

Pure functions over the bottle list, with no Home Assistant imports, so they
are cheap to test and safe to run on the executor with the rest of the parse.

Nothing here creates an entity. The integration exposes five aggregate sensors
and serves per-bottle detail over HTTP, because an entity per bottle is what
bloats the recorder. These results ride in the coordinator's payload for the
views, the services and diagnostics to read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

DrinkStatus = Literal["ready", "past", "aging", "unknown"]

# location -> bin -> positions in the bottle list. Positions rather than
# copies: the payload is replaced wholesale on every refresh, so they cannot go
# stale, and the index stays a few bytes per bottle.
LocationIndex = dict[str, dict[str, list[int]]]


class DrinkWindowBreakdown(TypedDict):
    """Bottle counts by where the current year falls in their window."""

    ready_to_drink: int
    past_drink_window: int
    needs_aging: int
    peak_drinking: int


def consume_year(value: object) -> int | None:
    """Read a BeginConsume/EndConsume cell as a year, or None if absent.

    CellarTracker gives these as plain years, and cellar.html already reads
    them that way - ``parseInt`` compared against the current year, with a
    blank collapsing to 0. Anything that is not a whole positive number means
    "no window given" rather than an error: a cellar is full of wines nobody
    has assigned a drinking window to.
    """
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if year > 0 else None


def drink_status(bottle: Mapping[str, Any], year: int) -> DrinkStatus:
    """Where ``year`` falls in a bottle's drinking window.

    A bottle with no window at all is "unknown": the export does not say, and
    guessing would be worse than reporting nothing.

    The last year of a window counts as ready, not past - it is still inside
    the window. The dashboard paints that year red, but that is urgency rather
    than expiry.

    A half-open window counts as far as it goes: a begin with no end is ready
    once it has begun, and an end with no begin is ready until it passes.
    """
    begin = consume_year(bottle.get("BeginConsume"))
    end = consume_year(bottle.get("EndConsume"))

    if end is not None and end < year:
        return "past"
    if begin is None and end is None:
        return "unknown"
    if begin is not None and begin > year:
        return "aging"
    return "ready"


def is_peak(bottle: Mapping[str, Any], year: int) -> bool:
    """True in the middle third of a bottle's drinking window.

    ``BeginConsume + span/3 <= year <= EndConsume - span/3``, where
    ``span = EndConsume - BeginConsume``. The first and last thirds are still
    ready to drink - just not at their best - so a wine's opening and closing
    years are never peak. It needs both ends: with either missing there is no
    span to divide, so an open-ended window is never "peak".

    Worked in integers. Multiplying through by three gives
    ``2*begin + end <= 3*year <= begin + 2*end``, so a span that is not a
    multiple of three cannot pick up a float rounding surprise at a boundary.
    An inverted window (begin after end) satisfies neither side, and a
    one-year window is peak in that year.
    """
    begin = consume_year(bottle.get("BeginConsume"))
    end = consume_year(bottle.get("EndConsume"))
    if begin is None or end is None:
        return False
    return 2 * begin + end <= 3 * year <= begin + 2 * end


def drink_window_breakdown(bottles: Sequence[Mapping[str, Any]], year: int) -> DrinkWindowBreakdown:
    """Count bottles in each drink-window category for ``year``.

    ``ready_to_drink`` and ``past_drink_window`` are the rules the sensors and
    the dashboard already share; ``peak_drinking`` is a subset of
    ``ready_to_drink``. A bottle with no window is counted nowhere.
    """
    ready = past = aging = peak = 0
    for bottle in bottles:
        status = drink_status(bottle, year)
        if status == "ready":
            ready += 1
            if is_peak(bottle, year):
                peak += 1
        elif status == "past":
            past += 1
        elif status == "aging":
            aging += 1
    return {
        "ready_to_drink": ready,
        "past_drink_window": past,
        "needs_aging": aging,
        "peak_drinking": peak,
    }


def drink_window_counts(bottles: Sequence[Mapping[str, Any]], year: int) -> tuple[int, int]:
    """Count bottles drinkable now, and bottles past their window."""
    breakdown = drink_window_breakdown(bottles, year)
    return breakdown["ready_to_drink"], breakdown["past_drink_window"]


class InventoryDelta(TypedDict):
    """What changed between two inventories, as whole bottles."""

    added: list[Mapping[str, Any]]
    removed: list[Mapping[str, Any]]


def inventory_delta(
    previous: Sequence[Mapping[str, Any]], current: Sequence[Mapping[str, Any]]
) -> InventoryDelta | None:
    """The bottles gained and lost between two inventories, or None if the same.

    Compared by ``unique_bottle_id`` alone, so a revaluation or an edited note
    is not a change. That id covers Location and Bin, which makes moving a
    bottle a removal from the old place and an addition to the new one.

    Both lists keep the order of the inventory they came from.
    """
    before = {bottle["unique_bottle_id"] for bottle in previous}
    after = {bottle["unique_bottle_id"] for bottle in current}
    if before == after:
        return None
    return {
        "added": [b for b in current if b["unique_bottle_id"] not in before],
        "removed": [b for b in previous if b["unique_bottle_id"] not in after],
    }


def _cell(bottle: Mapping[str, Any], column: str) -> str:
    return str(bottle.get(column) or "").strip()


def index_by_location_bin(bottles: Sequence[Mapping[str, Any]]) -> LocationIndex:
    """Index bottles by Location, then Bin.

    Bottles with no placement are kept under the blank key rather than dropped,
    so the index accounts for every bottle in the list. The same bin name in two
    locations stays separate: "A1" in the cellar and "A1" in the fridge are
    different places.
    """
    index: LocationIndex = {}
    for position, bottle in enumerate(bottles):
        index.setdefault(_cell(bottle, "Location"), {}).setdefault(_cell(bottle, "Bin"), []).append(
            position
        )
    return index


def find_bottles(
    bottles: Sequence[Mapping[str, Any]],
    index: LocationIndex,
    *,
    bin_name: str,
    location: str | None = None,
) -> list[Mapping[str, Any]]:
    """Bottles in a bin, optionally narrowed to one location.

    Matching ignores case and surrounding whitespace, because bins are typed by
    hand into CellarTracker and an automation should not have to know how.

    A blank ``bin_name`` matches nothing. Matching it would light every
    unplaced bottle for the sake of an empty template.
    """
    wanted_bin = bin_name.strip().casefold()
    if not wanted_bin:
        return []
    wanted_location = None if location is None else location.strip().casefold()

    positions: list[int] = []
    for loc, bins in index.items():
        if wanted_location is not None and loc.casefold() != wanted_location:
            continue
        for bin_key, found in bins.items():
            if bin_key.casefold() == wanted_bin:
                positions.extend(found)

    return [bottles[position] for position in sorted(positions)]
