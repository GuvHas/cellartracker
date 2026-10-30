"""The rack LED examples must keep telling the same story as the sensors.

``examples/`` ships two wine racks lit from this integration: a U-shaped rack
of 129 bins in a 13 x 13 envelope, and a plain 7 x 7 beside it. The U is two
ESPHome nodes - one Lightish E8-WiFi Plus for rows A-G, one for rows H-M - and
the 7 x 7 is a third. Each owns pixels and knows nothing about wine; two Home
Assistant blueprints, used once per rack, hand each node the integration's
per-rack grid sensor and drive its locator.

That grid, built in ``racks.py``, is a third implementation of the
drinking-window rule, after ``cellar_data.py`` and ``cellar.html``, so the
reasoning in
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

import math
import pathlib
import re
from urllib.parse import quote

import pytest
import yaml

from cellar_tracker.cellar_data import _drink_window_counts
from cellar_tracker.racks import STATES, bottles_off_rack, parse_racks, rack_grid

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"
NODE1A_FILE = EXAMPLES / "esphome" / "winerack1aled.yaml"
NODE1B_FILE = EXAMPLES / "esphome" / "winerack1bled.yaml"
NODE2_FILE = EXAMPLES / "esphome" / "winerack2led.yaml"
BLUEPRINTS = REPO_ROOT / "blueprints"
PAINT_FILE = BLUEPRINTS / "automation" / "cellar_tracker" / "wine_rack_paint.yaml"
CONTROLS_FILE = BLUEPRINTS / "script" / "cellar_tracker" / "wine_rack_controls.yaml"
WAKE_FILE = BLUEPRINTS / "automation" / "cellar_tracker" / "wine_rack_wake.yaml"
README_FILE = REPO_ROOT / "README.md"

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


NODE1A = _load(NODE1A_FILE)
NODE1B = _load(NODE1B_FILE)
NODE2 = _load(NODE2_FILE)
#: Rack 1's two halves carry the same rack - the same table, the same envelope,
#: the same actions - so anything about the rack as a whole reads NODE1, and
#: test_the_two_halves_of_rack_one_are_one_rack holds 1B to it.
NODE1 = NODE1A
RACK1_HALVES = (NODE1A, NODE1B)
PAINT = _load(PAINT_FILE)
CONTROLS = _load(CONTROLS_FILE)
WAKE = _load(WAKE_FILE)
BLUEPRINT_FILES = (PAINT_FILE, CONTROLS_FILE, WAKE_FILE)
NODES = {node["substitutions"]["device_name"]: node for node in (NODE1A, NODE1B, NODE2)}

# The rack lines the README tells you to type into the options, read the way
# the options flow reads them. Tested here so the instructions and the nodes
# cannot drift apart.
RACK_LINES = re.findall(r"^(Wine Rack \d+: .+)$", README_FILE.read_text(), re.MULTILINE)
RACK1, RACK2 = parse_racks("\n".join(RACK_LINES))


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
# What the integration's grid sensors hold for a cellar
# --------------------------------------------------------------------------
def bottle(bin_id: str, begin: str = "", end: str = "", location: str = RACK1_LOCATION) -> dict:
    return {
        "Bin": bin_id,
        "Location": location,
        "BeginConsume": begin,
        "EndConsume": end,
        "Wine": f"Wine in {bin_id}",
    }


def render(rack, bottles: list[dict]) -> str:
    """What the rack's grid sensor would hold for this cellar."""
    return rack_grid(bottles, rack, YEAR)


def grid(bottles: list[dict]) -> str:
    return render(RACK1, bottles)


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
    assert set(render(RACK1, in_two)) == {"."}
    assert cell(render(RACK2, in_two), "A1", cols=7) == "R"

    in_one = [bottle("A1", "2020", "2030", location=RACK1_LOCATION)]
    assert set(render(RACK2, in_one)) == {"."}
    assert cell(render(RACK1, in_one), "A1") == "R"


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
    assert bottles_off_rack(gone, RACK1) == 2


