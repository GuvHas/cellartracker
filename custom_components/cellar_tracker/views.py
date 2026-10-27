# custom_components/cellar_tracker/views.py

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView

from .const import CURRENCY_SYMBOLS, DASHBOARD_URL, DEFAULT_CURRENCY, DOMAIN

if TYPE_CHECKING:
    from .cellar_data import CellarTrackerConfigEntry, WineCellarData

_LOGGER = logging.getLogger(__name__)


def _currency_payload(currency: str) -> dict[str, str]:
    """Describe a currency as both its code and its display symbol."""
    return {
        "currency": currency,
        "currency_symbol": CURRENCY_SYMBOLS.get(currency, currency),
    }


class _CellarTrackerView(HomeAssistantView):
    """Shared lookup for the CellarTracker endpoints.

    The config flow allows one account per installation, so there is nothing to
    disambiguate: both endpoints serve the same single coordinator, which is
    what stops them ever describing different accounts.
    """

    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    def _coordinator(self, request: web.Request) -> WineCellarData | None:
        """Return the coordinator to serve, or None if there is none yet.

        With the single account this integration now allows, ``?entry_id=`` is
        accepted and ignored, so dashboards configured against the
        multi-account release keep working unchanged.

        It is honoured only where ignoring it would be wrong: a legacy install
        still holding two entries, whose dashboard was copied to ``/local/``
        and so still forwards the parameter. Serving the lowest entry id there
        would answer for an account the caller did not ask for.
        """
        # async_entries is typed for any integration, so it hands back
        # ConfigEntry[Any]; naming the type here is what stops runtime_data
        # laundering Any into everything this method returns. Only entries of
        # our own domain are asked for, so the claim holds.
        entries: list[CellarTrackerConfigEntry] = self.hass.config_entries.async_entries(DOMAIN)
        coordinators = {
            entry.entry_id: entry.runtime_data
            for entry in entries
            # runtime_data is assigned at setup and cleared at unload, so its
            # presence is what "this entry is serving requests" means here.
            if getattr(entry, "runtime_data", None) is not None
        }
        if not coordinators:
            return None

        if len(coordinators) > 1:
            # Only reachable on an install that added a second account before
            # single-instance was enforced.
            entry_id = (request.query.get("entry_id") or "").strip()
            if entry_id in coordinators:
                return coordinators[entry_id]

            # Nothing usable to disambiguate with: pick deterministically so
            # both endpoints agree, and say so rather than silently choosing.
            _LOGGER.warning(
                "More than one CellarTracker account is configured (%s). Only one "
                "is supported; serving %s. Remove the others in Settings > "
                "Devices & Services.",
                ", ".join(sorted(coordinators)),
                min(coordinators),
            )
            return coordinators[min(coordinators)]

        return next(iter(coordinators.values()))


class CellarTrackerInventoryView(_CellarTrackerView):
    """Expose inventory data via a custom API endpoint."""

    url = "/api/cellartracker/inventory"
    name = "api:cellartracker:inventory"

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request for inventory.

        The body was rendered by the coordinator when it last refreshed, so a
        thousand-bottle cellar costs this handler nothing: serialising it here
        would block the event loop for every dashboard load.

        ``?view=compact`` serves only the columns the dashboard renders. The
        default is unchanged, because this endpoint is a public surface that
        users read from their own cards.
        """
        coordinator = self._coordinator(request)
        if coordinator is None or not coordinator.data:
            return web.json_response([])

        # Anything other than the one name we recognise gets everything. A typo
        # must not quietly hand back fewer fields than the caller expected.
        if request.query.get("view") == "compact":
            body = coordinator.compact_body
        else:
            body = coordinator.inventory_body

        return web.Response(body=body, content_type="application/json")


class CellarTrackerSettingsView(_CellarTrackerView):
    """Expose integration settings (e.g. currency) via API."""

    url = "/api/cellartracker/settings"
    name = "api:cellartracker:settings"

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request for settings."""
        coordinator = self._coordinator(request)
        currency = DEFAULT_CURRENCY if coordinator is None else coordinator.currency
        # The LED racks' locations, so the dashboard offers to light a bottle
        # only where a rack can show it.
        racks = [] if coordinator is None else [rack.location for rack in coordinator.racks]
        return web.json_response({**_currency_payload(currency), "racks": racks})


class CellarTrackerDashboardView(HomeAssistantView):
    """The dashboard page, which the browser must check for a newer copy.

    Home Assistant's static paths send either a month-long Cache-Control or
    none at all. With none, browsers cache by heuristic - a tenth of the file's
    age - so after an update a desktop kept showing the page from before it,
    hard reload or not: the page sits in an iframe, and reloading Home
    Assistant does not reload that. ``no-cache`` keeps the copy but asks every
    time, and the ETag makes asking cheap.

    No auth, like the static path it replaces: an iframe cannot send the
    bearer token, and the page holds no data until it calls the API, which
    does require it.
    """

    url = DASHBOARD_URL
    name = "cellartracker:dashboard"
    requires_auth = False

    def __init__(self, path: Path) -> None:
        """Serve the page at `path`."""
        self._path = path

    async def get(self, request: web.Request) -> web.FileResponse:
        """Serve the page, revalidated on every load."""
        return web.FileResponse(self._path, headers={"Cache-Control": "no-cache"})
