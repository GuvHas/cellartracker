# custom_components/cellar_tracker/views.py

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CURRENCY_SYMBOLS, DEFAULT_CURRENCY, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _currency_payload(currency: str) -> dict:
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

    def __init__(self, hass: HomeAssistant):
        """Initialize the view."""
        self.hass = hass

    def _coordinator(self, request):
        """Return the coordinator to serve, or None if there is none yet.

        With the single account this integration now allows, ``?entry_id=`` is
        accepted and ignored, so dashboards configured against the
        multi-account release keep working unchanged.

        It is honoured only where ignoring it would be wrong: a legacy install
        still holding two entries, whose dashboard was copied to ``/local/``
        and so still forwards the parameter. Serving the lowest entry id there
        would answer for an account the caller did not ask for.
        """
        coordinators = {
            entry.entry_id: entry.runtime_data
            for entry in self.hass.config_entries.async_entries(DOMAIN)
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

    async def get(self, request):
        """Handle GET request for inventory.

        The body was rendered by the coordinator when it last refreshed, so a
        thousand-bottle cellar costs this handler nothing: serialising it here
        would block the event loop for every dashboard load.
        """
        coordinator = self._coordinator(request)
        if coordinator is None or not coordinator.data:
            return web.json_response([])

        return web.Response(
            body=coordinator.inventory_body, content_type="application/json"
        )


class CellarTrackerSettingsView(_CellarTrackerView):
    """Expose integration settings (e.g. currency) via API."""

    url = "/api/cellartracker/settings"
    name = "api:cellartracker:settings"

    async def get(self, request):
        """Handle GET request for settings."""
        coordinator = self._coordinator(request)
        currency = DEFAULT_CURRENCY if coordinator is None else coordinator.currency
        return web.json_response(_currency_payload(currency))
