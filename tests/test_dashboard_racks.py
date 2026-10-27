"""The dashboard drives the LED racks.

Opening a bottle lights its bin, and a chip or a search lights only the bottles
in the list. The page does it through the integration's own actions -
``locate_bottle``, ``highlight_bottles`` and ``show_overview`` - which fire
events each rack's blueprint automation answers. So what is under test here is
what the page *asks* Home Assistant to do, recorded by the fetch stub.

Only bottles at a location the settings list as an LED rack are ever sent: a
bottle in the fridge has nowhere to light.
"""

from __future__ import annotations

import json

from dashboard_js import check, equals, requires_node, run_js

pytestmark = requires_node

PREAMBLE = "currentYear = 2026; currencySymbol = 'kr';"
RACKS = ["Wine Rack 1", "Wine Rack 2"]


def cellar() -> list:
    return [
        {
            "unique_bottle_id": "ready-1",
            "Wine": "Ready Red",
            "Vintage": "2019",
            "Location": "Wine Rack 1",
            "Bin": "A1",
            "BeginConsume": "2020",
            "EndConsume": "2030",
            "Valuation": "450.00",
        },
        {
            "unique_bottle_id": "ready-fridge",
            "Wine": "Fridge White",
            "Vintage": "2022",
            "Location": "Fridge",
            "Bin": "1",
            "BeginConsume": "2023",
            "EndConsume": "2027",
            "Valuation": "120.00",
        },
        {
            "unique_bottle_id": "aging-2",
            "Wine": "Laid Down",
            "Vintage": "2021",
            "Location": " Wine Rack 2 ",
            "Bin": " C3 ",
            "BeginConsume": "2030",
            "EndConsume": "2040",
            "Valuation": "4200.00",
        },
        {
            "unique_bottle_id": "no-bin",
            "Wine": "Unplaced",
            "Vintage": "2018",
            "Location": "Wine Rack 1",
            "Bin": "",
            "BeginConsume": "2020",
            "EndConsume": "2030",
            "Valuation": "90.00",
        },
    ]


FIND = """
function cardFor(name) {
    const found = document.getElementById('list').children.find(
        (el) => el.children[0].children[0].textContent === name
    );
    if (!found) throw new Error('no card rendered for ' + name);
    return found;
}
function open(name) {
    const bottle = cardFor(name);
    bottle.children[0].dispatch('click');
    return bottle;
}
function actions(bottle) {
    return bottle.children[1].children[1].children.map((b) => b.textContent);
}
"""


def page(extra: str, *, racks=RACKS, light=True, service_ok=True) -> str:
    """The page with a cellar loaded and the racks known, then `extra`."""
    return run_js(
        f"{PREAMBLE}\n{FIND}\n"
        f"ledRacks = {json.dumps(racks)};\n"
        f"lightRacks = {json.dumps(light)};\n"
        f"loadWines({json.dumps(cellar())});\n" + extra,
        wines=None,
        service_ok=service_ok,
    )


def later(js: str, ms: int = 20) -> str:
    """Run `js` once the page's promises and timers have settled."""
    return f"setTimeout(() => {{\n{js}\nif (failures) process.exit(1);\n}}, {ms});\n"


# --------------------------------------------------------------------------
# What the racks are asked to show
# --------------------------------------------------------------------------
def test_the_whole_cellar_is_the_overview():
    page(
        equals(
            "rackRequest(allWines, ledRacks, {filter: 'all', term: '  ', year: 2026})",
            {"service": "show_overview", "data": {}},
            "the unfiltered list should put the overview back",
        )
    )


def test_a_chip_lights_only_its_bottles_that_a_rack_can_show():
    """The fridge bottle is ready too, but no LED can show it."""
    page(
        equals(
            "rackRequest(allWines, ledRacks, {filter: 'ready', term: '', year: 2026})",
            {"service": "highlight_bottles", "data": {"bottles": ["ready-1"]}},
            "the ready chip sent the wrong bottles",
        )
    )


def test_a_search_lights_what_it_found():
    page(
        equals(
            "rackRequest(allWines, ledRacks, {filter: 'all', term: 'laid', year: 2026})",
            {"service": "highlight_bottles", "data": {"bottles": ["aging-2"]}},
            "the search sent the wrong bottles",
        )
    )


def test_a_filter_with_nothing_on_the_racks_darkens_them():
    """An empty highlight is an answer: nothing past its window is racked."""
    page(
        equals(
            "rackRequest(allWines, ledRacks, {filter: 'past', term: '', year: 2026})",
            {"service": "highlight_bottles", "data": {"bottles": []}},
            "an empty result should still be sent",
        )
    )


def test_without_led_racks_nothing_is_asked():
    page(
        equals(
            "rackRequest(allWines, [], {filter: 'ready', term: '', year: 2026})",
            None,
            "a cellar without LEDs should never call a rack action",
        ),
        racks=[],
    )


def test_a_bottle_is_on_a_rack_only_with_a_racked_location_and_a_bin():
    page(
        check("isOnRack(allWines[0], ledRacks)", "a racked bottle was not recognised")
        + check("isOnRack(allWines[2], ledRacks)", "surrounding spaces hid the rack")
        + check("!isOnRack(allWines[1], ledRacks)", "the fridge is not a rack")
        + check("!isOnRack(allWines[3], ledRacks)", "a bottle with no bin has nothing to light")
    )


