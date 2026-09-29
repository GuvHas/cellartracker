"""A persistent inventory cache, so a restart during an outage is not a blackout.

Before this, restarting Home Assistant while CellarTracker was unreachable left
every sensor unavailable until the upstream came back - the integration had
nothing to show for a cellar that had not changed. The cache holds the last
inventory that parsed successfully and is served only when the first refresh
cannot reach a live one.

What must hold:

- Only a payload that *parsed* is cached, so an error page can never become
  the "last known" inventory.
- It is served only when there is no data yet. A later failure keeps the
  standard behaviour: entities go unavailable rather than silently showing
  something older than what they already had.
- Never for an authentication failure. Bad credentials need the user, and
  masking them with old data would hide the reauth prompt.
- The timestamp is the cache's, not now's, so "last synchronised" tells the
  truth about how stale the data is.
- It holds personal data (purchases, stores, notes), so it is private and is
  removed with the integration.
- A cache that is corrupt, unreadable or unwritable must never break polling.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import aiohttp
import pytest
from cellartracker.const import NOT_LOGGED_REPONSE
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from yarl import URL

from cellar_tracker import async_remove_entry, cellar_data
from cellar_tracker.cellar_data import WineCellarData, cache_key
from conftest import ConfigEntry, FakeHass, FakeSession

HEADER = "iWine\tWine\tValuation\tBeginConsume\tEndConsume"
LIVE = "\n".join([HEADER, "1\tBarolo\t45.50\t2020\t2040", "2\tRioja\t22.00\t2020\t2030"])
STALE = "\n".join([HEADER, "9\tPort\t30.00\t2030\t2050"])
SAVED_AT = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)
ENTRY_ID = "test_entry"


def failing(status: int) -> aiohttp.ClientResponseError:
    url = URL("https://www.cellartracker.com/xlquery.asp?User=a&Password=b")
    return aiohttp.ClientResponseError(
        aiohttp.RequestInfo(url, "GET", (), url), (), status=status, message="upstream"
    )


def build(*, cached: str | None = None, scan_interval: int = 21600, **session) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(**session)
    if cached is not None:
        hass.storage_backend[cache_key(ENTRY_ID)] = {
            "payload": cached,
            "saved_at": SAVED_AT.isoformat(),
        }
    entry = ConfigEntry(
        entry_id=ENTRY_ID,
        data={"username": "alice", "password": "s3cret", "scan_interval": scan_interval},
    )
    return WineCellarData(hass, entry)


def update(coordinator: WineCellarData):
    return asyncio.run(coordinator._async_update_data())


def stored(coordinator: WineCellarData) -> dict | None:
    return coordinator.hass.storage_backend.get(cache_key(ENTRY_ID))


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
def test_a_successful_poll_writes_the_cache():
    coordinator = build(text=LIVE)
    update(coordinator)
    assert stored(coordinator)["payload"] == LIVE


def test_the_cache_records_when_it_was_written():
    coordinator = build(text=LIVE)
    before = datetime.now(UTC) - timedelta(seconds=5)
    update(coordinator)
    saved_at = datetime.fromisoformat(stored(coordinator)["saved_at"])
    assert before <= saved_at <= datetime.now(UTC) + timedelta(seconds=5)


def test_an_error_page_is_never_cached():
    """Only a payload that parsed may become the last known inventory."""
    coordinator = build(text="<html><title>503</title></html>\n<body>down</body>")
    with pytest.raises(UpdateFailed):
        update(coordinator)
    assert stored(coordinator) is None


def test_a_failed_poll_leaves_the_existing_cache_alone():
    coordinator = build(cached=STALE, raise_for_status=failing(503))
    coordinator.data = {"total_bottles": 1}  # type: ignore[assignment]  # not a first poll

    with pytest.raises(UpdateFailed):
        update(coordinator)

    assert stored(coordinator)["payload"] == STALE


def test_an_unchanged_payload_is_not_rewritten():
    coordinator = build(text=LIVE)
    update(coordinator)
    update(coordinator)
    assert coordinator.hass.storage_saves == 1


def test_a_changed_payload_is_rewritten():
    coordinator = build(text=LIVE)
    update(coordinator)
    coordinator.hass.session = FakeSession(text=LIVE + "\n3\tChablis\t12.00\t2018\t2024")
    update(coordinator)
    assert coordinator.hass.storage_saves == 2


def test_the_cache_holds_no_credentials():
    coordinator = build(text=LIVE)
    update(coordinator)
    dumped = json.dumps(stored(coordinator))
    assert "s3cret" not in dumped
    assert "alice" not in dumped


def test_the_cache_file_is_private():
    """It holds purchase history and free-form notes."""
    assert build(text=LIVE)._store.private is True


def test_the_cache_is_keyed_by_entry():
    """A legacy install with two entries must not have them overwrite each other."""
    assert cache_key("a") != cache_key("b")


# --------------------------------------------------------------------------
# Serving it
# --------------------------------------------------------------------------
UPSTREAM_DOWN = [
    pytest.param({"error": aiohttp.ClientConnectionError("boom")}, id="connection"),
    pytest.param({"raise_for_status": failing(503)}, id="server-error"),
    pytest.param({"raise_for_status": failing(502)}, id="bad-gateway"),
    pytest.param({"raise_for_status": failing(429)}, id="rate-limited"),
    pytest.param({"raise_for_status": failing(404)}, id="not-found"),
    pytest.param({"text": "<html>maintenance</html>\n<body>back soon</body>"}, id="error-page"),
]


@pytest.mark.parametrize("session", UPSTREAM_DOWN)
def test_the_cache_is_served_when_the_first_refresh_cannot_reach_upstream(session):
    coordinator = build(cached=LIVE, **session)
    data = update(coordinator)
    assert data["total_bottles"] == 2
    assert data["total_value"] == 67.5


def test_a_timeout_serves_the_cache(monkeypatch):
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 0.05)
    coordinator = build(cached=LIVE, text=STALE, delay=5)
    assert update(coordinator)["total_bottles"] == 2


def test_served_data_reports_the_caches_age_not_now():
    """'Last synchronised' must not claim a sync that did not happen."""
    coordinator = build(cached=LIVE, error=aiohttp.ClientConnectionError("boom"))
    data = update(coordinator)
    assert data["last_success"] == SAVED_AT
    assert coordinator.last_success == SAVED_AT


def test_served_data_is_flagged_as_cached():
    coordinator = build(cached=LIVE, error=aiohttp.ClientConnectionError("boom"))
    assert coordinator.serving_cached_data is False
    update(coordinator)
    assert coordinator.serving_cached_data is True


def test_served_data_feeds_the_http_views_too():
    coordinator = build(cached=LIVE, error=aiohttp.ClientConnectionError("boom"))
    update(coordinator)
    assert json.loads(coordinator.inventory_body)[0]["Wine"] == "Barolo"


def test_the_cached_inventory_is_recounted_for_the_current_year(monkeypatch):
    """Counts depend on the year, so they are computed at restore, not stored."""
    coordinator = build(cached=LIVE, error=aiohttp.ClientConnectionError("boom"))
    monkeypatch.setattr(coordinator, "_current_year", lambda: 2031)
    data = update(coordinator)
    assert data["past_drink_window"] == 1  # Rioja's window ended in 2030


def test_no_cache_and_no_upstream_still_fails():
    coordinator = build(error=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(UpdateFailed):
        update(coordinator)


def test_serving_the_cache_does_not_rewrite_it():
    coordinator = build(cached=LIVE, error=aiohttp.ClientConnectionError("boom"))
    update(coordinator)
    assert coordinator.hass.storage_saves == 0


# --------------------------------------------------------------------------
# When it must NOT be served
# --------------------------------------------------------------------------
def test_an_authentication_failure_never_uses_the_cache():
    """Bad credentials need the user; old data would hide the reauth prompt."""
    coordinator = build(cached=LIVE, text=f"<html>{NOT_LOGGED_REPONSE}</html>")
    with pytest.raises(ConfigEntryAuthFailed):
        update(coordinator)


def test_a_later_failure_does_not_swap_in_the_cache():
    coordinator = build(cached=STALE, raise_for_status=failing(503))
    coordinator.data = {"total_bottles": 5}  # type: ignore[assignment]
    with pytest.raises(UpdateFailed):
        update(coordinator)
    assert coordinator.serving_cached_data is False


# --------------------------------------------------------------------------
# A bad cache is no cache
# --------------------------------------------------------------------------
BAD_CACHES = [
    pytest.param("not a dict", id="not-a-dict"),
    pytest.param({}, id="empty"),
    pytest.param({"saved_at": SAVED_AT.isoformat()}, id="no-payload"),
    pytest.param({"payload": 12345, "saved_at": SAVED_AT.isoformat()}, id="payload-not-text"),
    pytest.param({"payload": LIVE}, id="no-timestamp"),
    pytest.param({"payload": LIVE, "saved_at": "yesterday-ish"}, id="bad-timestamp"),
    pytest.param(
        {"payload": "<html>x</html>\n<p>y</p>", "saved_at": SAVED_AT.isoformat()},
        id="payload-does-not-parse",
    ),
    pytest.param({"payload": "", "saved_at": SAVED_AT.isoformat()}, id="empty-payload"),
]


@pytest.mark.parametrize("content", BAD_CACHES)
def test_a_corrupt_cache_is_treated_as_absent(content):
    coordinator = build(error=aiohttp.ClientConnectionError("boom"))
    coordinator.hass.storage_backend[cache_key(ENTRY_ID)] = content
    with pytest.raises(UpdateFailed):
        update(coordinator)


def test_an_unreadable_cache_is_treated_as_absent():
    coordinator = build(cached=LIVE, error=aiohttp.ClientConnectionError("boom"))
    coordinator.hass.storage_load_error = OSError("disk unplugged")
    with pytest.raises(UpdateFailed):
        update(coordinator)


def test_an_unwritable_cache_does_not_break_polling(caplog):
    coordinator = build(text=LIVE)
    coordinator.hass.storage_save_error = OSError("disk full")
    with caplog.at_level("WARNING"):
        data = update(coordinator)
    assert data["total_bottles"] == 2
    assert "cache" in caplog.text.lower()


# --------------------------------------------------------------------------
# Recovering from stale
# --------------------------------------------------------------------------
def test_a_live_poll_after_serving_the_cache_takes_over():
    coordinator = build(cached=STALE, error=aiohttp.ClientConnectionError("boom"))
    coordinator.data = update(coordinator)

    coordinator.hass.session = FakeSession(text=LIVE)
    data = update(coordinator)

    assert data["total_bottles"] == 2
    assert coordinator.serving_cached_data is False
    assert coordinator.last_success > SAVED_AT


def test_stale_data_retries_sooner_than_a_six_hour_schedule():
    """The point of the cache is a short blackout, not a six-hour one."""
    coordinator = build(cached=LIVE, error=aiohttp.ClientConnectionError("boom"))
    update(coordinator)
    assert coordinator.update_interval == timedelta(seconds=900)


def test_the_stale_retry_never_exceeds_the_configured_interval():
    coordinator = build(cached=LIVE, scan_interval=900, error=aiohttp.ClientConnectionError("x"))
    update(coordinator)
    assert coordinator.update_interval == timedelta(seconds=900)


def test_a_backoff_wins_over_the_stale_retry():
    """Being throttled must still be respected while serving stale data.

    Scan interval 3600 makes the two distinguishable: the stale retry would be
    900, the backoff is somewhere in [5400, 7200].
    """
    coordinator = build(cached=LIVE, scan_interval=3600, raise_for_status=failing(429))
    update(coordinator)
    assert coordinator.update_interval >= timedelta(seconds=5400)


def test_a_backoff_that_lands_on_the_configured_interval_still_wins():
    """Compared by streak, not by interval: at 21600 the backoff cap equals it."""
    coordinator = build(cached=LIVE, scan_interval=21600, raise_for_status=failing(429))
    update(coordinator)
    assert coordinator.update_interval == timedelta(seconds=21600)


def test_the_configured_interval_returns_after_a_live_poll():
    coordinator = build(cached=STALE, error=aiohttp.ClientConnectionError("boom"))
    coordinator.data = update(coordinator)
    coordinator.hass.session = FakeSession(text=LIVE)
    update(coordinator)
    assert coordinator.update_interval == timedelta(seconds=21600)


def test_serving_the_cache_says_so(caplog):
    coordinator = build(cached=LIVE, error=aiohttp.ClientConnectionError("boom"))
    with caplog.at_level("WARNING"):
        update(coordinator)
    assert "cached" in caplog.text.lower()


# --------------------------------------------------------------------------
# Removal
# --------------------------------------------------------------------------
def test_removing_the_integration_deletes_the_cache():
    """The user's cellar must not outlive the integration on disk."""
    coordinator = build(text=LIVE)
    update(coordinator)
    assert stored(coordinator) is not None

    entry = ConfigEntry(entry_id=ENTRY_ID)
    asyncio.run(async_remove_entry(coordinator.hass, entry))

    assert stored(coordinator) is None


