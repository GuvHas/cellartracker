"""P2-5: counters for what is drinkable now and what is past its window.

These are pure derivations of data already in memory, so they cost nothing at
poll time and add no entity per bottle - the property that keeps this
integration cheap at cellar scale.

The fields are confirmed rather than assumed: cellar.html already reads
``BeginConsume`` and ``EndConsume``, and it reads them with ``parseInt``
compared against the current year, so they are *years* and a blank parses to 0
meaning "no window given". This mirrors that exactly.

One deliberate divergence from the dashboard's colouring. It paints
``EndConsume > currentYear`` green and everything else red, so a wine to be
drunk by 2026 shows red during 2026. That reads as urgency, not expiry: the
last year of a window is still inside it. "Past its window" here means strictly
before the current year, and such a wine counts as ready.

Bottles with no window at all are counted in neither. The export simply does
not say, and inventing an answer would be worse than reporting none.
"""

from __future__ import annotations

import asyncio

import pytest

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass, FakeSession

YEAR = 2026
HEADER = "iWine\tWine\tValuation\tBeginConsume\tEndConsume"


def export(*windows: tuple[str, str]) -> str:
    rows = [
        f"{i}\tWine {i}\t10.00\t{begin}\t{end}"
        for i, (begin, end) in enumerate(windows, start=1)
    ]
    return "\n".join([HEADER, *rows])


def counts(*windows: tuple[str, str], year: int = YEAR) -> tuple[int, int]:
    hass = FakeHass()
    hass.session = FakeSession(text=export(*windows))
    coordinator = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))
    coordinator._current_year = lambda: year
    data = asyncio.run(coordinator._async_update_data())
    return data["ready_to_drink"], data["past_drink_window"]


# --------------------------------------------------------------------------
# Inside, before and after the window
# --------------------------------------------------------------------------
def test_a_wine_inside_its_window_is_ready():
    assert counts(("2020", "2030")) == (1, 0)


def test_a_wine_not_yet_open_is_neither():
    """Laid down for 2030: not ready, and certainly not past."""
    assert counts(("2030", "2040")) == (0, 0)


def test_a_wine_past_its_window_is_counted_as_past():
    assert counts(("2010", "2020")) == (0, 1)


def test_the_first_year_of_the_window_counts_as_ready():
    assert counts((str(YEAR), "2030")) == (1, 0)


def test_the_last_year_of_the_window_counts_as_ready():
    """Urgent, not expired - this is where we diverge from the dashboard's red."""
    assert counts(("2010", str(YEAR))) == (1, 0)


def test_the_year_after_the_window_is_past():
    assert counts(("2010", str(YEAR - 1))) == (0, 1)


# --------------------------------------------------------------------------
# Half-known and unknown windows
# --------------------------------------------------------------------------
def test_an_open_ended_window_that_has_started_is_ready():
    assert counts(("2020", "")) == (1, 0)


def test_an_open_ended_window_that_has_not_started_is_neither():
    assert counts(("2030", "")) == (0, 0)


def test_a_drink_by_date_with_no_start_is_ready_until_it_passes():
    assert counts(("", "2030")) == (1, 0)


def test_a_drink_by_date_in_the_past_is_past_even_with_no_start():
    assert counts(("", "2020")) == (0, 1)


@pytest.mark.parametrize("begin,end", [("", ""), ("0", "0"), ("   ", "   ")])
def test_a_wine_with_no_window_is_counted_in_neither(begin, end):
    """The export does not say; neither do we."""
    assert counts((begin, end)) == (0, 0)


@pytest.mark.parametrize("value", ["N/A", "soon", "2016-2020", "20.16"])
def test_an_unparseable_year_is_treated_as_absent(value):
    assert counts((value, value)) == (0, 0)


# --------------------------------------------------------------------------
# Together
# --------------------------------------------------------------------------
def test_a_mixed_cellar_is_counted_correctly():
    ready, past = counts(
        ("2020", "2030"),   # ready
        ("2010", "2020"),   # past
        ("2030", "2040"),   # too early
        ("", ""),           # unknown
        ("2015", str(YEAR)),  # last year of its window: ready
    )
    assert (ready, past) == (2, 1)


def test_an_empty_cellar_counts_zero():
    hass = FakeHass()
    hass.session = FakeSession(text=HEADER + "\n1\tWine\t10.00\t2020\t2030")
    coordinator = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))
    data = asyncio.run(coordinator._async_update_data())
    assert data["ready_to_drink"] == 1

    # An export with no rows at all short-circuits before any counting.
    hass.session = FakeSession(text=HEADER)
    coordinator.data = None
    empty = asyncio.run(coordinator._async_update_data())
    assert empty["ready_to_drink"] == 0
    assert empty["past_drink_window"] == 0


def test_an_export_without_the_columns_counts_zero_rather_than_failing():
    """Not every CellarTracker export is guaranteed to carry them."""
    hass = FakeHass()
    hass.session = FakeSession(text="iWine\tWine\tValuation\n1\tBarolo\t45.50")
    coordinator = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))
    data = asyncio.run(coordinator._async_update_data())

    assert data["total_bottles"] == 1
    assert data["ready_to_drink"] == 0
    assert data["past_drink_window"] == 0
