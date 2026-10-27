"""Native actions: cellar_tracker.refresh and cellar_tracker.get_wine_by_bin.

Naming: the brief called these ``cellartracker.*``, but a service must be
registered under the integration's own domain, which is ``cellar_tracker``.
That is the domain services.yaml, strings.json and hassfest tie them to.

Registered once in async_setup, not per entry: they are global to the component
and Home Assistant offers no way to unregister one, the same reason the HTTP
views live there.

get_wine_by_bin returns a response, which is what makes it usable from a script
or automation via ``response_variable`` - an LED driver asks "what is in A1?"
and acts on the answer.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re

import pytest
import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from cellar_tracker import async_setup
from cellar_tracker.const import DOMAIN
from cellar_tracker.services import SERVICE_GET_WINE_BY_BIN, SERVICE_REFRESH
from conftest import FakeCoordinator, ViewHass

COMPONENT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "cellar_tracker"

BOTTLES = [
    {
        "iWine": "1",
        "Wine": "Barolo",
        "Vintage": "2016",
        "Location": "Cellar",
        "Bin": "A1",
        "BeginConsume": "2020",
        "EndConsume": "2040",
        "unique_bottle_id": "u1",
        "Valuation": 50.0,
        "BottleNote": "private",
        "Barcode": "BC-1",
    },
    {
        "iWine": "2",
        "Wine": "Rioja",
        "Vintage": "0",
        "Location": "Cellar",
        "Bin": "A1",
        "BeginConsume": "2010",
        "EndConsume": "2020",
        "unique_bottle_id": "u2",
    },
    {
        "iWine": "3",
        "Wine": "Port",
        "Vintage": "2015",
        "Location": "Cellar",
        "Bin": "B2",
        "BeginConsume": "2030",
        "EndConsume": "2050",
        "unique_bottle_id": "u3",
    },
    {
        "iWine": "4",
        "Wine": "Chablis",
        "Vintage": "2019",
        "Location": "Fridge",
        "Bin": "A1",
        "BeginConsume": "",
        "EndConsume": "",
        "unique_bottle_id": "u4",
    },
]


def make_hass(**coordinators: FakeCoordinator) -> ViewHass:
    hass = ViewHass({DOMAIN: dict(coordinators)})
    asyncio.run(async_setup(hass, {}))
    return hass


def call(hass: ViewHass, service: str, data=None, *, response: bool = False):
    return asyncio.run(hass.services.async_call(DOMAIN, service, data, return_response=response))


def lookup(hass: ViewHass, **data):
    return call(hass, SERVICE_GET_WINE_BY_BIN, data, response=True)


@pytest.fixture
def hass() -> ViewHass:
    return make_hass(a=FakeCoordinator(bottles=BOTTLES, year=2026))


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------
def test_both_services_are_registered_under_the_integration_domain(hass):
    assert hass.services.has_service(DOMAIN, "refresh")
    assert hass.services.has_service(DOMAIN, "get_wine_by_bin")


def test_the_service_names_are_stable():
    assert SERVICE_REFRESH == "refresh"
    assert SERVICE_GET_WINE_BY_BIN == "get_wine_by_bin"


def test_the_lookup_returns_a_response_and_refresh_does_not(hass):
    registered = hass.services.registered
    assert registered[(DOMAIN, "get_wine_by_bin")].supports_response == SupportsResponse.ONLY
    assert registered[(DOMAIN, "refresh")].supports_response == SupportsResponse.NONE


def test_setup_registers_them_exactly_once():
    hass = ViewHass({})
    asyncio.run(async_setup(hass, {}))
    assert sorted(service for _, service in hass.services.registered) == [
        "get_wine_by_bin",
        "highlight_bottles",
        "locate_bottle",
        "refresh",
        "show_overview",
    ]


# --------------------------------------------------------------------------
# hassfest pre-checks: services.yaml and the strings that describe it
# --------------------------------------------------------------------------
def declared_in_yaml() -> set[str]:
    text = (COMPONENT / "services.yaml").read_text()
    return set(re.findall(r"^([a-z_]+):", text, re.M))


def test_services_yaml_declares_exactly_the_registered_services(hass):
    registered = {service for _, service in hass.services.registered}
    assert declared_in_yaml() == registered


def test_every_service_is_described_in_the_strings(hass):
    strings = json.loads((COMPONENT / "strings.json").read_text())["services"]
    for name in declared_in_yaml():
        assert strings[name]["name"]
        assert strings[name]["description"]


def test_every_field_is_described_in_the_strings():
    strings = json.loads((COMPONENT / "strings.json").read_text())["services"]
    fields = strings["get_wine_by_bin"]["fields"]
    assert set(fields) == {"bin", "location"}
    for field in fields.values():
        assert field["name"]
        assert field["description"]


def test_the_not_loaded_error_is_translated():
    strings = json.loads((COMPONENT / "strings.json").read_text())
    assert strings["exceptions"]["not_loaded"]["message"]


# --------------------------------------------------------------------------
# refresh
# --------------------------------------------------------------------------
def test_refresh_requests_an_immediate_poll(hass):
    coordinator = hass.config_entries.async_entries()[0].runtime_data
    call(hass, "refresh")
    assert coordinator.refresh_requests == 1


def test_refresh_goes_through_the_coordinators_own_debouncer():
    """Not a bare fetch: Home Assistant's request_refresh rate-limits itself."""
    coordinator = FakeCoordinator(bottles=BOTTLES)
    hass = make_hass(a=coordinator)
    call(hass, "refresh")
    assert coordinator.refresh_requests == 1