def test_bins_the_rack_still_has_are_not_orphans():
    kept = [bottle(f"{chr(ord('A') + r)}{c + 1}", "2020", "2030") for r, c in sorted(RACK1_SHAPE)]
    assert bottles_off_rack(kept, RACK1) == 0


def test_the_other_racks_bottles_are_not_rack_ones_orphans():
    assert bottles_off_rack([bottle("A1", "2020", "2030", location=RACK2_LOCATION)], RACK1) == 0


# --------------------------------------------------------------------------
# The grid has to fit both a Home Assistant state and the node's buffer
# --------------------------------------------------------------------------
def test_each_grid_is_one_character_per_bin_of_its_envelope():
    assert len(grid([])) == subs(NODE1, "rack_cells") == 13 * 13
    assert len(render(RACK2, [])) == subs(NODE2, "rack_cells") == 7 * 7


def test_the_grids_fit_in_a_state():
    """Home Assistant truncates a state longer than 255 characters."""
    assert len(grid(one_bottle_per_bin())) <= 255
    assert len(render(RACK2, [])) <= 255


def test_a_full_rack_is_still_one_character_per_bin():
    full = [bottle(f"{chr(ord('A') + r)}{c + 1}", "2020", "2030") for r, c in sorted(RACK1_SHAPE)]
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
        out.append(
            {
                "id": light["id"],
                "row": int(m.group(1)),
                "num_leds": int(resolve(node, light["num_leds"])),
            }
        )
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
    """Every row of each rack has exactly one strand, on exactly one board."""
    for nodes, rows in ((RACK1_HALVES, 13), ((NODE2,), 7)):
        lights = [light for node in nodes for light in node["light"]]
        assert len(lights) == rows
        assert [light["id"] for light in lights] == [
            f"row_{chr(ord('a') + i)}" for i in range(rows)
        ]
        assert [s["row"] for node in nodes for s in strands(node)] == list(range(rows))
        for node in nodes:
            pins = [light["pin"] for light in node["light"]]
            assert len(set(pins)) == len(pins), "two strands share a data pin"


def test_each_half_of_rack_one_drives_the_rows_it_says_it_does():
    """`node_first_row` and `node_rows` bound the render loop and the locator's
    ownership check; the lights are what is actually wired. They must agree,
    or a half would switch a strand on for a row it is not painting."""
    for node in RACK1_HALVES:
        first, count = subs(node, "node_first_row"), subs(node, "node_rows")
        assert [s["row"] for s in strands(node)] == list(range(first, first + count))
        render_script = next(s for s in node["script"] if s["id"] == "render")
        listed = re.findall(r"id\((row_[a-m])\)", render_script["then"][0]["lambda"])
        assert listed == [light["id"] for light in node["light"]]


def test_render_only_calls_the_strands_that_change():
    """Each light call logs and sends Home Assistant a state message. Calling
    all seven strands on every render turned a burst of dashboard clicks into
    a flood of messages and dropped rack 2's API connection, so a strand is
    called only when its on/off or its effect has to change."""
    for name, node in NODES.items():
        render_script = next(s for s in node["script"] if s["id"] == "render")
        body = render_script["then"][0]["lambda"]
        assert "remote_values.is_on()" in body, name
        assert "get_current_effect_index() != 1" in body, name
        assert "id(led_power).state" in body, name
        for light in node["light"]:
            assert [e["addressable_lambda"]["name"] for e in light["effects"]] == ["Rack"], (
                f"{name}: effect index 1 must be Rack"
            )


def test_nodes_keep_the_radio_awake_and_report_why_they_restarted():
    for name, node in NODES.items():
        assert node["wifi"]["power_save_mode"] == "none", name
        assert {s["platform"] for s in node["sensor"]} >= {"uptime", "wifi_signal"}, name
        debug = [s for s in node["text_sensor"] if s["platform"] == "debug"]
        assert debug and "reset_reason" in debug[0], name


