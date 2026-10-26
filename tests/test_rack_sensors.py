"""Rack grids as sensors of the integration.

These used to be Jinja templates in a Home Assistant package, fed by a REST
sensor reading the integration's own inventory endpoint back with a
long-lived access token. test_rack_leds_example.py checks the grid against the
drink-window sensors and the ESPHome nodes; this file covers the parts that
are the integration's own: reading the options, computing during the poll,
and the entities.
"""

from __future__ import annotations

import asyncio

import pytest

from cellar_tracker.cellar_data import WineCellarData
from cellar_tracker.config_flow import CellarTrackerOptionsFlowHandler
from cellar_tracker.const import CONF_RACKS, DOMAIN
from cellar_tracker.racks import Rack, format_racks, parse_bin, parse_racks
from cellar_tracker.sensor import RackGridSensor, RackOffRackSensor, async_setup_entry
from conftest import ConfigEntry, FakeHass, FakeSession, ViewHass

RACKS = "Wine Rack 1: 13x13 without A5-H9\nWine Rack 2: 7x7"


# --------------------------------------------------------------------------
# Reading the options field
# --------------------------------------------------------------------------
def test_both_racks_are_read():
    one, two = parse_racks(RACKS)
    assert (one.location, one.rows, one.cols) == ("Wine Rack 1", 13, 13)
    assert (two.location, two.rows, two.cols, two.missing) == ("Wine Rack 2", 7, 7, frozenset())


def test_a_range_removes_a_rectangle():
    rack = parse_racks("R: 13x13 without A5-H9")[0]
    assert len(rack.missing) == 8 * 5
    assert not rack.has((0, 4)) and not rack.has((7, 8))
    assert rack.has((0, 3)) and rack.has((8, 4)) and rack.has((0, 9))


def test_a_range_can_be_written_either_way_round():
    assert parse_racks("R: 9x9 without H9-A5")[0].missing == parse_racks(
        "R: 9x9 without A5-H9"
    )[0].missing


def test_single_bins_and_ranges_mix():
    rack = parse_racks("R: 4x4 without A1, d-4, B2-C3")[0]
    assert rack.missing == {(0, 0), (3, 3), (1, 1), (1, 2), (2, 1), (2, 2)}


def test_blank_lines_comments_and_spacing_are_forgiven():
    racks = parse_racks("\n  # the cellar\n  Wine Rack 2 :  7 X 7  \n\n")
    assert racks == [Rack("Wine Rack 2", 7, 7)]


def test_a_location_may_contain_a_colon():
    assert parse_racks("Cellar: north wall: 2x3")[0].location == "Cellar: north wall"


def test_nothing_configured_is_no_racks():
    assert parse_racks(None) == []
    assert parse_racks("") == []


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("Wine Rack 2", "Line 1"),
        ("Wine Rack 2: 7", "Line 1"),
        ("A: 2x2\nB: 0x7", "Line 2"),
        ("A: 27x2", "26 rows"),
        ("A: 16x16", "256 bins"),
        ("A: 2x2\na: 3x3", "listed twice"),
        ("A: 2x2 without Z9", "outside"),
        ("A: 2x2 without banana", "not a bin"),
    ],
)
def test_a_bad_line_is_refused_with_its_line_number(text, complaint):
    with pytest.raises(ValueError, match=complaint):
        parse_racks(text)


def test_format_reads_back_to_the_same_racks():
    racks = parse_racks(RACKS)
    assert parse_racks(format_racks(racks)) == racks


@pytest.mark.parametrize(
    ("written", "cell"),
    [("D2", (3, 1)), ("d-2", (3, 1)), ("D 2", (3, 1)), ("D02", (3, 1)), ("A0", None), ("7", None)],
)
def test_bins_are_read_the_way_people_write_them(written, cell):
    assert parse_bin(written) == cell


# --------------------------------------------------------------------------
# The options flow
# --------------------------------------------------------------------------
def options_flow(options=None) -> CellarTrackerOptionsFlowHandler:
    flow = CellarTrackerOptionsFlowHandler()
    flow.config_entry = ConfigEntry(
        data={"username": "a", "password": "b"}, options=options or {}
    )
    return flow


def submit(flow, racks):
    user_input = {"scan_interval": 21600, "currency": "USD"}
    if racks is not None:
        user_input[CONF_RACKS] = racks
    return asyncio.run(flow.async_step_init(user_input))


def test_valid_racks_are_saved_as_typed():
    result = submit(options_flow(), RACKS)
    assert result["type"] == "create_entry"
    assert result["data"][CONF_RACKS] == RACKS


def test_leaving_the_field_empty_is_fine():
    assert submit(options_flow(), None)["type"] == "create_entry"


def test_invalid_racks_are_refused_with_the_reason():
    result = submit(options_flow(), "Wine Rack 1: 13x13\nWine Rack 2: 7")
    assert result["type"] == "form"
    assert result["errors"] == {CONF_RACKS: "invalid_racks"}
    assert "Line 2" in result["description_placeholders"]["racks_problem"]


def test_a_refused_submit_keeps_what_was_typed():
    typed = "Wine Rack 1: 13x13\nWine Rack 2: 7"
    result = submit(options_flow({CONF_RACKS: "old"}), typed)
    (key,) = [k for k in result["data_schema"].schema if k == CONF_RACKS]
    assert key.description == {"suggested_value": typed}


