# sensor.py

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
        "model": "Online Cellar",
        "entry_type": "service",
    }

    # We now only create 3 sensors total, regardless of cellar size
    sensors = [
        TotalBottlesSensor(coordinator, device_info, entry.entry_id),
        TotalValueSensor(coordinator, device_info, entry.entry_id),
        CellarInventorySensor(coordinator, device_info, entry.entry_id),
    ]

    async_add_entities(sensors, update_before_add=True)


class TotalBottlesSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the total number of bottles in the cellar."""

    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_name = "CellarTracker Total Bottles"
        self._attr_unique_id = f"{entry_id}_total_bottles"
        self._attr_icon = "mdi:bottle-wine"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("total_bottles", 0)


class TotalValueSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the total value of the cellar."""

    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_name = "CellarTracker Total Value"
        self._attr_unique_id = f"{entry_id}_total_value"
        self._attr_device_info = device_info
        self._attr_icon = "mdi:currency-eur"
        self._attr_native_unit_of_measurement = "kr"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("total_value", 0.0)


class CellarInventorySensor(CoordinatorEntity, SensorEntity):
    """Master sensor containing the full bottle list as attributes."""

    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_name = "CellarTracker Inventory"
        self._attr_unique_id = f"{entry_id}_inventory"
        self._attr_icon = "mdi:clipboard-list"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        """State is simply the timestamp of the last update or 'OK'."""
        return "OK" if self.coordinator.data else "Empty"

    @property
    def extra_state_attributes(self):
        """Return the list of bottles in the attributes."""
        # We expose the entire list of bottles here.
        # Frontend cards will iterate over this list instead of over entities.
        return {
            "bottles": self.coordinator.data.get("bottles", [])
        }