def test_refresh_reaches_every_loaded_entry():
    """Only reachable on a legacy install still holding two entries."""
    first, second = FakeCoordinator(bottles=BOTTLES), FakeCoordinator(bottles=BOTTLES)
    hass = make_hass(a=first, b=second)
    call(hass, "refresh")
    assert (first.refresh_requests, second.refresh_requests) == (1, 1)


def test_refresh_with_nothing_configured_says_so():
    hass = make_hass()
    with pytest.raises(ServiceValidationError) as raised:
        call(hass, "refresh")
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "not_loaded"


def test_refresh_skips_an_entry_that_has_been_unloaded():
    hass = make_hass(a=FakeCoordinator(bottles=BOTTLES))
    hass.config_entries.async_entries()[0].runtime_data = None
    with pytest.raises(ServiceValidationError):
        call(hass, "refresh")


def test_refresh_takes_no_arguments(hass):
    with pytest.raises(vol.Invalid):
        call(hass, "refresh", {"bin": "A1"})


# --------------------------------------------------------------------------
# get_wine_by_bin
# --------------------------------------------------------------------------
def test_lookup_returns_the_bottles_in_a_bin(hass):
    result = lookup(hass, bin="A1", location="Cellar")
    assert result["count"] == 2
    assert [b["name"] for b in result["bottles"]] == ["Barolo", "Rioja"]


def test_lookup_without_a_location_spans_every_location(hass):
    result = lookup(hass, bin="A1")
    assert [b["name"] for b in result["bottles"]] == ["Barolo", "Rioja", "Chablis"]


def test_lookup_of_an_unknown_bin_is_empty_not_an_error(hass):
    assert lookup(hass, bin="Z9") == {"bin": "Z9", "location": None, "count": 0, "bottles": []}


def test_lookup_ignores_case_and_padding(hass):
    assert lookup(hass, bin=" a1 ", location=" cellar ")["count"] == 2


def test_a_blank_bin_matches_nothing(hass):
    """An empty template must not light every unplaced bottle."""
    assert lookup(hass, bin="")["count"] == 0


def test_a_numeric_bin_from_yaml_is_accepted(hass):
    """`bin: 12` in a script is an int until the schema coerces it."""
    hass = make_hass(a=FakeCoordinator(bottles=[{**BOTTLES[0], "Bin": "12"}]))
    assert lookup(hass, bin=12)["count"] == 1


def test_the_bin_is_required(hass):
    with pytest.raises(vol.Invalid):
        lookup(hass)


def test_the_response_echoes_the_query(hass):
    result = lookup(hass, bin="A1", location="Cellar")
    assert (result["bin"], result["location"]) == ("A1", "Cellar")


# --------------------------------------------------------------------------
# The bottle shape
# --------------------------------------------------------------------------
def first_bottle(hass) -> dict:
    return lookup(hass, bin="A1", location="Cellar")["bottles"][0]


