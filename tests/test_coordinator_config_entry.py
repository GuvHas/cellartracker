"""P0-1: the coordinator must be constructed with its config entry.

Home Assistant 2024.11 added ``config_entry`` to ``DataUpdateCoordinator``.
Omitting it logs a deprecation warning today and is scheduled to become
mandatory; when it does, setup raises and the integration stops loading.

Passing it is not only about silencing the warning. The coordinator registers
its refresh task against the entry, so unloading the entry cancels a poll that
is still in flight instead of leaving it running against a torn-down entry.

The entry is already the constructor's own argument, so nothing has to be
threaded through to make this work.
"""

from __future__ import annotations

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass, FakeSession

ENTRY_DATA = {"username": "alice", "password": "s3cret", "currency": "USD"}


def build() -> tuple[WineCellarData, ConfigEntry]:
    hass = FakeHass()
    hass.session = FakeSession()
    entry = ConfigEntry(entry_id="entry-abc", data=ENTRY_DATA)
    return WineCellarData(hass, entry), entry


def test_the_entry_reaches_the_base_coordinator():
    coordinator, entry = build()
    assert coordinator.config_entry is entry, (
        "DataUpdateCoordinator must receive config_entry= or Home Assistant "
        "will refuse to construct it once the deprecation lands"
    )


def test_the_entry_is_not_smuggled_through_kwargs():
    """It has to be the named parameter, not an extra the base class ignores."""
    coordinator, _ = build()
    assert "config_entry" not in coordinator.init_kwargs
