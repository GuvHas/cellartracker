"""The rack map: each LED rack drawn as its grid of bins, coloured like its LEDs.

The colours are the integration's rack_grid rule, so the map and the rack agree
on what a bin shows - a bin holds several bottles and shows the most urgent.
With a chip or a search on, only the bottles in the list colour their bins, as
the highlight the racks get then. Tapping a bin lights it, empty or not.
"""

from __future__ import annotations

import json

from dashboard_js import check, equals, requires_node, run_js

pytestmark = requires_node

RACK_1 = {"location": "Rack 1", "rows": 3, "cols": 4, "missing": [[1, 1], [1, 2]]}
RACK_2 = {"location": "Rack 2", "rows": 2, "cols": 2, "missing": []}


def bottle(uid, location, bin_, begin, end, name=None):
    return {
        "unique_bottle_id": uid,
        "Wine": name or uid,
        "Vintage": "2019",
        "Location": location,
        "Bin": bin_,
        "BeginConsume": begin,
        "EndConsume": end,
        "Valuation": "100",
    }


def cellar() -> list:
    return [
        bottle("ready", "Rack 1", "A1", "2020", "2030"),
        bottle("past", "rack  1", "a-1", "2010", "2020"),
        bottle("aging", "Rack 1", "C4", "2030", "2040"),
        bottle("urgent", "Rack 2", "B2", "2020", "2026"),
        bottle("nowindow", "Rack 2", "A1", "", ""),
        bottle("in-a-gap", "Rack 1", "B2", "2020", "2030"),
        bottle("outside", "Rack 1", "D9", "2020", "2030"),
        bottle("fridge", "Fridge", "A1", "2020", "2030"),
    ]


def page(extra: str, *, light=True) -> str:
    return run_js(
        "currentYear = 2026;\n"
        f"ledRacks = {json.dumps(['Rack 1', 'Rack 2'])};\n"
        f"rackShapes = {json.dumps([RACK_1, RACK_2])};\n"
        f"lightRacks = {json.dumps(light)};\n"
        "mapOpen = true;\n"
        f"loadWines({json.dumps(cellar())});\n"
        "function states(shape, shown) {\n"
        "    return rackCells(allWines, shape, 2026, shown || null).map((c) => c.state);\n"
        "}\n"
        "const map = () => document.getElementById('rack-map');\n"
        "const rackGrid = (i) => map().children[i].children[1];\n"
        "const cellButton = (i, bin) => rackGrid(i).children.find(\n"
        "    (el) => el.tagName === 'BUTTON'\n"
        "        && String(el.title).indexOf(' ' + bin + ':') !== -1);\n" + extra
    )


def test_parse_bin_follows_the_boards_grammar():
    page(
        equals("parseBin('D2')", [3, 1], "plain bin")
        + equals("parseBin(' d - 0 2 ')", [3, 1], "spacing, dashes and zeros")
        + equals("parseBin('A1B')", None, "a trailing letter is not a bin")
        + equals("parseBin('12A')", None, "a leading number is not a bin")
        + equals("parseBin('A0')", None, "there is no bin 0")
        + equals("parseBin('')", None, "blank")
    )


def test_a_bin_shows_its_most_urgent_bottle():
    """A1 holds a ready and a past bottle: past wins, as on the LEDs."""
    page(
        equals(
            "states(rackShapes[0])",
            [
                "past",
                "empty",
                "empty",
                "empty",
                "empty",
                "empty",
                "empty",
                "empty",
                "empty",
                "empty",
                "empty",
                "aging",
            ],
            "rack 1 coloured wrong",
        )
        + equals(
            "states(rackShapes[1])",
            ["unknown", "empty", "empty", "urgent"],
            "rack 2 coloured wrong",
        )
    )


def test_gaps_and_bins_off_the_grid_hold_nothing():
    page(
        equals(
            "rackCells(allWines, rackShapes[0], 2026, null)"
            ".filter((c) => !c.exists).map((c) => c.bin)",
            ["B2", "B3"],
            "the gaps are not the missing bins",
        )
        + equals(
            "rackCells(allWines, rackShapes[0], 2026, null)"
            ".reduce((n, c) => n + c.bottles.length, 0)",
            3,
            "a bottle in a gap or outside the grid was put on the map",
        )
    )