#: A classic ESP32 has eight RMT channels with one 64-symbol memory block each.
RMT_BLOCK_SYMBOLS = 64
RMT_BLOCKS = 8


def test_every_strand_gets_rmt_memory():
    """Each strand claims `rmt_symbols` of RMT memory, in whole 64-symbol
    blocks, from the ESP32's 512. ESPHome's default of 192 takes three blocks a
    strand, so a seven-strand board starts two strands and marks the other
    five FAILED - which is what rack 2's first boot did."""
    for name, node in NODES.items():
        lights = node["light"]
        blocks = 0
        for light in lights:
            symbols = int(light.get("rmt_symbols", 192))
            assert symbols % RMT_BLOCK_SYMBOLS == 0, f"{name}: {light['id']}"
            blocks += symbols // RMT_BLOCK_SYMBOLS
        assert blocks <= RMT_BLOCKS, f"{name} needs {blocks} RMT blocks of {RMT_BLOCKS}"


def test_every_strand_sends_colours_in_the_strips_order():
    """The strip on the racks is RGB, measured: GRB lit red bins green.

    All three nodes drive the same strip, so a node left on another order
    would paint every ready bottle as past its window, or the reverse.
    """
    for name, node in NODES.items():
        for light in node["light"]:
            assert light.get("channel_colors") == "RGB", f"{name}: {light['id']}"
            assert "rgb_order" not in light, f"{name}: rgb_order is deprecated"


def test_rack_one_needs_no_more_data_lines_than_before():
    """Chaining each split row keeps rack 1 at thirteen data lines.

    That is what fits it on two seven-port controllers: seven rows on one and
    six on the other. Running each piece of a split row as its own strand
    would make it 21.
    """
    assert [len(node["light"]) for node in RACK1_HALVES] == [7, 6]


def test_the_two_halves_of_rack_one_are_one_rack():
    """1A and 1B differ in which rows they drive, their pins and their name.

    Everything else - the shape, the envelope, the arithmetic, the palette,
    the actions - is the same rack and must stay identical, or one half of the
    U would disagree with the other about where a bottle is.
    """
    allowed = {"device_name", "friendly_name", "node_first_row", "node_rows"}
    a, b = NODE1A["substitutions"], NODE1B["substitutions"]
    assert set(a) == set(b)
    for key in set(a) - allowed:
        assert a[key] == b[key], key
    assert _node_actions(NODE1A) == _node_actions(NODE1B)


#: ESP32 pins that cannot drive a strand on any board, whoever chose them.
#: 6-11 are the SPI flash. 12 is MTDI, which selects flash voltage at reset -
#: held high, a 3.3 V module does not boot at all. 34-39 are input-only.
PINS_NEVER = {6, 7, 8, 9, 10, 11, 12, 34, 35, 36, 37, 38, 39}

#: Pins to avoid when the choice is yours. These all work; they are just worse
#: than the alternatives. 14 emits a pulse during boot, 0/2/5/15 are strapping
#: pins, 1/3 are UART0 - so using them costs the serial console.
PINS_AVOID_IF_FREE = {0, 1, 2, 3, 5, 14, 15}

#: The pins a controller's fixed port map forces us to accept. Every node is a
#: Lightish E8-WiFi Plus, whose eight ports are GPIO 5, 12, 4, 27, 17, 26, 33
#: and 25. A seven-strand board may skip exactly one, and 12 is the one that
#: matters - GPIO5's worst case is a flicker at reset, GPIO12's is a board
#: that will not start. So GPIO5 is used, deliberately, on the two
#: seven-strand boards; rack 1's six-strand half skips it.
FIXED_PINOUT = {"winerack1aled": {5}, "winerack2led": {5}}

#: The E8-WiFi Plus's ports O1..O8, in order.
E8_PORTS = [5, 12, 4, 27, 17, 26, 33, 25]


