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
        "refresh",
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