def test_a_bottle_reports_name_vintage_and_drink_window(hass):
    bottle = first_bottle(hass)
    assert bottle["name"] == "Barolo"
    assert bottle["vintage"] == 2016
    assert bottle["drink_window"] == {"begin": 2020, "end": 2040}


def test_a_non_vintage_wine_has_no_vintage_rather_than_zero(hass):
    non_vintage = lookup(hass, bin="A1", location="Cellar")["bottles"][1]
    assert non_vintage["vintage"] is None


def test_a_missing_window_is_null_not_zero(hass):
    chablis = lookup(hass, bin="A1", location="Fridge")["bottles"][0]
    assert chablis["drink_window"] == {"begin": None, "end": None}
    assert chablis["drink_status"] == "unknown"


@pytest.mark.parametrize(
    ("bin_name", "status", "peak"),
    [("A1", "ready", False), ("B2", "aging", False)],
)
def test_status_and_peak_are_worked_out_for_the_current_year(hass, bin_name, status, peak):
    bottle = lookup(hass, bin=bin_name, location="Cellar")["bottles"][0]
    assert bottle["drink_status"] == status
    assert bottle["peak"] is peak


@pytest.mark.parametrize(
    ("year", "peak"),
    [
        (2020, False),
        (2026, False),
        (2027, True),
        (2030, True),
        (2033, True),
        (2034, False),
        (2040, False),
    ],
)
def test_peak_follows_the_middle_third_of_the_window(year, peak):
    """Barolo is 2020-2040: the middle third is 2026.67..2033.33."""
    hass = make_hass(a=FakeCoordinator(bottles=BOTTLES, year=year))
    bottle = lookup(hass, bin="A1", location="Cellar")["bottles"][0]
    assert bottle["peak"] is peak
    assert bottle["drink_status"] == "ready"


def test_a_past_bottle_is_reported_past(hass):
    rioja = lookup(hass, bin="A1", location="Cellar")["bottles"][1]
    assert rioja["drink_status"] == "past"


def test_the_year_is_the_coordinators_not_the_wall_clock():
    hass = make_hass(a=FakeCoordinator(bottles=BOTTLES, year=2031))
    assert lookup(hass, bin="B2", location="Cellar")["bottles"][0]["drink_status"] == "ready"


def test_a_bottle_carries_where_it_is_and_which_it_is(hass):
    bottle = first_bottle(hass)
    assert bottle["location"] == "Cellar"
    assert bottle["bin"] == "A1"
    assert bottle["wine_id"] == "1"
    assert bottle["unique_bottle_id"] == "u1"


def test_a_bottle_carries_nothing_that_belongs_to_the_owner_alone(hass):
    """Scripts and automations are shared and logged; notes and prices are not."""
    assert set(first_bottle(hass)) == {
        "name",
        "vintage",
        "wine_id",
        "location",
        "bin",
        "drink_window",
        "drink_status",
        "peak",
        "unique_bottle_id",
    }


def test_the_response_is_json_serialisable(hass):
    json.dumps(lookup(hass, bin="A1"))


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------
def test_lookup_with_nothing_configured_says_so():
    hass = make_hass()
    with pytest.raises(ServiceValidationError) as raised:
        lookup(hass, bin="A1")
    assert raised.value.translation_key == "not_loaded"


def test_lookup_before_the_first_data_is_empty():
    hass = make_hass(a=FakeCoordinator(data=False))
    assert lookup(hass, bin="A1")["count"] == 0


def test_a_legacy_second_entry_is_served_deterministically():
    hass = make_hass(
        bbb=FakeCoordinator(bottles=[{**BOTTLES[2], "Bin": "A1"}]),
        aaa=FakeCoordinator(bottles=BOTTLES),
    )
    assert lookup(hass, bin="A1", location="Cellar")["bottles"][0]["name"] == "Barolo"


# --------------------------------------------------------------------------
# A blank location is no filter (Codex, #23)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_location_searches_every_location(hass, blank):
    result = lookup(hass, bin="A1", location=blank)
    assert [b["name"] for b in result["bottles"]] == ["Barolo", "Rioja", "Chablis"]


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_location_is_echoed_as_none(hass, blank):
    """The response describes the query that was actually run."""
    assert lookup(hass, bin="A1", location=blank)["location"] is None


