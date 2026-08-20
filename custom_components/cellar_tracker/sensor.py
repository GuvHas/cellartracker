from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cellar_data import WineCellarData
from .const import CONF_CURRENCY, DEFAULT_CURRENCY, DOMAIN, normalize_currency


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: WineCellarData = hass.data[DOMAIN][entry.entry_id]

    currency = normalize_currency(
        entry.options.get(CONF_CURRENCY, entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY))
    )

    # Name the device after the account so two configured cellars are
    # distinguishable. entry.title is the username by default and follows a
    # rename of the config entry; a device the user renamed themselves keeps
    # their name regardless. The identifiers are unchanged, so this renames the
    # existing device rather than creating a second one.
    device_info = {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.title or "CellarTracker",
        "manufacturer": "CellarTracker",
        "model": "Inventory",
        "entry_type": "service",
    }

    sensors = [
        TotalBottlesSensor(coordinator, device_info, entry.entry_id),
        TotalValueSensor(coordinator, device_info, entry.entry_id, currency),
        CellarInventorySensor(coordinator, device_info, entry.entry_id),
    ]

    async_add_entities(sensors)


class TotalBottlesSensor(CoordinatorEntity, SensorEntity):
    # Home Assistant composes the friendly name as "<device> <entity>", so the
    # entity name must not repeat the integration's own name.
    _attr_has_entity_name = True

    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_name = "Total bottles"
        self._attr_unique_id = f"{entry_id}_total_bottles"
        self._attr_icon = "mdi:bottle-wine"
        self._attr_device_info = device_info
        self._attr_native_unit_of_measurement = "bottles"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data.get("total_bottles", 0)


class TotalValueSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, device_info, entry_id, currency=DEFAULT_CURRENCY):
        super().__init__(coordinator)
        self._attr_name = "Total value"
        self._attr_unique_id = f"{entry_id}_total_value"
        self._attr_device_info = device_info
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = currency
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_suggested_display_precision = 2

    @property
    def native_value(self):
        return self.coordinator.data.get("total_value", 0.0)


class CellarInventorySensor(CoordinatorEntity, SensorEntity):
    """
    Master sensor indicating status.
    NOTE: Detailed bottle list is exposed via API, not attributes, to avoid DB crash.
    """
    _attr_has_entity_name = True

    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_name = "Status"
        self._attr_unique_id = f"{entry_id}_inventory_status"
        self._attr_icon = "mdi:api"
        self._attr_device_info = device_info
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return "Connected" if self.coordinator.data else "Empty"

    @property
    def extra_state_attributes(self):
        # We purposely do NOT include 'bottles' here.
        return {
            "api_endpoint": "/api/cellartracker/inventory",
            "info": "Configure Flex Table Card with 'url: /api/cellartracker/inventory'"
        }
