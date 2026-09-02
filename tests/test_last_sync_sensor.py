"""P2-2 and P2-6: the status sensor had one reachable value and stored docs.

``return "Connected" if self.coordinator.data else "Empty"``. After the first
successful refresh ``coordinator.data`` is always a non-empty dict - an empty
cellar still yields ``{"total_bottles": 0, ...}``, which is truthy - and before
that refresh the entity is unavailable anyway, because CoordinatorEntity
derives ``available`` from ``last_update_success``. "Empty" was unreachable in
any state a user could observe, and "Connected" restated availability the
entity already reported.

Because the value was a constant, nothing could have been triggering on a
transition, which is what makes replacing it safe rather than breaking. It now
reports when the cellar last synchronised successfully - the thing a user
actually wants from a diagnostic entity, and the thing that tells them a
six-hourly integration is still alive.

P2-6: its attributes were a fixed API path and a sentence of setup advice,
persisted by the recorder on every state write. The README documents the
endpoint; the state machine is not the place for documentation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass

from cellar_tracker.const import DOMAIN
from cellar_tracker.sensor import CellarLastSyncSensor
from cellar_tracker.sensor import async_setup_entry as sensor_setup_entry
from conftest import ConfigEntry, ViewHass


class _Coordinator:
    def __init__(self, last_success=None, data=None):
        self.data = data if data is not None else {"total_bottles": 2, "bottles": []}
        self.currency = "USD"
        self.last_success = last_success


def build(coordinator) -> CellarLastSyncSensor:
    entry = ConfigEntry(entry_id="a", data={"username": "alice", "password": "x"})
    entry.runtime_data = coordinator
    hass = ViewHass({DOMAIN: {"a": coordinator}})
    added = []
    asyncio.run(sensor_setup_entry(hass, entry, added.extend))
    return next(s for s in added if isinstance(s, CellarLastSyncSensor))


def test_it_reports_a_timestamp():
    stamp = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)
    sensor = build(_Coordinator(last_success=stamp))

    assert sensor.device_class == SensorDeviceClass.TIMESTAMP
    assert sensor.native_value == stamp


def test_it_is_none_before_the_first_successful_poll():
    """Not a fabricated timestamp: unknown is the honest state."""
    assert build(_Coordinator(last_success=None)).native_value is None


def test_the_timestamp_is_timezone_aware():
    """A naive datetime is rejected by Home Assistant's timestamp sensors."""
    sensor = build(_Coordinator(last_success=datetime.now(UTC)))
    assert sensor.native_value.tzinfo is not None


def test_it_stores_no_documentation_in_its_attributes():
    """P2-6: the recorder persisted a fixed API path on every state write."""
    sensor = build(_Coordinator(last_success=datetime.now(UTC)))
    assert not (sensor.extra_state_attributes or {})


def test_it_stays_a_diagnostic_entity():
    sensor = build(_Coordinator())
    assert sensor.entity_category == "diagnostic"


def test_its_unique_id_is_unchanged():
    """Keeping the id means the existing entity is repurposed, not orphaned."""
    sensor = build(_Coordinator())
    assert sensor.unique_id == "a_inventory_status"


def test_the_coordinator_records_when_it_last_succeeded():
    from cellar_tracker.cellar_data import WineCellarData
    from conftest import FakeHass, FakeSession

    hass = FakeHass()
    hass.session = FakeSession(text="iWine\tWine\tValuation\n1\tBarolo\t45.50")
    coordinator = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))

    assert coordinator.last_success is None
    asyncio.run(coordinator._async_update_data())

    assert coordinator.last_success is not None
    assert coordinator.last_success.tzinfo is not None


# --------------------------------------------------------------------------
# Reported by Codex on #18
# --------------------------------------------------------------------------
def test_the_timestamp_is_part_of_the_coordinator_payload():
    """Otherwise always_update=False suppresses the update that carries it.

    A cellar's inventory is identical between most polls, so the coordinator
    compares the new payload equal to the old and notifies no listeners. A
    timestamp held outside that payload therefore never reaches the sensor,
    and "last synchronised" would silently mean "last time a bottle changed".
    """
    from cellar_tracker.cellar_data import WineCellarData
    from conftest import FakeHass, FakeSession

    export = "iWine\tWine\tValuation\n1\tBarolo\t45.50"
    hass = FakeHass()
    hass.session = FakeSession(text=export)
    coordinator = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))

    first = asyncio.run(coordinator._async_update_data())
    coordinator.data = first
    second = asyncio.run(coordinator._async_update_data())

    assert "last_success" in first
    assert first["bottles"] == second["bottles"], "the fixture must be unchanged"
    assert first != second, (
        "two polls of an unchanged cellar produced equal payloads, so the "
        "coordinator would notify no listeners and the timestamp would stall"
    )


def test_the_sensor_reads_the_timestamp_the_payload_carries():
    stamp = datetime(2026, 9, 2, 8, 30, tzinfo=UTC)
    sensor = build(_Coordinator(last_success=stamp))
    assert sensor.native_value == stamp
