from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .cellar_data import WineCellarData

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: WineCellarData = hass.data[DOMAIN][entry.entry_id]

    device_info = {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "CellarTracker",
        "manufacturer": "CellarTracker",
        "model": "Inventory",
        "entry_type": "service",
    }

    sensors = [
        TotalBottlesSensor(coordinator, device_info, entry.entry_id),
        TotalValueSensor(coordinator, device_info, entry.entry_id),
        CellarInventorySensor(coordinator, device_info, entry.entry_id),
    ]

    async_add_entities(sensors)


class TotalBottlesSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_name = "CellarTracker Total Bottles"
        self._attr_unique_id = f"{entry_id}_total_bottles"
        self._attr_icon = "mdi:bottle-wine"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return self.coordinator.data.get("total_bottles", 0)


class TotalValueSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_name = "CellarTracker Total Value"
        self._attr_unique_id = f"{entry_id}_total_value"
        self._attr_device_info = device_info
        self._attr_icon = "mdi:currency-usd"

    @property
    def native_value(self):
        return self.coordinator.data.get("total_value", 0.0)


class CellarInventorySensor(CoordinatorEntity, SensorEntity):
    """
    Master sensor indicating status. 
    NOTE: Detailed bottle list is exposed via API, not attributes, to avoid DB crash.
    """
    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_name = "CellarTracker Status"
        self._attr_unique_id = f"{entry_id}_inventory_status"
        self._attr_icon = "mdi:api"
        self._attr_device_info = device_info

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