def test_removing_an_entry_that_never_cached_is_harmless():
    hass = FakeHass()
    asyncio.run(async_remove_entry(hass, ConfigEntry(entry_id="never-cached")))


# --------------------------------------------------------------------------
# The timestamp must advance even when the inventory does not change
#
# Reported by Codex on #23. An unchanged payload returned early, so saved_at was
# never refreshed: a cellar untouched for months, then a restart during an
# outage, reported a "last synchronised" months in the past. That defeats the
# point of the cache's own timestamp, which exists to tell the truth about age.
#
# Rewriting the whole file every poll would fix it, but the writes are pointless
# for an unchanged cellar; so an unchanged payload is rewritten at most hourly.
# That is exact at the six-hour default and bounds the lag at one hour at the
# fifteen-minute minimum.
# --------------------------------------------------------------------------
T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def clock(monkeypatch, moments: list[datetime]):
    """Make dt_util.utcnow return each moment in turn, then repeat the last."""
    remaining = list(moments)

    def now():
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    monkeypatch.setattr(cellar_data.dt_util, "utcnow", now)


def saved_at(coordinator: WineCellarData) -> datetime:
    return datetime.fromisoformat(stored(coordinator)["saved_at"])


def test_an_unchanged_payload_refreshes_the_timestamp_after_the_refresh_interval(monkeypatch):
    coordinator = build(text=LIVE)
    later = T0 + cellar_data.CACHE_REFRESH_INTERVAL + timedelta(minutes=1)
    clock(monkeypatch, [T0, T0, later, later])  # a poll reads the clock twice

    update(coordinator)
    assert saved_at(coordinator) == T0
    update(coordinator)

    assert saved_at(coordinator) == later
    assert coordinator.hass.storage_saves == 2


