from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, NotRequired, TypedDict

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
from homeassistant.util import dt as dt_util

from .const import (
    COMPACT_FIELDS,
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

# A throttled cellar should wait, but a server must not be able to park the
# integration indefinitely by sending an enormous Retry-After.
MAX_BACKOFF = 21600


class CellarData(TypedDict):
    """What one successful poll produces.

    Named once here because five sensors, two HTTP views and the diagnostics
    module all read it. Untyped, every one of those call sites saw ``Any`` and
    a mistyped key would have gone unnoticed until runtime.
    """

    total_bottles: int
    total_value: float
    bottles: list[dict[str, Any]]
    ready_to_drink: int
    past_drink_window: int
    # Attached after the parse returns, so it is absent from the executor's
    # own result for the moment between the two.
    last_success: NotRequired[datetime]


class RateLimited(CannotConnect):
    """CellarTracker answered 429.

    Subclasses CannotConnect so every existing caller - the config flow's
    credential check among them - keeps classifying it as a connection
    problem without knowing this type exists.
    """

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _retry_after_seconds(headers: Mapping[str, str] | None) -> int | None:
    """Read Retry-After as a whole number of seconds, or None.

    The header also has an HTTP-date form. It is not read here: the fallback
    backoff is already sensible, and mis-parsing a date is worse than not
    trying.
    """
    if not headers:
        return None
    try:
        seconds = int(str(headers.get("Retry-After", "")).strip())
    except (AttributeError, TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


TABLE_INVENTORY = CellarTrackerTable.Inventory.value
FORMAT_TAB = CellarTrackerFormat.tab.value

# Columns that identify a physical bottle. Volatile columns are deliberately
# excluded: Valuation moves whenever CellarTracker re-prices a wine, and an id
# that changed on every re-pricing would be useless to anything keying on it.
IDENTITY_FIELDS = ("iWine", "PurchaseDate", "Barcode", "Location", "Bin")

# Unit separator: cannot occur in CellarTracker's tab-separated payload, so it
# cannot be forged by field contents to collide with another row's identity.
_FIELD_SEPARATOR = "\x1f"


def _consume_year(value: object) -> int | None:
    """Read a BeginConsume/EndConsume cell as a year, or None if absent.

    CellarTracker gives these as plain years, and cellar.html already reads
    them that way - ``parseInt`` compared against the current year, with a
    blank collapsing to 0. Anything that is not a whole positive number means
    "no window given" rather than an error: a cellar is full of wines nobody
    has assigned a drinking window to.
    """
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if year > 0 else None


def _drink_window_counts(bottles: list, year: int) -> tuple[int, int]:
    """Count bottles drinkable now, and bottles past their window.

    A bottle with no window at all is counted in neither: the export does not
    say, and guessing would be worse than reporting nothing.

    The last year of a window counts as ready, not past - it is still inside
    the window. The dashboard paints that year red, but that is urgency rather
    than expiry.
    """
    ready = past = 0
    for bottle in bottles:
        begin = _consume_year(bottle.get("BeginConsume"))
        end = _consume_year(bottle.get("EndConsume"))

        if end is not None and end < year:
            past += 1
        elif (begin is not None or end is not None) and (
            (begin is None or begin <= year) and (end is None or end >= year)
        ):
            ready += 1
    return ready, past


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


async def async_fetch_inventory_payload(
    hass: HomeAssistant, username: str, password: str
) -> str:
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
    retry_after: int | None = None
    throttled = False

    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with session.get(BASE_URL, params=params) as response:
                response.raise_for_status()
                payload = await response.text()
    except aiohttp.ClientResponseError as err:
        # The status is the diagnostic part and carries nothing sensitive.
        failure = f"HTTP {err.status} from CellarTracker"
        if err.status == 429:
            # The header is a count of seconds; unlike the error's URL it
            # carries nothing sensitive, so it is safe to keep.
            throttled = True
            retry_after = _retry_after_seconds(err.headers)
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
        if throttled:
            raise RateLimited(failure, retry_after=retry_after)
        raise CannotConnect(failure)

    # An auth failure arrives as HTTP 200 with a marker in the body.
    if NOT_LOGGED_REPONSE in payload:
        raise AuthenticationError

    return payload


class WineCellarData(DataUpdateCoordinator[CellarData]):
    """Fetch and process CellarTracker inventory data."""

    # Home Assistant declares `data` as the payload itself and then assigns
    # None to it until the first refresh completes - a white lie the framework
    # tells with a `type: ignore` of its own. Every reader here already guards
    # for that (see F-15: a state read must survive a coordinator with no data
    # yet), and without this redeclaration mypy calls those guards dead code,
    # because a TypedDict with required keys can never be falsy.
    #
    # Stated once here rather than narrowed at each of the five call sites. If
    # Home Assistant ever types it honestly, warn_unused_ignores will say so.
    data: CellarData | None  # type: ignore[assignment]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
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
        # Kept so a rate-limit backoff knows what to restore, and so it never
        # polls sooner than the user asked for.
        self._scan_interval = scan_interval

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # Mandatory from a future Home Assistant release, and deprecated
            # without it since 2024.11. It also ties the refresh task to the
            # entry, so unloading cancels a poll still in flight.
            config_entry=entry,
            update_interval=scan_interval,
            # Every payload now carries the time of the poll that produced it,
            # so no two ever compare equal and this could never suppress an
            # update. Left at the default rather than kept as a flag that
            # reads like it does something.
        )

        # Consecutive polls that reported an empty cellar after it held stock.
        self._suspicious_empty_polls = 0

        # Replaced wholesale by each refresh, never mutated in place, and only
        # one refresh runs at a time - so the loop can read it without a lock.
        self._inventory_body: bytes = b"[]"
        self._compact_body: bytes = b"[]"

        # When the cellar last synchronised. None until the first success, so
        # the sensor can report "unknown" rather than invent a time.
        self._last_success: datetime | None = None

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

    def _current_year(self) -> int:
        """This year, read once per poll.

        A method rather than an inline call so a test can pin it: the counts
        would otherwise change meaning every January. It also means the counts
        are as stale as the poll interval across a year boundary, which for a
        six-hourly integration is not worth a separate timer.
        """
        return dt_util.utcnow().year

    @property
    def last_success(self) -> datetime | None:
        """When the last poll succeeded, or None if none has yet.

        ``last_update_success`` says whether the most recent attempt worked;
        this says when the data was last actually refreshed, which is what
        tells a user that a six-hourly integration is still alive.
        """
        return self._last_success

    @property
    def compact_body(self) -> bytes:
        """The bottle list reduced to the columns the dashboard renders.

        Rendered here rather than per request for the same reason as the full
        body: encoding on the event loop is what P0-2 removed. That is also why
        the projection is a fixed named set rather than an arbitrary field
        list - an arbitrary one could not be rendered ahead of time.
        """
        return self._compact_body

    def _backoff_for(self, retry_after: int | None) -> timedelta:
        """How long to wait after being throttled.

        Never sooner than the configured interval - the user chose that - and
        never longer than MAX_BACKOFF, whatever the server asks for. With no
        usable hint, back off to twice the configured interval.
        """
        configured = int(self._scan_interval.total_seconds())
        seconds = retry_after if retry_after is not None else configured * 2

        # Cap what the *server* can ask for, then apply the configured interval
        # as the floor. Doing it the other way round let the cap undercut a
        # schedule longer than six hours - the options schema sets a minimum
        # and no maximum, so a daily poll became six-hourly while being rate
        # limited, which is the opposite of backing off.
        return timedelta(seconds=max(min(seconds, MAX_BACKOFF), configured))

    def _restore_interval(self) -> None:
        """Undo a backoff once CellarTracker is answering again."""
        if self.update_interval != self._scan_interval:
            _LOGGER.info(
                "CellarTracker is responding again; restoring the %s poll interval",
                self._scan_interval,
            )
            self.update_interval = self._scan_interval

    def _process_inventory(
        self, inventory: list[dict[str, Any]], previous: CellarData | None = None
    ) -> CellarData:
        """Process the raw inventory list into a structured dictionary.

        Args:
            inventory: rows as returned by the cellartracker library.
            previous: the last successful result, used to tell a genuinely empty
                cellar apart from an upstream error page.

        Raises:
            UpdateFailed: the response does not look like inventory data.
        """
        # Narrowed once here so the branches below can index it: `previous`
        # is only ever read when it actually held stock.
        stocked: CellarData | None = (
            previous if previous and previous.get("total_bottles") else None
        )

        if not inventory:
            # An error page that parses to zero rows is indistinguishable from
            # an empty cellar on its own, and a stocked cellar does not empty
            # itself between two polls - but a one-bottle cellar can. Reject the
            # first suspicious zero, then accept it so the sensor recovers
            # instead of being stranded as unavailable.
            if stocked is not None:
                self._suspicious_empty_polls += 1
                if self._suspicious_empty_polls <= TOLERATED_SUSPICIOUS_EMPTY_POLLS:
                    raise UpdateFailed(
                        "CellarTracker returned no inventory rows but the cellar "
                        f"previously held {stocked['total_bottles']} bottles; "
                        "treating as an upstream error"
                    )
                _LOGGER.warning(
                    "CellarTracker has reported an empty cellar for %s consecutive "
                    "polls (previously %s bottles); accepting it as correct",
                    self._suspicious_empty_polls,
                    stocked["total_bottles"],
                )
            return {
                "total_bottles": 0,
                "total_value": 0.0,
                "bottles": [],
                "ready_to_drink": 0,
                "past_drink_window": 0,
            }

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

        if stocked is not None and len(processed_bottles) < stocked["total_bottles"] // 2:
            # A truncated response can still yield some valid rows. We cannot
            # know whether the drop is real, so publish it but leave a trace.
            _LOGGER.warning(
                "CellarTracker inventory dropped from %s to %s bottles in a "
                "single poll; verify the data is correct",
                stocked["total_bottles"],
                len(processed_bottles),
            )

        ready, past = _drink_window_counts(processed_bottles, self._current_year())

        return {
            "total_bottles": len(processed_bottles),
            "total_value": round(total_value, 2),
            "bottles": processed_bottles,
            "ready_to_drink": ready,
            "past_drink_window": past,
        }

    async def _fetch_payload(self) -> str:
        """Fetch the raw inventory export for this entry's account."""
        return await async_fetch_inventory_payload(
            self._hass, self._username, self._password
        )

    async def _async_update_data(self) -> CellarData:
        """Fetch inventory from CellarTracker."""
        try:
            payload = await self._fetch_payload()
        except AuthenticationError as err:
            # Surfaces as a reauth flow (see async_step_reauth in config_flow).
            raise ConfigEntryAuthFailed(
                "Invalid CellarTracker credentials"
            ) from err
        except RateLimited as err:
            # Being throttled is normal operation, not a fault: back off
            # quietly rather than knocking again on the next tick.
            backoff = self._backoff_for(err.retry_after)
            self.update_interval = backoff
            _LOGGER.info(
                "CellarTracker is rate limiting us (%s); next poll in %s", err, backoff
            )
            raise UpdateFailed(f"Rate limited by CellarTracker: {err}") from err
        except (CannotConnect, TimeoutError, OSError) as err:
            _LOGGER.warning("Temporary communication error with CellarTracker: %r", err)
            raise UpdateFailed(f"Cannot reach CellarTracker: {err!r}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching CellarTracker inventory")
            raise UpdateFailed(f"Unexpected CellarTracker error: {err!r}") from err

        # I/O no longer needs a thread, but parsing still does: a large cellar
        # means splitting 66 columns per row, hashing each one and copying every
        # dict. self.data is the last successful result, or None on first poll.
        try:
            data = await self._hass.async_add_executor_job(
                self._parse_and_process, payload, self.data
            )
        except UpdateFailed:
            # _process_inventory's own refusals already carry their reasoning.
            raise
        except csv.Error as err:
            # Reachable without malice: csv enforces field_size_limit, and one
            # long tasting note is enough to exceed it. Classify it here rather
            # than leaving the coordinator to log a traceback.
            raise UpdateFailed(f"Malformed CellarTracker export: {err}") from err

        # Carried inside the payload, not just alongside it. The coordinator
        # compares payloads to decide whether to notify listeners, and a
        # cellar's inventory is identical between most polls - so a timestamp
        # held outside would never reach the sensor, and "last synchronised"
        # would quietly come to mean "last time a bottle changed".
        self._last_success = dt_util.utcnow()
        data["last_success"] = self._last_success

        self._restore_interval()
        return data

    def _parse_and_process(self, payload: str, previous: CellarData | None) -> CellarData:
        """Parse the tab-separated export, then summarise it. Runs in an executor."""
        rows = list(csv.DictReader(io.StringIO(payload), dialect="excel-tab"))
        result = self._process_inventory(rows, previous=previous)
        # Rendered here, on the executor thread, for the HTTP views to serve.
        bottles = result["bottles"]
        self._inventory_body = json_bytes(bottles)
        self._compact_body = json_bytes(
            [
                {field: b[field] for field in COMPACT_FIELDS if field in b}
                for b in bottles
            ]
        )
        return result


# Carries the coordinator's type on the entry, so `entry.runtime_data` is
# checked rather than `Any` in __init__, sensor.py, views.py and diagnostics.
CellarTrackerConfigEntry = ConfigEntry[WineCellarData]
