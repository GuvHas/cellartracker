"""The rack LED example must keep telling the same story as the sensors.

``examples/`` ships a wine rack lit from this integration: an ESPHome node that
owns the pixels and knows nothing about wine, and a Home Assistant package that
turns the inventory into one state character per bin for it to paint. That
character is a third implementation of the drinking-window rule, after
``cellar_data.py`` and ``cellar.html``, so the reasoning in
``test_dashboard_agrees_with_sensors.py`` applies here too: run it over one
cellar beside the definition and compare. A rack painting a bottle red while
the sensor counts it as ready is the integration contradicting itself in the
room where you are choosing what to open.

The two halves of the example are also checked against each other. The package
calls actions by name with a fixed set of fields and the node declares them; a
rename on one side alone is a rack that silently stops updating.
"""

from __future__ import annotations

import datetime
import pathlib
import re

import jinja2.sandbox
import yaml

from cellar_tracker.cellar_data import _drink_window_counts

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"
NODE_FILE = EXAMPLES / "esphome" / "winerack1led.yaml"
PACKAGE_FILE = EXAMPLES / "home_assistant" / "wine_rack_leds.yaml"

YEAR = 2026
RACK_LOCATION = "Wine Rack 1"

# Deliberately awkward, and the same shape as the dashboard's fixture: both
# bounds, one bound, neither, the boundary years on each side, an inverted
# window and a year that is not one.
WINDOWS = [
    ("2020", "2030"),
    ("2010", "2015"),
    ("2030", "2040"),
    ("", ""),
    (str(YEAR), "2030"),
    ("2010", str(YEAR)),
    ("2010", str(YEAR - 1)),
    ("2020", ""),
    ("", "2030"),
    ("", "2010"),
    ("2030", "2020"),
    ("not a year", "2030"),
]


class _ExampleLoader(yaml.SafeLoader):
    """Read the example YAML without resolving the tags a live system would.

    ``!secret`` and ``!lambda`` mean something to ESPHome and to Home Assistant
    and nothing here; keeping their argument as text is enough to check the
    structure around them.
    """


for _tag in ("!secret", "!lambda", "!include", "!input"):
    _ExampleLoader.add_constructor(_tag, lambda loader, node: loader.construct_scalar(node))


def _load(path: pathlib.Path) -> dict:
    return yaml.load(path.read_text(), Loader=_ExampleLoader)


NODE = _load(NODE_FILE)
PACKAGE = _load(PACKAGE_FILE)

RACK_ROWS = int(NODE["substitutions"]["rack_rows"])
RACK_COLS = int(NODE["substitutions"]["rack_cols"])
RACK_CELLS = int(NODE["substitutions"]["rack_cells"])
DEVICE_NAME = NODE["substitutions"]["device_name"]

GRID_TEMPLATE = PACKAGE["rest"][0]["sensor"][0]["value_template"]


# --------------------------------------------------------------------------
# Rendering the package's template the way Home Assistant would
# --------------------------------------------------------------------------
def _regex_findall(value, find="", ignorecase=False):
    """Home Assistant's filter of the same name."""
    return re.findall(find, str(value), re.I if ignorecase else 0)


def _environment() -> jinja2.sandbox.SandboxedEnvironment:
    """Home Assistant renders templates in a sandbox, so this does too.

    The sandbox is not a detail: it refuses the mutating methods a template
    might reach for (``list.append``, ``dict.update``), which is why the
    template builds its grid by rebuilding a list rather than writing into one.
    """
    env = jinja2.sandbox.SandboxedEnvironment()
    env.filters["regex_findall"] = _regex_findall
    env.globals["now"] = lambda: datetime.datetime(YEAR, 6, 1, 12, 0, 0)
    return env


def bottle(bin_id: str, begin: str = "", end: str = "", location: str = RACK_LOCATION) -> dict:
    return {
        "Bin": bin_id,
        "Location": location,
        "BeginConsume": begin,
        "EndConsume": end,
        "Wine": f"Wine in {bin_id}",
    }


def grid(bottles: list[dict]) -> str:
    """The state string the rack sensor would hold for this cellar."""
    # Home Assistant strips a rendered template before storing it as a state.
    return _environment().from_string(GRID_TEMPLATE).render(value_json=bottles).strip()