def test_an_unchanged_payload_is_not_rewritten_within_the_refresh_interval(monkeypatch):
    coordinator = build(text=LIVE)
    soon = T0 + timedelta(minutes=5)
    clock(monkeypatch, [T0, T0, soon, soon])

    update(coordinator)
    update(coordinator)

    assert coordinator.hass.storage_saves == 1


def test_the_refresh_interval_is_short_next_to_a_default_poll():
    """At the six-hour default every poll refreshes the stamp; it is exact there."""
    assert timedelta(hours=6) > cellar_data.CACHE_REFRESH_INTERVAL
    assert timedelta(hours=1) >= cellar_data.CACHE_REFRESH_INTERVAL


def test_a_cellar_unchanged_for_a_month_still_reports_recent_when_restored(monkeypatch):
    """The scenario reported: months unchanged, then a restart during an outage."""
    coordinator = build(text=LIVE)
    polls = [T0 + timedelta(hours=6 * n) for n in range(4 * 30)]  # a month, 6-hourly
    clock(monkeypatch, [moment for poll in polls for moment in (poll, poll)])
    for _ in polls:
        update(coordinator)

    last_poll = polls[-1]
    restarted = build(cached=None, error=aiohttp.ClientConnectionError("boom"))
    restarted.hass.storage_backend = coordinator.hass.storage_backend
    update(restarted)

    assert restarted.last_success == last_poll
    assert last_poll - restarted.last_success < cellar_data.CACHE_REFRESH_INTERVAL


