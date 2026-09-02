"""Test harness for the CellarTracker integration.

Generics here use ``typing.Generic`` with a UP046 suppression rather than PEP
695 type parameters. CI runs 3.12 and 3.13 where the modern form is valid, but
the development container runs 3.11, and a harness that cannot be imported
locally is a harness nobody runs before pushing.

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
import dataclasses
import enum
import json as _json
import pathlib
import sys
import types
import typing
from datetime import UTC
from datetime import datetime as _datetime

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
_DataT = typing.TypeVar("_DataT")
_RuntimeT = typing.TypeVar("_RuntimeT")
_CoordinatorT = typing.TypeVar("_CoordinatorT")


class DataUpdateCoordinator(typing.Generic[_DataT]):  # noqa: UP046
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

    async def async_config_entry_first_refresh(self):
        """No-op: tests that want data drive _async_update_data directly."""
        return


# --- homeassistant.config_entries --------------------------------------------
class ConfigEntry(typing.Generic[_RuntimeT]):  # noqa: UP046
    """Lightweight config entry double.

    Generic like the real one since 2024.11, so ConfigEntry[WineCellarData]
    is a usable annotation rather than a TypeError at import.
    """

    def __init__(self, *, entry_id="test_entry", data=None, options=None, title="alice"):
        self.entry_id = entry_id
        self.data = data or {}
        self.options = options or {}
        self.title = title
        self.unload_callbacks = []
        # Home Assistant 2024.6+: where an integration keeps its live objects.
        self.runtime_data = None

    def as_dict(self):
        """The shape diagnostics redacts; runtime_data is deliberately absent."""
        return {
            "entry_id": self.entry_id,
            "title": self.title,
            "data": dict(self.data),
            "options": dict(self.options),
        }

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
@dataclasses.dataclass(frozen=True, kw_only=True)
class EntityDescription:
    """Stub of homeassistant.helpers.entity.EntityDescription."""

    key: str
    translation_key: str | None = None
    device_class: object = None
    entity_category: object = None
    icon: str | None = None
    name: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SensorEntityDescription(EntityDescription):
    """Stub of homeassistant.components.sensor.SensorEntityDescription."""

    native_unit_of_measurement: str | None = None
    state_class: object = None
    suggested_display_precision: int | None = None


class DeviceEntryType(enum.StrEnum):
    """Stub of homeassistant.helpers.device_registry.DeviceEntryType."""

    SERVICE = "service"


class DeviceInfo(dict):
    """Stub of homeassistant.helpers.device_registry.DeviceInfo.

    A TypedDict upstream, so a plain dict at runtime; subclassing dict keeps
    the tests reading it exactly as Home Assistant would.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


# Attached after definition: the helpers.entity stub is registered above.
sys.modules["homeassistant.helpers.entity"].EntityDescription = EntityDescription

_module(
    "homeassistant.helpers.device_registry",
    DeviceEntryType=DeviceEntryType,
    DeviceInfo=DeviceInfo,
)

_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
# The real ConfigType is dict[str, Any]; async_setup takes one.
_module("homeassistant.helpers.typing", ConfigType=dict)
_module("homeassistant.util")
_module("homeassistant.util.dt", utcnow=lambda: _datetime.now(UTC))


def _async_redact_data(data, to_redact):
    """Stub of homeassistant.components.diagnostics.async_redact_data.

    Recurses the way the real helper does, so a test cannot pass by redacting
    only the top level of a nested structure.
    """
    if isinstance(data, list):
        return [_async_redact_data(item, to_redact) for item in data]
    if not isinstance(data, dict):
        return data
    return {
        key: ("**REDACTED**" if key in to_redact else _async_redact_data(value, to_redact))
        for key, value in data.items()
    }


_module("homeassistant.components.diagnostics", async_redact_data=_async_redact_data)
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
    """Stub of homeassistant.components.sensor.SensorEntity.

    Home Assistant's Entity base resolves each public property from the
    matching ``_attr_`` attribute. Modelling that here keeps tests reading the
    same surface a Home Assistant instance would, rather than reaching into
    private attributes and passing whatever they find.
    """

    _attr_device_class = None
    _attr_entity_category = None
    _attr_extra_state_attributes = None
    _attr_icon = None
    _attr_name = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_translation_key = None
    _attr_unique_id = None

    @property
    def device_class(self):
        return self._described("device_class")

    @property
    def entity_category(self):
        return self._described("entity_category")

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes

    @property
    def icon(self):
        return self._described("icon")

    @property
    def name(self):
        return self._described("name")

    @property
    def native_unit_of_measurement(self):
        return self._described("native_unit_of_measurement")

    @property
    def state_class(self):
        return self._described("state_class")

    entity_description = None

    def _described(self, attribute):
        """Home Assistant's Entity resolution order: _attr_ then description.

        Modelled here because the integration now carries device class, state
        class, unit, icon and category on a SensorEntityDescription. A stub
        that only read _attr_ would report None for all of them and the tests
        would be measuring the double rather than the entity.
        """
        value = getattr(self, f"_attr_{attribute}", None)
        if value is not None:
            return value
        if self.entity_description is not None:
            return getattr(self.entity_description, attribute, None)
        return None

    @property
    def translation_key(self):
        return self._described("translation_key")

    @property
    def unique_id(self):
        return self._attr_unique_id


class CoordinatorEntity(typing.Generic[_CoordinatorT]):  # noqa: UP046
    """Stub of the CoordinatorEntity mixin.

    Generic like the real one, which has been parameterised by its coordinator
    since 2023. Without that, ``CoordinatorEntity[WineCellarData]`` in
    sensor.py is a TypeError at import - and a double that cannot express what
    the real base class expresses is how a typing bug hides.
    """

    def __init__(self, coordinator):
        self.coordinator = coordinator


_module(
    "homeassistant.components.sensor",
    SensorEntity=SensorEntity,
    SensorDeviceClass=types.SimpleNamespace(MONETARY="monetary", TIMESTAMP="timestamp"),
    SensorEntityDescription=SensorEntityDescription,
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


class _ViewEntries:
    """The slice of hass.config_entries the views use."""

    def __init__(self, entries):
        self._entries = list(entries)

    def async_entries(self, domain=None):
        return list(self._entries)

    def async_get_entry(self, entry_id):
        return next((e for e in self._entries if e.entry_id == entry_id), None)


class ViewHass:
    """HomeAssistant double carrying config entries and an http/executor surface.

    Still constructed as ``ViewHass({DOMAIN: {entry_id: coordinator}})``: the
    coordinators are turned into loaded config entries here, so tests written
    against the old hass.data lookup keep working unchanged.
    """

    def __init__(self, data=None):
        self.data = data if data is not None else {}
        self.http = FakeHttp()
        entries = []
        for entry_id, coordinator in (self.data.get("cellar_tracker") or {}).items():
            entry = ConfigEntry(entry_id=entry_id)
            entry.runtime_data = coordinator
            entries.append(entry)
        self.config_entries = _ViewEntries(entries)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class SetupHass:
    """Enough HomeAssistant to run async_setup_entry and async_unload_entry."""

    def __init__(self, *, unload_ok=True):
        self.data = {}
        self.http = FakeHttp()
        self.config_entries = _SetupEntries(unload_ok)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _SetupEntries:
    def __init__(self, unload_ok=True):
        self.unload_ok = unload_ok

    async def async_forward_entry_setups(self, entry, platforms):
        return True

    async def async_unload_platforms(self, entry, platforms):
        return self.unload_ok

    async def async_reload(self, entry_id):
        return True

    def async_entries(self, domain=None):
        return []


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
