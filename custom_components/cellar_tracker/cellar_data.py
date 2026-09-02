import asyncio
import csv
import hashlib
import io
import logging
from collections import defaultdict
from datetime import timedelta

# The library still owns the endpoint contract - its URL, the marker that
# signals a rejected login, and the exception types - but not the transport:
# its requests.get() sets no timeout. See _fetch_payload.
#
# The exception *types* are also the only reliable way to classify failures:
# the library raises them bare (`raise AuthenticationError`), so `str(err)` is
# always the empty string and message sniffing can never match.
#
# Imported at module scope: Home Assistant imports integration modules in an
# executor, so this file I/O happens off the event loop.
import aiohttp
from cellartracker.const import BASE_URL, NOT_LOGGED_REPONSE
from cellartracker.enum import CellarTrackerFormat, CellarTrackerTable
from cellartracker.errors import AuthenticationError, CannotConnect
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.json import json_bytes
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

# Enforced by asyncio.timeout around an aiohttp request, so it genuinely
# cancels. The library's own requests.get() sets no timeout, which is why the
# transport is no longer routed through it.
REQUEST_TIMEOUT = 60

TABLE_INVENTORY = CellarTrackerTable.Inventory.value
FORMAT_TAB = CellarTrackerFormat.tab.value

# Columns that identify a physical bottle. Volatile columns are deliberately
# excluded: Valuation moves whenever CellarTracker re-prices a wine, and an id
# that changed on every re-pricing would be useless to anything keying on it.
IDENTITY_FIELDS = ("iWine", "PurchaseDate", "Barcode", "Location", "Bin")

# Unit separator: cannot occur in CellarTracker's tab-separated payload, so it
# cannot be forged by field contents to collide with another row's identity.
_FIELD_SEPARATOR = "\x1f"


