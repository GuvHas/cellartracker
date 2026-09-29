"""Drink-window analytics and the Location/Bin index.

Everything here is derived data carried in the coordinator's payload. None of it
becomes an entity: the integration deliberately exposes five aggregate sensors
and serves per-bottle detail over HTTP, because an entity per bottle is what
bloats the recorder.

``ready`` and ``past`` are not redefined here. They are the rules the sensors
and the dashboard already agree on (see test_dashboard_agrees_with_sensors), so
this module reuses them rather than restating them and inviting drift.
"""

from __future__ import annotations

import pytest

from cellar_tracker.analytics import (
    consume_year,
    drink_status,
    drink_window_breakdown,
    find_bottles,
    index_by_location_bin,
    is_peak,
)

YEAR = 2026


def bottle(begin: object = "", end: object = "", **extra: object) -> dict:
    return {"iWine": "1", "BeginConsume": begin, "EndConsume": end, **extra}


# --------------------------------------------------------------------------
# Reading a year
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2030", 2030),
        (" 2030 ", 2030),
        (2030, 2030),
        ("", None),
        (None, None),
        ("0", None),
        ("-4", None),
        ("soon", None),
        ("20.5", None),
    ],
)
def test_consume_year(raw, expected):
    assert consume_year(raw) == expected


# --------------------------------------------------------------------------
# Per-bottle status
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("begin", "end", "expected"),
    [
        (2020, 2030, "ready"),
        (2026, 2030, "ready"),  # first year of the window
        (2020, 2026, "ready"),  # last year: still inside, not past
        (2027, 2035, "aging"),
        (2010, 2025, "past"),
        ("", "", "unknown"),
        (2020, "", "ready"),  # open-ended window
        ("", 2030, "ready"),
        ("", 2020, "past"),
        (2030, "", "aging"),
    ],
)
def test_drink_status(begin, end, expected):
    assert drink_status(bottle(begin, end), YEAR) == expected


# --------------------------------------------------------------------------
# Peak: BeginConsume <= year <= (BeginConsume + EndConsume) / 2
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("begin", "end", "expected"),
    [
        (2020, 2040, True),  # midpoint 2030; 2026 inside [2020, 2030]
        (2026, 2040, True),  # begins this year
        (2020, 2030, False),  # midpoint 2025 < 2026
        (2027, 2040, False),  # not begun
        (2010, 2020, False),  # ended
        (2020, "", False),  # no end: a midpoint cannot be computed
        ("", 2040, False),  # no begin
        ("", "", False),
    ],
)
def test_is_peak(begin, end, expected):
    assert is_peak(bottle(begin, end), YEAR) is expected


def test_peak_uses_the_midpoint_not_the_end():
    """Guards the formula against being 'simplified' into ready."""
    b = bottle(2020, 2040)
    assert drink_status(b, 2035) == "ready"
    assert is_peak(b, 2035) is False


# --------------------------------------------------------------------------
# Aggregate breakdown
# --------------------------------------------------------------------------
def test_breakdown_counts_every_category():
    bottles = [
        bottle(2020, 2040),  # ready + peak
        bottle(2020, 2030),  # ready, not peak (midpoint 2025)
        bottle(2027, 2035),  # needs aging
        bottle(2010, 2025),  # past
        bottle("", ""),  # no window: counted nowhere
    ]
    result = drink_window_breakdown(bottles, YEAR)
    assert result == {
        "ready_to_drink": 2,
        "past_drink_window": 1,
        "needs_aging": 1,
        "peak_drinking": 1,
    }


def test_peak_is_a_subset_of_ready():
    bottles = [bottle(2020, 2040), bottle(2026, 2028), bottle(2020, 2030)]
    result = drink_window_breakdown(bottles, YEAR)
    assert result["peak_drinking"] <= result["ready_to_drink"]


def test_categories_partition_bottles_with_a_window():
    bottles = [bottle(2020, 2040), bottle(2027, 2035), bottle(2010, 2025), bottle(2020, "")]
    r = drink_window_breakdown(bottles, YEAR)
    assert r["ready_to_drink"] + r["past_drink_window"] + r["needs_aging"] == len(bottles)