# --------------------------------------------------------------------------
# Tapping a bottle
# --------------------------------------------------------------------------
def test_opening_a_racked_bottle_lights_its_bin():
    page(
        "open('Laid Down');\n"
        + equals("posted.length", 1, "opening the bottle should light it once")
        + equals("posted[0].url", "/api/services/cellar_tracker/locate_bottle", "wrong action")
        + equals(
            "posted[0].body",
            {"location": "Wine Rack 2", "bin": "C3"},
            "the bin sent is not the bottle's",
        )
        + equals("posted[0].headers['Content-Type']", "application/json", "not sent as JSON")
    )


def test_closing_a_bottle_does_not_light_it_again():
    page(
        "const bottle = open('Ready Red');\n"
        "bottle.children[0].dispatch('click');\n" + equals("posted.length", 1, "closed and relit")
    )


def test_opening_a_bottle_off_the_racks_asks_nothing():
    page(
        "const bottle = open('Fridge White');\n"
        + equals("posted.length", 0, "asked a rack to show a fridge bottle")
        + check("actions(bottle).indexOf('Show on rack') === -1", "offered a rack it is not on")
    )


def test_with_the_racks_switched_off_opening_only_opens():
    page("open('Ready Red');\n" + equals("posted.length", 0, "lit a rack while off"), light=False)


def test_the_drawer_can_light_the_bin_on_demand():
    """Even with automatic lighting off, the button does what it says."""
    page(
        "const bottle = open('Ready Red');\n"
        "const button = bottle.children[1].children[1].children"
        ".find((b) => b.textContent === 'Show on rack');\n"
        "button.dispatch('click', {stopPropagation() {}});\n"
        + later(
            equals("button.textContent", "Lit on the rack", "did not say it worked")
            + equals("posted.map((p) => p.body.bin)", ["A1"], "lit the wrong bin")
        ),
        light=False,
    )


def test_the_button_says_so_when_home_assistant_refused():
    page(
        "const bottle = open('Ready Red');\n"
        "const button = bottle.children[1].children[1].children"
        ".find((b) => b.textContent === 'Show on rack');\n"
        "button.dispatch('click', {stopPropagation() {}});\n"
        + later(equals("button.textContent", "Could not light it", "claimed success")),
        light=False,
        service_ok=False,
    )


# --------------------------------------------------------------------------
# Chips, search and the switch
# --------------------------------------------------------------------------
def test_the_racks_follow_the_list_once_it_settles():
    """Three quick changes are one request, for the last of them."""
    page(
        "setFilter('past'); syncRacks();\n"
        "setFilter('aging'); syncRacks();\n"
        "setFilter('ready'); syncRacks();\n"
        + equals("posted.length", 0, "sent before the typing stopped")
        + later(
            equals("posted.length", 1, "every change was sent")
            + equals(
                "posted[0].url",
                "/api/services/cellar_tracker/highlight_bottles",
                "wrong action",
            )
            + equals("posted[0].body", {"bottles": ["ready-1"]}, "not the last filter"),
            ms=700,
        )
    )


def test_back_to_all_wines_puts_the_overview_back():
    page(
        "setFilter('ready'); setFilter('all'); syncRacks();\n"
        + later(
            equals(
                "posted.map((p) => p.url)",
                ["/api/services/cellar_tracker/show_overview"],
                "the unfiltered list should put the overview back",
            ),
            ms=700,
        )
    )


def test_switching_the_racks_off_hands_them_back_to_the_overview():
    page(
        "const toggle = document.getElementById('light-racks');\n"
        "toggle.dispatch('click');\n"
        + equals("lightRacks", False, "the switch did not switch")
        + equals("toggle.getAttribute('aria-pressed')", "false", "the switch did not say so")
        + equals(
            "posted.map((p) => p.url)",
            ["/api/services/cellar_tracker/show_overview"],
            "the racks were left highlighted",
        )
        + "setFilter('ready'); syncRacks();\n"
        + later(equals("posted.length", 1, "followed the list while switched off"), ms=700)
    )


def test_the_switch_appears_only_with_led_racks():
    """Loaded through the page's own fetch of the settings."""
    for racks, hidden in ((RACKS, False), ([], True)):
        run_js(
            later(
                equals(
                    "document.getElementById('light-racks').hidden",
                    hidden,
                    f"switch hidden should be {hidden}",
                )
                + equals("ledRacks", racks, "the racks were not read from the settings")
            ),
            wines=cellar(),
            racks=racks,
        )


def test_opening_a_bottle_cancels_a_list_update_still_waiting():
    """Reported by Codex on #29: the late highlight would clear the locator.
    The latest thing the user did is what the rack shows."""
    page(
        "setFilter('ready'); syncRacks();\n"
        "open('Ready Red');\n"
        + later(
            equals(
                "posted.map((p) => p.url)",
                ["/api/services/cellar_tracker/locate_bottle"],
                "a stale highlight followed the locator",
            ),
            ms=700,
        )
    )
