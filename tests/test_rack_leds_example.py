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
and the wiring against the shape of the rack. The strips run horizontally along
the back of the rack - one strand per bin row - because a strip holder anywhere
else covers a bin's opening. The U splits eight of rack 1's rows in two; each
of those is still one strand, its two pieces chained by a jumper across the
opening, and this file asserts that the row table describes exactly that.
"""

from __future__ import annotations

import datetime
import math
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
def geometry(node: dict) -> dict:
    """Read a rack's shape out of its own configuration.

    The rack's shape is the `rack_table` substitution and nothing else - the
    same characters the lambdas paste in and tests/cpp compiles. Each row is
    up to two pieces of strip, `{first column, bins, first column, bins}`, in
    the order the data reaches them.
    """
    subs_ = node["substitutions"]
    rows = [
        ((int(a_first), int(a_bins)), (int(b_first), int(b_bins)))
        for a_first, a_bins, b_first, b_bins in re.findall(
            r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}", subs_["rack_table"]
        )
    ]
    assert len(rows) == int(subs_["rack_rows"]), "rack_table does not cover every row"
    return {
        "rows": rows,
        "bin_width_mm": int(subs_["bin_width_mm"]),
        "strip_density": int(subs_["strip_density"]),
    }


def pieces(geo: dict, row: int) -> list[tuple[int, int]]:
    """The pieces of strip a row is made of, leaving out an empty second one."""
    return [(first, bins) for first, bins in geo["rows"][row] if bins > 0]


def edge(geo: dict, k: int) -> int:
    """The first LED whose centre lies past the k-th bin wall of a piece.

    Written independently of the C++ - in floats, from the definition - so the
    two can be compared rather than one copied from the other.
    """
    spacing_mm = 1000 / geo["strip_density"]
    return math.ceil(k * geo["bin_width_mm"] / spacing_mm - 0.5)


def piece_leds(geo: dict, bins: int) -> int:
    """The LEDs whose centres fall inside a piece's `bins` bins."""
    return edge(geo, bins)


def strand_leds(geo: dict, row: int) -> int:
    """How long that row's strip is: its pieces end to end. The jumper between
    them carries power and data and no pixels."""
    return sum(piece_leds(geo, bins) for _, bins in pieces(geo, row))


def strands(node: dict) -> list[dict]:
    """Each light, and the bin row its lambda says it is."""
    out = []
    for light in node["light"]:
        body = light["effects"][0]["addressable_lambda"]["lambda"]
        m = re.search(r"constexpr int kRow = (\d+);", body)
        assert m, f"{light['id']} does not say which row it is"
        out.append({
            "id": light["id"],
            "row": int(m.group(1)),
            "num_leds": int(resolve(node, light["num_leds"])),
        })
    return out


def covered(node: dict) -> set[tuple[int, int]]:
    """Every (row, column) the rack_table says this rack has."""
    geo = geometry(node)
    return {
        (row, first + i)
        for row in range(len(geo["rows"]))
        for first, bins in pieces(geo, row)
        for i in range(bins)
    }


def runs(cols: list[int]) -> list[tuple[int, int]]:
    """Sorted columns as contiguous (first, length) runs."""
    out: list[tuple[int, int]] = []
    for c in cols:
        if out and out[-1][0] + out[-1][1] == c:
            out[-1] = (out[-1][0], out[-1][1] + 1)
        else:
            out.append((c, 1))
    return out


def test_rack_one_lights_exactly_the_bins_it_has():
    """The strands are the rack's shape, expressed in copper."""
    assert covered(NODE1) == set(RACK1_SHAPE)


def test_rack_two_lights_exactly_the_bins_it_has():
    assert covered(NODE2) == set(RACK2_SHAPE)


def test_every_piece_of_strip_is_one_unbroken_run_of_bins():
    """A piece of strip can only light bins it reaches without a break.

    So each piece in the table must be exactly one contiguous run of the
    rack's shape - not two runs glued together, which would put pixels
    behind the U's opening, and not half a run, which would leave a bin dark.
    """
    for node, shape in ((NODE1, RACK1_SHAPE), (NODE2, RACK2_SHAPE)):
        geo = geometry(node)
        for row in range(len(geo["rows"])):
            cols = sorted(c for (r, c) in shape if r == row)
            assert pieces(geo, row) == runs(cols), f"row {chr(ord('A') + row)}"


def test_eight_rows_of_the_u_need_a_jumper():
    """Rows A-H are split by the U's opening and rows I-M are not.

    One strand per row means one jumper per split row: eight, each carrying
    12 V, ground and data across the opening. No row is split more than once,
    which is why the table has room for exactly two pieces.
    """
    geo = geometry(NODE1)
    split = [row for row in range(13) if len(pieces(geo, row)) == 2]
    assert split == list(range(8))
    for row in range(13):
        cols = sorted(c for (r, c) in RACK1_SHAPE if r == row)
        assert len(runs(cols)) <= 2, f"row {chr(ord('A') + row)} has more than one gap"


def test_rack_two_has_no_jumpers():
    geo = geometry(NODE2)
    assert all(len(pieces(geo, row)) == 1 for row in range(7))