def test_an_empty_cellar_breaks_down_to_zeros():
    assert drink_window_breakdown([], YEAR) == {
        "ready_to_drink": 0,
        "past_drink_window": 0,
        "needs_aging": 0,
        "peak_drinking": 0,
    }


def test_the_year_changes_the_answer():
    bottles = [bottle(2027, 2035)]
    assert drink_window_breakdown(bottles, 2026)["needs_aging"] == 1
    assert drink_window_breakdown(bottles, 2028)["ready_to_drink"] == 1


# --------------------------------------------------------------------------
# Location / Bin index
# --------------------------------------------------------------------------
BOTTLES = [
    {"iWine": "1", "Location": "Cellar", "Bin": "A1"},
    {"iWine": "2", "Location": "Cellar", "Bin": "A1"},
    {"iWine": "3", "Location": "Cellar", "Bin": "B2"},
    {"iWine": "4", "Location": "Fridge", "Bin": "A1"},
    {"iWine": "5", "Location": "", "Bin": ""},
]


def test_index_groups_by_location_then_bin():
    index = index_by_location_bin(BOTTLES)
    assert index["Cellar"]["A1"] == [0, 1]
    assert index["Cellar"]["B2"] == [2]
    assert index["Fridge"]["A1"] == [3]


def test_the_same_bin_in_two_locations_stays_separate():
    index = index_by_location_bin(BOTTLES)
    assert index["Cellar"]["A1"] != index["Fridge"]["A1"]


def test_unplaced_bottles_are_indexed_under_blank_not_dropped():
    assert index_by_location_bin(BOTTLES)[""][""] == [4]


def test_index_of_nothing_is_empty():
    assert index_by_location_bin([]) == {}


def test_missing_columns_are_treated_as_blank():
    assert index_by_location_bin([{"iWine": "9"}]) == {"": {"": [0]}}


def test_index_values_are_positions_that_resolve_to_the_bottles():
    index = index_by_location_bin(BOTTLES)
    assert [BOTTLES[i]["iWine"] for i in index["Cellar"]["A1"]] == ["1", "2"]


# --------------------------------------------------------------------------
# Lookup
# --------------------------------------------------------------------------
def test_find_by_bin_across_locations():
    found = find_bottles(BOTTLES, index_by_location_bin(BOTTLES), bin_name="A1")
    assert [b["iWine"] for b in found] == ["1", "2", "4"]


def test_find_narrowed_by_location():
    found = find_bottles(BOTTLES, index_by_location_bin(BOTTLES), bin_name="A1", location="Fridge")
    assert [b["iWine"] for b in found] == ["4"]


@pytest.mark.parametrize("query", ["a1", " A1 ", "A1"])
def test_bin_matching_ignores_case_and_padding(query):
    """Bins are typed by hand into CellarTracker; an automation should not care."""
    found = find_bottles(BOTTLES, index_by_location_bin(BOTTLES), bin_name=query)
    assert len(found) == 3


def test_location_matching_ignores_case_and_padding():
    found = find_bottles(
        BOTTLES, index_by_location_bin(BOTTLES), bin_name="A1", location=" fridge "
    )
    assert [b["iWine"] for b in found] == ["4"]


def test_an_unknown_bin_finds_nothing():
    assert find_bottles(BOTTLES, index_by_location_bin(BOTTLES), bin_name="Z9") == []


def test_a_blank_bin_query_does_not_match_unplaced_bottles():
    """Otherwise an automation with an empty template would light every stray bottle."""
    assert find_bottles(BOTTLES, index_by_location_bin(BOTTLES), bin_name="") == []


def test_find_returns_the_bottles_in_cellar_order():
    found = find_bottles(BOTTLES, index_by_location_bin(BOTTLES), bin_name="A1")
    assert found == [BOTTLES[0], BOTTLES[1], BOTTLES[3]]
