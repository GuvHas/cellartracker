"""Phase 1 (RED): the dashboard's filtering, search and drink-window logic.

The page shows a 150-bottle cellar on a phone. Everything that decides *which*
bottles a person is looking at - the quick filter chips, the search box, the
sort order - is logic, and until now none of it was tested: the only dashboard
tests covered auth wiring and the ``?entry_id=`` forward.

These tests pin that logic as pure functions, called directly under node. They
are written against a contract the page does not implement yet:

    normaliseWine(raw)              -> numbers coerced, junk collapsed to 0
    drinkWindowState(wine, year)    -> 'ready' | 'past' | 'aging' | 'unknown'
    windowProgress(wine, year)      -> 0..1 within the window, or null
    matchesSearch(wine, term)       -> every whitespace-separated token found
    filterCounts(wines, year)       -> {all, ready, past, aging}
    selectWines(wines, options)     -> filter and search composed
    sortWines(wines, key, dir)      -> a new array, stable on ties

The single most important property is the last section: the chip counts must
agree with what the integration's own sensors report, or the dashboard and the
sensor cards on the same Home Assistant page disagree about the same cellar.
"""

from __future__ import annotations

import pytest
from dashboard_js import check, equals, requires_node, run_js

pytestmark = requires_node

YEAR = 2026


def wine(**fields) -> dict:
    """One export row, with only what a test cares about set."""
    row = {
        "iWine": "1", "Wine": "Some Wine", "Vintage": "2020",
        "Location": "", "Bin": "", "Barcode": "",
        "BeginConsume": "", "EndConsume": "", "Valuation": "10.00",
    }
    row.update(fields)
    return row


def state_of(begin, end, year=YEAR) -> str:
    """The state the page would give one bottle, straight from its own code."""
    import json

    raw = json.dumps(wine(BeginConsume=begin, EndConsume=end))
    output = run_js(
        f"console.log(drinkWindowState(normaliseWine({raw}), {year}));"
    )
    return output.strip()


# --------------------------------------------------------------------------
# Drink-window state: the whole point of the chips
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("begin", "end", "expected"),
    [
        ("2020", "2030", "ready"),
        ("2030", "2040", "aging"),
        ("2010", "2020", "past"),
        (str(YEAR), "2030", "ready"),
        ("2010", str(YEAR), "ready"),
        ("2010", str(YEAR - 1), "past"),
        (str(YEAR + 1), "2040", "aging"),
    ],
)
def test_the_state_of_a_bottle_with_both_bounds(begin, end, expected):
    assert state_of(begin, end) == expected


def test_the_last_year_of_the_window_is_ready_not_past():
    """A wine to drink by 2026 is urgent during 2026, not expired.

    The old page painted it red, which read as "too late". The coordinator has
    always counted it as ready, and the two must not disagree.
    """
    assert state_of("2010", str(YEAR)) == "ready"


@pytest.mark.parametrize(
    ("begin", "end", "expected"),
    [
        ("2020", "", "ready"),
        ("2030", "", "aging"),
        ("", "2030", "ready"),
        ("", "2010", "past"),
    ],
)
def test_a_single_bound_is_enough_to_place_a_bottle(begin, end, expected):
    assert state_of(begin, end) == expected


@pytest.mark.parametrize("blank", ["", " ", None, "N/A", "0", "not a year", "-5"])
def test_a_bottle_with_no_usable_window_is_unknown(blank):
    """The export simply does not say. Guessing would be worse than nothing."""
    assert state_of(blank, blank) == "unknown"


def test_an_inverted_window_is_past_rather_than_aging():
    """Bad data: drink from 2030, by 2020. Already over is the safer reading."""
    assert state_of("2030", "2020") == "past"


# --------------------------------------------------------------------------
# The visual indicator
# --------------------------------------------------------------------------
def test_progress_is_null_without_a_window():
    run_js(check("windowProgress(normaliseWine({}), 2026) === null", "invented a position"))


def test_progress_runs_from_zero_at_the_first_year_to_one_at_the_last():
    run_js(
        equals("windowProgress({BeginConsume: 2020, EndConsume: 2030}, 2020)", 0,
               "the first year should sit at the start")
        + equals("windowProgress({BeginConsume: 2020, EndConsume: 2030}, 2030)", 1,
                 "the last year should sit at the end")
        + equals("windowProgress({BeginConsume: 2020, EndConsume: 2030}, 2025)", 0.5,
                 "the midpoint should sit in the middle")
    )


def test_progress_is_clamped_outside_the_window():
    run_js(
        equals("windowProgress({BeginConsume: 2020, EndConsume: 2030}, 2015)", 0,
               "a bottle not yet open should not read negative")
        + equals("windowProgress({BeginConsume: 2020, EndConsume: 2030}, 2040)", 1,
                 "a bottle long past should not read over one")
    )