def test_no_strand_uses_a_pin_that_cannot_drive_one():
    """The flash pins, MTDI and the input-only pins, on any board."""
    for node in NODES.values():
        for light in node["light"]:
            pin = int(re.sub(r"\D", "", str(light["pin"])))
            assert pin not in PINS_NEVER, f"{light['id']} is on GPIO{pin}"


def test_a_node_that_picks_its_own_pins_picks_good_ones():
    """A strapping pin has to be argued for, not appear by accident.

    The controller's eight ports are fixed in copper. FIXED_PINOUT records
    exactly which compromises that forces on each node, so a pin creeping onto
    this list fails here.
    """
    for name, node in NODES.items():
        allowed = FIXED_PINOUT.get(name, set())
        for light in node["light"]:
            pin = int(re.sub(r"\D", "", str(light["pin"])))
            if pin in allowed:
                continue
            assert pin not in PINS_AVOID_IF_FREE, f"{light['id']} is on GPIO{pin}"


def test_every_node_matches_its_controllers_port_map():
    """The pins are the E8-WiFi Plus's ports, so they cannot drift from it.

    Ports O1..O8 are GPIO 5, 12, 4, 27, 17, 26, 33, 25. Every board leaves O2
    (GPIO12) empty and uses the rest in port order from its top row down;
    rack 1's six-row half leaves O1 empty too.
    """
    for name, node in NODES.items():
        pins = [int(re.sub(r"\D", "", str(light["pin"]))) for light in node["light"]]
        assert set(pins) <= set(E8_PORTS), f"{name}: a pin that is not one of the board's ports"
        assert len(set(pins)) == len(pins), f"{name}: two strands on one port"
        assert 12 not in pins, f"{name}: port O2 should be left empty"
        assert pins == sorted(pins, key=E8_PORTS.index), f"{name}: rows out of port order"
        if len(pins) < 7:
            assert 5 not in pins, f"{name}: a six-strand board has no reason to use O1"


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
        action["action"]: set(action.get("variables") or {}) for action in node["api"]["actions"]
    }


def _calls(node: object) -> list[dict]:
    """Every ESPHome action call in a blueprint, wherever it is nested."""
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


#: A rack's boards are an input, so every call is templated over them.
_NODE_CALL = re.compile(r"esphome\.\{\{ repeat\.item \}\}_(\w+)")


def _action(call: dict) -> str:
    """The node action a call invokes, whichever board it goes to."""
    m = _NODE_CALL.fullmatch(call["action"])
    assert m, f"{call['action']} does not go through the rack's list of boards"
    return m.group(1)


def _blueprint_calls() -> list[dict]:
    return _calls(PAINT) + _calls(CONTROLS)


def test_the_blueprints_call_the_nodes():
    """The rest of this section proves nothing if it finds no calls."""
    names = {_action(c) for c in _blueprint_calls()}
    assert names == {"light_rack", "light_bin", "clear_all"}


def test_every_call_goes_to_every_board_on_the_rack():
    """Rack 1's halves each draw only their own rows, so a call that reached
    one half would leave the other showing a stale picture - or, for the
    locator, a lit overview beside the one bin you asked for. Every call sits
    in a loop over the rack's whole list of boards."""

    def check(node: object, in_loop: bool) -> None:
        if isinstance(node, dict):
            if "repeat" in node:
                assert node["repeat"]["for_each"] == "{{ node_names }}"
                check(node["repeat"]["sequence"], True)
                return
            if isinstance(node.get("action"), str) and node["action"].startswith("esphome."):
                assert in_loop, node["action"]
            for value in node.values():
                check(value, in_loop)
        elif isinstance(node, list):
            for item in node:
                check(item, in_loop)

    check(PAINT["actions"], False)
    check(CONTROLS["sequence"], False)


def test_the_blueprints_only_call_actions_the_nodes_declare():
    for call in _blueprint_calls():
        for device, node in NODES.items():
            assert _action(call) in _node_actions(node), f"{device} has no {_action(call)}"


