"""What the page actually builds, not just what it decides.

The filtering tests call pure functions. These drive the page's render path
through a fake DOM, because the interesting regressions are in the wiring: a
chip that filters correctly but never repaints, a drawer that opens on the
wrong bottle, a refresh that silently resets the view.

The fake DOM is a handful of objects, not a browser - so it proves structure
and text, not layout. Layout was checked in Chromium; the verification steps
are in the pull request.
"""

from __future__ import annotations

import json

from dashboard_js import check, equals, requires_node, run_js

pytestmark = requires_node

# The page reads both from the settings endpoint, which these tests do not
# exercise. Pinning them keeps the assertions about rendering rather than
# about what year it happens to be when the suite runs.
PREAMBLE = "currentYear = 2026; currencySymbol = 'kr';"


def cellar() -> list:
    """One bottle in each state, plus one with nothing recorded."""
    return [
        {"iWine": "1", "Wine": "Ready Red", "Vintage": "2019", "Location": "Cellar",
         "Bin": "A1", "Barcode": "7350001", "BeginConsume": "2020",
         "EndConsume": "2030", "Valuation": "450.00"},
        {"iWine": "2", "Wine": "Last Call", "Vintage": "2015", "Location": "Cellar",
         "Bin": "B2", "Barcode": "7350002", "BeginConsume": "2018",
         "EndConsume": "2026", "Valuation": "265.00"},
        {"iWine": "3", "Wine": "Gone By", "Vintage": "2010", "Location": "", "Bin": "",
         "Barcode": "", "BeginConsume": "2012", "EndConsume": "2020",
         "Valuation": "89.00"},
        {"iWine": "4", "Wine": "Laid Down", "Vintage": "2021", "Location": "Cellar",
         "Bin": "C3", "Barcode": "7350004", "BeginConsume": "2030",
         "EndConsume": "2040", "Valuation": "4200.00"},
    ]


# Looked up by name, not by position: the list is sorted, so an index would
# couple every assertion to the current sort order.
FIND = """
function cardFor(name) {
    const found = document.getElementById('list').children.find(
        (el) => el.children[0].children[0].textContent === name
    );
    if (!found) throw new Error('no card rendered for ' + name);
    return found;
}
"""


def load(extra: str) -> str:
    """Put the fixture through the page's own loadWines, then run `extra`."""
    return run_js(
        f"{PREAMBLE}\n{FIND}\nloadWines({json.dumps(cellar())});\n" + extra,
        wines=None,
    )


def card(name: str) -> str:
    return f"cardFor({json.dumps(name)})"


def window_row(name: str) -> str:
    return f"{card(name)}.children[0].children[3]"


# --------------------------------------------------------------------------
# The list
# --------------------------------------------------------------------------
def test_one_card_is_built_per_selected_bottle():
    load(
        equals("document.getElementById('list').children.length", 4,
               "the list should hold one card per bottle")
    )


def test_a_card_carries_the_name_the_vintage_and_the_price():
    load(
        f"const summary = {card('Ready Red')}.children[0];\n"
        + equals("summary.children[0].textContent", "Ready Red", "the name is wrong")
        + equals("summary.children[1].textContent", "kr 450", "the price is wrong")
        + check(
            "summary.children[2].children.map((c) => c.textContent).join('')"
            ".indexOf('2019') !== -1",
            "the vintage is missing from the meta line",
        )
    )


def test_the_bin_and_location_reach_the_summary_line():
    """A bin you have to tap to see is a bin you cannot scan a shelf against."""
    load(
        f"const meta = {card('Ready Red')}.children[0].children[2];\n"
        + check(
            "meta.children.map((c) => c.textContent).join(' ').indexOf('A1') !== -1",
            "the bin should be visible without expanding the card",
        )
    )


# --------------------------------------------------------------------------
# The drink-window indicator
# --------------------------------------------------------------------------
def pill(name: str) -> str:
    return f"{window_row(name)}.children.slice(-1)[0].textContent"


def test_each_state_gets_its_own_label():
    load(
        equals(pill("Ready Red"), "Ready", "a bottle inside its window")
        + equals(pill("Gone By"), "Past window", "a bottle past its window")
        + equals(pill("Laid Down"), "Needs aging", "a bottle not yet open")
    )


def test_the_final_year_of_a_window_is_called_out_rather_than_shown_as_expired():
    """The old page painted this red, which read as too late. It is not."""
    load(equals(pill("Last Call"), "Drink this year", "the last year should read as urgent"))


def test_the_bar_is_filled_in_proportion_to_the_window():
    """2020-2030, currently 2026: six years into a ten-year window."""
    load(
        equals(f"{window_row('Ready Red')}.children[0].children[0].style.width", "60%",
               "the fill does not match where this year sits in the window")
    )


def test_a_bottle_with_no_window_gets_no_bar_at_all():
    run_js(
        f"{PREAMBLE}\n{FIND}\n"
        "loadWines([{Wine: 'Nothing Known', Valuation: '10'}]);\n"
        f"const row = {window_row('Nothing Known')};\n"
        + equals("row.children.length", 1, "drew a bar for a window nobody recorded")
        + equals("row.children[0].textContent", "No window", "mislabelled a bottle"),
        wines=None,
    )