def test_pieces_are_listed_in_the_order_the_data_reaches_them():
    """Data enters at the bin-1 end, so the first piece is the leftmost."""
    for node in NODES.values():
        geo = geometry(node)
        for row in range(len(geo["rows"])):
            firsts = [first for first, _ in pieces(geo, row)]
            assert firsts == sorted(firsts), f"row {chr(ord('A') + row)}"
            assert firsts[0] == 0, "every row's feed is at bin 1"


def test_one_strand_per_row_and_no_shared_pins():
    for node, rows in ((NODE1, 13), (NODE2, 7)):
        lights = node["light"]
        assert len(lights) == rows
        assert [light["id"] for light in lights] == [
            f"row_{chr(ord('a') + i)}" for i in range(rows)
        ]
        assert [s["row"] for s in strands(node)] == list(range(rows))
        pins = [light["pin"] for light in lights]
        assert len(set(pins)) == len(pins), "two strands share a data pin"


def test_rack_one_needs_no_more_data_lines_than_before():
    """Chaining each split row keeps rack 1 at thirteen data lines.

    That is what lets it stay on two seven-port controllers. Running each
    piece of a split row as its own strand would make it 21.
    """
    assert len(NODE1["light"]) == 13


#: ESP32 pins that cannot drive a strand on any board, whoever chose them.
#: 6-11 are the SPI flash. 12 is MTDI, which selects flash voltage at reset -
#: held high, a 3.3 V module does not boot at all. 34-39 are input-only.
PINS_NEVER = {6, 7, 8, 9, 10, 11, 12, 34, 35, 36, 37, 38, 39}

#: Pins to avoid when the choice is yours. These all work; they are just worse
#: than the alternatives. 14 emits a pulse during boot, 0/2/5/15 are strapping
#: pins, 1/3 are UART0 - so using them costs the serial console.
PINS_AVOID_IF_FREE = {0, 1, 2, 3, 5, 14, 15}

#: Nodes whose pins are fixed by the controller they run on, and the pins that
#: controller forces us to accept. Rack 2 is a Lightish E8-WiFi Plus, whose
#: eight ports are GPIO 5, 12, 4, 27, 17, 26, 33 and 25. Seven strands out of
#: eight ports means exactly one may be skipped, and 12 is the one that
#: matters - GPIO5's worst case is a flicker at reset, GPIO12's is a board
#: that will not start. So GPIO5 is used, deliberately.
FIXED_PINOUT = {"winerack2led": {5}}


def test_no_strand_uses_a_pin_that_cannot_drive_one():
    """The flash pins, MTDI and the input-only pins, on any board."""
    for node in NODES.values():
        for light in node["light"]:
            pin = int(re.sub(r"\D", "", str(light["pin"])))
            assert pin not in PINS_NEVER, f"{light['id']} is on GPIO{pin}"


def test_a_node_that_picks_its_own_pins_picks_good_ones():
    """Rack 1 is a bare ESP32, so it has no excuse for a strapping pin.

    Rack 2 does: its controller's eight ports are fixed in copper. FIXED_PINOUT
    records exactly which compromises that forces, so a pin creeping onto this
    list has to be argued for rather than appearing by accident.
    """
    for name, node in NODES.items():
        allowed = FIXED_PINOUT.get(name, set())
        for light in node["light"]:
            pin = int(re.sub(r"\D", "", str(light["pin"])))
            if pin in allowed:
                continue
            assert pin not in PINS_AVOID_IF_FREE, f"{light['id']} is on GPIO{pin}"


def test_rack_two_matches_its_controllers_port_map():
    """The pins are the E8-WiFi Plus's ports, so they cannot drift from it.

    Ports O1..O8 are GPIO 5, 12, 4, 27, 17, 26, 33, 25. Rack 2 uses seven of
    them with O2 (GPIO12) left empty, in port order from row A down.
    """
    e8_ports = [5, 12, 4, 27, 17, 26, 33, 25]
    pins = [int(re.sub(r"\D", "", str(light["pin"]))) for light in NODE2["light"]]

    assert set(pins) <= set(e8_ports), "a pin that is not one of the board's ports"
    assert len(set(pins)) == len(pins), "two strands on one port"
    assert 12 not in pins, "port O2 should be left empty"
    assert len(pins) == 7


def test_the_split_rows_are_the_arms_of_the_u():
    """Rows A-H are bins 1-4 and 10-13; rows I-M are all thirteen."""
    rows = geometry(NODE1)["rows"]
    for row in range(0, 8):
        assert rows[row] == ((0, 4), (9, 4)), f"row {chr(ord('A') + row)} should be split"
    for row in range(8, 13):
        assert rows[row] == ((0, 13), (0, 0)), f"row {chr(ord('A') + row)} should be whole"


def test_every_light_is_as_long_as_the_geometry_says_its_row_is():
    """`num_leds` has to be a literal in YAML, so it is a second copy of a
    number `rack_table` already implies. This is the only thing stopping the
    two from drifting - and a light one pixel short truncates its last bin,
    which on a split row is bin 13, on the far side of the jumper."""
    for node in NODES.values():
        geo = geometry(node)
        for strand in strands(node):
            assert strand["num_leds"] == strand_leds(geo, strand["row"]), strand["id"]


