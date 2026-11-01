"""Open in CellarTracker opens from Home Assistant's window, not the iframe's.

The iframe card sandboxes the page, and a window it opens inherits the
sandbox; in the Companion app that window went nowhere. So the link asks the
parent to open it, and falls back to the plain link only where there is no
reachable parent.
"""

from __future__ import annotations

from dashboard_js import equals, requires_node, run_js

pytestmark = requires_node

URL = "https://go.cellartracker.com/wine/42"


def test_embedded_the_parent_opens_the_link():
    run_js(
        "const opened = [];\n"
        "window.top = { open: (...args) => { opened.push(args); return null; } };\n"
        + equals(f"openFromHomeAssistant('{URL}')", True, "the parent should open it")
        + equals("opened", [[URL, "_blank", "noopener,noreferrer"]], "opened wrong")
    )


def test_on_its_own_the_plain_link_opens_it():
    run_js(
        "window.top = window;\n"
        + equals(f"openFromHomeAssistant('{URL}')", False, "not embedded: leave it to the link")
    )


def test_an_unreachable_parent_leaves_it_to_the_link():
    run_js(
        "Object.defineProperty(window, 'top', { get() { throw new Error('cross-origin'); } });\n"
        + equals(f"openFromHomeAssistant('{URL}')", False, "a cross-origin parent threw")
    )


def test_the_link_is_the_one_the_cellartracker_app_shares():
    """The classic wine.asp address opened the app on its start screen."""
    run_js(
        equals("wineUrl('5776149')", "https://go.cellartracker.com/wine/5776149", "wrong page")
        + equals("wineUrl(' 42 ')", "https://go.cellartracker.com/wine/42", "spaces kept")
        + equals("wineUrl('1/2')", "https://go.cellartracker.com/wine/1%2F2", "not escaped")
    )
