"""The rack LED examples must keep telling the same story as the sensors.

``examples/`` ships two wine racks lit from this integration: a U-shaped rack
of 129 bins in a 13 x 13 envelope, and a plain 7 x 7 beside it. Each has an
ESPHome node that owns the pixels and knows nothing about wine; one Home
Assistant package turns the inventory into a string of per-bin states for both.

That string is a third implementation of the drinking-window rule, after
``cellar_data.py`` and ``cellar.html``, so the reasoning in
``test_dashboard_agrees_with_sensors.py`` applies here too: run it over one
cellar beside the definition and compare. A rack painting a bottle red while
the sensor counts it as ready is the integration contradicting itself in the
room where you are choosing what to open.

The rest of the file checks the two halves of the example against each other,
and the wiring against the shape of the rack. The strips run vertically - one
strand per bin column - and the reason is a geometric fact this file asserts
rather than asks you to believe: every column of the U is contiguous, and most
of its rows are not.
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
NODE1_FILE = EXAMPLES / "esphome" / "winerack1led.yaml"
NODE2_FILE = EXAMPLES / "esphome" / "winerack2led.yaml"
PACKAGE_FILE = EXAMPLES / "home_assistant" / "wine_rack_leds.yaml"

YEAR = 2026
RACK1_LOCATION = "Wine Rack 1"
RACK2_LOCATION = "Wine Rack 2"

# The rack as rebuilt: rows A-H (0-7) keep bins 1-4 and 10-13, with the U's
# opening across the middle; rows I-M (8-12) run the full width.
RACK1_SHAPE = frozenset(
    [(r, c) for r in range(0, 8) for c in list(range(0, 4)) + list(range(9, 13))]
    + [(r, c) for r in range(8, 13) for c in range(13)]
)
RACK2_SHAPE = frozenset((r, c) for r in range(7) for c in range(7))

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


NODE1 = _load(NODE1_FILE)
NODE2 = _load(NODE2_FILE)
PACKAGE = _load(PACKAGE_FILE)
NODES = {NODE1["substitutions"]["device_name"]: NODE1,
         NODE2["substitutions"]["device_name"]: NODE2}

SENSORS = {s["name"]: s for s in PACKAGE["rest"][0]["sensor"]}
GRID1 = SENSORS["Wine rack 1 grid"]["value_template"]
GRID2 = SENSORS["Wine rack 2 grid"]["value_template"]
ORPHANS = SENSORS["Wine rack 1 bottles in missing bins"]["value_template"]


def subs(node: dict, key: str) -> int:
    return int(node["substitutions"][key])


def resolve(node: dict, value: object) -> str:
    """Expand a ``${name}`` substitution the way ESPHome would.

    The example files keep their geometry in ``substitutions:`` so one number
    is not written in six places; a plain YAML load hands those back as the
    literal ``${tall_strand}``.
    """
    text = str(value)
    m = re.fullmatch(r"\$\{(\w+)\}", text.strip())
    return node["substitutions"][m.group(1)] if m else text


# --------------------------------------------------------------------------
# Rendering the package's templates the way Home Assistant would
# --------------------------------------------------------------------------
def _regex_findall(value, find="", ignorecase=False):
    """Home Assistant's filter of the same name."""
    return re.findall(find, str(value), re.I if ignorecase else 0)


def _environment() -> jinja2.sandbox.SandboxedEnvironment:
    """Home Assistant renders templates in a sandbox, so this does too.

    The sandbox is not a detail: it refuses the mutating methods a template
    might reach for (``list.append``, ``dict.update``), which is why the
    templates build their grids by rebuilding a list rather than writing into
    one.
    """
    env = jinja2.sandbox.SandboxedEnvironment()
    env.filters["regex_findall"] = _regex_findall
    env.globals["now"] = lambda: datetime.datetime(YEAR, 6, 1, 12, 0, 0)
    return env


def bottle(bin_id: str, begin: str = "", end: str = "", location: str = RACK1_LOCATION) -> dict:
    return {
        "Bin": bin_id,
        "Location": location,
        "BeginConsume": begin,
        "EndConsume": end,
        "Wine": f"Wine in {bin_id}",
    }


def render(template: str, bottles: list[dict]) -> str:
    """What the sensor would hold for this cellar."""
    # Home Assistant strips a rendered template before storing it as a state.
    return _environment().from_string(template).render(value_json=bottles).strip()


def grid(bottles: list[dict]) -> str:
    return render(GRID1, bottles)


def cell(rendered: str, bin_id: str, cols: int = 13) -> str:
    row = ord(bin_id[0].upper()) - ord("A")
    column = int(bin_id[1:])
    return rendered[row * cols + column - 1]


