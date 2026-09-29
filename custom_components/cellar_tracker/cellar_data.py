from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
import random
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
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
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .analytics import (
    LocationIndex,
    drink_window_breakdown,
    index_by_location_bin,
    inventory_delta,
)
from .analytics import consume_year as _consume_year  # noqa: F401
from .analytics import drink_window_counts as _drink_window_counts  # noqa: F401
from .const import (
    COMPACT_FIELDS,
    CONF_CURRENCY,
    DEFAULT_CURRENCY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_BOTTLE_FIELDS,
    EVENT_INVENTORY_CHANGED,
    MAX_EVENT_BOTTLES,
    MIN_SCAN_INTERVAL,
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

_BACKOFF_ENDED_BY_ANOTHER_FAILURE = (
    "The last poll failed for another reason, so the backoff has ended"
)

# A throttled cellar should wait, but a server must not be able to park the
# integration indefinitely by sending an enormous Retry-After.
MAX_BACKOFF = 21600

# A delay we compute ourselves is spread over [JITTER_FLOOR, 1] of its nominal
# value, so installs throttled together do not all come back together. Only the
# top is kept and never exceeded: the nominal delay is already the cap's idea of
# "long enough", so jitter shortens it rather than lengthening past the cap.
JITTER_FLOOR = 0.75

# Bounds the exponent so a very long streak cannot build an absurd integer
# before the cap is applied. 2**16 is far past any cap this can meet.
MAX_BACKOFF_EXPONENT = 16

# Bumped only if the stored shape changes incompatibly; Store then hands
# migration to us rather than to whatever happens to parse.
CACHE_VERSION = 1

# An unchanged payload is rewritten to disk at most this often. The write exists
# to advance the stored timestamp, so the age a restart reports stays true; the
# bytes are the same, so doing it every poll would be pointless flash wear at the
# fifteen-minute minimum. An hour is exact at the six-hour default - every poll
# is later than that - and bounds the timestamp's lag at one hour at the minimum.
CACHE_REFRESH_INTERVAL = timedelta(hours=1)


def cache_key(entry_id: str) -> str:
    """The storage key for one entry's inventory cache.

    Per entry, so a legacy install still holding two of them cannot have one
    overwrite the other. The file lands in ``.storage/`` under this name.
    """
    return f"{DOMAIN}.inventory_cache_{entry_id}"


async def async_remove_cache(hass: HomeAssistant, entry_id: str) -> None:
    """Delete an entry's cache. The cellar must not outlive the integration."""
    await Store[dict[str, Any]](
        hass, CACHE_VERSION, cache_key(entry_id), private=True
    ).async_remove()


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
    # Not sensors: carried for the views, the services and diagnostics.
    needs_aging: int
    peak_drinking: int
    location_index: LocationIndex
    # Attached after the parse returns, so it is absent from the executor's
    # own result for the moment between the two.
    last_success: NotRequired[datetime]


class UpstreamBackoff(CannotConnect):
    """CellarTracker is telling us to slow down, by status or by header.

    Subclasses CannotConnect so every existing caller - the config flow's
    credential check among them - keeps classifying it as a connection
    problem without knowing this type exists.
    """

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimited(UpstreamBackoff):
    """CellarTracker answered 429."""


class ServerError(UpstreamBackoff):
    """CellarTracker answered 5xx.

    A struggling server is asking for the same thing a throttling one is: fewer
    requests, not a knock on the next tick.
    """


def _jittered(seconds: float) -> float:
    """Spread a computed delay over the top quarter of itself."""
    return random.uniform(seconds * JITTER_FLOOR, seconds)


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


def _bottle_identity(bottle: Mapping[str, Any]) -> str:
    """Return the 16-hex-character identity of a physical bottle.

    Truncating to 64 bits keeps the id readable; at cellar scale (thousands of
    bottles, not billions) the collision probability is negligible.
    """
    payload = _FIELD_SEPARATOR.join(str(bottle.get(field, "")) for field in IDENTITY_FIELDS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _row_fingerprint(bottle: Mapping[str, Any]) -> str:
    """Order-independent digest of a row's full contents.

    Used only to rank bottles that share an identity, so that duplicate
    suffixes do not depend on the order CellarTracker happened to return.
    """
    payload = _FIELD_SEPARATOR.join(
        f"{key}={bottle[key]}" for key in sorted(bottle) if key != "unique_bottle_id"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event_bottle(bottle: Mapping[str, Any]) -> dict[str, Any]:
    """A bottle reduced to what an event may carry."""
    return {field: bottle[field] for field in EVENT_BOTTLE_FIELDS if field in bottle}


async def async_fetch_inventory_payload(hass: HomeAssistant, username: str, password: str) -> str:
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
    backoff: type[UpstreamBackoff] | None = None

    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with session.get(BASE_URL, params=params) as response:
                response.raise_for_status()
                payload = await response.text()
    except aiohttp.ClientResponseError as err:
        # The status is the diagnostic part and carries nothing sensitive.
        failure = f"HTTP {err.status} from CellarTracker"
        if err.status == 429 or 500 <= err.status <= 599:
            # The header is a count of seconds; unlike the error's URL it
            # carries nothing sensitive, so it is safe to keep.
            backoff = RateLimited if err.status == 429 else ServerError
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
        if backoff is not None:
            raise backoff(failure, retry_after=retry_after)
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

        # Consecutive suspicious polls: an empty cellar, or a drastically smaller
        # one, right after it held stock. (Named for the case that came first.)
        self._suspicious_empty_polls = 0

        # Replaced wholesale by each refresh, never mutated in place, and only
        # one refresh runs at a time - so the loop can read it without a lock.
        self._inventory_body: bytes = b"[]"
        self._compact_body: bytes = b"[]"

        # The cache holds personal data - purchases, stores, free-form notes -
        # so the file is private. Home Assistant's Store also brings atomic
        # writes and keeps the file I/O off the event loop, which a hand-rolled
        # json.dump into .storage/ would not.
        self._store: Store[dict[str, Any]] = Store(
            hass, CACHE_VERSION, cache_key(entry.entry_id), private=True
        )
        # What is on disk and when it was written, so an unchanged payload is
        # not rewritten on every poll - but is still refreshed often enough that
        # its timestamp does not drift from the truth.
        self._cached_payload: str | None = None
        self._cache_saved_at: datetime | None = None
        # True while the data on show came from disk rather than from a poll.
        self._serving_cache = False

        # Why the most recent poll failed, in words we built ourselves - never
        # text copied from the failed request. Cleared by the next success.
        # For diagnostics: a bare "unavailable" tells a user nothing.
        self._last_error: str | None = None

        # Consecutive polls the upstream asked us to slow down for. Drives the
        # exponential growth; forgotten on the first success.
        self._consecutive_backoffs = 0

        # When the cellar last synchronised. None until the first success, so
        # the sensor can report "unknown" rather than invent a time.
        self._last_success: datetime | None = None

    @property
    def scan_interval(self) -> timedelta:
        """The poll interval the user configured, whatever a backoff has set."""
        return self._scan_interval

    @property
    def last_error(self) -> str | None:
        """Why the last poll failed, or None if it did not."""
        return self._last_error

    @property
    def serving_cached_data(self) -> bool:
        """True while what is on show came from the disk cache, not a live poll."""
        return self._serving_cache

    @property
    def consecutive_backoffs(self) -> int:
        """How many polls in a row the upstream has asked us to slow down for."""
        return self._consecutive_backoffs

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

    def current_year(self) -> int:
        """This year, as the coordinator counts it - for the services to share."""
        return self._current_year()

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
        """How long to wait after the upstream asked us to slow down.

        Never sooner than the configured interval - the user chose that - and
        never longer than MAX_BACKOFF, whatever the server asks for.

        A Retry-After is honoured as given: the server said when, so it is
        neither grown nor jittered. Without one the delay doubles with every
        consecutive failure, is capped, and is then jittered.
        """
        configured = int(self._scan_interval.total_seconds())

        # Cap what the *server* can ask for, then apply the configured interval
        # as the floor. Doing it the other way round let the cap undercut a
        # schedule longer than six hours - the options schema sets a minimum
        # and no maximum, so a daily poll became six-hourly while being rate
        # limited, which is the opposite of backing off.
        if retry_after is not None:
            seconds = float(min(retry_after, MAX_BACKOFF))
        else:
            exponent = min(self._consecutive_backoffs, MAX_BACKOFF_EXPONENT)
            seconds = _jittered(min(configured * 2**exponent, MAX_BACKOFF))

        return timedelta(seconds=max(seconds, configured))

    def _end_backoff(self, why: str) -> None:
        """End a backoff episode and return to the configured schedule.

        Being asked to slow down is a statement about the upstream's load, so the
        first poll that is not that statement ends the episode - whatever else
        went wrong with it. Ending it only after a fully successful poll left a
        429 followed by a timeout, an ordinary 4xx, an auth failure or a
        malformed response on the stale slowed schedule, with a later 429 wrongly
        counted as consecutive.
        """
        # Reset unconditionally: a backoff that landed exactly on the configured
        # interval leaves nothing to restore, but the streak is over all the same.
        self._consecutive_backoffs = 0
        if self.update_interval != self._scan_interval:
            _LOGGER.info("%s; restoring the %s poll interval", why, self._scan_interval)
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
                "needs_aging": 0,
                "peak_drinking": 0,
                "location_index": {},
            }

        total_value = 0.0
        processed_bottles = []

        # Pass 1: copy each row and derive its identity. Rows are copied
        # because they belong to the caller.
        identities: list[str] = []
        for bottle in inventory:
            if "iWine" not in bottle:
                continue

            row = dict(bottle)

            try:
                valuation = float(row.get("Valuation") or 0.0)
            except (ValueError, TypeError):
                valuation = 0.0
            row["Valuation"] = valuation
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
                processed_bottles[indexes[0]]["unique_bottle_id"] = identity
                continue

            ranked = sorted(
                indexes,
                key=lambda index: (_row_fingerprint(processed_bottles[index]), index),
            )
            for rank, index in enumerate(ranked):
                processed_bottles[index]["unique_bottle_id"] = (
                    identity if not rank else f"{identity}_{rank}"
                )

        if stocked is not None and len(processed_bottles) < stocked["total_bottles"] // 2:
            # A truncated response can still yield some valid rows, and we cannot
            # know whether the drop is real. It used to be published with a
            # warning; publishing now also overwrites the disk cache and
            # announces every missing bottle as removed, which can set off
            # destructive automations. So it gets the same treatment as a
            # suspicious empty response: refused once, believed if it repeats,
            # since people do sell or drink a lot at once. The counter is shared:
            # two suspicious polls in a row are believed, whichever kind.
            self._suspicious_empty_polls += 1
            if self._suspicious_empty_polls <= TOLERATED_SUSPICIOUS_EMPTY_POLLS:
                raise UpdateFailed(
                    f"CellarTracker returned {len(processed_bottles)} bottles but the "
                    f"cellar previously held {stocked['total_bottles']}; treating it "
                    "as a truncated export"
                )
            _LOGGER.warning(
                "CellarTracker inventory dropped from %s to %s bottles for %s "
                "consecutive polls; accepting it as correct",
                stocked["total_bottles"],
                len(processed_bottles),
                self._suspicious_empty_polls,
            )
        else:
            # Real inventory came back; any earlier suspicion is resolved.
            self._suspicious_empty_polls = 0

        window = drink_window_breakdown(processed_bottles, self._current_year())

        return {
            "total_bottles": len(processed_bottles),
            "total_value": round(total_value, 2),
            "bottles": processed_bottles,
            "ready_to_drink": window["ready_to_drink"],
            "past_drink_window": window["past_drink_window"],
            "needs_aging": window["needs_aging"],
            "peak_drinking": window["peak_drinking"],
            "location_index": index_by_location_bin(processed_bottles),
        }

    async def _fetch_payload(self) -> str:
        """Fetch the raw inventory export for this entry's account."""
        return await async_fetch_inventory_payload(self.hass, self._username, self._password)

    async def _async_update_data(self) -> CellarData:
        """Fetch inventory from CellarTracker, or fall back to the disk cache.

        The cache is only ever a stand-in for a first refresh that could not
        reach a live inventory - typically a restart during an outage. Once
        there is data, a failing poll keeps the standard behaviour: entities go
        unavailable rather than silently swapping in something older than what
        they were already showing.

        ConfigEntryAuthFailed is not an UpdateFailed, so bad credentials
        bypass this entirely: they need the user, and masking them with old
        data would hide the reauth prompt.
        """
        try:
            payload, data, history = await self._async_poll_upstream()
        except ConfigEntryAuthFailed as err:
            self._last_error = str(err)
            raise
        except UpdateFailed as err:
            self._last_error = str(err)
            if self.data is None:
                cached = await self._async_data_from_cache()
                if cached is not None:
                    _LOGGER.warning(
                        "CellarTracker is unavailable (%s); showing the inventory "
                        "cached at %s until it responds",
                        err,
                        cached["last_success"],
                    )
                    return cached
            raise

        self._serving_cache = False
        self._last_error = None
        await self._async_save_cache(payload)
        self._fire_inventory_changed(None if history is None else history["bottles"], data)
        return data

    async def _async_history(self, live_payload: str) -> CellarData | None:
        """What a poll is validated and compared against.

        Normally the previous poll's data. After a restart there is none, and
        the disk cache stands in: it is history, so it has to take part in
        everything history is for - the empty-response and truncation checks as
        well as the change event. Without it a first response that was
        transiently empty was accepted as "no bottles", announced the removal of
        the whole cellar, and overwrote the good cache with the empty payload.

        None means there is nothing to compare with: no cache, an unusable one,
        or one identical to the live response. The identical case skips the
        parse entirely - equal bytes cannot differ - so an unchanged cellar
        costs a restart one file read and a string comparison.

        Also records what is on disk, so the save that follows can tell an
        unchanged payload from a changed one.
        """
        if self.data is not None:
            return self.data

        cached = await self._async_load_cache()
        if cached is None:
            return None
        cached_payload, cached_at = cached
        self._cached_payload = cached_payload
        self._cache_saved_at = cached_at

        if cached_payload == live_payload:
            return None

        # Parsing the cache is not a poll, so it must not disturb the count of
        # consecutive suspicious empty ones - _process_inventory resets it on
        # any success, and a reset here would defeat "believe a repeat".
        suspicious = self._suspicious_empty_polls
        try:
            return await self.hass.async_add_executor_job(
                self._parse_for_comparison, cached_payload
            )
        except (UpdateFailed, csv.Error):
            # An unusable cache is no history, and must not fail a poll that
            # itself succeeded.
            return None
        finally:
            self._suspicious_empty_polls = suspicious

    def _parse_for_comparison(self, payload: str) -> CellarData:
        """Parse a cached payload only to use it as history. Runs in an executor.

        Deliberately not _parse_and_process: that also renders the pre-rendered
        bodies the HTTP views serve, and going through it here would overwrite
        the live inventory with the stale one.
        """
        rows = list(csv.DictReader(io.StringIO(payload), dialect="excel-tab"))
        return self._process_inventory(rows, previous=None)

    def _fire_inventory_changed(
        self, previous_bottles: list[dict[str, Any]] | None, current: CellarData
    ) -> None:
        """Announce a change in which bottles the cellar holds.

        Silent with no history: announcing the whole cellar as "added" would be
        noise every time Home Assistant restarts with nothing on disk to compare
        with. History is the previous poll's bottles or, on the first poll after
        a restart, the disk cache - whether or not that poll needed the cache
        served - so bottles changed while offline are announced either way.
        """
        if previous_bottles is None:
            return
        delta = inventory_delta(previous_bottles, current["bottles"])
        if delta is None:
            return

        added, removed = delta["added"], delta["removed"]
        self.hass.bus.async_fire(
            EVENT_INVENTORY_CHANGED,
            {
                "added_bottles": [_event_bottle(b) for b in added[:MAX_EVENT_BOTTLES]],
                "removed_bottles": [_event_bottle(b) for b in removed[:MAX_EVENT_BOTTLES]],
                "total_count": current["total_bottles"],
                # The lists are capped; these say what was left out.
                "added_count": len(added),
                "removed_count": len(removed),
                "truncated": max(len(added), len(removed)) > MAX_EVENT_BOTTLES,
            },
        )

    async def _async_poll_upstream(self) -> tuple[str, CellarData, CellarData | None]:
        """Fetch and process a live inventory.

        Returns the raw payload, the processed data, and the history the data
        was validated against - which the caller reuses to announce changes.
        """
        try:
            payload = await self._fetch_payload()
        except AuthenticationError as err:
            self._end_backoff(_BACKOFF_ENDED_BY_ANOTHER_FAILURE)
            # Surfaces as a reauth flow (see async_step_reauth in config_flow).
            raise ConfigEntryAuthFailed("Invalid CellarTracker credentials") from err
        except UpstreamBackoff as err:
            # Being throttled, or the server struggling, is normal operation
            # rather than a fault: back off quietly instead of knocking again
            # on the next tick.
            self._consecutive_backoffs += 1
            backoff = self._backoff_for(err.retry_after)
            self.update_interval = backoff
            _LOGGER.info("CellarTracker asked us to slow down (%s); next poll in %s", err, backoff)
            raise UpdateFailed(f"CellarTracker asked us to slow down: {err}") from err
        except (CannotConnect, TimeoutError, OSError) as err:
            self._end_backoff(_BACKOFF_ENDED_BY_ANOTHER_FAILURE)
            _LOGGER.warning("Temporary communication error with CellarTracker: %r", err)
            raise UpdateFailed(f"Cannot reach CellarTracker: {err!r}") from err
        except Exception as err:
            self._end_backoff(_BACKOFF_ENDED_BY_ANOTHER_FAILURE)
            _LOGGER.exception("Unexpected error fetching CellarTracker inventory")
            raise UpdateFailed(f"Unexpected CellarTracker error: {err!r}") from err

        # The upstream answered, and did not ask us to slow down. That ends any
        # backoff here rather than at the end of the poll: what follows can still
        # fail - an error page, a malformed export - and a 200 is not throttling.
        self._end_backoff("CellarTracker is responding again")

        # Resolved before the parse, not after: it is what the response is
        # checked against, not merely what it is compared to.
        history = await self._async_history(payload)

        # I/O no longer needs a thread, but parsing still does: a large cellar
        # means splitting 66 columns per row, hashing each one and copying every
        # dict.
        try:
            data = await self.hass.async_add_executor_job(self._parse_and_process, payload, history)
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

        return payload, data, history

    async def _async_save_cache(self, payload: str) -> None:
        """Persist a payload that has just parsed. Never raises.

        Called only after a successful parse, so an error page can never become
        the last known inventory. A failure to write is logged and swallowed:
        the cache exists to help a bad day, and must not cause one.
        """
        saved_at = self._last_success or dt_util.utcnow()
        if (
            payload == self._cached_payload
            and self._cache_saved_at is not None
            and saved_at - self._cache_saved_at < CACHE_REFRESH_INTERVAL
        ):
            return
        try:
            await self._store.async_save({"payload": payload, "saved_at": saved_at.isoformat()})
        except Exception as err:  # noqa: BLE001 - whatever the disk throws
            _LOGGER.warning("Could not write the CellarTracker inventory cache: %s", err)
            return
        self._cached_payload = payload
        self._cache_saved_at = saved_at

    async def _async_load_cache(self) -> tuple[str, datetime] | None:
        """Read the cache, or None if it is absent, unreadable or malformed."""
        try:
            stored = await self._store.async_load()
        except Exception as err:  # noqa: BLE001 - a bad cache is no cache
            _LOGGER.warning("Could not read the CellarTracker inventory cache: %s", err)
            return None

        if not isinstance(stored, dict):
            return None
        payload = stored.get("payload")
        raw_saved_at = stored.get("saved_at")
        if not isinstance(payload, str) or not payload or not isinstance(raw_saved_at, str):
            return None

        try:
            saved_at = datetime.fromisoformat(raw_saved_at)
        except ValueError:
            return None
        if saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=UTC)
        return payload, saved_at

    async def _async_data_from_cache(self) -> CellarData | None:
        """Build a payload from the cache, or None if there is nothing usable.

        Parsed exactly like a live response, so the drink-window counts are
        computed for the current year rather than trusted from when it was
        stored, and the HTTP views get their pre-rendered bodies.
        """
        cached = await self._async_load_cache()
        if cached is None:
            return None
        payload, saved_at = cached

        # As in _async_history: this parse is not a poll and must leave the
        # count of consecutive suspicious empty ones alone. It runs right after
        # one was rejected, which is exactly when a reset would hurt.
        suspicious = self._suspicious_empty_polls
        try:
            data = await self.hass.async_add_executor_job(self._parse_and_process, payload, None)
        except (UpdateFailed, csv.Error) as err:
            _LOGGER.warning("Ignoring an unusable CellarTracker inventory cache: %s", err)
            return None
        finally:
            self._suspicious_empty_polls = suspicious

        # The cache's own age, not now: "last synchronised" must not claim a
        # sync that did not happen.
        self._last_success = saved_at
        data["last_success"] = saved_at
        self._cached_payload = payload
        self._cache_saved_at = saved_at
        self._serving_cache = True

        # Stale data is worth replacing soon, not in six hours. Skipped while
        # backing off - decided by the streak, not by comparing intervals,
        # because a backoff can land exactly on the configured interval and
        # would then look like no backoff at all.
        if self._consecutive_backoffs == 0:
            self.update_interval = min(self._scan_interval, timedelta(seconds=MIN_SCAN_INTERVAL))
        return data

    def _parse_and_process(self, payload: str, previous: CellarData | None) -> CellarData:
        """Parse the tab-separated export, then summarise it. Runs in an executor."""
        rows = list(csv.DictReader(io.StringIO(payload), dialect="excel-tab"))
        result = self._process_inventory(rows, previous=previous)
        # Rendered here, on the executor thread, for the HTTP views to serve.
        bottles = result["bottles"]
        self._inventory_body = json_bytes(bottles)
        self._compact_body = json_bytes(
            [{field: b[field] for field in COMPACT_FIELDS if field in b} for b in bottles]
        )
        return result


# Carries the coordinator's type on the entry, so `entry.runtime_data` is
# checked rather than `Any` in __init__, sensor.py, views.py and diagnostics.
CellarTrackerConfigEntry = ConfigEntry[WineCellarData]
