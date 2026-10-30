"""Physical racks, and the per-bin picture an LED node paints on one.

This used to live in a Home Assistant package as Jinja templates fed by a REST
sensor that read the integration's own inventory endpoint back over HTTP. That
needed a long-lived, full-account access token and a loopback request for data
the coordinator already held in memory. Computing it here during the parse
removes both, and puts the third copy of the drinking-window rule beside the
first one, where test_rack_leds_example.py can hold them together.

A rack is described in the options flow, one per line:

    Wine Rack 1: 13x13 without A5-H9
    Wine Rack 2: 7x7

The name before the colon is the CellarTracker ``Location`` the rack's bottles
are filed under; ``Bin`` is the slot inside it. ``ROWSxCOLS`` is the envelope
the node's grid covers, and ``without`` lists bins - or rectangles of bins -
the rack does not physically have. Those stay in the grid as empty, so its
length always matches the node's buffer, but a bottle filed at one is counted
as off the rack instead of being silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# One character per bin, indexed by rank. The nodes switch on the same
# letters, so adding a state here without adding it there paints an occupied
# bin as empty.
STATES = ".NARUP"
EMPTY, NO_WINDOW, AGING, READY, THIS_YEAR, PAST = range(len(STATES))

# Home Assistant truncates a state longer than 255 characters.
MAX_CELLS = 255
ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

_RACK_LINE = re.compile(
    r"^(?P<location>.+?)\s*:\s*(?P<rows>\d+)\s*[x×]\s*(?P<cols>\d+)"
    r"(?:\s+without\s+(?P<without>.+))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Rack:
    """One physical rack: where its bottles are filed and the shape it has."""

    location: str
    rows: int
    cols: int
    # (row, col), both from 0. Inside the envelope but not a real bin.
    missing: frozenset[tuple[int, int]] = frozenset()

    @property
    def cells(self) -> int:
        return self.rows * self.cols

    def has(self, cell: tuple[int, int]) -> bool:
        row, col = cell
        return 0 <= row < self.rows and 0 <= col < self.cols and cell not in self.missing


# A row letter, then digits, with spaces, tabs, dashes and underscores allowed
# anywhere after the letter. The same grammar as parse_bin_id on the boards, so
# a bin the grid paints is a bin the locator can light, and the other way round.
_BIN = re.compile(r"([A-Z])[\s\-_]*((?:[0-9][\s\-_]*)+)")


def parse_bin(value: object) -> tuple[int, int] | None:
    """Read a bin the way people write them: "D2", "d2", "D-2", "D 2", "D02".

    Anything else is None - "A1B" and "12A" too - so a typo goes dark rather
    than lighting the wrong bottle.
    """
    match = _BIN.fullmatch(str(value or "").strip().upper())
    if match is None:
        return None
    digits = re.sub(r"[\s\-_]", "", match.group(2))
    # The boards stop at 999; past that it is not a bin.
    col = int(digits)
    if not 1 <= col <= 999:
        return None
    return ROW_LETTERS.find(match.group(1)), col - 1


def _parse_without(text: str, rows: int, cols: int) -> frozenset[tuple[int, int]]:
    missing: set[tuple[int, int]] = set()
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        # Split only on a dash followed by a row letter, so "D-2" is still one bin.
        ends = re.split(r"\s*-\s*(?=[A-Za-z])", part)
        if len(ends) > 2:
            raise ValueError(f"'{part}' is not a bin or a range of bins like A5-H9")
        corners = [corner for corner in map(parse_bin, ends) if corner is not None]
        if len(corners) != len(ends):
            raise ValueError(f"'{part}' is not a bin or a range of bins like A5-H9")
        (r1, c1), (r2, c2) = corners[0], corners[-1]
        if not (r1 < rows and r2 < rows and c1 < cols and c2 < cols):
            raise ValueError(f"'{part}' is outside a {rows}x{cols} rack")
        for row in range(min(r1, r2), max(r1, r2) + 1):
            for col in range(min(c1, c2), max(c1, c2) + 1):
                missing.add((row, col))
    return frozenset(missing)


def parse_racks(text: str | None) -> list[Rack]:
    """Read the options field into racks.

    Raises:
        ValueError: with a message naming the line that is wrong, for the
            options form to show.
    """
    racks: list[Rack] = []
    seen: set[str] = set()
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _RACK_LINE.match(line)
        if match is None:
            raise ValueError(
                f"Line {number}: write it as 'Location: ROWSxCOLUMNS', "
                "for example 'Wine Rack 2: 7x7'"
            )
        location = match["location"].strip()
        rows, cols = int(match["rows"]), int(match["cols"])
        if not 1 <= rows <= len(ROW_LETTERS) or cols < 1:
            raise ValueError(f"Line {number}: a rack has 1 to 26 rows and at least one column")
        if rows * cols > MAX_CELLS:
            raise ValueError(
                f"Line {number}: {rows}x{cols} is {rows * cols} bins, and a "
                f"sensor state holds at most {MAX_CELLS}"
            )
        if location_key(location) in seen:
            raise ValueError(f"Line {number}: '{location}' is listed twice")
        seen.add(location_key(location))
        try:
            missing = _parse_without(match["without"] or "", rows, cols)
        except ValueError as err:
            raise ValueError(f"Line {number}: {err}") from None
        racks.append(Rack(location, rows, cols, missing))
    return racks


def format_racks(racks: list[Rack]) -> str:
    """The inverse of parse_racks, bins listed one by one.

    Only used by tests and diagnostics; the options form keeps what the user
    typed, ranges and all.
    """
    lines = []
    for rack in racks:
        line = f"{rack.location}: {rack.rows}x{rack.cols}"
        if rack.missing:
            bins = ", ".join(f"{ROW_LETTERS[r]}{c + 1}" for r, c in sorted(rack.missing))
            line += f" without {bins}"
        lines.append(line)
    return "\n".join(lines)


def _year(value: object) -> int:
    """A BeginConsume/EndConsume cell as a year, 0 when there is none.

    Matches the template this replaced, and cellar.html: ``int(0)`` on
    anything that is not a whole number.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def bottle_rank(bottle: dict[str, Any], year: int) -> int:
    """How urgently a bottle wants dealing with, as an index into STATES.

    The dashboard's rule, in the dashboard's order: an inverted window (from
    2030, by 2020) reads as over rather than as still laying down, and the
    final year of a window is urgent rather than past, because it is still
    inside the window.
    """
    begin = _year(bottle.get("BeginConsume"))
    end = _year(bottle.get("EndConsume"))
    if begin < 1 and end < 1:
        return NO_WINDOW
    if 0 < end < year:
        return PAST
    if begin > 0 and begin > year:
        return AGING
    if end == year:
        return THIS_YEAR
    return READY


