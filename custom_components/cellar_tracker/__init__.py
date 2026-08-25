"""The CellarTracker integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .cellar_data import WineCellarData
from .const import DOMAIN, PLATFORMS
from .views import CellarTrackerInventoryView, CellarTrackerSettingsView

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the component.

    Home Assistant calls this once, before the first config entry. The views
    belong here rather than in async_setup_entry: they are global to the
    component and Home Assistant offers no way to unregister one, so
    registering them per entry risked registering the same route twice after
    an unload/reload cycle.
    """
    hass.http.register_view(CellarTrackerInventoryView(hass))
    hass.http.register_view(CellarTrackerSettingsView(hass))
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CellarTracker from a config entry."""
    coordinator = WineCellarData(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # Holds coordinators keyed by entry id and nothing else: the views rely on
    # every value here being a coordinator.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Defaulted: a setup that failed before storing its coordinator still
        # gets unloaded, and that must not become a KeyError.
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
