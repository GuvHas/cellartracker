import logging
import hashlib
from datetime import timedelta

# `cellartracker.errors` is a dependency-free module, so importing it here is
# cheap. The exception *types* are the only reliable way to classify failures:
# the library raises them bare (`raise AuthenticationError`), so `str(err)` is
# always the empty string and message sniffing can never match.
from cellartracker.errors import AuthenticationError, CannotConnect

from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CURRENCY,
    DEFAULT_CURRENCY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    normalize_currency,
)

_LOGGER = logging.getLogger(__name__)


class WineCellarData(DataUpdateCoordinator):
    """Fetch and process CellarTracker inventory data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the data coordinator."""
        self._hass = hass
        self._username = entry.data[CONF_USERNAME]
        self._password = entry.data[CONF_PASSWORD]
        self._currency = normalize_currency(
            entry.options.get(CONF_CURRENCY, entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY))
        )

        scan_interval = timedelta(
            seconds=entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            always_update=False,
        )
        
        # Using the standard library as requested
        from cellartracker import cellartracker
        self._client = cellartracker.CellarTracker(self._username, self._password)

    @property
    def currency(self) -> str:
        """Return the configured currency symbol."""
        return self._currency

    def _process_inventory(self, inventory: list) -> dict:
        """Process the raw inventory list into a structured dictionary."""
        if not inventory:
            return {"total_bottles": 0, "total_value": 0.0, "bottles": []}

        total_value = 0.0
        processed_bottles = []
        seen_ids = set()

        for bottle in inventory:
            if 'iWine' not in bottle:
                continue

            # Stable Unique ID Generation
            base_id_string = (
                f"{bottle['iWine']}_"
                f"{bottle.get('PurchaseDate', '')}_"
                f"{bottle.get('Barcode', '')}_"
                f"{bottle.get('Location', '')}_"
                f"{bottle.get('Bin', '')}"
            )
            
            counter = 0
            unique_id = hashlib.sha1(base_id_string.encode('utf-8')).hexdigest()[:16]
            temp_id = unique_id
            
            while temp_id in seen_ids:
                counter += 1
                temp_id = f"{unique_id}_{counter}"
            
            seen_ids.add(temp_id)
            bottle['unique_bottle_id'] = temp_id

            try:
                valuation = float(bottle.get('Valuation', 0.0))
                bottle['Valuation'] = valuation
                total_value += valuation
            except (ValueError, TypeError):
                bottle['Valuation'] = 0.0
            
            processed_bottles.append(bottle)
        
        return {
            "total_bottles": len(processed_bottles),
            "total_value": round(total_value, 2),
            "bottles": processed_bottles,
        }

    async def _async_update_data(self) -> dict:
        """Fetch inventory from CellarTracker."""
        try:
            inventory_list = await self._hass.async_add_executor_job(
                self._client.get_inventory
            )
        except AuthenticationError as err:
            # Surfaces as a reauth flow (see async_step_reauth in config_flow).
            raise ConfigEntryAuthFailed(
                "Invalid CellarTracker credentials"
            ) from err
        except (CannotConnect, TimeoutError, OSError) as err:
            _LOGGER.warning("Temporary communication error with CellarTracker: %r", err)
            raise UpdateFailed(f"Cannot reach CellarTracker: {err!r}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching CellarTracker inventory")
            raise UpdateFailed(f"Unexpected CellarTracker error: {err!r}") from err

        return self._process_inventory(inventory_list)
