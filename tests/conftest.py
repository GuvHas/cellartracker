"""Test harness for the CellarTracker integration.

Home Assistant is a very heavy test dependency (``pytest-homeassistant-custom-component``
pulls in the full HA core). These unit tests exercise *our* logic - error
classification, the reauth flow, inventory parsing - none of which needs a running
Home Assistant. So we stub the handful of ``homeassistant.*`` symbols the
integration imports.

Anything that genuinely needs HA's flow engine or entity registry belongs in a
separate integration-test suite (see F-19 in the review).
"""

from __future__ import annotations

import pathlib
import sys
import types

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "custom_components"))


def _module(name: str, **attrs: object) -> types.ModuleType:
    """Register a stub module in ``sys.modules``."""
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


# --- homeassistant.exceptions -------------------------------------------------
class ConfigEntryAuthFailed(Exception):
    """Stub of homeassistant.exceptions.ConfigEntryAuthFailed."""


class ConfigEntryNotReady(Exception):
    """Stub of homeassistant.exceptions.ConfigEntryNotReady."""


class UpdateFailed(Exception):
    """Stub of homeassistant.helpers.update_coordinator.UpdateFailed."""


# --- homeassistant.helpers.update_coordinator ---------------------------------
class DataUpdateCoordinator:
    """Minimal stand-in that records what the real base class would receive."""

    def __init__(self, hass, logger, *, name=None, update_interval=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None


# --- homeassistant.config_entries --------------------------------------------
class ConfigEntry:
    """Lightweight config entry double."""

    def __init__(self, *, entry_id="test_entry", data=None, options=None):
        self.entry_id = entry_id
        self.data = data or {}
        self.options = options or {}


class _FlowBase:
    """Shared fake for ConfigFlow/OptionsFlow result helpers.

    Each helper returns a plain dict describing what HA would have done, so tests
    can assert on flow outcomes without HA's data_entry_flow engine.
    """

    hass = None
    context: dict

    def __init_subclass__(cls, **kwargs):
        # Swallow the `domain=DOMAIN` keyword the real ConfigFlow accepts.
        kwargs.pop("domain", None)
        super().__init_subclass__(**kwargs)

    def async_show_form(self, *, step_id, data_schema=None, errors=None, **kwargs):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            **kwargs,
        }

    def async_create_entry(self, *, title, data, **kwargs):
        return {"type": "create_entry", "title": title, "data": data}

    def async_abort(self, *, reason, **kwargs):
        return {"type": "abort", "reason": reason}

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        return None

    # --- reauth helpers (HA >= 2024.11) ---
    def _get_reauth_entry(self):
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    def async_update_reload_and_abort(
        self, entry, *, data_updates=None, reason="reauth_successful", **kwargs
    ):
        if data_updates:
            entry.data = {**entry.data, **data_updates}
        return {"type": "abort", "reason": reason, "entry": entry}


class ConfigFlow(_FlowBase):
    """Stub of homeassistant.config_entries.ConfigFlow."""


class OptionsFlow(_FlowBase):
    """Stub of homeassistant.config_entries.OptionsFlow."""

    config_entry: ConfigEntry


_module("homeassistant")
_module(
    "homeassistant.const",
    CONF_PASSWORD="password",
    CONF_USERNAME="username",
    CONF_SCAN_INTERVAL="scan_interval",
)
_module(
    "homeassistant.config_entries",
    ConfigEntry=ConfigEntry,
    ConfigFlow=ConfigFlow,
    OptionsFlow=OptionsFlow,
)
_module("homeassistant.core", HomeAssistant=object, callback=lambda func: func)
_module(
    "homeassistant.exceptions",
    ConfigEntryAuthFailed=ConfigEntryAuthFailed,
    ConfigEntryNotReady=ConfigEntryNotReady,
)
_module("homeassistant.helpers")
_module(
    "homeassistant.helpers.update_coordinator",
    DataUpdateCoordinator=DataUpdateCoordinator,
    UpdateFailed=UpdateFailed,
)
_module("homeassistant.helpers.entity", EntityCategory=types.SimpleNamespace(DIAGNOSTIC="diagnostic"))
_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)

# views.py imports aiohttp; stub it so the package __init__ is importable.
_module("aiohttp")
_module("aiohttp.web", json_response=lambda *args, **kwargs: (args, kwargs))
_module("homeassistant.components")
_module("homeassistant.components.http", HomeAssistantView=object)


class FakeHass:
    """Just enough HomeAssistant to run executor jobs inline."""

    def __init__(self, entries=None):
        self.config_entries = _FakeEntryManager(entries or {})

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _FakeEntryManager:
    def __init__(self, entries):
        self._entries = entries

    def async_get_entry(self, entry_id):
        return self._entries.get(entry_id)
