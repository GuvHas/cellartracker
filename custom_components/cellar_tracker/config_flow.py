# config_flow.py

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL

from .const import DOMAIN, CONF_CURRENCY, DEFAULT_CURRENCY, CURRENCY_OPTIONS

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=3600): vol.All(vol.Coerce(int), vol.Range(min=300)),
        vol.Optional(CONF_CURRENCY, default=DEFAULT_CURRENCY): vol.In(CURRENCY_OPTIONS),
    }
)

class CellarTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CellarTracker."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial user step."""
        errors = {}

        if user_input is not None:
            try:
                def _validate_credentials():
                    """Validate credentials by authenticating and fetching data."""
                    from cellartracker import cellartracker
                    
                    client = cellartracker.CellarTracker(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
                    client.get_inventory()
                    return True
                
                await self.hass.async_add_executor_job(_validate_credentials)
                
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)

            except Exception:
                _LOGGER.exception("Failed to connect to CellarTracker with provided credentials")
                errors["base"] = "auth"
        
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow handler."""
        return CellarTrackerOptionsFlowHandler()


class CellarTrackerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for CellarTracker."""

    # The __init__ method has been completely removed as it is no longer necessary.
    # The 'self.config_entry' attribute is now automatically provided by the base class.

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, self.config_entry.data.get(CONF_SCAN_INTERVAL, 3600)
        )
        current_currency = self.config_entry.options.get(
            CONF_CURRENCY, self.config_entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)
        )

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_scan_interval): vol.All(vol.Coerce(int), vol.Range(min=300)),
                vol.Optional(CONF_CURRENCY, default=current_currency): vol.In(CURRENCY_OPTIONS),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)