def _bottle_identity(bottle: dict) -> str:
    """Return the 16-hex-character identity of a physical bottle.

    Truncating to 64 bits keeps the id readable; at cellar scale (thousands of
    bottles, not billions) the collision probability is negligible.
    """
    payload = _FIELD_SEPARATOR.join(
        str(bottle.get(field, "")) for field in IDENTITY_FIELDS
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _row_fingerprint(bottle: dict) -> str:
    """Order-independent digest of a row's full contents.

    Used only to rank bottles that share an identity, so that duplicate
    suffixes do not depend on the order CellarTracker happened to return.
    """
    payload = _FIELD_SEPARATOR.join(
        f"{key}={bottle[key]}" for key in sorted(bottle) if key != "unique_bottle_id"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def async_fetch_inventory_payload(hass, username: str, password: str) -> str:
    """Fetch the raw inventory export for an account.

    Shared by the coordinator and by the config flow's credential check, so the
    two cannot drift apart on transport or on what counts as an auth failure.

    Home Assistant's shared aiohttp session replaces the library's
    ``requests.get()``, which sets no timeout: an ``asyncio.timeout`` around an
    executor job bounds the wait but cannot interrupt a worker already blocked
    in ``recv()``. Cancelling an aiohttp request actually cancels it, and no
    thread is involved.

    Raises:
        AuthenticationError: CellarTracker rejected the credentials.
        CannotConnect: the export could not be retrieved.
    """
    session = async_get_clientsession(hass)
    params = {
        "User": username,
        "Password": password,
        "Table": TABLE_INVENTORY,
        "Format": FORMAT_TAB,
        "Location": "1",
    }

    # The password is a query parameter, so it travels in the request URL - and
    # aiohttp's ClientResponseError renders that URL in both str() and repr().
    # Nothing derived from the failed request may escape this function except a
    # description we build ourselves.
    failure: str | None = None

    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with session.get(BASE_URL, params=params) as response:
                response.raise_for_status()
                payload = await response.text()
    except aiohttp.ClientResponseError as err:
        # The status is the diagnostic part and carries nothing sensitive.
        failure = f"HTTP {err.status} from CellarTracker"
    except aiohttp.ClientError as err:
        # Connector and payload errors name the host rather than the query
        # string, but the same rule applies: name the failure, copy nothing.
        failure = type(err).__name__

    if failure is not None:
        # Raised outside the handler deliberately. `raise ... from None` would
        # clear __cause__ but leave the original on __context__, where a
        # traceback would not print it but a diagnostics dump walking the chain
        # still could. Once the except block has exited the exception is no
        # longer being handled, so nothing is attached at all.
        raise CannotConnect(failure)

    # An auth failure arrives as HTTP 200 with a marker in the body.
    if NOT_LOGGED_REPONSE in payload:
        raise AuthenticationError

    return payload


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
            # Mandatory from a future Home Assistant release, and deprecated
            # without it since 2024.11. It also ties the refresh task to the
            # entry, so unloading cancels a poll still in flight.
            config_entry=entry,
            update_interval=scan_interval,
            always_update=False,
        )

        # Consecutive polls that reported an empty cellar after it held stock.
        self._suspicious_empty_polls = 0

        # Replaced wholesale by each refresh, never mutated in place, and only
        # one refresh runs at a time - so the loop can read it without a lock.
        self._inventory_body: bytes = b"[]"

    @property
    def currency(self) -> str:
        """Return the configured currency symbol."""
        return self._currency

    @property
    def inventory_body(self) -> bytes:
        """The bottle list as a JSON body, rendered ahead of any request.

        Serialising a large cellar costs real time - tens of milliseconds at a
        few thousand bottles, more on the hardware Home Assistant usually runs
        on - and doing it inside a request handler spends that time on the
        event loop. It is rendered in the executor that already runs the parse
        instead, so the view only ever hands over bytes.
        """
        return self._inventory_body

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

        # Pass 1: copy each row and derive its identity. Rows are copied
        # because they belong to the caller.
        identities: list[str] = []
        for bottle in inventory:
            if 'iWine' not in bottle:
                continue

            row = dict(bottle)

            try:
                valuation = float(row.get('Valuation') or 0.0)
            except (ValueError, TypeError):
                valuation = 0.0
            row['Valuation'] = valuation
            total_value += valuation

            processed_bottles.append(row)
            identities.append(_bottle_identity(row))

        if not processed_bottles:
            # Rows parsed, but none carried the key column: we were handed an
            # HTML error page or the upstream schema changed.
            raise UpdateFailed(
                f"CellarTracker returned {len(inventory)} unrecognised row(s) "
                "with no 'iWine' column; treating as an upstream error rather "
                "than an empty cellar"
            )

        # Pass 2: assign ids. Bottles sharing an identity are interchangeable,
        # so their suffixes are ranked by a fingerprint of the whole row rather
        # than by arrival order - otherwise a reordered response moves an id
        # onto a different row. Only duplicates need that tie-break, so the
        # extra hashing is confined to them.
        groups: dict[str, list[int]] = defaultdict(list)
        for index, identity in enumerate(identities):
            groups[identity].append(index)

        for identity, indexes in groups.items():
            if len(indexes) == 1:
                processed_bottles[indexes[0]]['unique_bottle_id'] = identity
                continue

            ranked = sorted(
                indexes,
                key=lambda index: (_row_fingerprint(processed_bottles[index]), index),
            )
            for rank, index in enumerate(ranked):
                processed_bottles[index]['unique_bottle_id'] = (
                    identity if not rank else f"{identity}_{rank}"
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

    async def _fetch_payload(self) -> str:
        """Fetch the raw inventory export for this entry's account."""
        return await async_fetch_inventory_payload(
            self._hass, self._username, self._password
        )

    async def _async_update_data(self) -> dict:
        """Fetch inventory from CellarTracker."""
        try:
            payload = await self._fetch_payload()
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

        # I/O no longer needs a thread, but parsing still does: a large cellar
        # means splitting 66 columns per row, hashing each one and copying every
        # dict. self.data is the last successful result, or None on first poll.
        return await self._hass.async_add_executor_job(
            self._parse_and_process, payload, self.data
        )

    def _parse_and_process(self, payload: str, previous: dict | None) -> dict:
        """Parse the tab-separated export, then summarise it. Runs in an executor."""
        rows = list(csv.DictReader(io.StringIO(payload), dialect="excel-tab"))
        result = self._process_inventory(rows, previous=previous)
        # Rendered here, on the executor thread, for the HTTP views to serve.
        self._inventory_body = json_bytes(result["bottles"])
        return result
