from __future__ import annotations

from datetime import datetime
from typing import Literal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cellar_data import CellarData, CellarTrackerConfigEntry, WineCellarData
from .const import CONF_CURRENCY, DEFAULT_CURRENCY, DOMAIN, normalize_currency

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
        key="last_synchronised",
        translation_key="last_synchronised",
        icon="mdi:cloud-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

DESCRIPTIONS_BY_KEY = {description.key: description for description in SENSOR_DESCRIPTIONS}


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

    async_add_entities(sensors)


class TotalBottlesSensor(CoordinatorEntity[WineCellarData], SensorEntity):
    """How many bottles the cellar currently holds."""

    # Home Assistant composes the friendly name as "<device> <entity>", so the
    # entity name must not repeat the integration's own name. The name itself
    # comes from strings.json via the translation key, not from a literal here.
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: WineCellarData, device_info: DeviceInfo, entry_id: str
    ) -> None:
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

    def __init__(
        self, coordinator: WineCellarData, device_info: DeviceInfo, entry_id: str
    ) -> None:
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

    def __init__(
        self, coordinator: WineCellarData, device_info: DeviceInfo, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = DESCRIPTIONS_BY_KEY["last_synchronised"]
        self._attr_unique_id = f"{entry_id}_inventory_status"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> datetime | None:
        """The last successful refresh, or None if none has happened yet."""
        return self.coordinator.last_success
