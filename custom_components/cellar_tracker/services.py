"""Native actions for the CellarTracker integration.

``refresh`` triggers an immediate sync. ``get_wine_by_bin`` returns what is in a
rack coordinate, for a script or automation to act on - an LED driver asking
"what is in A1?" and lighting the answer.

``locate_bottle``, ``highlight_bottles`` and ``show_overview`` are what the
dashboard calls to put the cellar on the LED racks. They fire events rather
than calling the boards: the integration knows which rack a bottle is on but
not which ESPHome nodes light it, and the rack's own automation does. The
events name the rack by its Location, so each automation acts on its own.

They are registered once, in async_setup: they are global to the component, and
Home Assistant offers no way to unregister a service, the same reason the HTTP
views are registered there.

Neither creates an entity. The bin lookup reads the index the coordinator
already built during the parse, so answering costs a dictionary walk, not a
scan of the cellar.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later

from .analytics import consume_year, drink_status, find_bottles, is_peak
from .const import (
    DEFAULT_HIGHLIGHT_SECONDS,
    DEFAULT_LOCATE_SECONDS,
    DOMAIN,
    EVENT_RACK_LOCATE,
    EVENT_RACK_PAINT,
)
from .racks import rack_grid

if TYPE_CHECKING:
    from .cellar_data import CellarTrackerConfigEntry, WineCellarData

SERVICE_REFRESH = "refresh"
SERVICE_GET_WINE_BY_BIN = "get_wine_by_bin"
SERVICE_LOCATE_BOTTLE = "locate_bottle"
SERVICE_HIGHLIGHT_BOTTLES = "highlight_bottles"
SERVICE_SHOW_OVERVIEW = "show_overview"

ATTR_BIN = "bin"
ATTR_LOCATION = "location"
ATTR_BOTTLES = "bottles"
ATTR_SECONDS = "seconds"

# Where the pending "put the overview back" timer of a highlight lives, so a
# new highlight or an explicit overview replaces it rather than racing it.
_RESTORE_TIMER = f"{DOMAIN}_highlight_restore"

REFRESH_SCHEMA = vol.Schema({})

# cv.string rather than str: a bin written as `bin: 12` in a script arrives as
# an int, and a bin is a label, not a number.
GET_WINE_BY_BIN_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BIN): cv.string,
        vol.Optional(ATTR_LOCATION): cv.string,
    }
)


LOCATE_BOTTLE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_LOCATION): cv.string,
        vol.Required(ATTR_BIN): cv.string,
        vol.Optional(ATTR_SECONDS, default=DEFAULT_LOCATE_SECONDS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=3600)
        ),
    }
)

# Bottles by unique_bottle_id: the dashboard already holds them, and an id
# cannot be misread the way a filter or a search would be if the integration
# had to repeat the page's logic to understand it.
HIGHLIGHT_BOTTLES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BOTTLES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_SECONDS, default=DEFAULT_HIGHLIGHT_SECONDS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=86400)
        ),
    }
)

SHOW_OVERVIEW_SCHEMA = vol.Schema({})


def _loaded_coordinators(hass: HomeAssistant) -> list[WineCellarData]:
    """Coordinators of every entry that is currently serving requests.

    Ordered by entry id so a legacy install still holding two entries answers
    deterministically instead of by dictionary order.
    """
    entries: list[CellarTrackerConfigEntry] = hass.config_entries.async_entries(DOMAIN)
    return [
        entry.runtime_data
        for entry in sorted(entries, key=lambda e: e.entry_id)
        # Set at setup and cleared at unload, so its presence is what "loaded"
        # means here - the same test the HTTP views use.
        if getattr(entry, "runtime_data", None) is not None
    ]


def _require_loaded(hass: HomeAssistant) -> list[WineCellarData]:
    coordinators = _loaded_coordinators(hass)
    if not coordinators:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_loaded",
        )
    return coordinators


def _service_bottle(bottle: Mapping[str, Any], year: int) -> dict[str, Any]:
    """One bottle as a service response.

    Only what a script needs to act on it. Notes, the price paid and the barcode
    stay out: service responses land in automation traces and logs, which are
    shared far more freely than the cellar itself.
    """
    return {
        "name": bottle.get("Wine"),
        # 0 is how the export writes a non-vintage wine; None says what it means.
        "vintage": consume_year(bottle.get("Vintage")),
        "wine_id": bottle.get("iWine"),
        "location": bottle.get("Location") or "",
        "bin": bottle.get("Bin") or "",
        "drink_window": {
            "begin": consume_year(bottle.get("BeginConsume")),
            "end": consume_year(bottle.get("EndConsume")),
        },
        "drink_status": drink_status(bottle, year),
        "peak": is_peak(bottle, year),
        "unique_bottle_id": bottle.get("unique_bottle_id"),
    }


class _PendingRestore(NamedTuple):
    cancel: Callable[[], None]
    # time.monotonic() at which the overview is due back.
    due: float
    coordinator: WineCellarData


def _cancel_restore(hass: HomeAssistant) -> None:
    pending: _PendingRestore | None = hass.data.pop(_RESTORE_TIMER, None)
    if pending is not None:
        pending.cancel()


def _schedule_restore(hass: HomeAssistant, coordinator: WineCellarData, seconds: int) -> None:
    """Put the overview back in `seconds`, replacing any restore already due."""
    _cancel_restore(hass)

    # @callback: without it Home Assistant runs a plain function on an
    # executor thread, and firing an event from there is not allowed.
    @callback
    def restore(_now: object) -> None:
        hass.data.pop(_RESTORE_TIMER, None)
        if (live := _loaded_coordinators(hass)) and live[0] is coordinator:
            _paint_overview(hass, coordinator)

    hass.data[_RESTORE_TIMER] = _PendingRestore(
        async_call_later(hass, seconds, restore), time.monotonic() + seconds, coordinator
    )


def _keep_restore_off_a_locator(hass: HomeAssistant, hold: int) -> None:
    """Hold back a pending restore until a new locator has had its time.

    The restore repaints with clear_all, which ends a locator. Without this, a
    bottle opened a few seconds before a highlight expires would be lit for
    those few seconds instead of its hold.
    """
    pending: _PendingRestore | None = hass.data.get(_RESTORE_TIMER)
    if pending is None:
        return
    if hold == 0:
        # Held until something else changes the rack; the next sync does.
        _cancel_restore(hass)
    elif pending.due - time.monotonic() < hold:
        _schedule_restore(hass, pending.coordinator, hold)


def _paint_overview(hass: HomeAssistant, coordinator: WineCellarData) -> None:
    """Ask every configured rack to show the cellar as the grid sensors do."""
    data = coordinator.data
    states = {} if data is None else data.get("racks") or {}
    for rack in coordinator.racks:
        state = states.get(rack.location)
        if state is not None:
            hass.bus.async_fire(
                EVENT_RACK_PAINT,
                {"location": rack.location, "grid": state["grid"], "highlight": False},
            )


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    async def handle_refresh(call: ServiceCall) -> None:
        # request_refresh, not a bare fetch: Home Assistant's debouncer then
        # rate-limits repeated calls, so an automation in a loop cannot hammer
        # CellarTracker.
        await asyncio.gather(
            *(coordinator.async_request_refresh() for coordinator in _require_loaded(hass))
        )

    async def handle_get_wine_by_bin(call: ServiceCall) -> ServiceResponse:
        coordinator = _require_loaded(hass)[0]
        bin_name: str = call.data[ATTR_BIN]
        # Normalised here too, so the response describes the query that was
        # actually run: a blank location is no filter and is echoed as None.
        location: str | None = (call.data.get(ATTR_LOCATION) or "").strip() or None

        data = coordinator.data
        found = (
            []
            if data is None
            else find_bottles(
                data["bottles"], data["location_index"], bin_name=bin_name, location=location
            )
        )
        year = coordinator.current_year()
        return {
            "bin": bin_name,
            "location": location,
            "count": len(found),
            "bottles": [_service_bottle(bottle, year) for bottle in found],
        }

    async def handle_locate_bottle(call: ServiceCall) -> None:
        coordinator = _require_loaded(hass)[0]
        location = call.data[ATTR_LOCATION].strip()
        bin_name = call.data[ATTR_BIN].strip()
        if not bin_name or location not in {rack.location for rack in coordinator.racks}:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_on_a_rack",
                translation_placeholders={"location": location, "bin": bin_name},
            )
        hold: int = call.data[ATTR_SECONDS]
        _keep_restore_off_a_locator(hass, hold)
        hass.bus.async_fire(
            EVENT_RACK_LOCATE, {"location": location, "bin": bin_name, "seconds": hold}
        )

    async def handle_highlight_bottles(call: ServiceCall) -> None:
        coordinator = _require_loaded(hass)[0]
        data = coordinator.data
        if data is None or not coordinator.racks:
            return
        wanted = set(call.data[ATTR_BOTTLES])
        chosen = [b for b in data["bottles"] if b.get("unique_bottle_id") in wanted]
        year = coordinator.current_year()
        _cancel_restore(hass)
        # Every rack, including one with nothing chosen on it: "show me what is
        # ready" means the other bins go dark, not that they keep their colour.
        for rack in coordinator.racks:
            hass.bus.async_fire(
                EVENT_RACK_PAINT,
                {
                    "location": rack.location,
                    "grid": rack_grid(chosen, rack, year),
                    "highlight": True,
                },
            )
        seconds: int = call.data[ATTR_SECONDS]
        if seconds:
            _schedule_restore(hass, coordinator, seconds)

    async def handle_show_overview(call: ServiceCall) -> None:
        coordinator = _require_loaded(hass)[0]
        _cancel_restore(hass)
        _paint_overview(hass, coordinator)

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh, schema=REFRESH_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_LOCATE_BOTTLE, handle_locate_bottle, schema=LOCATE_BOTTLE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_HIGHLIGHT_BOTTLES,
        handle_highlight_bottles,
        schema=HIGHLIGHT_BOTTLES_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SHOW_OVERVIEW, handle_show_overview, schema=SHOW_OVERVIEW_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_WINE_BY_BIN,
        handle_get_wine_by_bin,
        schema=GET_WINE_BY_BIN_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
