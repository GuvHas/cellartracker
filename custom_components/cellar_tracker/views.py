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
    """Shared entry resolution for the CellarTracker endpoints.

    Both endpoints must describe the *same* config entry, otherwise a dashboard
    can render one account's bottles priced in another account's currency.
    Resolution therefore lives here rather than in each view.
    """

    requires_auth = True

    def __init__(self, hass: HomeAssistant):
        """Initialize the view."""
        self.hass = hass

    def _coordinators(self) -> dict:
        """Return only real config entries, never bookkeeping keys."""
        return {
            entry_id: coordinator
            for entry_id, coordinator in self.hass.data.get(DOMAIN, {}).items()
            if not entry_id.startswith("_")
        }

    def _resolve(self, request):
        """Resolve the requested config entry.

        Returns:
            (coordinator, error_response). ``coordinator`` is None with no error
            when nothing is configured; callers then return their own default.
        """
        coordinators = self._coordinators()
        if not coordinators:
            return None, None

        entry_id = (request.query.get("entry_id") or "").strip()

        if entry_id:
            coordinator = coordinators.get(entry_id)
            if coordinator is None:
                return None, web.json_response(
                    {
                        "error": "unknown_entry_id",
                        "detail": f"No CellarTracker config entry with id {entry_id!r}.",
                        "entries": sorted(coordinators),
                    },
                    status=404,
                )
            return coordinator, None

        if len(coordinators) > 1:
            # Never guess: picking the first entry silently showed the wrong
            # cellar and left the others unreachable.
            return None, web.json_response(
                {
                    "error": "entry_id_required",
                    "detail": (
                        "Multiple CellarTracker accounts are configured. "
                        "Add ?entry_id=<id> to the request."
                    ),
                    "entries": sorted(coordinators),
                },
                status=400,
            )

        return next(iter(coordinators.values())), None


class CellarTrackerInventoryView(_CellarTrackerView):
    """Expose inventory data via a custom API endpoint."""

    url = "/api/cellartracker/inventory"
    name = "api:cellartracker:inventory"

    async def get(self, request):
        """Handle GET request for inventory."""
        coordinator, error = self._resolve(request)
        if error is not None:
            return error

        if coordinator is None or not coordinator.data:
            return web.json_response([])

        return web.json_response(coordinator.data.get("bottles", []))


class CellarTrackerSettingsView(_CellarTrackerView):
    """Expose integration settings (e.g. currency) via API."""

    url = "/api/cellartracker/settings"
    name = "api:cellartracker:settings"

    async def get(self, request):
        """Handle GET request for settings."""
        coordinator, error = self._resolve(request)
        if error is not None:
            return error

        currency = DEFAULT_CURRENCY if coordinator is None else coordinator.currency
        return web.json_response(_currency_payload(currency))
