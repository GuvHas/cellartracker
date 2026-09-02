"""F-13: modern entity naming, and a device named after the account.

The sensors baked "CellarTracker" into every entity name and never set
``has_entity_name``, so Home Assistant treated each ``_attr_name`` as the whole
friendly name. Renaming the device in the UI therefore changed nothing, and the
integration's own name was duplicated into every entity label by hand.

The device was also hardcoded to "CellarTracker" for every config entry, so two
accounts produced two identically named devices and a new second account got
``..._2`` entity ids.

Entity ids of existing installs are NOT affected by any of this: these entities
set a unique_id, so they are in the entity registry, which persists the entity
id assigned at first registration. Only friendly names change. The unique_ids
themselves must stay byte-identical - changing one would orphan the registry
entry and silently create a duplicate entity.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import UTC, datetime

import pytest

from cellar_tracker.const import DOMAIN
from cellar_tracker.sensor import async_setup_entry
from conftest import ConfigEntry, ViewHass

ENTITY_NAMES = json.loads(
    (
        pathlib.Path(__file__).resolve().parent.parent
        / "custom_components"
        / "cellar_tracker"
        / "strings.json"
    ).read_text()
)["entity"]["sensor"]


class _Coordinator:
    data = {"total_bottles": 3, "total_value": 30.0, "bottles": []}
    currency = "USD"
    last_success = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)


def build_sensors(*, title="alice", entry_id="entry1", data=None):
    entry = ConfigEntry(
        entry_id=entry_id,
        title=title,
        data=data or {"username": "alice", "password": "x", "currency": "USD"},
    )
    entry.runtime_data = _Coordinator()
    hass = ViewHass({DOMAIN: {entry_id: entry.runtime_data}})
    added = []
    asyncio.run(async_setup_entry(hass, entry, lambda sensors: added.extend(sensors)))
    return {type(sensor).__name__: sensor for sensor in added}


ALL_SENSORS = [
    "TotalBottlesSensor",
    "TotalValueSensor",
    "ReadyToDrinkSensor",
    "PastDrinkWindowSensor",
    "CellarLastSyncSensor",
]


# --------------------------------------------------------------------------
# A: has_entity_name, with the device name no longer repeated in each entity
# --------------------------------------------------------------------------
@pytest.mark.parametrize("sensor_name", ALL_SENSORS)
def test_sensors_opt_into_modern_naming(sensor_name):
    sensor = build_sensors()[sensor_name]
    assert sensor._attr_has_entity_name is True


@pytest.mark.parametrize("sensor_name", ALL_SENSORS)
def test_entity_names_do_not_repeat_the_integration_name(sensor_name):
    """With has_entity_name, HA prepends the device name itself.

    The names now live in strings.json under the translation key, so that is
    where this has to look; a literal _attr_name would defeat the translation
    and is asserted absent in test_entity_translations.py.
    """
    sensor = build_sensors()[sensor_name]
    name = ENTITY_NAMES[sensor.translation_key]["name"]
    assert "cellartracker" not in name.lower(), (
        f"{name!r} would render as 'CellarTracker CellarTracker ...'"
    )


def test_entity_names_are_the_expected_short_labels():
    sensors = build_sensors()
    labels = {
        cls: ENTITY_NAMES[sensor.translation_key]["name"]
        for cls, sensor in sensors.items()
    }
    assert labels == {
        "TotalBottlesSensor": "Total bottles",
        "TotalValueSensor": "Total value",
        "ReadyToDrinkSensor": "Ready to drink",
        "PastDrinkWindowSensor": "Past drinking window",
        "CellarLastSyncSensor": "Last synchronised",
    }


# --------------------------------------------------------------------------
# B: the device is named after the account, not hardcoded
# --------------------------------------------------------------------------
def test_device_is_named_after_the_config_entry():
    sensor = build_sensors(title="alice")["TotalBottlesSensor"]
    assert sensor._attr_device_info["name"] == "alice"


def test_two_accounts_produce_distinctly_named_devices():
    first = build_sensors(title="alice", entry_id="entry1")["TotalBottlesSensor"]
    second = build_sensors(title="bob", entry_id="entry2")["TotalBottlesSensor"]

    names = {
        first._attr_device_info["name"],
        second._attr_device_info["name"],
    }
    assert names == {"alice", "bob"}


def test_device_name_falls_back_when_the_title_is_blank():
    sensor = build_sensors(title="")["TotalBottlesSensor"]
    assert sensor._attr_device_info["name"] == "CellarTracker"


def test_manufacturer_stays_the_service_name():
    """Only the device *name* becomes account-specific."""
    info = build_sensors()["TotalBottlesSensor"]._attr_device_info
    assert info["manufacturer"] == "CellarTracker"


# --------------------------------------------------------------------------
# Registry safety: these must not change
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("sensor_name", "suffix"),
    [
        ("TotalBottlesSensor", "_total_bottles"),
        ("TotalValueSensor", "_total_value"),
        # Unchanged even though the sensor was repurposed from a status
        # string to a timestamp: a new id would orphan the registry entry.
        ("CellarLastSyncSensor", "_inventory_status"),
    ],
)
def test_unique_ids_are_unchanged(sensor_name, suffix):
    """A changed unique_id orphans the registry entry and duplicates the entity."""
    sensor = build_sensors(entry_id="entry1")[sensor_name]
    assert sensor._attr_unique_id == f"entry1{suffix}"


def test_device_identifiers_are_unchanged():
    """A changed identifier would create a second device."""
    info = build_sensors(entry_id="entry1")["TotalBottlesSensor"]._attr_device_info
    assert info["identifiers"] == {(DOMAIN, "entry1")}


# --------------------------------------------------------------------------
# Everything the earlier cycles established must still hold
# --------------------------------------------------------------------------
def test_value_sensor_keeps_its_currency_and_classes():
    sensor = build_sensors(data={"username": "a", "password": "b", "currency": "SEK"})[
        "TotalValueSensor"
    ]
    assert sensor.native_unit_of_measurement == "SEK"
    assert sensor.device_class == "monetary"
    assert sensor.state_class == "total"


def test_bottles_sensor_keeps_its_unit():
    sensor = build_sensors()["TotalBottlesSensor"]
    assert sensor.native_unit_of_measurement == "bottles"
    assert sensor.state_class == "measurement"


def test_sensors_still_read_from_the_coordinator():
    sensors = build_sensors()
    assert sensors["TotalBottlesSensor"].native_value == 3
    assert sensors["TotalValueSensor"].native_value == 30.0
    assert sensors["CellarLastSyncSensor"].native_value == _Coordinator.last_success


def test_status_sensor_stays_diagnostic():
    sensor = build_sensors()["CellarLastSyncSensor"]
    assert sensor.entity_category == "diagnostic"
