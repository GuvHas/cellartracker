from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Literal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cellar_data import CellarData, CellarTrackerConfigEntry, RackState, WineCellarData
from .const import CONF_CURRENCY, DEFAULT_CURRENCY, DOMAIN, normalize_currency
from .rack_lights import SIGNAL_RACK_LIGHTS, showing
from .racks import Rack

# One typed place for what five constructors used to spell out. The key is
# also the translation key and the unique-id suffix, so nothing can drift
# between the registry, strings.json and the entity.
SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="total_bottles",
        translation_key="total_bottles",
        icon="mdi:bottle-wine",
        native_unit_of_measurement="bottles",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="total_value",
        translation_key="total_value",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ready_to_drink",
        translation_key="ready_to_drink",
        icon="mdi:glass-wine",
        native_unit_of_measurement="bottles",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="past_drink_window",
        translation_key="past_drink_window",
        icon="mdi:clock-alert-outline",
        native_unit_of_measurement="bottles",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="rack_grid",
        translation_key="rack_grid",
        icon="mdi:grid",
    ),
    SensorEntityDescription(
        key="rack_off_rack",
        translation_key="rack_off_rack",
        icon="mdi:map-marker-question",
        native_unit_of_measurement="bottles",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_synchronised",
        translation_key="last_synchronised",
        icon="mdi:cloud-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

DESCRIPTIONS_BY_KEY = {description.key: description for description in SENSOR_DESCRIPTIONS}

# Enough to work through after a rack is rebuilt; more means the rack line is wrong.
MAX_OFF_RACK_LISTED = 25


def _count(
    data: CellarData | None,
    key: Literal["total_bottles", "ready_to_drink", "past_drink_window"],
) -> int:
    """Read a count from the payload, defaulting rather than raising.

    Both defences are deliberate and covered by F-15. ``data`` is None until
    the first refresh succeeds, which is the state a sensor is in if its
    entity is read during a failed setup; and a payload that predates a key -
    the drink-window counters were added after the totals - has no such key at
    all. Neither should turn a state read into a traceback.
    """
    return 0 if data is None else data.get(key, 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CellarTrackerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: WineCellarData = entry.runtime_data

    currency = normalize_currency(
        entry.options.get(CONF_CURRENCY, entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY))
    )

    # Name the device after the account so two configured cellars are
    # distinguishable. entry.title is the username by default and follows a
    # rename of the config entry; a device the user renamed themselves keeps
    # their name regardless. The identifiers are unchanged, so this renames the
    # existing device rather than creating a second one.
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or "CellarTracker",
        manufacturer="CellarTracker",
        model="Inventory",
        # The enum rather than the string it happens to equal: a typo in a
        # bare "service" would silently produce a normal device.
        entry_type=DeviceEntryType.SERVICE,
    )

    sensors = [
        TotalBottlesSensor(coordinator, device_info, entry.entry_id),
        TotalValueSensor(coordinator, device_info, entry.entry_id, currency),
        ReadyToDrinkSensor(coordinator, device_info, entry.entry_id),
        PastDrinkWindowSensor(coordinator, device_info, entry.entry_id),
        CellarLastSyncSensor(coordinator, device_info, entry.entry_id),
    ]

    # Two per configured rack, and none for a cellar without LEDs.
    for rack in coordinator.racks:
        sensors.append(RackGridSensor(coordinator, device_info, entry.entry_id, rack))
        sensors.append(RackOffRackSensor(coordinator, device_info, entry.entry_id, rack))

    async_add_entities(sensors)


class TotalBottlesSensor(CoordinatorEntity[WineCellarData], SensorEntity):
    """How many bottles the cellar currently holds."""

    # Home Assistant composes the friendly name as "<device> <entity>", so the
    # entity name must not repeat the integration's own name. The name itself
    # comes from strings.json via the translation key, not from a literal here.
    _attr_has_entity_name = True

    def __init__(self, coordinator: WineCellarData, device_info: DeviceInfo, entry_id: str) -> None:
        super().__init__(coordinator)
        self.entity_description = DESCRIPTIONS_BY_KEY["total_bottles"]
        self._attr_unique_id = f"{entry_id}_total_bottles"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> int:
        return _count(self.coordinator.data, "total_bottles")


