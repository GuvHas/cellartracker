"""Config and options flow for the CellarTracker integration."""

import logging

import voluptuous as vol

# Classify failures by exception type: the library raises these bare, so
# `str(err)` is always "" and message sniffing can never match.
from cellartracker import cellartracker
from cellartracker.errors import AuthenticationError, CannotConnect

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import callback

from .const import (
    CONF_CURRENCY,
    CURRENCY_OPTIONS,
    DEFAULT_CURRENCY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    normalize_currency,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
        ),
        vol.Optional(CONF_CURRENCY, default=DEFAULT_CURRENCY): vol.In(CURRENCY_OPTIONS),
    }
)

REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def _validate_credentials(username: str, password: str) -> None:
    """Authenticate against CellarTracker. Blocking - run in an executor.

    Raises:
        AuthenticationError: the username/password pair was rejected.
        CannotConnect: CellarTracker was unreachable.
    """
    cellartracker.CellarTracker(username, password).get_inventory()


class CellarTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CellarTracker."""

    VERSION = 1

    async def _async_check_credentials(self, username: str, password: str) -> dict:
        """Return a form-errors dict; empty means the credentials are valid."""
        try:
            await self.hass.async_add_executor_job(
                _validate_credentials, username, password
            )
        except AuthenticationError:
            _LOGGER.warning("CellarTracker rejected the credentials for %s", username)
            return {"base": "invalid_auth"}
        except (CannotConnect, TimeoutError, OSError) as err:
            _LOGGER.warning("Cannot reach CellarTracker while validating: %r", err)
            return {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001 - third-party library, unknown surface
            _LOGGER.exception("Unexpected error validating CellarTracker credentials")
            return {"base": "unknown"}
        return {}

    async def async_step_user(self, user_input=None):
        """Handle the initial user step."""
        errors = {}

        if user_input is not None:
            user_input[CONF_CURRENCY] = normalize_currency(
                user_input.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            )

            errors = await self._async_check_credentials(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data):
        """Entry point when the coordinator raises ConfigEntryAuthFailed."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Ask for a new password for the existing account."""
        entry = self._get_reauth_entry()
        username = entry.data[CONF_USERNAME]
        errors = {}

        if user_input is not None:
            errors = await self._async_check_credentials(
                username, user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"username": username},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow handler."""
        return CellarTrackerOptionsFlowHandler()


class CellarTrackerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for CellarTracker."""

    # `self.config_entry` is provided automatically by the base class.

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            user_input[CONF_CURRENCY] = normalize_currency(
                user_input.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            )
            return self.async_create_entry(title="", data=user_input)

        current_scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_currency = normalize_currency(
            self.config_entry.options.get(
                CONF_CURRENCY, self.config_entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            )
        )

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_scan_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
                ),
                vol.Optional(CONF_CURRENCY, default=current_currency): vol.In(CURRENCY_OPTIONS),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