def one_bottle_per_bin() -> list[dict]:
    """The fixture, spread one to a bin so no bin has to choose between two.

    Placed only in bins the rack actually has, so the counts it produces are
    the counts the rack can show.
    """
    slots = sorted(RACK1_SHAPE)[: len(WINDOWS)]
    return [
        bottle(f"{chr(ord('A') + r)}{c + 1}", begin, end)
        for (r, c), (begin, end) in zip(slots, WINDOWS, strict=True)
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


def test_the_two_racks_do_not_read_each_others_bottles():
    """`Location` is the rack and `Bin` is the slot inside it.

    Both racks number their bins from A1, so without the location test a
    bottle in one would light a bin in the other.
    """
    in_two = [bottle("A1", "2020", "2030", location=RACK2_LOCATION)]
    assert set(render(GRID1, in_two)) == {"."}
    assert cell(render(GRID2, in_two), "A1", cols=7) == "R"

    in_one = [bottle("A1", "2020", "2030", location=RACK1_LOCATION)]
    assert set(render(GRID2, in_one)) == {"."}
    assert cell(render(GRID1, in_one), "A1") == "R"


def test_a_bin_outside_the_envelope_lights_nothing():
    """A typo in CellarTracker should go dark, not light the wrong bottle."""
    for bad in ("N1", "A0", "A14", "Z9", "A", "", "7", "AA"):
        assert set(grid([bottle(bad, "2020", "2030")])) == {"."}, f"bin {bad!r}"


def test_bins_are_read_the_way_people_write_them():
    for written in ("D2", "d2", "D-2", "D 2", "D02", "  D2  "):
        assert cell(grid([bottle(written, "2020", "2030")]), "D2") == "R", written


# --------------------------------------------------------------------------
# The U, and the bottles that fall in its hole
# --------------------------------------------------------------------------
def test_a_bottle_in_the_us_opening_is_counted_as_an_orphan():
    """After a rebuild, CellarTracker still files bottles at bins that went.

    They are not lost and they are not mis-lit - there is no strand there - but
    something has to say they exist, or a rebuild quietly swallows them.
    """
    gone = [bottle("A7", "2020", "2030"), bottle("C6", "2020", "2030")]
    assert render(ORPHANS, gone) == "2"


def test_bins_the_rack_still_has_are_not_orphans():
    kept = [bottle(f"{chr(ord('A') + r)}{c + 1}", "2020", "2030") for r, c in sorted(RACK1_SHAPE)]
    assert render(ORPHANS, kept) == "0"


def test_the_other_racks_bottles_are_not_rack_ones_orphans():
    assert render(ORPHANS, [bottle("A1", "2020", "2030", location=RACK2_LOCATION)]) == "0"


# --------------------------------------------------------------------------
# The grid has to fit both a Home Assistant state and the node's buffer
# --------------------------------------------------------------------------
def test_each_grid_is_one_character_per_bin_of_its_envelope():
    assert len(grid([])) == subs(NODE1, "rack_cells") == 13 * 13
    assert len(render(GRID2, [])) == subs(NODE2, "rack_cells") == 7 * 7


def test_the_grids_fit_in_a_state():
    """Home Assistant truncates a state longer than 255 characters."""
    assert len(grid(one_bottle_per_bin())) <= 255
    assert len(render(GRID2, [])) <= 255


def test_a_full_rack_is_still_one_character_per_bin():
    full = [
        bottle(f"{chr(ord('A') + r)}{c + 1}", "2020", "2030")
        for r, c in sorted(RACK1_SHAPE)
    ]
    rendered = grid(full)
    assert len(rendered) == subs(NODE1, "rack_cells")
    assert set(rendered) == {"R", "."}, "only the bins the rack has should light"
    assert rendered.count("R") == len(RACK1_SHAPE)


# --------------------------------------------------------------------------
# The wiring has to match the shape of the rack
# --------------------------------------------------------------------------
GEOMETRY_FILES = {
    "winerack1led": EXAMPLES / "esphome" / "winerack1_geometry.h",
    "winerack2led": EXAMPLES / "esphome" / "winerack2_geometry.h",
}


def geometry(node: dict) -> dict:
    """Read a rack's shape out of its C++ geometry header.

    The header is the single source of truth for which bins exist: the ESPHome
    lambdas ask it, tests/cpp tests it, and this reads it so the Python side
    checks the same table rather than a second description of it.
    """
    text = GEOMETRY_FILES[node["substitutions"]["device_name"]].read_text()

    def constant(name: str) -> int:
        m = re.search(rf"constexpr int {name} = (\d+);", text)
        assert m, f"{name} missing from the geometry header"
        return int(m.group(1))

    table = re.search(r"constexpr rack::Column kColumns\[\] = \{(.*?)\};", text, re.S)
    if table:
        columns = [
            (int(first), int(bins))
            for first, bins in re.findall(r"\{\s*(\d+)\s*,\s*(\d+)\s*\}", table.group(1))
        ]
    else:
        # A rectangular rack needs no table: every column is the same.
        columns = [(0, constant("kBinsPerColumn"))] * constant("kEnvelopeColumns")

    return {
        "columns": columns,
        "leds_per_bin": constant("kLedsPerBin"),
        "bin_pitch": constant("kBinPitch"),
    }


def strand_leds(geo: dict, column: int) -> int:
    """The same arithmetic rack_geometry.h does, so the two can be compared."""
    bins = geo["columns"][column][1]
    return bins * geo["bin_pitch"] - (geo["bin_pitch"] - geo["leds_per_bin"])


def strands(node: dict) -> list[dict]:
    """Each light, and the bin column its lambda says it is."""
    out = []
    for light in node["light"]:
        body = light["effects"][0]["addressable_lambda"]["lambda"]
        m = re.search(r"constexpr int kCol = (\d+);", body)
        assert m, f"{light['id']} does not say which column it is"
        out.append({
            "id": light["id"],
            "col": int(m.group(1)),
            "num_leds": int(resolve(node, light["num_leds"])),
        })
    return out


def covered(node: dict) -> set[tuple[int, int]]:
    """Every (row, column) the geometry header says this rack has."""
    geo = geometry(node)
    return {
        (first + i, col)
        for col, (first, bins) in enumerate(geo["columns"])
        for i in range(bins)
    }


def test_rack_one_lights_exactly_the_bins_it_has():
    """The strands are the rack's shape, expressed in copper."""
    assert covered(NODE1) == set(RACK1_SHAPE)


def test_rack_two_lights_exactly_the_bins_it_has():
    assert covered(NODE2) == set(RACK2_SHAPE)


def test_every_column_of_the_u_is_contiguous():
    """This is why the strips run vertically rather than per row.

    A strand can only light a run of bins it can reach without a break. Every
    column of the U is such a run, so every strand is one uncut length of
    strip.
    """
    for col in range(13):
        rows = sorted(r for (r, c) in RACK1_SHAPE if c == col)
        assert rows == list(range(rows[0], rows[-1] + 1)), f"column {col + 1} has a gap"


def test_most_rows_of_the_u_are_not_contiguous():
    """And this is the other half of the argument.

    Eight of the thirteen rows are split by the U's opening. Running the strips
    per row would need a jumper carrying 12 V, ground and data across each of
    those gaps.
    """
    split = 0
    for row in range(13):
        cols = sorted(c for (r, c) in RACK1_SHAPE if r == row)
        if cols != list(range(cols[0], cols[-1] + 1)):
            split += 1
    assert split == 8


def test_one_strand_per_column_and_no_shared_pins():
    for node, cols in ((NODE1, 13), (NODE2, 7)):
        lights = node["light"]
        assert len(lights) == cols
        assert [light["id"] for light in lights] == [f"col_{i + 1:02d}" for i in range(cols)]
        assert sorted(s["col"] for s in strands(node)) == list(range(cols))
        pins = [light["pin"] for light in lights]
        assert len(set(pins)) == len(pins), "two strands share a data pin"


def test_no_strand_uses_a_pin_that_misbehaves_at_boot():
    """GPIO14 pulses during boot, which would flick a column at every reset.

    The strapping pins and the flash pins would be worse. This is the whole
    list of ESP32 pins not to drive an LED strand from.
    """
    avoid = {14, 0, 2, 5, 12, 15, 1, 3, 6, 7, 8, 9, 10, 11}
    for node in (NODE1, NODE2):
        for light in node["light"]:
            pin = int(re.sub(r"\D", "", str(light["pin"])))
            assert pin not in avoid, f"{light['id']} is on GPIO{pin}"


def test_the_short_strands_are_the_ones_in_the_us_opening():
    """Columns 5-9 exist only for rows I-M, so they are five bins, not thirteen."""
    columns = geometry(NODE1)["columns"]
    for col in range(4, 9):
        assert columns[col] == (8, 5), f"column {col + 1} should be rows I-M"
    for col in list(range(0, 4)) + list(range(9, 13)):
        assert columns[col] == (0, 13), f"column {col + 1} should be rows A-M"


def test_every_light_is_as_long_as_the_geometry_says_its_column_is():
    """`num_leds` has to be a literal in YAML, so it is a second copy of a
    number the header already knows. This is the only thing stopping the two
    from drifting - and a light one pixel short truncates its last bin."""
    for node in NODES.values():
        geo = geometry(node)
        for strand in strands(node):
            assert strand["num_leds"] == strand_leds(geo, strand["col"]), strand["id"]


def test_the_racks_agree_about_how_many_leds_light_a_bin():
    """Two racks that lit bins differently would read as two different systems."""
    assert geometry(NODE1)["leds_per_bin"] == geometry(NODE2)["leds_per_bin"]
    assert geometry(NODE1)["bin_pitch"] == geometry(NODE2)["bin_pitch"]


def test_the_geometry_headers_match_the_yaml_substitutions():
    """The substitutions are what the config's own arithmetic and comments use."""
    for node in NODES.values():
        geo = geometry(node)
        assert len(geo["columns"]) == subs(node, "rack_cols")
        assert geo["leds_per_bin"] == subs(node, "bin_leds")
        assert geo["bin_pitch"] == subs(node, "bin_pitch")
        assert max(f + b for f, b in geo["columns"]) == subs(node, "rack_rows")


# --------------------------------------------------------------------------
# The two halves of the example must agree with each other
# --------------------------------------------------------------------------
def _node_actions(node: dict) -> dict[str, set[str]]:
    """Every action a node declares, and the variables it takes."""
    return {
        action["action"]: set(action.get("variables") or {})
        for action in node["api"]["actions"]
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


def _split(call: str) -> tuple[str, str]:
    for device in NODES:
        if call.startswith(f"esphome.{device}_"):
            return device, call[len(f"esphome.{device}_"):]
    raise AssertionError(f"{call} does not name either node")


def test_the_package_calls_both_nodes():
    """The rest of this section proves nothing if it finds no calls."""
    devices = {_split(c["action"])[0] for c in _calls(PACKAGE)}
    assert devices == set(NODES)


def test_the_package_only_calls_actions_the_nodes_declare():
    for call in _calls(PACKAGE):
        device, name = _split(call["action"])
        assert name in _node_actions(NODES[device]), f"{call['action']} is not an action"


def test_every_field_the_package_sends_is_a_variable_the_node_takes():
    """Home Assistant requires every declared variable, and no others."""
    for call in _calls(PACKAGE):
        device, name = _split(call["action"])
        data = call.get("data")
        # A call that hands over a whole templated payload is checked where the
        # payload is built, not here.
        if isinstance(data, str):
            continue
        assert set(data or {}) == _node_actions(NODES[device])[name], call["action"]


def test_the_locate_script_sends_exactly_the_variables_light_bin_takes():
    """It builds its payload once and hands the same dict to either rack."""
    payload = PACKAGE["script"]["wine_rack_locate"]["sequence"][0]["variables"]["payload"]
    for node in NODES.values():
        assert set(payload) == _node_actions(node)["light_bin"]


def test_every_state_the_package_emits_is_a_state_the_nodes_draw():
    """The alphabet is the contract between the files.

    Each grid template ends by indexing a literal alphabet with a rank; the
    nodes switch on the same characters. Adding a state to one side without
    the other paints an occupied bin as empty.
    """
    for template in (GRID1, GRID2):
        alphabet = re.search(r"'([.A-Z]+)'\[rank\]", template)
        assert alphabet, "the template should render its states from one literal alphabet"
        emitted = set(alphabet.group(1)) - {"."}

        for node in NODES.values():
            render_script = next(s for s in node["script"] if s["id"] == "render")
            drawn = set(re.findall(r"case '([A-Z])':", render_script["then"][0]["lambda"]))
            assert emitted == drawn, "the package and a node disagree about the states"


def test_the_nodes_know_the_racks_the_package_is_describing():
    """Both sides carry each rack's shape; disagreeing means a shifted picture."""
    for template, node, location, letters in (
        (GRID1, NODE1, RACK1_LOCATION, 13),
        (GRID2, NODE2, RACK2_LOCATION, 7),
    ):
        assert f"set cols = {subs(node, 'rack_cols')}" in template
        assert re.search(rf"set rows = '[A-Z]{{{subs(node, 'rack_rows')}}}'", template)
        assert f"RACK_LOCATION = '{location}'" in template
        assert subs(node, "rack_rows") == letters


def test_the_two_racks_share_one_palette():
    """Two racks disagreeing about what amber means is worse than no colour."""
    keys = [k for k in NODE1["substitutions"] if k.startswith("colour_")]
    assert keys, "the palette should be in substitutions"
    for key in keys:
        assert NODE1["substitutions"][key] == NODE2["substitutions"][key], key