class TotalValueSensor(CoordinatorEntity[WineCellarData], SensorEntity):
    """What the cellar is worth, in the configured currency.

    MONETARY with state_class TOTAL, so Home Assistant keeps a long-term
    statistic - cellar value over time being the reason to have the sensor.
    That also means the unit cannot change without invalidating the existing
    statistic, which is why the options flow warns before letting it happen.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WineCellarData,
        device_info: DeviceInfo,
        entry_id: str,
        currency: str = DEFAULT_CURRENCY,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = DESCRIPTIONS_BY_KEY["total_value"]
        self._attr_unique_id = f"{entry_id}_total_value"
        self._attr_device_info = device_info
        # The one field the description cannot hold: it is per-entry.
        self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> float:
        data = self.coordinator.data
        return 0.0 if data is None else data.get("total_value", 0.0)


class _BottleCountSensor(CoordinatorEntity[WineCellarData], SensorEntity):
    """Shared shape for the drink-window counters.

    Both are plain counts the coordinator computed during the parse, so they
    add no work at read time and - importantly - no entity per bottle. That is
    the property that keeps a 1,000-bottle cellar cheap, and these counters
    exist to give drink-window information without giving it up.
    """

    _attr_has_entity_name = True
    # A literal union rather than a bare str: it is used to index CellarData,
    # and only a literal lets the checker confirm the key exists at all.
    _data_key: Literal["ready_to_drink", "past_drink_window"]

    def __init__(self, coordinator: WineCellarData, device_info: DeviceInfo, entry_id: str) -> None:
        super().__init__(coordinator)
        self.entity_description = DESCRIPTIONS_BY_KEY[self._data_key]
        self._attr_unique_id = f"{entry_id}_{self._data_key}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> int:
        return _count(self.coordinator.data, self._data_key)


class ReadyToDrinkSensor(_BottleCountSensor):
    """Bottles whose drinking window includes this year."""

    _data_key = "ready_to_drink"


class PastDrinkWindowSensor(_BottleCountSensor):
    """Bottles whose drinking window ended before this year."""

    _data_key = "past_drink_window"


class CellarLastSyncSensor(CoordinatorEntity[WineCellarData], SensorEntity):
    """When the cellar last synchronised with CellarTracker.

    This replaces a status sensor that reported "Connected" or "Empty". After
    the first refresh ``coordinator.data`` is always a non-empty dict - an
    empty cellar still yields ``{"total_bottles": 0, ...}`` - and before it the
    entity is unavailable anyway, so "Empty" was unreachable and "Connected"
    only restated the availability the entity already reports.

    It keeps the old unique id, so the existing entity is repurposed rather
    than orphaned and a second one is not created. Nothing could have been
    triggering on the old value, which never changed.

    A timestamp is what a user actually needs from a diagnostic entity here: it
    is how you tell that an integration polling every six hours is still alive.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: WineCellarData, device_info: DeviceInfo, entry_id: str) -> None:
        super().__init__(coordinator)
        self.entity_description = DESCRIPTIONS_BY_KEY["last_synchronised"]
        self._attr_unique_id = f"{entry_id}_inventory_status"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> datetime | None:
        """The last successful refresh, or None if none has happened yet."""
        return self.coordinator.last_success


def _rack_slug(location: str) -> str:
    """A unique-id fragment for a rack, stable across renames of its sensors.

    Readable, plus a short hash of the exact location: the readable part alone
    collapses "Wine Rack 1" and "Wine-Rack-1", or any two all non-ASCII names,
    into one id, and Home Assistant would then drop one rack's sensors.
    """
    readable = re.sub(r"[^a-z0-9]+", "_", location.casefold()).strip("_") or "rack"
    return f"{readable}_{hashlib.sha256(location.encode('utf-8')).hexdigest()[:8]}"


