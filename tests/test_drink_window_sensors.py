"""The two drink-window counters as entities.

No entity is created per bottle - that decision is what keeps this integration
cheap at cellar scale, and these counters are deliberately built the same way:
two more static sensors reading numbers the coordinator already computed.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from cellar_tracker.const import DOMAIN
from cellar_tracker.sensor import async_setup_entry
from conftest import ConfigEntry, ViewHass

STRINGS = json.loads(
    (
        pathlib.Path(__file__).resolve().parent.parent
        / "custom_components"
        / "cellar_tracker"
        / "strings.json"
    ).read_text()
)


class _Coordinator:
    currency = "USD"
    last_success = None

    def __init__(self, data=None):
        self.data = data


def sensors(data=None):
    entry = ConfigEntry(entry_id="e1", data={"username": "alice", "password": "x"})
    entry.runtime_data = _Coordinator(data)
    hass = ViewHass({DOMAIN: {"e1": entry.runtime_data}})
    added = []
    asyncio.run(async_setup_entry(hass, entry, added.extend))
    return {type(s).__name__: s for s in added}


FULL = {
    "total_bottles": 9,
    "total_value": 100.0,
    "bottles": [],
    "ready_to_drink": 4,
    "past_drink_window": 2,
}


def test_both_counters_are_created():
    created = sensors(FULL)
    assert "ReadyToDrinkSensor" in created
    assert "PastDrinkWindowSensor" in created


def test_they_report_the_coordinator_counts():
    created = sensors(FULL)
    assert created["ReadyToDrinkSensor"].native_value == 4
    assert created["PastDrinkWindowSensor"].native_value == 2


def test_they_default_to_zero_before_the_first_refresh():
    """coordinator.data is None until the first successful poll."""
    created = sensors(None)
    assert created["ReadyToDrinkSensor"].native_value == 0
    assert created["PastDrinkWindowSensor"].native_value == 0


def test_they_survive_a_payload_written_by_an_older_version():
    """A cached payload from before these counters existed has no such keys."""
    created = sensors({"total_bottles": 3, "total_value": 0.0, "bottles": []})
    assert created["ReadyToDrinkSensor"].native_value == 0
    assert created["PastDrinkWindowSensor"].native_value == 0


@pytest.mark.parametrize(
    ("name", "key", "suffix"),
    [
        ("ReadyToDrinkSensor", "ready_to_drink", "_ready_to_drink"),
        ("PastDrinkWindowSensor", "past_drink_window", "_past_drink_window"),
    ],
)
def test_they_follow_the_naming_and_id_conventions(name, key, suffix):
    sensor = sensors(FULL)[name]
    assert sensor._attr_has_entity_name is True
    assert sensor.translation_key == key
    assert sensor.unique_id == f"e1{suffix}"
    assert STRINGS["entity"]["sensor"][key]["name"]


@pytest.mark.parametrize("name", ["ReadyToDrinkSensor", "PastDrinkWindowSensor"])
def test_they_are_measurements_counted_in_bottles(name):
    sensor = sensors(FULL)[name]
    assert sensor.native_unit_of_measurement == "bottles"
    assert sensor.state_class == "measurement"


@pytest.mark.parametrize("name", ["ReadyToDrinkSensor", "PastDrinkWindowSensor"])
def test_they_are_primary_entities_not_diagnostics(name):
    """These are the point of the feature, not troubleshooting detail."""
    assert sensors(FULL)[name].entity_category is None


def test_the_cellar_still_creates_no_entity_per_bottle():
    """The scale property that makes this design work must not regress."""
    created = sensors({**FULL, "bottles": [{"iWine": str(i)} for i in range(500)]})
    assert len(created) == 5
