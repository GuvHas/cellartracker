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

    def _coordinator(self):
        """Return the configured coordinator, or None if there is none yet.

        ``?entry_id=`` is accepted and ignored so dashboards configured against
        the multi-account release keep working unchanged.
        """
        coordinators = self.hass.data.get(DOMAIN, {})
        if not coordinators:
            return None

        if len(coordinators) > 1:
            # Only reachable on an install that added a second account before
            # single-instance was enforced. Pick deterministically so both
            # endpoints agree, and say so rather than silently choosing.
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
        """Handle GET request for inventory."""
        coordinator = self._coordinator()
        if coordinator is None or not coordinator.data:
            return web.json_response([])

        return web.json_response(coordinator.data.get("bottles", []))


class CellarTrackerSettingsView(_CellarTrackerView):
    """Expose integration settings (e.g. currency) via API."""

    url = "/api/cellartracker/settings"
    name = "api:cellartracker:settings"

    async def get(self, request):
        """Handle GET request for settings."""
        coordinator = self._coordinator()
        currency = DEFAULT_CURRENCY if coordinator is None else coordinator.currency
        return web.json_response(_currency_payload(currency))
