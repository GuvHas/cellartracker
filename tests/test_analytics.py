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
# Peak: the middle third of the window
#
#   BeginConsume + span/3 <= year <= EndConsume - span/3,   span = End - Begin
#
# Worked in integers as 2*begin + end <= 3*year <= begin + 2*end, so a span that
# is not divisible by three cannot pick up a float rounding surprise.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("begin", "end", "year", "expected"),
    [
        # Thirds land on whole years: 2020-2029 has span 9, peak 2023..2026.
        (2020, 2029, 2022, False),  # first third
        (2020, 2029, 2023, True),  # first year of the middle third, exactly
        (2020, 2029, 2026, True),  # last year of the middle third, exactly
        (2020, 2029, 2027, False),  # last third
        # Thirds fall between years: 2020-2030 has span 10, peak 2023.33..2026.67.
        (2020, 2030, 2023, False),
        (2020, 2030, 2024, True),
        (2020, 2030, 2026, True),
        (2020, 2030, 2027, False),
        # A longer window.
        (2020, 2040, 2026, False),  # ready, but still in its first third
        (2020, 2040, 2030, True),
        (2020, 2040, 2035, False),  # ready, but into its last third
    ],
)
def test_is_peak_is_the_middle_third(begin, end, year, expected):
    assert is_peak(bottle(begin, end), year) is expected


@pytest.mark.parametrize(
    ("begin", "end", "expected"),
    [
        (2018, 2032, True),  # span 14: peak 2022.67..2027.33, 2026 inside
        (2020, 2040, False),  # begun, but not yet into the middle third
        (2026, 2040, False),  # begins this year: the very start of the window
        (2010, 2028, False),  # 2010..2028 peak 2016..2022; long past it
        (2027, 2040, False),  # not begun
        (2010, 2020, False),  # ended
        (2026, 2026, True),  # a one-year window is all peak, in that year
        (2040, 2020, False),  # inverted: no year can satisfy it
        (2020, "", False),  # no end: thirds cannot be computed
        ("", 2040, False),  # no begin
        ("", "", False),
    ],
)
def test_is_peak(begin, end, expected):
    assert is_peak(bottle(begin, end), YEAR) is expected


def test_peak_is_not_the_first_half_any_more():
    """The original definition ran from the start to the midpoint; guard the change.

    2020-2040 at 2021 was peak under the first-half rule and is not now.
    """
    b = bottle(2020, 2040)
    assert drink_status(b, 2021) == "ready"
    assert is_peak(b, 2021) is False


def test_peak_is_neither_the_start_nor_the_end_of_a_window():
    """A wine's first and last years are both ready and both not peak."""
    b = bottle(2020, 2030)
    assert is_peak(b, 2020) is False
    assert is_peak(b, 2030) is False
    assert drink_status(b, 2020) == "ready"
    assert drink_status(b, 2030) == "ready"


def test_peak_is_symmetric_about_the_middle_of_the_window():
    """Equal thirds either side: reflecting the year reflects the answer."""
    for begin, end in [(2020, 2029), (2020, 2030), (2018, 2041), (2000, 2050)]:
        b = bottle(begin, end)
        for year in range(begin - 1, end + 2):
            mirrored = begin + end - year
            assert is_peak(b, year) == is_peak(b, mirrored), (begin, end, year)


def test_peak_never_falls_outside_ready():
    """Peak is a refinement of ready for every window and every year."""
    for begin in range(2015, 2030):
        for end in range(begin, begin + 15):
            b = bottle(begin, end)
            for year in range(begin - 2, end + 3):
                if is_peak(b, year):
                    assert drink_status(b, year) == "ready", (begin, end, year)


# --------------------------------------------------------------------------
# Aggregate breakdown
# --------------------------------------------------------------------------
def test_breakdown_counts_every_category():
    bottles = [
        bottle(2018, 2032),  # ready + peak (middle third is 2022.67..2027.33)
        bottle(2020, 2040),  # ready, but still in its first third
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


# --------------------------------------------------------------------------
# A blank location means "no filter", not "unplaced bottles only"
#
# Reported by Codex on #23. `location: ""` - which an automation produces from an
# empty template - became the filter "", matching only bottles with no location
# and skipping every bin in a named one. The action's own description says to
# leave it empty to search every location.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("blank", ["", "   ", "\t", None])
def test_a_blank_location_searches_every_location(blank):
    found = find_bottles(BOTTLES, index_by_location_bin(BOTTLES), bin_name="A1", location=blank)
    assert [b["iWine"] for b in found] == ["1", "2", "4"]


def test_a_blank_location_is_not_the_same_as_unplaced_only():
    unplaced_with_a_bin = [*BOTTLES, {"iWine": "9", "Location": "", "Bin": "A1"}]
    index = index_by_location_bin(unplaced_with_a_bin)
    found = find_bottles(unplaced_with_a_bin, index, bin_name="A1", location="")
    assert [b["iWine"] for b in found] == ["1", "2", "4", "9"]