class _RackSensor(CoordinatorEntity[WineCellarData], SensorEntity):
    """Shared shape for the per-rack sensors.

    Keyed by the rack's CellarTracker location, which is what the user typed
    and what the bottles are filed under. Renaming a location in CellarTracker
    and in the options therefore makes a new entity, which is right: the old
    one described a rack that no longer has that name anywhere.
    """

    _attr_has_entity_name = True
    _key: Literal["rack_grid", "rack_off_rack"]

    def __init__(
        self,
        coordinator: WineCellarData,
        device_info: DeviceInfo,
        entry_id: str,
        rack: Rack,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = DESCRIPTIONS_BY_KEY[self._key]
        self._rack = rack
        self._attr_unique_id = f"{entry_id}_{self._key}_{_rack_slug(rack.location)}"
        self._attr_device_info = device_info
        self._attr_translation_placeholders = {"rack": rack.location}

    def _state(self) -> RackState | None:
        data = self.coordinator.data
        racks = None if data is None else data.get("racks")
        return None if racks is None else racks.get(self._rack.location)


class RackGridSensor(_RackSensor):
    """One state character per bin of a rack, for its LED node to paint.

    The node's ``light_rack`` action takes this string as it is. Characters
    are row-major over the rack's whole envelope - ``.NARUP``: empty, no
    window, aging, ready, drink this year, past - and bins the rack does not
    have are always ``.``, so the length never depends on the shape.
    """

    _key = "rack_grid"

    def __init__(
        self,
        coordinator: WineCellarData,
        device_info: DeviceInfo,
        entry_id: str,
        rack: Rack,
    ) -> None:
        super().__init__(coordinator, device_info, entry_id, rack)
        # Static, so an automation can check it is talking to the rack it
        # thinks it is without parsing the options.
        self._shape = {
            "location": rack.location,
            "rows": rack.rows,
            "columns": rack.cols,
        }

    async def async_added_to_hass(self) -> None:
        """Say so whenever the racks are asked to show something else."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_RACK_LIGHTS, self.async_write_ha_state)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The rack's shape, and what the racks were last asked to show.

        ``showing`` is what the paint automation checks before a background
        repaint, so a sync neither lights a rack that went dark nor wipes a
        highlight someone is looking at.
        """
        # Home Assistant types hass as always set, but it is None until the
        # entity is added.
        hass: HomeAssistant | None = self.hass
        if hass is None:
            return dict(self._shape)
        return {**self._shape, "showing": showing(hass, self.coordinator.racks_idle_off)}

    @property
    def native_value(self) -> str | None:
        """None until the first poll that knew about this rack."""
        state = self._state()
        return None if state is None else state["grid"]


class RackOffRackSensor(_RackSensor):
    """Bottles filed at a rack that no bin on it will light.

    A bin outside the rack, in a gap the rack does not have, or unreadable.
    Typically what a rebuild leaves behind; re-bin them in CellarTracker.
    """

    _key = "rack_off_rack"
    # The list is for finding the bottles now, not for history: kept out of
    # the recorder, like the grid would be if it were not the state.
    _unrecorded_attributes = frozenset({"bottles"})

    @property
    def native_value(self) -> int | None:
        state = self._state()
        return None if state is None else state["off_rack"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which bottles, so they can be found and re-binned in CellarTracker.

        Capped: a rack line with the wrong shape can put a whole rack here,
        and an entity's attributes are not the place for a cellar listing.
        """
        state = self._state()
        off = [] if state is None else state.get("off_rack_bottles", [])
        attributes: dict[str, Any] = {"bottles": off[:MAX_OFF_RACK_LISTED]}
        if len(off) > MAX_OFF_RACK_LISTED:
            attributes["not_listed"] = len(off) - MAX_OFF_RACK_LISTED
        return attributes