def cell(rendered: str, bin_id: str) -> str:
    row = ord(bin_id[0].upper()) - ord("A")
    column = int(bin_id[1:])
    return rendered[row * RACK_COLS + column - 1]


def one_bottle_per_bin() -> list[dict]:
    """The fixture, spread one to a bin so no bin has to choose between two."""
    return [
        bottle(f"{chr(ord('A') + index // RACK_COLS)}{index % RACK_COLS + 1}", begin, end)
        for index, (begin, end) in enumerate(WINDOWS)
    ]


# --------------------------------------------------------------------------
# The rack and the sensors must count alike
# --------------------------------------------------------------------------
def test_ready_to_drink_agrees_with_the_sensor():
    """Green and amber bins together are what the ready sensor counts.

    Amber is the final year of a window. The integration counts that bottle as
    ready - it is still inside its window - and the rack says "drink this year"
    rather than painting it red, which is the same distinction the dashboard
    makes.
    """
    bottles = one_bottle_per_bin()
    ready, _ = _drink_window_counts(bottles, YEAR)
    rendered = grid(bottles)
    assert rendered.count("R") + rendered.count("U") == ready


def test_past_the_window_agrees_with_the_sensor():
    bottles = one_bottle_per_bin()
    _, past = _drink_window_counts(bottles, YEAR)
    assert grid(bottles).count("P") == past


def test_the_fixture_actually_exercises_both_states():
    """A cellar where both counts are zero would agree about nothing."""
    ready, past = _drink_window_counts(one_bottle_per_bin(), YEAR)
    assert ready > 0 and past > 0


def test_the_fixture_reaches_every_state_the_rack_can_paint():
    rendered = grid(one_bottle_per_bin())
    for state in "RUPAN.":
        assert state in rendered, f"the fixture never produces {state!r}"


def test_a_bottle_with_no_window_is_neither_ready_nor_past():
    """The sensors count it in neither, so the rack must not claim otherwise."""
    bottles = [bottle("A1", "", "")]
    assert _drink_window_counts(bottles, YEAR) == (0, 0)
    assert cell(grid(bottles), "A1") == "N"


def test_the_most_urgent_bottle_in_a_bin_is_the_one_shown():
    """A bin holds several bottles and can only show one state."""
    ready = bottle("C4", "2018", "2030")
    past = bottle("C4", "2000", "2010")
    assert cell(grid([ready, past]), "C4") == "P"
    assert cell(grid([past, ready]), "C4") == "P", "the answer cannot depend on row order"


def test_bottles_in_another_location_are_not_in_this_rack():
    """`Location` is the rack and `Bin` is the slot inside it.

    Without the location test, a second rack numbered the same way would light
    bins in this one.
    """
    elsewhere = [bottle("A1", "2020", "2030", location="Wine Rack 2")]
    assert set(grid(elsewhere)) == {"."}


def test_a_bin_outside_the_rack_lights_nothing():
    """A typo in CellarTracker should go dark, not light the wrong bottle."""
    for bad in ("N1", "A0", f"A{RACK_COLS + 1}", "Z9", "A", "", "7", "AA"):
        assert set(grid([bottle(bad, "2020", "2030")])) == {"."}, f"bin {bad!r}"


def test_bins_are_read_the_way_people_write_them():
    for written in ("D7", "d7", "D-7", "D 7", "D07", "  D7  "):
        assert cell(grid([bottle(written, "2020", "2030")]), "D7") == "R", written


# --------------------------------------------------------------------------
# The grid has to fit both a Home Assistant state and the node's buffer
# --------------------------------------------------------------------------
def test_the_grid_is_one_character_per_bin():
    assert len(grid([])) == RACK_CELLS == RACK_ROWS * RACK_COLS


def test_the_grid_fits_in_a_state():
    """Home Assistant truncates a state longer than 255 characters."""
    assert len(grid(one_bottle_per_bin())) <= 255


def test_a_full_rack_is_still_one_character_per_bin():
    full = [
        bottle(f"{row}{column}", "2020", "2030")
        for row in "ABCDEFGHIJKLM"
        for column in range(1, RACK_COLS + 1)
    ]
    rendered = grid(full)
    assert len(rendered) == RACK_CELLS
    assert set(rendered) == {"R"}


