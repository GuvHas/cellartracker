"""Native actions for the CellarTracker integration.

``refresh`` triggers an immediate sync. ``get_wine_by_bin`` returns what is in a
rack coordinate, for a script or automation to act on - an LED driver asking
"what is in A1?" and lighting the answer.

They are registered once, in async_setup: they are global to the component, and
Home Assistant offers no way to unregister a service, the same reason the HTTP
views are registered there.

Neither creates an entity. The bin lookup reads the index the coordinator
already built during the parse, so answering costs a dictionary walk, not a
scan of the cellar.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .analytics import consume_year, drink_status, find_bottles, is_peak
from .const import DOMAIN

if TYPE_CHECKING:
    from .cellar_data import CellarTrackerConfigEntry, WineCellarData

SERVICE_REFRESH = "refresh"
SERVICE_GET_WINE_BY_BIN = "get_wine_by_bin"

ATTR_BIN = "bin"
ATTR_LOCATION = "location"

REFRESH_SCHEMA = vol.Schema({})

# cv.string rather than str: a bin written as `bin: 12` in a script arrives as
# an int, and a bin is a label, not a number.
GET_WINE_BY_BIN_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BIN): cv.string,
        vol.Optional(ATTR_LOCATION): cv.string,
    }
)


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
        location: str | None = call.data.get(ATTR_LOCATION)

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

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh, schema=REFRESH_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_WINE_BY_BIN,
        handle_get_wine_by_bin,
        schema=GET_WINE_BY_BIN_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
