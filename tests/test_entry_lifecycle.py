"""F-14 and F-15: setup/unload lifecycle and defensive state reads.

F-14: ``async_unload_entry`` popped the entry id with no default, and the
``_view_registered`` flag was a bool stored in the same dict as the
coordinators. That flag was also cleared when the last entry unloaded, so a
reload re-registered views that Home Assistant cannot unregister.

F-15: the summary sensors read ``self.coordinator.data.get(...)`` with no guard.
``DataUpdateCoordinator.data`` is None until the first successful refresh, so
any future change that adds entities before that refresh turns into an
AttributeError rather than a sensible default.
"""

from __future__ import annotations

import asyncio

import pytest

from cellar_tracker import async_setup, async_setup_entry, async_unload_entry
from cellar_tracker.const import DOMAIN
from cellar_tracker.sensor import TotalBottlesSensor, TotalValueSensor
from cellar_tracker.sensor import async_setup_entry as sensor_setup_entry
from conftest import ConfigEntry, ViewHass


class _Entries:
    def __init__(self):
        self.unload_ok = True

    async def async_forward_entry_setups(self, entry, platforms):
        return True

    async def async_unload_platforms(self, entry, platforms):
        return self.unload_ok

    async def async_reload(self, entry_id):
        return True


class LifecycleHass(ViewHass):
    def __init__(self):
        super().__init__({})
        self.config_entries = _Entries()


class _Coordinator:
    """Stands in for WineCellarData without touching the network."""

    def __init__(self, data=None):
        self.data = data
        self.currency = "USD"

    async def async_config_entry_first_refresh(self):
        return None


@pytest.fixture
def hass(monkeypatch):
    import cellar_tracker

    monkeypatch.setattr(
        cellar_tracker, "WineCellarData", lambda hass, entry: _Coordinator({"total_bottles": 1})
    )
    return LifecycleHass()


def setup(hass, entry):
    return asyncio.run(async_setup_entry(hass, entry))


def unload(hass, entry):
    return asyncio.run(async_unload_entry(hass, entry))


# --------------------------------------------------------------------------
# F-14: views are registered once, not tied to entry lifetime
# --------------------------------------------------------------------------
def test_views_are_registered_once_for_the_component():
    hass = LifecycleHass()
    asyncio.run(async_setup(hass, {}))
    assert sorted(hass.http.registered) == [
        "CellarTrackerInventoryView",
        "CellarTrackerSettingsView",
    ]


def test_a_second_entry_does_not_re_register_views(hass):
    asyncio.run(async_setup(hass, {}))
    setup(hass, ConfigEntry(entry_id="a"))
    setup(hass, ConfigEntry(entry_id="b"))
    assert len(hass.http.registered) == 2, "views registered more than once"


def test_reloading_the_last_entry_does_not_re_register_views(hass):
    asyncio.run(async_setup(hass, {}))
    entry = ConfigEntry(entry_id="a")
    setup(hass, entry)
    unload(hass, entry)
    setup(hass, entry)
    assert len(hass.http.registered) == 2, "views re-registered after a reload"


# --------------------------------------------------------------------------
# F-14: unload must be resilient
# --------------------------------------------------------------------------
def test_unloading_an_entry_removes_only_that_entry(hass):
    first, second = ConfigEntry(entry_id="a"), ConfigEntry(entry_id="b")
    setup(hass, first)
    setup(hass, second)

    assert unload(hass, first) is True
    assert set(hass.data[DOMAIN]) == {"b"}


def test_unloading_an_entry_that_was_never_stored_does_not_raise(hass):
    """A partially failed setup must not turn unload into a KeyError."""
    assert unload(hass, ConfigEntry(entry_id="never-set-up")) is True


def test_a_failed_platform_unload_leaves_the_entry_in_place(hass):
    entry = ConfigEntry(entry_id="a")
    setup(hass, entry)
    hass.config_entries.unload_ok = False

    assert unload(hass, entry) is False
    assert "a" in hass.data[DOMAIN]


def test_hass_data_holds_only_coordinators(hass):
    """No bookkeeping flags alongside the entries."""
    setup(hass, ConfigEntry(entry_id="a"))
    assert set(hass.data[DOMAIN]) == {"a"}
    assert all(not key.startswith("_") for key in hass.data[DOMAIN])


# --------------------------------------------------------------------------
# F-15: state reads must survive a coordinator with no data yet
# --------------------------------------------------------------------------
def _sensor(cls, data):
    entry = ConfigEntry(entry_id="a")
    hass = ViewHass({DOMAIN: {"a": _Coordinator(data)}})
    added = []
    asyncio.run(sensor_setup_entry(hass, entry, added.extend))
    return next(sensor for sensor in added if isinstance(sensor, cls))


@pytest.mark.parametrize(
    ("cls", "expected"),
    [(TotalBottlesSensor, 0), (TotalValueSensor, 0.0)],
)
def test_summary_sensors_tolerate_missing_data(cls, expected):
    assert _sensor(cls, None).native_value == expected


@pytest.mark.parametrize(
    ("cls", "expected"),
    [(TotalBottlesSensor, 0), (TotalValueSensor, 0.0)],
)
def test_summary_sensors_tolerate_a_partial_payload(cls, expected):
    assert _sensor(cls, {}).native_value == expected


def test_summary_sensors_still_report_real_values():
    payload = {"total_bottles": 7, "total_value": 12.5}
    assert _sensor(TotalBottlesSensor, payload).native_value == 7
    assert _sensor(TotalValueSensor, payload).native_value == 12.5
