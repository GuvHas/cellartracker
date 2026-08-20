import asyncio
import logging
import hashlib
from collections import Counter
from datetime import timedelta

# Imported at module scope: Home Assistant imports integration modules in an
# executor, so the file I/O happens off the event loop. Importing inside
# __init__ runs it *on* the loop and trips HA's blocking-call detector.
#
# The exception *types* are also the only reliable way to classify failures:
# the library raises them bare (`raise AuthenticationError`), so `str(err)` is
# always the empty string and message sniffing can never match.
from cellartracker import cellartracker
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

# A cellar reporting zero bottles right after holding stock is usually an
# upstream error page, but it can also mean the last bottle was drunk. Reject
# the first such poll to protect the statistics, then believe a repeat.
TOLERATED_SUSPICIOUS_EMPTY_POLLS = 1

# The library calls requests.get() without a timeout, so a server that accepts
# the connection and never replies holds the worker until TCP keepalive expires
# (~2h by default). This bounds what Home Assistant waits for; it cannot cancel
# the blocked thread, which needs timeout= upstream in cellartracker.
REQUEST_TIMEOUT = 60


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
        
        self._client = cellartracker.CellarTracker(self._username, self._password)

        # Consecutive polls that reported an empty cellar after it held stock.
        self._suspicious_empty_polls = 0

    @property
    def currency(self) -> str:
        """Return the configured currency symbol."""
        return self._currency

    def _process_inventory(self, inventory: list, previous: dict | None = None) -> dict:
        """Process the raw inventory list into a structured dictionary.

        Args:
            inventory: rows as returned by the cellartracker library.
            previous: the last successful result, used to tell a genuinely empty
                cellar apart from an upstream error page.

        Raises:
            UpdateFailed: the response does not look like inventory data.
        """
        had_bottles = bool(previous and previous.get("total_bottles"))

        if not inventory:
            # An error page that parses to zero rows is indistinguishable from
            # an empty cellar on its own, and a stocked cellar does not empty
            # itself between two polls - but a one-bottle cellar can. Reject the
            # first suspicious zero, then accept it so the sensor recovers
            # instead of being stranded as unavailable.
            if had_bottles:
                self._suspicious_empty_polls += 1
                if self._suspicious_empty_polls <= TOLERATED_SUSPICIOUS_EMPTY_POLLS:
                    raise UpdateFailed(
                        "CellarTracker returned no inventory rows but the cellar "
                        f"previously held {previous['total_bottles']} bottles; "
                        "treating as an upstream error"
                    )
                _LOGGER.warning(
                    "CellarTracker has reported an empty cellar for %s consecutive "
                    "polls (previously %s bottles); accepting it as correct",
                    self._suspicious_empty_polls,
                    previous["total_bottles"],
                )
            return {"total_bottles": 0, "total_value": 0.0, "bottles": []}

        total_value = 0.0
        processed_bottles = []
        # Occurrences per base id. A Counter resolves duplicates in O(1); the
        # previous linear probe restarted at 0 for every duplicate, making a
        # group of N identical bottles cost O(N^2).
        id_counts: Counter[str] = Counter()

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
            
            unique_id = hashlib.sha1(base_id_string.encode('utf-8')).hexdigest()[:16]

            # Suffixes are allocated densely (base, base_1, base_2, ...), which
            # is exactly what the probe produced, so ids are unchanged.
            occurrence = id_counts[unique_id]
            id_counts[unique_id] += 1
            bottle['unique_bottle_id'] = (
                unique_id if not occurrence else f"{unique_id}_{occurrence}"
            )

            try:
                valuation = float(bottle.get('Valuation', 0.0))
                bottle['Valuation'] = valuation
                total_value += valuation
            except (ValueError, TypeError):
                bottle['Valuation'] = 0.0
            
            processed_bottles.append(bottle)

        if not processed_bottles:
            # Rows parsed, but none carried the key column: we were handed an
            # HTML error page or the upstream schema changed.
            raise UpdateFailed(
                f"CellarTracker returned {len(inventory)} unrecognised row(s) "
                "with no 'iWine' column; treating as an upstream error rather "
                "than an empty cellar"
            )

        # Real inventory came back; any earlier suspicion is resolved.
        self._suspicious_empty_polls = 0

        if had_bottles and len(processed_bottles) < previous["total_bottles"] // 2:
            # A truncated response can still yield some valid rows. We cannot
            # know whether the drop is real, so publish it but leave a trace.
            _LOGGER.warning(
                "CellarTracker inventory dropped from %s to %s bottles in a "
                "single poll; verify the data is correct",
                previous["total_bottles"],
                len(processed_bottles),
            )

        return {
            "total_bottles": len(processed_bottles),
            "total_value": round(total_value, 2),
            "bottles": processed_bottles,
        }

    async def _async_update_data(self) -> dict:
        """Fetch inventory from CellarTracker."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
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

        # Parsing a large cellar means hashing every row and copying every dict,
        # so keep it off the event loop. self.data is the last successful
        # result, or None on the first poll.
        return await self._hass.async_add_executor_job(
            self._process_inventory, inventory_list, self.data
        )