def test_a_changed_payload_is_always_rewritten_whatever_the_time(monkeypatch):
    coordinator = build(text=LIVE)
    clock(monkeypatch, [T0, T0, T0 + timedelta(seconds=1), T0 + timedelta(seconds=1)])
    update(coordinator)
    coordinator.hass.session = FakeSession(text=LIVE + "\n3\tChablis\t12.00\t2018\t2024")
    update(coordinator)
    assert coordinator.hass.storage_saves == 2


def test_a_timestamp_that_was_refreshed_is_what_the_restore_reports(monkeypatch):
    coordinator = build(text=LIVE)
    later = T0 + timedelta(hours=6)
    clock(monkeypatch, [T0, T0, later, later])
    update(coordinator)
    update(coordinator)

    restarted = build(error=aiohttp.ClientConnectionError("boom"))
    restarted.hass.storage_backend = coordinator.hass.storage_backend
    update(restarted)
    assert restarted.last_success == later


# --------------------------------------------------------------------------
# The first live poll is validated against the cache
#
# Reported by Codex on #23 (P1). After a restart self.data is None, so the first
# response was parsed with no stock to compare against and the empty-response
# safeguard was bypassed: a transiently empty or header-only answer was accepted
# as zero bottles, announced the removal of the whole cellar, and - worst -
# overwrote the good cache with the empty payload, destroying the very thing the
# cache exists to protect. The cache is history, so it must count as history for
# validation as well as for the event.
# --------------------------------------------------------------------------
HEADER_ONLY = HEADER
TEN = "\n".join([HEADER, *(f"{n}\tWine {n}\t10.00\t2020\t2030" for n in range(1, 11))])