def test_every_field_the_blueprints_send_is_a_variable_the_node_takes():
    """Home Assistant requires every declared variable, and no others."""
    for call in _blueprint_calls():
        data = call.get("data")
        # A call that hands over a whole templated payload is checked where the
        # payload is built, not here.
        if isinstance(data, str):
            continue
        for node in NODES.values():
            assert set(data or {}) == _node_actions(node)[_action(call)], call["action"]


def test_the_locator_sends_exactly_the_variables_light_bin_takes():
    """It builds its payload once and hands the same dict to every board."""
    locate = CONTROLS["sequence"][0]["choose"][0]["sequence"]
    payload = locate[0]["variables"]["payload"]
    for node in NODES.values():
        assert set(payload) == _node_actions(node)["light_bin"]


def test_the_blueprints_name_the_example_boards():
    """The node-name inputs tell you what to type; it must be what the
    example nodes are actually called, or the actions do not exist."""
    for blueprint in (PAINT, CONTROLS):
        text = blueprint["blueprint"]["input"]["nodes"]["description"]
        assert set(re.findall(r"winerack\w+", text)) == set(NODES)


def test_every_input_a_blueprint_declares_is_used_and_vice_versa():
    """An unused input is a question the user answers for nothing; an
    !input with no declaration fails to import."""
    for path in BLUEPRINT_FILES:
        text = path.read_text()
        declared = set(_load(path)["blueprint"]["input"])
        used = set(re.findall(r"!input (\w+)", text))
        assert declared == used, path.name


def test_the_blueprints_read_the_integrations_own_sensors():
    """The grid picker offers CellarTracker's sensors, not every sensor."""
    for blueprint in (PAINT, CONTROLS):
        selector = blueprint["blueprint"]["input"]["grid_sensor"]["selector"]["entity"]
        assert selector["filter"][0]["integration"] == "cellar_tracker"


def test_the_blueprints_point_at_where_they_live():
    """source_url is how Home Assistant re-imports a blueprint to update it."""
    for path in BLUEPRINT_FILES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        url = _load(path)["blueprint"]["source_url"]
        assert url == f"https://github.com/GuvHas/cellartracker/blob/main/{rel}"


def test_the_readme_imports_each_blueprint():
    """Each import button points at the file it claims to."""
    readme = README_FILE.read_text()
    for path in BLUEPRINT_FILES:
        url = f"https://github.com/GuvHas/cellartracker/blob/main/{path.relative_to(REPO_ROOT)}"
        assert f"blueprint_import/?blueprint_url={quote(url, safe='')}" in readme


def test_no_package_is_left_to_drift_from_the_blueprints():
    """One copy of the push logic. The old package is gone, not kept beside."""
    assert not (EXAMPLES / "home_assistant" / "wine_rack_leds.yaml").exists()


def test_every_state_the_integration_emits_is_a_state_the_nodes_draw():
    """The alphabet is the contract between the integration and the nodes.

    The grid sensors index racks.STATES with a rank; the nodes switch on the
    same characters. Adding a state to one side without the other paints an
    occupied bin as empty.
    """
    emitted = set(STATES) - {"."}
    for node in NODES.values():
        render_script = next(s for s in node["script"] if s["id"] == "render")
        drawn = set(re.findall(r"case '([A-Z])':", render_script["then"][0]["lambda"]))
        assert emitted == drawn, "the integration and a node disagree about the states"


def test_the_nodes_know_the_racks_the_readme_is_describing():
    """Both sides carry each rack's shape; disagreeing means a shifted picture."""
    for rack, node, location, shape in (
        (RACK1, NODE1A, RACK1_LOCATION, RACK1_SHAPE),
        (RACK1, NODE1B, RACK1_LOCATION, RACK1_SHAPE),
        (RACK2, NODE2, RACK2_LOCATION, RACK2_SHAPE),
    ):
        assert rack.location == location
        assert rack.rows == subs(node, "rack_rows")
        assert rack.cols == subs(node, "rack_cols")
        assert rack.cells == subs(node, "rack_cells")
        envelope = {(r, c) for r in range(rack.rows) for c in range(rack.cols)}
        assert {cell for cell in envelope if rack.has(cell)} == shape