def test_a_real_location_is_still_a_filter(hass):
    assert lookup(hass, bin="A1", location="Fridge")["count"] == 1


# --------------------------------------------------------------------------
# Putting the dashboard on the LED racks
#
# The integration knows the racks and the bottles, not the boards. These
# services fire events naming a rack by Location; the rack's own blueprint
# automation lights it.
# --------------------------------------------------------------------------
RACKS = "Cellar: 2x2\nFridge: 1x1"


@pytest.fixture
def racked() -> ViewHass:
    return make_hass(a=FakeCoordinator(bottles=BOTTLES, year=2026, racks=RACKS))


def events(hass, event_type):
    return [data for kind, data in hass.bus.events if kind == event_type]


def test_locate_names_the_rack_and_the_bin(racked):
    call(racked, "locate_bottle", {"location": " Cellar ", "bin": " B2 "})
    assert events(racked, "cellartracker_rack_locate") == [
        {"location": "Cellar", "bin": "B2", "seconds": 120}
    ]


def test_locate_passes_the_hold_through(racked):
    call(racked, "locate_bottle", {"location": "Cellar", "bin": "A1", "seconds": 0})
    assert events(racked, "cellartracker_rack_locate")[0]["seconds"] == 0


def test_locate_names_the_rack_as_configured(racked):
    """The page sends the bottle's own Location. Each rack's automation
    compares the event against the rack's configured name, so a Location that
    differs only in case or spacing must arrive as that name."""
    call(racked, "locate_bottle", {"location": "cellar", "bin": "A1"})
    assert events(racked, "cellartracker_rack_locate")[0]["location"] == "Cellar"


@pytest.mark.parametrize(
    "data", [{"location": "Garage", "bin": "A1"}, {"location": "Cellar", "bin": "  "}]
)
def test_locate_refuses_a_bottle_no_rack_can_show(racked, data):
    """Saying so beats firing an event no automation will ever answer."""
    with pytest.raises(ServiceValidationError):
        call(racked, "locate_bottle", data)
    assert racked.bus.events == []


def test_highlight_paints_only_the_chosen_bottles_on_every_rack(racked):
    # u1 is ready (A1), u3 is aging (B2); u2 shares A1 but is not chosen.
    call(racked, "highlight_bottles", {"bottles": ["u1", "u3"]})
    painted = {e["location"]: e for e in events(racked, "cellartracker_rack_paint")}
    assert painted["Cellar"] == {"location": "Cellar", "grid": "R..A", "highlight": True}
    # Nothing chosen in the fridge, so it goes dark rather than keeping colour.
    assert painted["Fridge"]["grid"] == "."


def test_a_bin_shows_the_chosen_bottle_not_its_neighbour(racked):
    """A1 holds a ready bottle and a past one; highlighting the ready one
    must not paint the bin red because of the other."""
    call(racked, "highlight_bottles", {"bottles": ["u1"]})
    cellar = next(
        e for e in events(racked, "cellartracker_rack_paint") if e["location"] == "Cellar"
    )
    assert cellar["grid"][0] == "R"


def test_the_overview_comes_back_after_a_highlight(racked):
    call(racked, "highlight_bottles", {"bottles": ["u1"], "seconds": 30})
    ((delay, restore, cancelled),) = racked.later
    assert delay == 30 and not cancelled
    racked.bus.events.clear()
    restore(None)
    painted = events(racked, "cellartracker_rack_paint")
    assert {e["location"] for e in painted} == {"Cellar", "Fridge"}
    assert all(e["highlight"] is False for e in painted)
    assert next(e for e in painted if e["location"] == "Cellar")["grid"] == "P..A"


def test_a_new_highlight_replaces_the_pending_restore(racked):
    """Otherwise the first timer would wipe the second highlight early."""
    call(racked, "highlight_bottles", {"bottles": ["u1"]})
    call(racked, "highlight_bottles", {"bottles": ["u3"]})
    assert [t[2] for t in racked.later] == [True, False]


def test_a_hold_of_zero_waits_for_the_next_sync(racked):
    call(racked, "highlight_bottles", {"bottles": ["u1"], "seconds": 0})
    assert racked.later == []