def test_a_single_year_window_does_not_divide_by_zero():
    run_js(
        equals("windowProgress({BeginConsume: 2026, EndConsume: 2026}, 2026)", 1,
               "a one-year window should be complete, not NaN")
    )


# --------------------------------------------------------------------------
# Search: more than one field, and more than one word
# --------------------------------------------------------------------------
SEARCH_ROW = (
    '{Wine: "Bindi Sergardi Chianti Classico", Vintage: 2023, '
    'Location: "Cellar", Bin: "A4", Barcode: "7350012345678"}'
)


@pytest.mark.parametrize(
    ("term", "expected", "why"),
    [
        ("bindi", True, "wine name"),
        ("BINDI", True, "case-insensitive"),
        ("2023", True, "vintage as text"),
        ("cellar", True, "location"),
        ("a4", True, "bin"),
        ("7350012345678", True, "barcode"),
        ("bindi 2023", True, "two tokens, both present"),
        ("bindi 2024", False, "second token absent"),
        ("rioja", False, "matches nothing"),
        ("", True, "an empty search excludes nothing"),
        ("   ", True, "whitespace is not a query"),
    ],
)
def test_search_matches_across_fields_and_tokens(term, expected, why):
    import json

    run_js(
        check(
            f"matchesSearch({SEARCH_ROW}, {json.dumps(term)}) === "
            f"{'true' if expected else 'false'}",
            why,
        )
    )


def test_search_survives_a_row_with_missing_fields():
    """A cellar has rows with no bin, no barcode and no vintage."""
    run_js(
        check('matchesSearch({}, "anything") === false', "threw or matched on an empty row")
        + check('matchesSearch({}, "") === true', "an empty search should still pass")
    )


# --------------------------------------------------------------------------
# The chips
# --------------------------------------------------------------------------
CELLAR = (
    "[{BeginConsume: 2020, EndConsume: 2030, Wine: 'Ready One'},"
    " {BeginConsume: 2025, EndConsume: 2026, Wine: 'Ready Two'},"
    " {BeginConsume: 2010, EndConsume: 2015, Wine: 'Past One'},"
    " {BeginConsume: 2030, EndConsume: 2040, Wine: 'Aging One'},"
    " {BeginConsume: 0, EndConsume: 0, Wine: 'Unknown One'}]"
)


def test_the_counts_cover_every_bottle_exactly_once():
    run_js(
        equals(f"filterCounts({CELLAR}, {YEAR})",
               {"all": 5, "ready": 2, "past": 1, "aging": 1},
               "the chip counts do not describe this cellar")
    )


def test_all_is_the_total_including_bottles_with_no_window():
    """A bottle nothing can say anything about still belongs to the cellar."""
    run_js(
        check(f"filterCounts({CELLAR}, {YEAR}).all === {CELLAR}.length",
              "'All wines' lost the bottles with no drinking window")
    )


@pytest.mark.parametrize(
    ("chip", "expected"),
    [
        ("all", ["Ready One", "Ready Two", "Past One", "Aging One", "Unknown One"]),
        ("ready", ["Ready One", "Ready Two"]),
        ("past", ["Past One"]),
        ("aging", ["Aging One"]),
    ],
)
def test_each_chip_selects_its_own_bottles(chip, expected):
    run_js(
        equals(
            f"selectWines({CELLAR}, {{filter: '{chip}', term: '', year: {YEAR}}})"
            ".map((w) => w.Wine)",
            expected,
            f"the '{chip}' chip selected the wrong bottles",
        )
    )


def test_an_unknown_chip_name_shows_everything_rather_than_nothing():
    """A typo in a saved state must not present an empty cellar as the truth."""
    run_js(
        check(
            f"selectWines({CELLAR}, {{filter: 'nonsense', term: '', year: {YEAR}}})"
            f".length === {CELLAR}.length",
            "an unrecognised filter emptied the list",
        )
    )


def test_the_chip_and_the_search_box_apply_together():
    run_js(
        equals(
            f"selectWines({CELLAR}, {{filter: 'ready', term: 'two', year: {YEAR}}})"
            ".map((w) => w.Wine)",
            ["Ready Two"],
            "the search should narrow the chip's selection, not replace it",
        )
    )


def test_selecting_does_not_disturb_the_source_list():
    """Filtering is a view. The cellar itself is not reordered or emptied."""
    run_js(
        f"const source = {CELLAR};\n"
        "const before = JSON.stringify(source.map((w) => w.Wine));\n"
        f"selectWines(source, {{filter: 'past', term: 'x', year: {YEAR}}});\n"
        + check(
            "JSON.stringify(source.map((w) => w.Wine)) === before",
            "filtering mutated the underlying cellar",
        )
    )


