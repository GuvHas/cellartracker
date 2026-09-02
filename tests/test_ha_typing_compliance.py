"""Typed coordinator, typed entry, typed descriptions, typed device.

The gaps this pins are all the same gap wearing different clothes: the
integration's central data structure was untyped, so `coordinator.data` was
`Any` everywhere it was read - three modules, five sensors, the views and
diagnostics - and no checker could see a typo in a key.

  * `CellarData` names the payload once, and the coordinator is generic over
    it, so `self.data` has a type at every call site.
  * `CellarTrackerConfigEntry` carries the coordinator's type on the entry, so
    `entry.runtime_data` is not `Any` either.
  * `SENSOR_DESCRIPTIONS` puts key, translation key, device class, state class
    and unit in one typed place instead of five constructors.
  * `DeviceInfo` with `DeviceEntryType.SERVICE` rather than a bare dict with
    the string "service".

None of this changes behaviour, which is why it comes with a mypy gate in CI:
without one, typing rots silently and the next contributor inherits `Any`.
"""

from __future__ import annotations

import json
import pathlib
import typing

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers.device_registry import DeviceEntryType

from cellar_tracker import cellar_data as cellar_data_module
from cellar_tracker.cellar_data import CellarData, WineCellarData
from cellar_tracker.const import DOMAIN
from cellar_tracker.sensor import SENSOR_DESCRIPTIONS
from cellar_tracker.sensor import async_setup_entry as sensor_setup_entry
from conftest import ConfigEntry, ViewHass

COMPONENT = (
    pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "cellar_tracker"
)
STRINGS = json.loads((COMPONENT / "strings.json").read_text())
CI = (
    pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
).read_text()


class _Coordinator:
    currency = "USD"
    last_success = None
    data = {
        "total_bottles": 3,
        "total_value": 30.0,
        "bottles": [],
        "ready_to_drink": 1,
        "past_drink_window": 0,
    }


def build():
    entry = ConfigEntry(entry_id="e1", data={"username": "alice", "password": "x"})
    entry.runtime_data = _Coordinator()
    hass = ViewHass({DOMAIN: {"e1": entry.runtime_data}})
    added = []
    import asyncio

    asyncio.run(sensor_setup_entry(hass, entry, added.extend))
    return added


# --------------------------------------------------------------------------
# The payload has a name
# --------------------------------------------------------------------------
def test_the_payload_is_a_typed_dict():
    hints = typing.get_type_hints(CellarData)
    assert hints["total_bottles"] is int
    assert hints["total_value"] is float
    assert hints["ready_to_drink"] is int
    assert hints["past_drink_window"] is int


def test_the_coordinator_is_generic_over_the_payload():
    """Otherwise self.data is Any in every module that reads it."""
    bases = getattr(WineCellarData, "__orig_bases__", ())
    args = [arg for base in bases for arg in typing.get_args(base)]
    assert CellarData in args, (
        "WineCellarData must be DataUpdateCoordinator[CellarData]"
    )


def test_the_entry_type_alias_carries_the_coordinator():
    """entry.runtime_data should not be Any either."""
    alias = getattr(cellar_data_module, "CellarTrackerConfigEntry", None)
    assert alias is not None, "CellarTrackerConfigEntry is missing"
    assert WineCellarData in typing.get_args(alias)


def test_a_real_payload_satisfies_the_declared_keys():
    """The TypedDict must describe what _process_inventory actually returns."""
    import asyncio

    from conftest import FakeHass, FakeSession

    hass = FakeHass()
    hass.session = FakeSession(text="iWine\tWine\tValuation\n1\tBarolo\t45.50")
    coordinator = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))
    payload = asyncio.run(coordinator._async_update_data())

    for key in typing.get_type_hints(CellarData):
        assert key in payload, f"{key} is declared but never produced"


# --------------------------------------------------------------------------
# Descriptions, not five hand-written constructors
# --------------------------------------------------------------------------
def test_every_sensor_is_described():
    keys = {description.key for description in SENSOR_DESCRIPTIONS}
    assert keys == {
        "total_bottles",
        "total_value",
        "ready_to_drink",
        "past_drink_window",
        "last_synchronised",
    }


def test_each_description_binds_its_translation_key():
    """One place decides the name, and strings.json has to agree."""
    for description in SENSOR_DESCRIPTIONS:
        assert description.translation_key == description.key
        assert STRINGS["entity"]["sensor"][description.translation_key]["name"]


def test_the_descriptions_carry_the_device_and_state_classes():
    by_key = {description.key: description for description in SENSOR_DESCRIPTIONS}

    assert by_key["total_value"].device_class == SensorDeviceClass.MONETARY
    assert by_key["total_value"].state_class == SensorStateClass.TOTAL
    assert by_key["last_synchronised"].device_class == SensorDeviceClass.TIMESTAMP
    assert by_key["total_bottles"].state_class == SensorStateClass.MEASUREMENT
    assert by_key["total_bottles"].native_unit_of_measurement == "bottles"


@pytest.mark.parametrize("description", SENSOR_DESCRIPTIONS, ids=lambda d: d.key)
def test_each_entity_carries_its_description(description):
    """The description must reach the entity, not just sit in a tuple."""
    by_key = {
        sensor.entity_description.key: sensor
        for sensor in build()
        if getattr(sensor, "entity_description", None)
    }
    sensor = by_key[description.key]

    assert sensor.entity_description is description
    assert sensor.translation_key == description.key


def test_unique_ids_still_derive_from_the_description_key():
    """Registry safety: these ids are what existing installs already hold."""
    ids = {s.unique_id for s in build()}
    assert ids == {
        "e1_total_bottles",
        "e1_total_value",
        "e1_ready_to_drink",
        "e1_past_drink_window",
        # Unchanged from when this entity reported "Connected".
        "e1_inventory_status",
    }


# --------------------------------------------------------------------------
# The device
# --------------------------------------------------------------------------
def test_the_device_declares_itself_a_service():
    """The enum, not the bare string it happens to equal."""
    info = build()[0]._attr_device_info
    assert info["entry_type"] is DeviceEntryType.SERVICE


def test_the_device_is_scoped_to_the_config_entry():
    info = build()[0]._attr_device_info
    assert info["identifiers"] == {(DOMAIN, "e1")}


def test_every_entity_shares_the_one_device():
    """Five entities, one device - not one device each."""
    identifiers = {
        frozenset(s._attr_device_info["identifiers"])
        for s in build()
        if getattr(s, "_attr_device_info", None)
    }
    assert len(identifiers) == 1


# --------------------------------------------------------------------------
# The gate that stops this rotting again
# --------------------------------------------------------------------------
def test_ci_runs_mypy():
    assert "mypy" in CI, "typing without a checker decays to decoration"


def test_mypy_is_configured():
    config = (pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml")
    assert config.is_file(), "mypy needs a configuration file to be reproducible"
    assert "[tool.mypy]" in config.read_text()
