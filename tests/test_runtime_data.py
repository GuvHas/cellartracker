"""P1-4: the coordinator belongs on the entry, not in hass.data.

``entry.runtime_data`` has been the convention since Home Assistant 2024.6 and
core review rejects ``hass.data[DOMAIN][entry_id]`` for new integrations. It is
typed, it dies with the entry, and it removes the manual pop in
``async_unload_entry`` that exists only to avoid leaking a coordinator.

The wrinkle here is the HTTP views. They are registered once in
``async_setup`` - deliberately, because Home Assistant offers no way to
unregister a view - so they have no entry in hand and cannot be handed one.
They reach the coordinator through the config entries instead, which keeps the
legacy two-entry behaviour intact: ``?entry_id=`` still selects, and an absent
or unknown id still falls back to the lowest entry id with a warning.

test_views.py is the contract for that behaviour and is deliberately unchanged
by this migration.
"""

from __future__ import annotations

import asyncio

from cellar_tracker import async_setup_entry, async_unload_entry
from cellar_tracker.const import DOMAIN
from conftest import ConfigEntry, FakeCoordinator, SetupHass


def test_setup_puts_the_coordinator_on_the_entry():
    hass = SetupHass()
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data is not None
    assert entry.runtime_data.currency == "USD"


def test_setup_no_longer_writes_to_hass_data():
    """The whole point of the migration: nothing accumulates in hass.data."""
    hass = SetupHass()
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})

    asyncio.run(async_setup_entry(hass, entry))

    assert DOMAIN not in hass.data


def test_unload_clears_the_runtime_data():
    hass = SetupHass()
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})
    asyncio.run(async_setup_entry(hass, entry))

    assert asyncio.run(async_unload_entry(hass, entry)) is True
    assert getattr(entry, "runtime_data", None) is None


def test_unloading_a_half_set_up_entry_does_not_raise():
    """Setup can fail before runtime_data is assigned; unload still runs."""
    hass = SetupHass()
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})

    assert asyncio.run(async_unload_entry(hass, entry)) is True


def test_the_views_find_the_coordinator_through_the_entries():
    """The lookup the views depend on, exercised without going through setup."""
    from cellar_tracker.views import CellarTrackerInventoryView
    from conftest import FakeRequest, ViewHass

    coordinator = FakeCoordinator(bottles=[{"iWine": "1", "Wine": "Barolo"}])
    hass = ViewHass({DOMAIN: {"a": coordinator}})

    view = CellarTrackerInventoryView(hass)
    response = asyncio.run(view.get(FakeRequest()))

    assert response.body == coordinator.inventory_body


def test_an_entry_that_is_not_loaded_is_invisible_to_the_views():
    """A failed or unloaded entry must not be served as if it were live."""
    from cellar_tracker.views import CellarTrackerInventoryView
    from conftest import FakeRequest, ViewHass

    hass = ViewHass({DOMAIN: {"a": FakeCoordinator(bottles=[{"iWine": "1"}])}})
    for entry in hass.config_entries.async_entries(DOMAIN):
        entry.runtime_data = None

    view = CellarTrackerInventoryView(hass)
    response = asyncio.run(view.get(FakeRequest()))

    assert response.body == b"[]"