# --------------------------------------------------------------------------
# The two halves of the example must agree with each other
# --------------------------------------------------------------------------
def _node_actions() -> dict[str, set[str]]:
    """Every action the node declares, and the variables it takes."""
    return {
        action["action"]: set(action.get("variables") or {})
        for action in NODE["api"]["actions"]
    }


def _calls(node: object) -> list[dict]:
    """Every ESPHome action call in the package, wherever it is nested."""
    found = []
    if isinstance(node, dict):
        target = node.get("action")
        if isinstance(target, str) and target.startswith("esphome."):
            found.append(node)
        for value in node.values():
            found.extend(_calls(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_calls(item))
    return found


def test_the_package_calls_something():
    """The rest of this section proves nothing if it finds no calls."""
    assert _calls(PACKAGE), "the package should call the node"


def test_the_package_only_calls_actions_the_node_declares():
    declared = _node_actions()
    for call in _calls(PACKAGE):
        name = call["action"].removeprefix(f"esphome.{DEVICE_NAME}_")
        assert name in declared, f"{call['action']} is not an action of {DEVICE_NAME}"


def test_every_field_the_package_sends_is_a_variable_the_node_takes():
    """Home Assistant requires every declared variable, and no others."""
    declared = _node_actions()
    for call in _calls(PACKAGE):
        name = call["action"].removeprefix(f"esphome.{DEVICE_NAME}_")
        assert set(call.get("data") or {}) == declared[name], call["action"]


def test_every_state_the_package_emits_is_a_state_the_node_draws():
    """The alphabet is the contract between the two files.

    The package ends by indexing a literal alphabet with a rank; the node
    switches on the same characters. Adding a state to one side without the
    other paints an occupied bin as empty.
    """
    alphabet = re.search(r"'([.A-Z]+)'\[rank\]", GRID_TEMPLATE)
    assert alphabet, "the package should render its states from one literal alphabet"
    emitted = set(alphabet.group(1)) - {"."}

    render = next(script for script in NODE["script"] if script["id"] == "render")
    drawn = set(re.findall(r"case '([A-Z])':", render["then"][0]["lambda"]))

    assert emitted == drawn, "the package and the node disagree about the states"


def test_the_node_knows_the_rack_the_package_is_describing():
    """Both files carry the rack's shape; disagreeing means a shifted picture."""
    assert f"set cols = {RACK_COLS}" in GRID_TEMPLATE
    assert re.search(rf"set rows = '[A-Z]{{{RACK_ROWS}}}'", GRID_TEMPLATE)
    assert f"RACK_LOCATION = '{RACK_LOCATION}'" in GRID_TEMPLATE


def test_the_strand_is_long_enough_for_the_bins_it_lights():
    """The last bin has no gap after it, which is where an off-by-one hides."""
    substitutions = NODE["substitutions"]
    pitch = int(substitutions["bin_pitch"])
    leds = int(substitutions["bin_leds"])
    assert int(substitutions["strand_leds"]) == RACK_COLS * pitch - (pitch - leds)


def test_there_is_a_strand_for_every_row():
    lights = NODE["light"]
    assert len(lights) == RACK_ROWS
    assert [light["id"] for light in lights] == [
        f"row_{chr(ord('a') + index)}" for index in range(RACK_ROWS)
    ]


def test_no_two_strands_share_a_pin():
    pins = [light["pin"] for light in NODE["light"]]
    assert len(set(pins)) == len(pins), "two strands share a data pin"


def test_the_strands_use_a_driver_that_can_have_more_of_them_than_the_esp32_has_channels():
    """Thirteen strands is more than an ESP32's timing hardware can give.

    A classic ESP32 has eight RMT channels and two I2S buses. FastLED takes one
    per strand as it transmits and hands it back, so the strand count is not
    bounded by it; neopixelbus pins a strand to a channel for the life of the
    node and cannot go past ten, which is what this guards against being
    quietly swapped back in.
    """
    assert len(NODE["light"]) > 10
    for light in NODE["light"]:
        assert light["platform"] == "fastled_clockless", light["id"]