def location_key(value: object) -> str:
    """A location as compared: "wine rack 2" and "Wine  Rack 2 " are one rack.

    The rack line is typed by hand in the options form while the bottles'
    Location comes from CellarTracker, so case and spacing are allowed to
    differ. Anything more and the rack names a different place.
    """
    return " ".join(str(value or "").split()).casefold()


def _at(bottle: dict[str, Any], rack: Rack) -> bool:
    return location_key(bottle.get("Location")) == location_key(rack.location)


def rack_grid(bottles: list[dict[str, Any]], rack: Rack, year: int) -> str:
    """One state character per bin of the envelope, row-major.

    A bin holds several bottles and shows the one that most wants dealing
    with: past, then drink-this-year, then ready, then aging, then a bottle
    with no window at all. A bin the rack does not have never lights.
    """
    cells = [EMPTY] * rack.cells
    for bottle in bottles:
        if not _at(bottle, rack):
            continue
        cell = parse_bin(bottle.get("Bin"))
        if cell is None or not rack.has(cell):
            continue
        index = cell[0] * rack.cols + cell[1]
        cells[index] = max(cells[index], bottle_rank(bottle, year))
    return "".join(STATES[rank] for rank in cells)


def off_rack_bottles(bottles: list[dict[str, Any]], rack: Rack) -> list[dict[str, Any]]:
    """Bottles filed at this rack that no bin will ever light.

    A bin outside the envelope, one the rack does not have - easy after a
    rebuild - or no readable bin at all. They are not lost, but nothing on
    the rack will show them, so they are counted rather than swallowed.
    """
    off = []
    for bottle in bottles:
        if not _at(bottle, rack):
            continue
        cell = parse_bin(bottle.get("Bin"))
        if cell is None or not rack.has(cell):
            off.append(bottle)
    return off


def bottles_off_rack(bottles: list[dict[str, Any]], rack: Rack) -> int:
    """How many of off_rack_bottles there are."""
    return len(off_rack_bottles(bottles, rack))