def test_the_blueprints_need_no_token():
    """The whole point of moving the grid into the integration."""
    for path in BLUEPRINT_FILES:
        assert "!secret" not in path.read_text()
        assert "rest" not in _load(path)


def test_the_two_racks_share_one_palette():
    """Two racks disagreeing about what amber means is worse than no colour."""
    keys = [k for k in NODE1["substitutions"] if k.startswith("colour_")]
    assert keys, "the palette should be in substitutions"
    for key in keys:
        for node in NODES.values():
            assert node["substitutions"][key] == NODE1["substitutions"][key], key


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
        for device, node in NODES.items():
            assert node["substitutions"][name] == NODE1["substitutions"][name], (
                f"{device} disagrees about {name}"
            )


def test_a_node_is_one_file_with_nothing_beside_it():
    """No `includes:`, and no C++ left in examples/ to forget to copy.

    The whole point of moving the coordinate map into `substitutions:` is that
    flashing a rack is copying one file. An `includes:` that crept back would
    compile perfectly well here and fail for whoever copied only the YAML.
    """
    for node in NODES.values():
        assert "includes" not in node.get("esphome", {}), "the node needs a file beside it"

    stray = sorted(p.name for p in (EXAMPLES / "esphome").glob("*.h"))
    assert stray == [], f"C++ left beside the configs: {stray}"


def test_the_lambdas_paste_the_map_rather_than_retyping_it():
    """Every strand's lambda is its row number and three substitutions.

    A lambda that spelled the arithmetic out again would pass every test in
    this file and every test in tests/cpp - because neither would be reading
    it - right up until it disagreed with the other twelve.
    """
    for node in NODES.values():
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


def test_every_sync_repaints_even_when_the_grid_has_not_changed():
    """An unchanged grid fires no state change, so a rack that was turned off
    would otherwise stay dark until a bottle moved."""
    watched = {str(t.get("entity_id")) for t in PAINT["triggers"]}
    assert {"grid_sensor", "sync_sensor", "board_lights"} <= watched


def test_show_overview_cancels_a_locator_before_painting():
    """light_rack leaves a running locator on top; only clear_all cancels it."""
    overview = CONTROLS["sequence"][0]["default"]
    assert [_action(c) for c in _calls(overview)] == ["clear_all", "light_rack"]


def test_each_command_does_what_its_label_says():
    options = CONTROLS["fields"]["command"]["selector"]["select"]["options"]
    assert {o["value"] for o in options} == {"locate", "overview", "off"}
    locate, off = CONTROLS["sequence"][0]["choose"]
    assert "'locate'" in locate["conditions"]
    assert [_action(c) for c in _calls(locate)] == ["light_bin"]
    assert "'off'" in off["conditions"]
    assert [_action(c) for c in _calls(off)] == ["clear_all"]


def test_the_paint_automation_answers_the_dashboards_events():
    """The integration fires these by name; a renamed trigger would leave the
    dashboard's taps and filters lighting nothing, silently."""
    from cellar_tracker.const import EVENT_RACK_LOCATE, EVENT_RACK_PAINT

    listened = {t["event_type"] for t in PAINT["triggers"] if t["trigger"] == "event"}
    assert listened == {EVENT_RACK_LOCATE, EVENT_RACK_PAINT}


def test_each_rack_answers_only_events_for_its_own_location():
    conditions = " ".join(str(c.get("value_template")) for c in PAINT["conditions"])
    assert "trigger.event.data.location == rack_location" in conditions
    assert PAINT["variables"]["rack_location"] == "{{ state_attr(grid_sensor, 'location') }}"


def test_a_highlight_from_the_dashboard_cancels_a_locator_first():
    dashboard = next(
        c for c in PAINT["actions"][0]["choose"] if c["conditions"][0]["id"] == "dashboard"
    )
    assert [_action(c) for c in _calls(dashboard)] == ["clear_all", "light_rack"]


