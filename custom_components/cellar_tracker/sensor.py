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
    coordinator: WineCellarData = entry.runtime_data

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
        CellarLastSyncSensor(coordinator, device_info, entry.entry_id),
    ]

    async_add_entities(sensors)


class TotalBottlesSensor(CoordinatorEntity, SensorEntity):
    """How many bottles the cellar currently holds."""

    # Home Assistant composes the friendly name as "<device> <entity>", so the
    # entity name must not repeat the integration's own name. The name itself
    # comes from strings.json via the translation key, not from a literal here.
    _attr_has_entity_name = True
    _attr_translation_key = "total_bottles"

    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_total_bottles"
        self._attr_icon = "mdi:bottle-wine"
        self._attr_device_info = device_info
        self._attr_native_unit_of_measurement = "bottles"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        # `or {}`: coordinator.data is None until the first successful refresh.
        return (self.coordinator.data or {}).get("total_bottles", 0)


class TotalValueSensor(CoordinatorEntity, SensorEntity):
    """What the cellar is worth, in the configured currency.

    MONETARY with state_class TOTAL, so Home Assistant keeps a long-term
    statistic - cellar value over time being the reason to have the sensor.
    That also means the unit cannot change without invalidating the existing
    statistic, which is why the options flow warns before letting it happen.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "total_value"

    def __init__(self, coordinator, device_info, entry_id, currency=DEFAULT_CURRENCY):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_total_value"
        self._attr_device_info = device_info
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = currency
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_suggested_display_precision = 2

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("total_value", 0.0)


class CellarLastSyncSensor(CoordinatorEntity, SensorEntity):
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
    _attr_translation_key = "last_synchronised"

    def __init__(self, coordinator, device_info, entry_id):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_inventory_status"
        self._attr_icon = "mdi:cloud-check-outline"
        self._attr_device_info = device_info
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """The last successful refresh, or None if none has happened yet."""
        return self.coordinator.last_success
