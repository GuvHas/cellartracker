"""The CellarTracker integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .cellar_data import WineCellarData
from .views import CellarTrackerInventoryView, CellarTrackerSettingsView
from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CellarTracker from a config entry."""
    coordinator = WineCellarData(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register the custom API view only once across all config entries
    if not hass.data[DOMAIN].get("_view_registered"):
        hass.http.register_view(CellarTrackerInventoryView(hass))
        hass.http.register_view(CellarTrackerSettingsView(hass))
        hass.data[DOMAIN]["_view_registered"] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        # Reset view flag when no more config entries remain
        remaining = {k: v for k, v in hass.data[DOMAIN].items() if k != "_view_registered"}
        if not remaining:
            hass.data[DOMAIN].pop("_view_registered", None)
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)