"""The CellarTracker integration."""
import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .cellar_data import WineCellarData
from .const import DASHBOARD_FILENAME, DASHBOARD_URL, DOMAIN, PLATFORMS
from .views import CellarTrackerInventoryView, CellarTrackerSettingsView

_LOGGER = logging.getLogger(__name__)

# There is nothing to configure in configuration.yaml; declaring that is also
# what hassfest requires of any integration that implements async_setup.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Shipped inside the integration directory, so that whichever way the
# integration was installed - HACS or a manual copy - the page is present.
DASHBOARD_FILE = Path(__file__).parent / "www" / DASHBOARD_FILENAME

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the component.

    Home Assistant calls this once, before the first config entry. The views
    belong here rather than in async_setup_entry: they are global to the
    component and Home Assistant offers no way to unregister one, so
    registering them per entry risked registering the same route twice after
    an unload/reload cycle. The dashboard page is static and equally global,
    so it is served from here too.
    """
    hass.http.register_view(CellarTrackerInventoryView(hass))
    hass.http.register_view(CellarTrackerSettingsView(hass))
    await _async_register_dashboard(hass)
    return True

async def _async_register_dashboard(hass: HomeAssistant) -> None:
    """Serve the bundled dashboard page at DASHBOARD_URL.

    Users no longer copy anything into <config>/www: the page travels with the
    integration and is served from where it was installed. Existing installs
    that copied it keep working, because /local/cellar.html is Home Assistant's
    own static mount and is untouched by this.

    A missing page must not take the whole integration down with it, so a
    partial install degrades to "no dashboard" rather than "no sensors".
    """
    if not await hass.async_add_executor_job(DASHBOARD_FILE.is_file):
        _LOGGER.warning(
            "Dashboard page %s is missing, so %s will not be served. Reinstall the "
            "integration to restore it; the sensors and the API are unaffected",
            DASHBOARD_FILE,
            DASHBOARD_URL,
        )
        return

    await hass.http.async_register_static_paths(
        # cache_headers=False: an integration update must not leave browsers
        # serving the previous page from cache.
        [StaticPathConfig(DASHBOARD_URL, str(DASHBOARD_FILE), False)]
    )

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
