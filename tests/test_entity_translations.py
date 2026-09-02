"""P2-1: entity names must be translatable.

``_attr_has_entity_name = True`` is already set, but each entity then hardcodes
an English ``_attr_name``. Core requires ``_attr_translation_key`` plus an
``entity`` block in strings.json, so a Home Assistant running in another
language shows translated names rather than English ones.

The machinery already exists here - the config and options flows are
translated - so only the entity section was missing.

Also covers P3-3: every sensor class carries a docstring. The surrounding code
documents its reasoning unusually well, which made two silent classes stand
out rather than blend in.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from cellar_tracker.const import DOMAIN
from cellar_tracker.sensor import (
    CellarLastSyncSensor,
    PastDrinkWindowSensor,
    ReadyToDrinkSensor,
    TotalBottlesSensor,
    TotalValueSensor,
)

COMPONENT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "cellar_tracker"
STRINGS = json.loads((COMPONENT / "strings.json").read_text())
EN = json.loads((COMPONENT / "translations" / "en.json").read_text())

SENSOR_CLASSES = [
    TotalBottlesSensor,
    TotalValueSensor,
    ReadyToDrinkSensor,
    PastDrinkWindowSensor,
    CellarLastSyncSensor,
]
EXPECTED_KEYS = {
    "total_bottles",
    "total_value",
    "ready_to_drink",
    "past_drink_window",
    "last_synchronised",
}


def _built() -> dict:
    """One instance of each sensor, keyed by class."""
    import asyncio

    from cellar_tracker.sensor import async_setup_entry
    from conftest import ConfigEntry, ViewHass

    class _Coordinator:
        currency = "USD"
        last_success = None
        data = {"total_bottles": 0, "total_value": 0.0, "bottles": []}

    entry = ConfigEntry(entry_id="e1", data={"username": "a", "password": "b"})
    entry.runtime_data = _Coordinator()
    added: list = []
    asyncio.run(
        async_setup_entry(ViewHass({DOMAIN: {"e1": entry.runtime_data}}), entry, added.extend)
    )
    return {type(sensor): sensor for sensor in added}


def entity_names(document: dict) -> dict:
    return document.get("entity", {}).get("sensor", {})


def test_strings_json_declares_every_entity():
    assert set(entity_names(STRINGS)) == EXPECTED_KEYS


def test_the_english_translation_matches_the_source_strings():
    """en.json is generated from strings.json; drift means a missing name."""
    assert entity_names(EN) == entity_names(STRINGS)


def test_every_declared_entity_has_a_name():
    for key, value in entity_names(STRINGS).items():
        assert value.get("name"), f"{key} has no name"


@pytest.mark.parametrize("cls", SENSOR_CLASSES)
def test_each_sensor_declares_a_translation_key(cls):
    """Declared on the entity description now, not as a class attribute.

    Read through the built entity rather than off the class, because that is
    where Home Assistant resolves it and therefore what a user actually sees.
    """
    key = _built()[cls].translation_key
    assert key in EXPECTED_KEYS, f"{cls.__name__} has no usable translation key"


@pytest.mark.parametrize("cls", SENSOR_CLASSES)
def test_no_sensor_hardcodes_an_english_name(cls):
    """A literal _attr_name would win over the translation and never localise."""
    assert getattr(cls, "_attr_name", None) is None, (
        f"{cls.__name__} sets _attr_name, which overrides the translation key"
    )


def test_the_translation_keys_are_unique():
    keys = [sensor.translation_key for sensor in _built().values()]
    assert len(set(keys)) == len(keys), "two sensors would share one name"


@pytest.mark.parametrize("cls", SENSOR_CLASSES)
def test_every_sensor_is_documented(cls):
    """P3-3: two of the three classes had no docstring at all."""
    assert (cls.__doc__ or "").strip(), f"{cls.__name__} has no docstring"
