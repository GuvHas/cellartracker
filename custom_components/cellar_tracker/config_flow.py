"""Config and options flow for the CellarTracker integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

# Classify failures by exception type: the library raises these bare, so
# `str(err)` is always "" and message sniffing can never match.
from cellartracker.errors import AuthenticationError, CannotConnect
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback

from .cellar_data import async_fetch_inventory_payload
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


class CellarTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CellarTracker."""

    VERSION = 1

    async def _async_check_credentials(self, username: str, password: str) -> dict:
        """Return a form-errors dict; empty means the credentials are valid."""
        try:
            # The same non-blocking fetch the coordinator uses, so a hung
            # server cannot stall setup on a worker thread.
            await async_fetch_inventory_payload(self.hass, username, password)
        except AuthenticationError:
            _LOGGER.warning("CellarTracker rejected the credentials for %s", username)
            return {"base": "invalid_auth"}
        except (CannotConnect, TimeoutError, OSError) as err:
            _LOGGER.warning("Cannot reach CellarTracker while validating: %r", err)
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error validating CellarTracker credentials")
            return {"base": "unknown"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Handle the initial user step."""
        # One CellarTracker account per installation. Checked before anything
        # else so a duplicate is refused without a round trip to CellarTracker,
        # and checked via the entry list rather than the unique id alone so
        # that legacy entries - keyed on the username - also block.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors = {}

        if user_input is not None:
            user_input[CONF_CURRENCY] = normalize_currency(
                user_input.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            )

            errors = await self._async_check_credentials(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                # The domain, not the username: a second entry is a duplicate
                # whichever account it names.
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> Any:
        """Entry point when the coordinator raises ConfigEntryAuthFailed."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
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
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CellarTrackerOptionsFlowHandler:
        """Return the options flow handler."""
        return CellarTrackerOptionsFlowHandler()


class CellarTrackerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for CellarTracker."""

    # `self.config_entry` is provided automatically by the base class.

    def _current_currency(self) -> str:
        return normalize_currency(
            self.config_entry.options.get(
                CONF_CURRENCY, self.config_entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            )
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Manage the options."""
        if user_input is not None:
            previous = self._current_currency()
            user_input[CONF_CURRENCY] = normalize_currency(
                user_input.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            )
            if user_input[CONF_CURRENCY] != previous:
                # The cellar value is a long-term statistic, and Home Assistant
                # treats a unit change on an existing statistic as an error: it
                # logs a mismatch and stops recording until the statistic is
                # cleared. Say so here, where the user has just done it and can
                # still act, rather than leaving them to find it in the log.
                _LOGGER.warning(
                    "CellarTracker currency changed from %s to %s. This relabels "
                    "the cellar value rather than converting it, and Home "
                    "Assistant will refuse to record the value sensor's "
                    "long-term statistic until its existing statistic is "
                    "cleared in Developer tools > Statistics.",
                    previous,
                    user_input[CONF_CURRENCY],
                )
            return self.async_create_entry(title="", data=user_input)

        current_scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_currency = self._current_currency()

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_scan_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
                ),
                vol.Optional(CONF_CURRENCY, default=current_currency): vol.In(CURRENCY_OPTIONS),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