def events_of(coordinator: WineCellarData) -> list[dict]:
    return [
        d for name, d in coordinator.hass.bus.events if name == "cellartracker_inventory_changed"
    ]


def test_a_transiently_empty_first_response_does_not_publish_zero():
    coordinator = build(cached=LIVE, text=HEADER_ONLY)
    data = update(coordinator)
    assert data["total_bottles"] == 2, "an empty answer must not replace a stocked cellar"
    assert coordinator.serving_cached_data is True


def test_a_transiently_empty_first_response_does_not_overwrite_the_cache():
    coordinator = build(cached=LIVE, text=HEADER_ONLY)
    update(coordinator)
    assert stored(coordinator)["payload"] == LIVE
    assert coordinator.hass.storage_saves == 0


def test_a_transiently_empty_first_response_does_not_announce_the_cellar_gone():
    coordinator = build(cached=LIVE, text=HEADER_ONLY)
    update(coordinator)
    assert events_of(coordinator) == []


def test_a_repeated_empty_response_is_believed_after_a_restart():
    """The rule elsewhere: reject the first suspicious zero, believe a repeat.

    The cache parse that serves the first rejection must not reset the counter,
    or the repeat would be rejected again and again.
    """
    coordinator = build(cached=LIVE, text=HEADER_ONLY)
    coordinator.data = update(coordinator)  # first empty: rejected, cache served
    assert coordinator.data["total_bottles"] == 2

    coordinator.data = update(coordinator)  # second empty: the cellar really is empty
    assert coordinator.data["total_bottles"] == 0


def test_an_empty_first_response_with_no_cache_is_still_an_empty_cellar():
    coordinator = build(text=HEADER_ONLY)
    assert update(coordinator)["total_bottles"] == 0


def test_an_empty_first_response_against_an_empty_cache_is_accepted():
    coordinator = build(cached=HEADER_ONLY, text=HEADER_ONLY)
    assert update(coordinator)["total_bottles"] == 0
    assert events_of(coordinator) == []


def test_a_first_response_far_smaller_than_the_cache_is_flagged(caplog):
    """The truncation warning reads history too, so it needs the cache as well."""
    coordinator = build(cached=TEN, text="\n".join([HEADER, "1\tWine 1\t10.00\t2020\t2030"]))
    with caplog.at_level("WARNING"):
        data = update(coordinator)
    assert data["total_bottles"] == 1
    assert "dropped from 10 to 1" in caplog.text


def test_a_normal_first_response_is_unaffected_by_the_history():
    coordinator = build(cached=LIVE, text=LIVE)
    data = update(coordinator)
    assert data["total_bottles"] == 2
    assert coordinator.serving_cached_data is False


def test_the_history_parse_does_not_touch_the_suspicion_counter():
    """Serving the cache after an empty first poll must leave the count alone."""
    coordinator = build(cached=LIVE, text=HEADER_ONLY)
    update(coordinator)
    assert coordinator._suspicious_empty_polls == 1