# --------------------------------------------------------------------------
# The drawer
# --------------------------------------------------------------------------
def test_tapping_a_card_opens_its_drawer():
    load(
        f"const bottle = {card('Ready Red')};\n"
        "bottle.children[0].dispatch('click');\n"
        + equals("bottle.getAttribute('data-open')", "true", "the card did not open")
        + equals("bottle.children[0].getAttribute('aria-expanded')", "true",
                 "the summary button did not announce that it opened")
        + equals("bottle.children.length", 2, "no drawer was added")
    )


def test_the_drawer_carries_what_a_phone_at_the_rack_needs():
    load(
        f"const bottle = {card('Ready Red')};\n"
        "bottle.children[0].dispatch('click');\n"
        "const text = JSON.stringify(bottle.children[1]);\n"
        + check("text.indexOf('7350001') !== -1", "the barcode is missing")
        + check("text.indexOf('A1') !== -1", "the bin is missing")
        + check("text.indexOf('Copy bin') !== -1", "there is no way to copy the bin")
        + check("text.indexOf('Open in CellarTracker') !== -1", "no link to the wine")
    )


def test_tapping_again_closes_it():
    load(
        f"const bottle = {card('Ready Red')};\n"
        "bottle.children[0].dispatch('click');\n"
        "bottle.children[0].dispatch('click');\n"
        + equals("bottle.getAttribute('data-open')", "false", "the card stayed open")
        + equals("bottle.children.length", 1, "the drawer was left behind")
    )


def test_a_bottle_with_no_bin_offers_no_copy_button():
    """An action that copies an empty string is worse than no action."""
    load(
        f"const gone = {card('Gone By')};\n"
        "gone.children[0].dispatch('click');\n"
        + check("JSON.stringify(gone.children[1]).indexOf('Copy bin') === -1",
                "offered to copy a bin that does not exist")
    )


# --------------------------------------------------------------------------
# State survives new data
# --------------------------------------------------------------------------
def test_a_refresh_keeps_the_chip_the_search_and_the_sort():
    """The coordinator repolls every six hours; the view must not reset."""
    load(
        "view.filter = 'past'; view.term = 'gone'; view.sort = 'Valuation';\n"
        "view.direction = 'desc';\n"
        f"loadWines({json.dumps(cellar())});\n"
        + equals("view.filter", "past", "the chip was reset by new data")
        + equals("view.term", "gone", "the search box was cleared by new data")
        + equals("view.sort", "Valuation", "the sort column was reset")
        + equals("view.direction", "desc", "the sort direction was reset")
        + equals("document.getElementById('list').children.length", 1,
                 "the refreshed list ignored the filter that was in force")
    )


def test_an_empty_result_says_so_instead_of_showing_nothing():
    load(
        "view.term = 'no such wine anywhere';\nrender();\n"
        + equals("document.getElementById('list').children.length", 0,
                 "rows survived a filter that matches nothing")
        + check("document.getElementById('status').textContent.length > 0",
                "an empty list with no explanation reads as a broken page")
    )


# --------------------------------------------------------------------------
# Reported by Codex on #22
# --------------------------------------------------------------------------
def copy_scenario(clipboard: str, exec_command: bool) -> dict:
    """Open a drawer, press Copy bin, and report the label and what was copied."""
    output = run_js(
        f"{PREAMBLE}\n{FIND}\n"
        f"loadWines({json.dumps(cellar())});\n"
        f"const bottle = {card('Ready Red')};\n"
        "bottle.children[0].dispatch('click');\n"
        "const copy = bottle.children[1].children[1].children[0];\n"
        "copy.dispatch('click', {stopPropagation() {}});\n"
        # Report the label and what actually reached a clipboard, so a test can
        # tell "said Copied" apart from "copied something".
        "setTimeout(() => {\n"
        "  console.log(JSON.stringify({label: copy.textContent, copied: copied}));\n"
        "}, 10);\n",
        wines=None,
        clipboard=clipboard,
        exec_command=exec_command,
    )
    return json.loads(output.strip())


def test_copying_says_so_when_it_worked():
    result = copy_scenario("async", True)
    assert result["label"] == "Copied"
    assert "A1" in result["copied"], "the bin never reached the clipboard"


def test_a_missing_clipboard_api_falls_back_rather_than_failing():
    """Home Assistant on plain http is not a secure context, so there is no
    navigator.clipboard at all - the common case here, not an edge one."""
    result = copy_scenario("missing", True)
    assert result["label"] == "Copied"
    assert result["copied"], "claimed success without using the fallback"


def test_a_rejected_clipboard_write_still_falls_back():
    result = copy_scenario("rejects", True)
    assert result["label"] == "Copied"
    assert result["copied"], "gave up instead of trying the legacy path"


def test_the_button_does_not_claim_success_when_nothing_was_copied():
    """It used to say "Copied" whenever the clipboard API was absent."""
    result = copy_scenario("missing", False)
    assert not result["copied"], "the fixture should model a copy that fails"
    assert result["label"] != "Copied"


def test_a_failed_copy_says_what_happened():
    label = copy_scenario("missing", False)["label"]
    assert label and label != "Copy bin", (
        "a copy that silently did nothing leaves the user believing it worked"
    )
