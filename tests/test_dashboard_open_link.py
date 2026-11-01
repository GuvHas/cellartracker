"""Open in CellarTracker opens from Home Assistant's window, not the iframe's.

The iframe card sandboxes the page, and a window it opens inherits the
sandbox; in the Companion app that window went nowhere. So the link asks the
parent to open it, and falls back to the plain link only where there is no
reachable parent.
"""

from __future__ import annotations

from dashboard_js import equals, requires_node, run_js

pytestmark = requires_node

URL = "https://www.cellartracker.com/wine.asp?iWine=42"


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
