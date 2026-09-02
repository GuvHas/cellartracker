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

import asyncio
import json as _json
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
    """Minimal stand-in that records what the real base class would receive.

    ``config_entry`` is captured explicitly rather than absorbed into
    ``**kwargs``: Home Assistant 2024.11 added it and is making it mandatory,
    so a test has to be able to see whether we passed it.
    """

    def __init__(
        self, hass, logger, *, name=None, config_entry=None, update_interval=None, **kwargs
    ):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.config_entry = config_entry
        self.update_interval = update_interval
        self.init_kwargs = kwargs
        self.data = None


# --- homeassistant.config_entries --------------------------------------------
class ConfigEntry:
    """Lightweight config entry double."""

    def __init__(self, *, entry_id="test_entry", data=None, options=None, title="alice"):
        self.entry_id = entry_id
        self.data = data or {}
        self.options = options or {}
        self.title = title
        self.unload_callbacks = []

    def async_on_unload(self, callback):
        self.unload_callbacks.append(callback)
        return callback

    def add_update_listener(self, listener):
        return listener


class _Aborted(Exception):
    """Raised by the stub when a flow helper would abort."""


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
        if any(getattr(e, "unique_id", None) == self.unique_id for e in self._existing_entries):
            raise _Aborted("already_configured")
        return None

    # Entries Home Assistant already has for this domain.
    _existing_entries: list = []

    def _async_current_entries(self, include_ignore=False):
        return list(self._existing_entries)

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
_module(
    "homeassistant.helpers.entity",
    EntityCategory=types.SimpleNamespace(DIAGNOSTIC="diagnostic"),
)
_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
_module(
    "homeassistant.helpers.json",
    # The real helper is orjson-backed; stdlib json is equivalent for our
    # payload, which is only str/int/float.
    json_bytes=lambda data: _json.dumps(data).encode("utf-8"),
)

class FakeRequest:
    """Minimal aiohttp request exposing only the query string."""

    def __init__(self, **query):
        self.query = dict(query)


class StaticPathConfig:
    """Stub of homeassistant.components.http.StaticPathConfig."""

    def __init__(self, url_path, path, cache_headers=True):
        self.url_path = url_path
        self.path = path
        self.cache_headers = cache_headers


def _config_entry_only_config_schema(domain):
    """Stub of cv.config_entry_only_config_schema; identity is all tests need."""
    return domain


# aiohttp is the real library: views.py builds real responses, and
# cellar_data catches real aiohttp.ClientError.
_module("homeassistant.components")
_module(
    "homeassistant.components.http",
    HomeAssistantView=object,
    StaticPathConfig=StaticPathConfig,
)
sys.modules["homeassistant.helpers"].config_validation = _module(
    "homeassistant.helpers.config_validation",
    config_entry_only_config_schema=_config_entry_only_config_schema,
)


class SensorEntity:
    """Stub of homeassistant.components.sensor.SensorEntity."""


class CoordinatorEntity:
    """Stub of the CoordinatorEntity mixin."""

    def __init__(self, coordinator):
        self.coordinator = coordinator


_module(
    "homeassistant.components.sensor",
    SensorEntity=SensorEntity,
    SensorDeviceClass=types.SimpleNamespace(MONETARY="monetary"),
    SensorStateClass=types.SimpleNamespace(MEASUREMENT="measurement", TOTAL="total"),
)
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = CoordinatorEntity


class FakeCoordinator:
    """Stands in for WineCellarData in view tests.

    Renders ``inventory_body`` the same way the real coordinator does: the
    views serve those bytes directly rather than encoding per request, so a
    double without them would not exercise the code path that runs in
    production.
    """

    def __init__(self, *, currency="USD", bottles=None, data=True):
        self.currency = currency
        if not data:
            self.data = None
            self.inventory_body = b"[]"
        else:
            bottles = bottles or []
            self.data = {
                "total_bottles": len(bottles),
                "total_value": 0.0,
                "bottles": bottles,
            }
            self.inventory_body = _json.dumps(bottles).encode("utf-8")


class FakeHttp:
    """Records what the component registered on hass.http."""

    def __init__(self):
        self.registered = []
        self.static_paths = []

    def register_view(self, view):
        self.registered.append(type(view).__name__)

    async def async_register_static_paths(self, configs):
        self.static_paths.extend(configs)


class ViewHass:
    """HomeAssistant double carrying hass.data and an http/executor surface."""

    def __init__(self, data=None):
        self.data = data if data is not None else {}
        self.http = FakeHttp()

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeHass:
    """Just enough HomeAssistant to run executor jobs inline."""

    def __init__(self, entries=None):
        self.config_entries = _FakeEntryManager(entries or {})
        self.executor_jobs = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append(getattr(func, "__name__", repr(func)))
        return func(*args)


class _FakeEntryManager:
    def __init__(self, entries):
        self._entries = entries

    def async_get_entry(self, entry_id):
        return self._entries.get(entry_id)


# --- homeassistant.helpers.aiohttp_client -------------------------------------
class FakeClientResponse:
    """Stand-in for an aiohttp ClientResponse used as an async context manager."""

    def __init__(self, text="", status=200, raise_for_status=None):
        self._text = text
        self.status = status
        self._raise_for_status = raise_for_status

    async def text(self):
        return self._text

    def raise_for_status(self):
        if self._raise_for_status is not None:
            raise self._raise_for_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _RequestContext:
    def __init__(self, session, response, error, delay):
        self._session = session
        self._response = response
        self._error = error
        self._delay = delay

    async def __aenter__(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return await self._response.__aenter__()

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """Records what was requested and returns a scripted response."""

    def __init__(self, *, text="", status=200, error=None, delay=0, raise_for_status=None):
        self.text = text
        self.status = status
        self.error = error
        self.delay = delay
        self.raise_for_status = raise_for_status
        self.requests = []

    def get(self, url, params=None, **kwargs):
        self.requests.append({"url": url, "params": dict(params or {})})
        response = FakeClientResponse(
            text=self.text, status=self.status, raise_for_status=self.raise_for_status
        )
        return _RequestContext(self, response, self.error, self.delay)


_module(
    "homeassistant.helpers.aiohttp_client",
    async_get_clientsession=lambda hass, *a, **kw: getattr(hass, "session", FakeSession()),
)