def test_show_overview_repaints_every_rack_and_cancels_the_restore(racked):
    call(racked, "highlight_bottles", {"bottles": ["u1"]})
    racked.bus.events.clear()
    call(racked, "show_overview")
    assert racked.later[0][2] is True
    painted = events(racked, "cellartracker_rack_paint")
    assert [e["location"] for e in painted] == ["Cellar", "Fridge"]


def test_without_led_racks_the_highlight_does_nothing(hass):
    call(hass, "highlight_bottles", {"bottles": ["u1"]})
    call(hass, "show_overview")
    assert hass.bus.events == []


# Reported by Codex on #29: a restore that fires during a locator's hold ends
# it, because the overview repaint clears the board first.
@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("cellar_tracker.services.time.monotonic", lambda: now[0])
    return now


def test_a_locator_near_the_end_of_a_highlight_pushes_the_restore_back(racked, clock):
    call(racked, "highlight_bottles", {"bottles": ["u1"], "seconds": 600})
    clock[0] += 590
    call(racked, "locate_bottle", {"location": "Cellar", "bin": "A1", "seconds": 120})
    first, second = racked.later
    assert first[2] is True, "the old restore would end the locator after 10 s"
    assert second[0] == 120 and second[2] is False


def test_a_locator_well_inside_a_highlight_leaves_the_restore_alone(racked, clock):
    call(racked, "highlight_bottles", {"bottles": ["u1"], "seconds": 600})
    clock[0] += 60
    call(racked, "locate_bottle", {"location": "Cellar", "bin": "A1", "seconds": 120})
    assert [t[2] for t in racked.later] == [False]


def test_a_locator_held_indefinitely_is_not_cut_short_by_a_restore(racked, clock):
    call(racked, "highlight_bottles", {"bottles": ["u1"]})
    call(racked, "locate_bottle", {"location": "Cellar", "bin": "A1", "seconds": 0})
    assert [t[2] for t in racked.later] == [True]


def test_the_deferred_restore_still_puts_the_overview_back(racked, clock):
    call(racked, "highlight_bottles", {"bottles": ["u1"], "seconds": 600})
    clock[0] += 590
    call(racked, "locate_bottle", {"location": "Cellar", "bin": "A1", "seconds": 120})
    racked.bus.events.clear()
    racked.later[-1][1](None)
    assert {e["location"] for e in events(racked, "cellartracker_rack_paint")} == {
        "Cellar",
        "Fridge",
    }


# --------------------------------------------------------------------------
# Racks that go dark when left alone
#
# Asked for 2026-10-27: every LED off two minutes after the latest selection,
# and a door or motion sensor that lights the overview only if nothing else
# is showing.
# --------------------------------------------------------------------------
@pytest.fixture
def sleepy() -> ViewHass:
    return make_hass(a=FakeCoordinator(bottles=BOTTLES, year=2026, racks=RACKS, idle_off=120))


def pending(hass):
    return [timer for timer in hass.later if not timer[2]]


def showing_now(hass):
    from cellar_tracker.rack_lights import showing

    return showing(hass, hass.data[DOMAIN]["a"].racks_idle_off)


def test_sleepy_racks_start_dark_and_awake_ones_on_the_overview(sleepy, racked):
    assert showing_now(sleepy) == "off"
    assert showing_now(racked) == "overview"


def test_a_highlight_goes_dark_after_the_idle_time_not_back_to_the_overview(sleepy):
    call(sleepy, "highlight_bottles", {"bottles": ["u1"]})
    assert showing_now(sleepy) == "highlight"
    ((delay, go_dark, _),) = pending(sleepy)
    assert delay == 120, "the idle time, not the highlight's own 600 s"
    sleepy.bus.events.clear()
    go_dark(None)
    painted = events(sleepy, "cellartracker_rack_paint")
    assert {e["location"]: e["grid"] for e in painted} == {"Cellar": "....", "Fridge": "."}
    assert all(e["highlight"] is False for e in painted)
    assert showing_now(sleepy) == "off"


def test_every_request_starts_the_countdown_again(sleepy):
    call(sleepy, "highlight_bottles", {"bottles": ["u1"]})
    call(sleepy, "locate_bottle", {"location": "Cellar", "bin": "A1"})
    call(sleepy, "show_overview")
    assert [t[2] for t in sleepy.later] == [True, True, False]
    assert pending(sleepy)[0][0] == 120


