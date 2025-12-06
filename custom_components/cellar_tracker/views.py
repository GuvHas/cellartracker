# custom_components/cellar_tracker/views.py

import logging
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class CellarTrackerInventoryView(HomeAssistantView):
    """Expose inventory data via a custom API endpoint."""

    url = "/api/cellartracker/inventory"
    name = "api:cellartracker:inventory"
    requires_auth = False 

    def __init__(self, hass: HomeAssistant):
        """Initialize the view."""
        self.hass = hass

    async def get(self, request):
        """Handle GET request for inventory."""
        if DOMAIN not in self.hass.data:
             return web.json_response([])

        # Return data from the first loaded coordinator
        for entry_id, coordinator in self.hass.data[DOMAIN].items():
            if coordinator.data:
                # Returns the raw list of bottle objects (JSON)
                return web.json_response(coordinator.data.get("bottles", []))
        
        return web.json_response([])