def test_the_form_shows_the_saved_racks():
    result = asyncio.run(options_flow({CONF_RACKS: RACKS}).async_step_init(None))
    (key,) = [k for k in result["data_schema"].schema if k == CONF_RACKS]
    assert key.description == {"suggested_value": RACKS}


# --------------------------------------------------------------------------
# Computed with the poll
# --------------------------------------------------------------------------
EXPORT = (
    "iWine\tWine\tValuation\tLocation\tBin\tBeginConsume\tEndConsume\n"
    "1\tBarolo\t40\tWine Rack 2\tA1\t2020\t2040\n"
    "2\tRioja\t20\tWine Rack 2\tA1\t2000\t2010\n"
    "3\tChablis\t30\tWine Rack 1\tA7\t2020\t2040\n"
    "4\tMosel\t10\tWine Rack 1\tM13\t2030\t2040\n"
    "5\tCava\t10\tFridge\tA1\t\t\n"
)


def poll(options):
    hass = FakeHass()
    hass.session = FakeSession(text=EXPORT)
    coordinator = WineCellarData(
        hass, ConfigEntry(data={"username": "a", "password": "b"}, options=options)
    )
    coordinator._current_year = lambda: 2026
    return coordinator, asyncio.run(coordinator._async_update_data())


def test_each_rack_gets_its_grid_and_off_rack_count():
    _, data = poll({CONF_RACKS: RACKS})
    one, two = data["racks"]["Wine Rack 1"], data["racks"]["Wine Rack 2"]

    # Past beats ready in a shared bin; the fridge bottle lights nothing.
    assert two["grid"] == "P" + "." * 48
    assert two["off_rack"] == 0

    # A7 is in the U's opening: dark, and counted.
    assert one["grid"] == "." * 168 + "A"
    assert one["off_rack"] == 1


def test_no_racks_means_an_empty_mapping():
    _, data = poll({})
    assert data["racks"] == {}


def test_racks_that_no_longer_parse_do_not_break_the_poll(caplog):
    coordinator, data = poll({CONF_RACKS: "nonsense"})
    assert coordinator.racks == []
    assert data["racks"] == {}
    assert data["total_bottles"] == 5
    assert "rack configuration" in caplog.text


# --------------------------------------------------------------------------
# The entities
# --------------------------------------------------------------------------
class _Coordinator:
    currency = "USD"
    last_success = None

    def __init__(self, racks, data):
        self.racks = racks
        self.data = data


def build(racks, data):
    entry = ConfigEntry(entry_id="e1", data={"username": "alice", "password": "x"})
    entry.runtime_data = _Coordinator(racks, data)
    added: list = []
    asyncio.run(
        async_setup_entry(ViewHass({DOMAIN: {"e1": entry.runtime_data}}), entry, added.extend)
    )
    return [s for s in added if isinstance(s, RackGridSensor | RackOffRackSensor)]


DATA = {
    "total_bottles": 1,
    "total_value": 0.0,
    "bottles": [],
    "ready_to_drink": 0,
    "past_drink_window": 1,
    "racks": {"Wine Rack 2": {"grid": "P" + "." * 48, "off_rack": 2}},
}


def test_no_racks_no_rack_entities():
    assert build([], DATA) == []


def test_two_entities_per_rack():
    grid, off = build([Rack("Wine Rack 2", 7, 7)], DATA)
    assert isinstance(grid, RackGridSensor) and isinstance(off, RackOffRackSensor)
    assert grid.native_value == "P" + "." * 48
    assert off.native_value == 2


def test_the_rack_name_reaches_the_translated_entity_name():
    for sensor in build([Rack("Wine Rack 2", 7, 7)], DATA):
        assert sensor.translation_placeholders == {"rack": "Wine Rack 2"}


def test_the_grid_says_which_rack_it_describes():
    grid, _ = build([Rack("Wine Rack 2", 7, 7)], DATA)
    assert grid.extra_state_attributes == {"location": "Wine Rack 2", "rows": 7, "columns": 7}


def test_unknown_until_a_poll_has_seen_the_rack():
    """A rack added in the options has no state until the reload's poll."""
    for data in (None, {**DATA, "racks": {}}, {k: v for k, v in DATA.items() if k != "racks"}):
        grid, off = build([Rack("Wine Rack 2", 7, 7)], data)
        assert grid.native_value is None
        assert off.native_value is None


def test_unique_ids_follow_the_location_not_the_order():
    first = {s.unique_id for s in build([Rack("A", 1, 1), Rack("B", 1, 1)], None)}
    second = {s.unique_id for s in build([Rack("B", 1, 1), Rack("A", 1, 1)], None)}
    assert first == second


@pytest.mark.parametrize(
    "locations",
    [("Wine Rack 1", "Wine-Rack-1"), ("Wine Rack 1", "wine rack 1 "), ("酒架", "葡萄酒")],
)
def test_locations_that_slug_alike_still_get_distinct_ids(locations):
    """Home Assistant drops an entity whose unique id is already taken."""
    racks = [Rack(location, 1, 1) for location in locations]
    ids = [s.unique_id for s in build(racks, None)]
    assert len(set(ids)) == len(ids)