def test_a_filter_colours_only_its_bottles():
    """The rest are 'other': they hold bottles but are dark on the rack."""
    page(
        "const shown = new Set(selectWines(allWines, {filter: 'aging', year: 2026}));\n"
        + equals(
            "states(rackShapes[0], shown).filter((s) => s !== 'empty')",
            ["other", "aging"],
            "the filter did not narrow the colours",
        )
    )


def test_the_map_draws_every_rack_with_its_gaps():
    page(
        equals("map().hidden", False, "the map should be open")
        # One section per rack, then the legend.
        + equals("map().children.length", 3, "two racks and a legend")
        + equals(
            "rackGrid(0).children.filter((el) => el.tagName === 'BUTTON').length",
            12,
            "rack 1 should have a cell for every place in its envelope",
        )
        + equals(
            "rackGrid(0).children.filter((el) => el.disabled).length",
            2,
            "the two gaps should not be tappable",
        )
        + check(
            "cellButton(0, 'A1').className.indexOf('state-past') !== -1",
            "A1 should be drawn as past",
        )
    )


def test_tapping_a_bin_shows_its_bottles_and_lights_it():
    page(
        "cellButton(0, 'A1').dispatch('click');\n"
        + equals("posted.length", 1, "the bin should be lit once")
        + equals("posted[0].url", "/api/services/cellar_tracker/locate_bottle", "wrong action")
        + equals("posted[0].body", {"location": "Rack 1", "bin": "A1"}, "wrong bin lit")
        + equals(
            "map().children[0].children[2].children.slice(1)"
            ".map((card) => card.children[0].children[0].textContent)",
            ["ready", "past"],
            "the bin's bottles were not listed",
        )
        + equals(
            "cellButton(0, 'A1').getAttribute('aria-pressed')",
            "true",
            "the tapped bin is not marked",
        )
    )


def test_focus_stays_on_the_bin_after_the_redraw():
    """Enter on a bin redraws the map; the keyboard must not lose its place."""
    page(
        "let focused = null;\n"
        "const realCreate = document.createElement;\n"
        "document.createElement = (tag) => {\n"
        "    const el = realCreate(tag);\n"
        "    el.focus = () => { focused = el; };\n"
        "    return el;\n"
        "};\n"
        "renderMap();\n"
        "cellButton(0, 'C4').dispatch('click');\n"
        + check("focused === cellButton(0, 'C4')", "focus left the bin when it opened")
        + "focused = null;\n"
        "cellButton(0, 'C4').dispatch('click');\n"
        + check("focused === cellButton(0, 'C4')", "focus left the bin when it closed")
    )


def test_tapping_an_empty_bin_still_lights_it():
    """Finding the space for a bottle you are putting away."""
    page(
        "cellButton(1, 'A2').dispatch('click');\n"
        + equals(
            "posted.map((p) => p.body)",
            [{"location": "Rack 2", "bin": "A2"}],
            "an empty bin should still be lit",
        )
        + equals(
            "map().children[1].children[2].children[1].textContent",
            "Empty bin.",
            "an empty bin should say so",
        )
    )


def test_tapping_the_bin_again_closes_it_without_lighting():
    page(
        "cellButton(0, 'C4').dispatch('click');\n"
        "cellButton(0, 'C4').dispatch('click');\n"
        + equals("posted.length", 1, "closing a bin should not light it again")
        + equals("map().children[0].children.length", 2, "the detail should be gone")
    )


def test_with_light_racks_off_the_map_only_shows():
    page(
        "cellButton(0, 'A1').dispatch('click');\n"
        + equals("posted.length", 0, "light racks is off: nothing should be sent"),
        light=False,
    )


def test_the_map_stays_hidden_when_closed():
    page(
        "mapOpen = false; renderMap();\n"
        + equals("map().hidden", True, "a closed map should be hidden")
        + equals("map().children.length", 0, "a closed map should hold nothing")
    )


def test_the_settings_turn_the_map_on():
    run_js(
        "setTimeout(() => {\n"
        + equals("rackShapes.map((s) => s.location)", ["Rack 1"], "shapes not read")
        + equals(
            "document.getElementById('map-toggle').hidden",
            False,
            "the map button should show once there are racks",
        )
        + "if (failures) process.exit(1);\n}, 20);\n",
        wines=cellar(),
        racks=["Rack 1"],
        rack_shapes=[RACK_1],
    )