# --------------------------------------------------------------------------
# Racks that go dark when left alone
# --------------------------------------------------------------------------
def _repaint_guard() -> str:
    default = PAINT["actions"][0]["default"]
    return default[0]["value_template"]


def test_a_background_repaint_only_ever_paints_over_the_overview():
    """A sync, a grid change or a board coming back must not light a rack that
    went dark, nor wipe a highlight someone is looking at."""
    jinja2 = pytest.importorskip("jinja2")
    template = jinja2.Environment().from_string(_repaint_guard())
    for showing, repaint in (
        ("overview", True),
        ("off", False),
        ("highlight", False),
        (None, True),
    ):
        rendered = template.render(state_attr=lambda entity, name, s=showing: s, grid_sensor="x")
        assert rendered.strip() == str(repaint), showing


def test_the_showing_attribute_changing_is_not_a_reason_to_repaint():
    """It changes with every dashboard request; only the grid and the sync
    themselves are."""
    by_id = {t["id"]: t for t in PAINT["triggers"] if t["trigger"] == "state"}
    assert "to" in by_id["grid"] and by_id["grid"]["to"] is None
    assert "to" in by_id["synced"] and by_id["synced"]["to"] is None


def test_the_showing_values_the_blueprint_checks_are_the_integrations():
    from typing import get_args

    from cellar_tracker.rack_lights import Showing

    (listed,) = re.findall(r"not in \[([^\]]*)\]", _repaint_guard())
    quoted = set(re.findall(r"'(\w+)'", listed))
    assert quoted == set(get_args(Showing)) - {"overview"}


def test_walking_in_asks_for_the_overview_only_if_the_racks_are_dark():
    (action,) = WAKE["actions"]
    assert action["action"] == "cellar_tracker.show_overview"
    assert action["data"] == {"only_if_dark": True}
    (trigger,) = WAKE["triggers"]
    assert trigger["to"] == "on"
    selector = WAKE["blueprint"]["input"]["sensors"]["selector"]["entity"]
    assert selector["multiple"] is True


def test_the_wake_blueprint_needs_no_node_names():
    """One for the whole cellar: the paint automations do the lighting."""
    assert set(WAKE["blueprint"]["input"]) == {"sensors"}


# --------------------------------------------------------------------------
# The node names box
# --------------------------------------------------------------------------
def _node_names(blueprint: dict, nodes: object) -> list[str]:
    """Render the blueprint's own node_names template, as Home Assistant would."""
    jinja2 = pytest.importorskip("jinja2")
    template = blueprint["variables"]["node_names"]
    rendered = jinja2.Environment().from_string(template).render(nodes=nodes)
    return yaml.safe_load(rendered)


def test_the_node_names_are_one_box():
    """A multi-entry text field keeps an entry only once you press Enter, and
    Home Assistant then refuses the whole form with "Missing input nodes".
    Reported 2026-10-27. One box, separated by commas, has no such step."""
    for blueprint in (PAINT, CONTROLS):
        assert blueprint["blueprint"]["input"]["nodes"]["selector"] == {"text": None}


def test_node_names_are_read_however_they_are_typed():
    for blueprint in (PAINT, CONTROLS):
        for typed in (
            "winerack1aled, winerack1bled",
            "winerack1aled,winerack1bled",
            " WineRack1aLED  winerack1bled ",
            "winerack1aled,\nwinerack1bled,",
        ):
            assert _node_names(blueprint, typed) == ["winerack1aled", "winerack1bled"], typed
        # ESPHome turns a dash in a node's name into an underscore in its actions.
        assert _node_names(blueprint, "rack-a, rack-b") == ["rack_a", "rack_b"]


def test_automations_saved_with_a_list_of_names_keep_working():
    """Made before the box was one, they hold a list."""
    for blueprint in (PAINT, CONTROLS):
        assert _node_names(blueprint, ["winerack1aled", " winerack1b-led"]) == [
            "winerack1aled",
            "winerack1b_led",
        ]