def test_a_located_bin_stays_lit_until_the_racks_go_dark(sleepy):
    """The board's own hold would bring the previous picture back first."""
    call(sleepy, "locate_bottle", {"location": "Cellar", "bin": "A1", "seconds": 30})
    assert events(sleepy, "cellartracker_rack_locate")[0]["seconds"] == 0
    assert pending(sleepy)[0][0] == 120


def test_the_overview_on_request_also_goes_dark_later(sleepy):
    call(sleepy, "show_overview")
    assert showing_now(sleepy) == "overview"
    assert pending(sleepy)[0][0] == 120


def test_someone_walking_in_lights_the_overview_when_the_racks_are_dark(sleepy):
    call(sleepy, "show_overview", {"only_if_dark": True})
    painted = events(sleepy, "cellartracker_rack_paint")
    assert next(e for e in painted if e["location"] == "Cellar")["grid"] == "P..A"
    assert showing_now(sleepy) == "overview"
    assert pending(sleepy)[0][0] == 120


def test_someone_walking_in_keeps_a_selection_and_keeps_it_lit(sleepy):
    call(sleepy, "highlight_bottles", {"bottles": ["u1"]})
    sleepy.bus.events.clear()
    call(sleepy, "show_overview", {"only_if_dark": True})
    assert sleepy.bus.events == [], "the highlight was replaced"
    assert showing_now(sleepy) == "highlight"
    assert [t[2] for t in sleepy.later] == [True, False]


def test_someone_walking_in_keeps_a_located_bin(sleepy):
    """Locating a bottle on a dark rack leaves it 'off' around the bin, but
    the countdown says something is lit."""
    call(sleepy, "locate_bottle", {"location": "Cellar", "bin": "A1"})
    sleepy.bus.events.clear()
    call(sleepy, "show_overview", {"only_if_dark": True})
    assert sleepy.bus.events == []


def test_walking_in_again_after_the_racks_went_dark_lights_them(sleepy):
    call(sleepy, "show_overview", {"only_if_dark": True})
    pending(sleepy)[0][1](None)
    sleepy.bus.events.clear()
    call(sleepy, "show_overview", {"only_if_dark": True})
    assert {e["location"] for e in events(sleepy, "cellartracker_rack_paint")} == {
        "Cellar",
        "Fridge",
    }


def test_only_if_dark_does_nothing_to_racks_that_never_go_dark(racked):
    call(racked, "show_overview", {"only_if_dark": True})
    assert racked.bus.events == []
    assert racked.later == []


def test_awake_racks_keep_their_old_timings(racked):
    """0 is the default, and nothing about it changes."""
    call(racked, "highlight_bottles", {"bottles": ["u1"]})
    assert pending(racked)[0][0] == 600
    call(racked, "locate_bottle", {"location": "Cellar", "bin": "A1"})
    assert events(racked, "cellartracker_rack_locate")[0]["seconds"] == 120


def test_sleepy_racks_are_put_out_when_home_assistant_starts(sleepy):
    """A rack lit when Home Assistant went down would otherwise stay lit."""
    from cellar_tracker.services import async_put_racks_out

    coordinator = sleepy.data[DOMAIN]["a"]
    sleepy.bus.events.clear()
    async_put_racks_out(sleepy, coordinator)
    assert {e["location"]: e["grid"] for e in events(sleepy, "cellartracker_rack_paint")} == {
        "Cellar": "....",
        "Fridge": ".",
    }


def test_awake_racks_are_left_alone_at_start(racked):
    from cellar_tracker.services import async_put_racks_out

    async_put_racks_out(racked, racked.data[DOMAIN]["a"])
    assert racked.bus.events == []


def test_turning_the_option_off_lights_racks_that_went_dark(sleepy):
    """Left "off", the paint automation would refuse every repaint for good."""
    from cellar_tracker.services import async_put_racks_out

    coordinator = sleepy.data[DOMAIN]["a"]
    async_put_racks_out(sleepy, coordinator)
    assert showing_now(sleepy) == "off"

    coordinator.racks_idle_off = 0
    sleepy.bus.events.clear()
    async_put_racks_out(sleepy, coordinator)
    assert showing_now(sleepy) == "overview"
    assert {e["location"] for e in events(sleepy, "cellartracker_rack_paint")} == {
        "Cellar",
        "Fridge",
    }