def test_rack_one_powers_738_pixels():
    geo = geometry(NODE1)
    assert sum(strand_leds(geo, row) for row in range(13)) == 738
    assert subs(NODE1, "split_strand") == 2 * piece_leds(geo, 4) == 46
    assert subs(NODE1, "full_strand") == piece_leds(geo, 13) == 74


def test_rack_two_powers_280_pixels():
    geo = geometry(NODE2)
    assert sum(strand_leds(geo, row) for row in range(7)) == 280
    assert subs(NODE2, "strand_leds") == piece_leds(geo, 7) == 40


def test_no_bin_drifts_along_a_row():
    """A 95 mm bin is 5.7 LEDs at 60/m, so a fixed whole number per bin would
    walk off the rack - 6 a bin is four LEDs out by bin 13. Placing bins by
    position keeps every bin's first LED within one LED of its wall."""
    for node in NODES.values():
        geo = geometry(node)
        spacing_mm = 1000 / geo["strip_density"]
        for k in range(subs(node, "rack_cols") + 1):
            centre_mm = (edge(geo, k) + 0.5) * spacing_mm
            wall_mm = k * geo["bin_width_mm"]
            assert 0 <= centre_mm - wall_mm < spacing_mm, f"bin wall {k}"


def test_every_bin_gets_five_or_six_leds():
    geo = geometry(NODE1)
    counts = [edge(geo, k + 1) - edge(geo, k) for k in range(13)]
    assert set(counts) <= {5, 6}, counts


def test_the_racks_agree_about_how_many_leds_light_a_bin():
    """Two racks that lit bins differently would read as two different systems."""
    assert geometry(NODE1)["bin_width_mm"] == geometry(NODE2)["bin_width_mm"]
    assert geometry(NODE1)["strip_density"] == geometry(NODE2)["strip_density"]


def test_the_row_table_agrees_with_the_rest_of_the_substitutions():
    """`rack_table` and the plain numbers beside it describe one rack.

    `rack_cols` and `rack_rows` size the state arrays and bound the action
    handlers; the table decides which of those cells a strand can reach. A
    table that outgrew them would light bins the envelope has no room for.
    """
    for node in NODES.values():
        geo = geometry(node)
        assert len(geo["rows"]) == subs(node, "rack_rows")
        ends = [first + bins for row in range(len(geo["rows"])) for first, bins in pieces(geo, row)]
        assert max(ends) == subs(node, "rack_cols")


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


# --------------------------------------------------------------------------
# One copy of the maths, in the file that uses it
# --------------------------------------------------------------------------
#: The substitutions that hold C++ rather than a value. tests/cpp lifts these
#: same blocks out and compiles them, which is what makes an inline YAML lambda
#: testable at all; these two tests guard the properties that arrangement
#: depends on.
CPP_SUBSTITUTIONS = ("bin_first_led", "row_extent", "paint_row", "parse_bin_id")


def test_both_nodes_ship_the_same_coordinate_map():
    """Two racks, two files, one piece of arithmetic.

    This is what a shared header used to buy and what the racks would quietly
    lose without it: rack 2 drifting to a different pitch, or keeping the old
    column-wise indexing after rack 1 was rewired, would show up as two rooms
    disagreeing about where a bottle is rather than as a failure anywhere.

    Compared before substitution, so the parameters they legitimately differ
    on - `${rack_cols}`, `${bin_width_mm}` - are still references and only a real
    difference in the maths registers.
    """
    for name in CPP_SUBSTITUTIONS:
        one = NODE1["substitutions"][name]
        two = NODE2["substitutions"][name]
        assert one == two, f"the two nodes disagree about {name}"


def test_a_node_is_one_file_with_nothing_beside_it():
    """No `includes:`, and no C++ left in examples/ to forget to copy.

    The whole point of moving the coordinate map into `substitutions:` is that
    flashing a rack is copying one file. An `includes:` that crept back would
    compile perfectly well here and fail for whoever copied only the YAML.
    """
    for node in (NODE1, NODE2):
        assert "includes" not in node.get("esphome", {}), "the node needs a file beside it"

    stray = sorted(p.name for p in (EXAMPLES / "esphome").glob("*.h"))
    assert stray == [], f"C++ left beside the configs: {stray}"


def test_the_lambdas_paste_the_map_rather_than_retyping_it():
    """Every strand's lambda is its row number and three substitutions.

    A lambda that spelled the arithmetic out again would pass every test in
    this file and every test in tests/cpp - because neither would be reading
    it - right up until it disagreed with the other twelve.
    """
    for node in (NODE1, NODE2):
        for light in node["light"]:
            body = light["effects"][0]["addressable_lambda"]["lambda"]
            statements = [line.strip() for line in body.splitlines() if line.strip()]
            assert statements == [
                statements[0],
                "${row_extent}",
                "${bin_first_led}",
                "${paint_row}",
            ], f"{light['id']} has maths of its own"
            assert re.fullmatch(r"constexpr int kRow = \d+;", statements[0]), light["id"]