# --------------------------------------------------------------------------
# Sorting
# --------------------------------------------------------------------------
SORTABLE = (
    "[{Wine: 'Chianti', Vintage: 2023, Valuation: 224, Bin: 'B2'},"
    " {Wine: 'Barolo', Vintage: 2019, Valuation: 450, Bin: 'A1'},"
    " {Wine: 'Rioja', Vintage: 2022, Valuation: 179, Bin: 'C3'}]"
)


@pytest.mark.parametrize(
    ("key", "direction", "expected"),
    [
        ("Wine", "asc", ["Barolo", "Chianti", "Rioja"]),
        ("Wine", "desc", ["Rioja", "Chianti", "Barolo"]),
        ("Vintage", "asc", ["Barolo", "Rioja", "Chianti"]),
        ("Valuation", "desc", ["Barolo", "Chianti", "Rioja"]),
        ("Bin", "asc", ["Barolo", "Chianti", "Rioja"]),
    ],
)
def test_sorting_orders_by_the_requested_column(key, direction, expected):
    run_js(
        equals(
            f"sortWines({SORTABLE}, '{key}', '{direction}').map((w) => w.Wine)",
            expected,
            f"sorting by {key} {direction} gave the wrong order",
        )
    )


def test_sorting_returns_a_new_array_rather_than_reordering_the_cellar():
    """The old page sorted the master list in place, so 'as fetched' was lost."""
    run_js(
        f"const source = {SORTABLE};\n"
        "const sorted = sortWines(source, 'Valuation', 'desc');\n"
        + check("sorted !== source", "sorting handed back the same array")
        + check("source[0].Wine === 'Chianti'", "sorting reordered the source list")
    )


def test_ties_keep_the_order_they_arrived_in():
    """Otherwise a re-sort on the same key shuffles equal rows under the user."""
    run_js(
        "const tied = [{Wine: 'A', Vintage: 2020}, {Wine: 'B', Vintage: 2020},"
        " {Wine: 'C', Vintage: 2020}];\n"
        + equals("sortWines(tied, 'Vintage', 'asc').map((w) => w.Wine)",
                 ["A", "B", "C"], "a stable sort must not shuffle ties")
        + equals("sortWines(tied, 'Vintage', 'desc').map((w) => w.Wine)",
                 ["A", "B", "C"], "reversing direction must not shuffle ties either")
    )


def test_rows_missing_the_sort_key_sort_last_in_both_directions():
    """A bin nobody filled in should not head the list just because it is empty."""
    run_js(
        "const rows = [{Wine: 'A', Bin: 'B1'}, {Wine: 'B'}, {Wine: 'C', Bin: 'A1'}];\n"
        + equals("sortWines(rows, 'Bin', 'asc').map((w) => w.Wine)",
                 ["C", "A", "B"], "a missing bin should sort last ascending")
        + equals("sortWines(rows, 'Bin', 'desc').map((w) => w.Wine)",
                 ["A", "C", "B"], "a missing bin should sort last descending too")
    )


# --------------------------------------------------------------------------
# Reported by Codex on #22
# --------------------------------------------------------------------------
UNRECORDED = (
    "[{Wine: 'Real Vintage', Vintage: 2019, EndConsume: 2030},"
    " {Wine: 'No Vintage', Vintage: 0, EndConsume: 0},"
    " {Wine: 'Older', Vintage: 2010, EndConsume: 2020}]"
)


@pytest.mark.parametrize("key", ["Vintage", "EndConsume"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_an_unrecorded_year_sorts_last_whichever_way_the_column_points(key, direction):
    """normaliseWine collapses a missing year to 0, and 0 is smaller than 2010.

    So an ascending sort by vintage led with every NV bottle in the cellar -
    the exact thing the missing-value rule was written to prevent, slipping
    through because the rule only recognised null and "".
    """
    run_js(
        equals(
            f"sortWines({UNRECORDED}, '{key}', '{direction}').slice(-1)[0].Wine",
            "No Vintage",
            f"a bottle with no recorded {key} should sort last, not first",
        )
    )


def test_a_valuation_of_zero_is_still_a_value():
    """Unlike a year: there is no year 0, but a bottle really can be worth 0."""
    run_js(
        equals(
            "sortWines([{Wine: 'Free', Valuation: 0}, {Wine: 'Costly', Valuation: 99}],"
            " 'Valuation', 'asc').map((w) => w.Wine)",
            ["Free", "Costly"],
            "a zero valuation was treated as missing rather than as cheap",
        )
    )
