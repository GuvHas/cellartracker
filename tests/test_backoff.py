"""Adaptive backoff: exponential growth with jitter, for 429 and 5xx.

Extends the 429 handling that already existed. Three rules carry over from it
unchanged, because tests/test_rate_limit.py pins them:

- never poll *sooner* than the user configured;
- never let a server's Retry-After park the integration indefinitely;
- honour a Retry-After exactly - the server said when, so it is not jittered.

What is new: consecutive failures without a hint grow the delay
exponentially rather than repeating one fixed doubling; that computed delay
carries jitter, so a fleet of installs throttled together does not come back
together; and 5xx joins 429, because a struggling server wants the same
treatment as a throttling one. Recovery restores the configured interval and
forgets the streak.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import aiohttp
import pytest
from cellartracker.errors import CannotConnect
from homeassistant.helpers.update_coordinator import UpdateFailed
from yarl import URL

from cellar_tracker import cellar_data
from cellar_tracker.cellar_data import (
    MAX_BACKOFF,
    RateLimited,
    ServerError,
    UpstreamBackoff,
    WineCellarData,
)
from conftest import ConfigEntry, FakeHass, FakeSession

GOOD = "iWine\tWine\tValuation\n1\tBarolo\t45.50"
CONFIGURED = 900


def failing(status: int, retry_after: str | None = None) -> aiohttp.ClientResponseError:
    url = URL("https://www.cellartracker.com/xlquery.asp?User=a&Password=b")
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return aiohttp.ClientResponseError(
        aiohttp.RequestInfo(url, "GET", (), url),
        (),
        status=status,
        message="upstream",
        headers=headers,
    )


def build(scan_interval: int = CONFIGURED, **session_kwargs) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(**session_kwargs)
    entry = ConfigEntry(
        data={"username": "alice", "password": "s3cret", "scan_interval": scan_interval}
    )
    return WineCellarData(hass, entry)


def fail_once(coordinator: WineCellarData, status: int, retry_after: str | None = None) -> None:
    coordinator.hass.session = FakeSession(raise_for_status=failing(status, retry_after))
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def succeed(coordinator: WineCellarData) -> None:
    coordinator.hass.session = FakeSession(text=GOOD)
    # Home Assistant assigns the result to .data after a successful refresh;
    # calling _async_update_data directly skips that, and without it the next
    # failure would look like a first poll and be answered from the cache.
    coordinator.data = asyncio.run(coordinator._async_update_data())


@pytest.fixture
def no_jitter(monkeypatch):
    """Make the computed delay exact so growth can be asserted precisely."""
    monkeypatch.setattr(cellar_data, "_jittered", lambda seconds: seconds)


def seconds(coordinator: WineCellarData) -> int:
    assert coordinator.update_interval is not None
    return int(coordinator.update_interval.total_seconds())


# --------------------------------------------------------------------------
# 5xx joins 429
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_a_server_error_backs_off(status):
    coordinator = build()
    fail_once(coordinator, status)
    assert coordinator.update_interval > timedelta(seconds=CONFIGURED)
    assert coordinator.update_interval <= timedelta(seconds=MAX_BACKOFF)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 418])
def test_a_client_error_is_not_a_reason_to_back_off(status):
    """Only throttling and server trouble are load signals. A 404 is not."""
    coordinator = build()
    fail_once(coordinator, status)
    assert coordinator.update_interval == timedelta(seconds=CONFIGURED)


def test_retry_after_is_honoured_on_a_server_error():
    coordinator = build()
    fail_once(coordinator, 503, "1800")
    assert coordinator.update_interval == timedelta(seconds=1800)


def test_the_two_causes_share_a_base_and_stay_connection_errors():
    """Existing callers classify on CannotConnect and must not need to know."""
    assert issubclass(RateLimited, UpstreamBackoff)
    assert issubclass(ServerError, UpstreamBackoff)
    assert issubclass(UpstreamBackoff, CannotConnect)


def test_the_status_is_named_in_the_failure_without_the_url(caplog):
    coordinator = build()
    with caplog.at_level("INFO"):
        fail_once(coordinator, 503)
    assert "503" in caplog.text
    assert "Password" not in caplog.text and "s3cret" not in caplog.text


def test_backing_off_is_logged_without_alarm(caplog):
    coordinator = build()
    with caplog.at_level("INFO"):
        fail_once(coordinator, 503)
    assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]


# --------------------------------------------------------------------------
# Exponential growth
# --------------------------------------------------------------------------
def test_consecutive_failures_grow_exponentially_to_the_cap(no_jitter):
    coordinator = build()
    seen = []
    for _ in range(7):
        fail_once(coordinator, 503)
        seen.append(seconds(coordinator))
    assert seen == [1800, 3600, 7200, 14400, MAX_BACKOFF, MAX_BACKOFF, MAX_BACKOFF]


def test_growth_mixes_throttling_and_server_errors(no_jitter):
    """One streak, whichever way the upstream is unhappy."""
    coordinator = build()
    fail_once(coordinator, 429)
    fail_once(coordinator, 503)
    fail_once(coordinator, 429)
    assert seconds(coordinator) == 7200


def test_a_retry_after_does_not_grow_with_the_streak(no_jitter):
    """The server said when; that is not ours to multiply."""
    coordinator = build()
    for _ in range(4):
        fail_once(coordinator, 503, "1800")
    assert seconds(coordinator) == 1800


def test_growth_never_drops_below_the_configured_interval(no_jitter):
    coordinator = build(scan_interval=86400)
    fail_once(coordinator, 503)
    assert seconds(coordinator) >= 86400


# --------------------------------------------------------------------------
# Jitter
# --------------------------------------------------------------------------
def test_computed_delays_are_jittered_within_bounds():
    samples = []
    for _ in range(60):
        coordinator = build()
        fail_once(coordinator, 503)
        samples.append(seconds(coordinator))
    assert min(samples) >= 1800 * 0.75 - 1
    assert max(samples) <= 1800
    assert len(set(samples)) > 1, "identical delays: jitter is not being applied"


def test_jitter_never_undercuts_the_configured_interval():
    for _ in range(40):
        coordinator = build(scan_interval=86400)
        fail_once(coordinator, 503)
        assert seconds(coordinator) >= 86400


def test_a_server_supplied_retry_after_is_never_jittered():
    delays = set()
    for _ in range(20):
        coordinator = build()
        fail_once(coordinator, 503, "1800")
        delays.add(seconds(coordinator))
    assert delays == {1800}


def test_jittered_helper_stays_within_its_range():
    for _ in range(200):
        assert 750 <= cellar_data._jittered(1000) <= 1000


# --------------------------------------------------------------------------
# Recovery
# --------------------------------------------------------------------------
def test_success_restores_the_configured_interval(no_jitter):
    coordinator = build()
    for _ in range(3):
        fail_once(coordinator, 503)
    assert seconds(coordinator) > CONFIGURED

    succeed(coordinator)

    assert coordinator.update_interval == timedelta(seconds=CONFIGURED)


def test_success_forgets_the_streak(no_jitter):
    """After recovering, the next failure starts from the bottom again."""
    coordinator = build()
    for _ in range(4):
        fail_once(coordinator, 503)
    succeed(coordinator)

    fail_once(coordinator, 503)

    assert seconds(coordinator) == 1800


def test_recovery_is_logged_once(caplog):
    coordinator = build()
    fail_once(coordinator, 503)
    with caplog.at_level("INFO"):
        succeed(coordinator)
        succeed(coordinator)
    assert caplog.text.count("responding again") == 1


def test_backoff_state_is_exposed_for_diagnostics(no_jitter):
    coordinator = build()
    assert coordinator.consecutive_backoffs == 0
    fail_once(coordinator, 503)
    fail_once(coordinator, 503)
    assert coordinator.consecutive_backoffs == 2
    succeed(coordinator)
    assert coordinator.consecutive_backoffs == 0


# --------------------------------------------------------------------------
# What must not change
# --------------------------------------------------------------------------
def test_a_plain_connection_failure_still_keeps_its_schedule():
    coordinator = build(error=aiohttp.ClientConnectorError(None, OSError("refused")))
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval == timedelta(seconds=CONFIGURED)


def test_a_timeout_still_keeps_its_schedule(monkeypatch):
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 0.05)
    coordinator = build(text=GOOD, delay=5)
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval == timedelta(seconds=CONFIGURED)


# --------------------------------------------------------------------------
# A failure that is not a slow-down request ends the streak
#
# Reported by Codex on #23. The interval and the streak were only cleared by a
# fully successful poll, so a 429 followed by a timeout, an ordinary 4xx, an
# auth failure or a malformed response left the stale slowed schedule in place,
# and a later 429 was wrongly counted as consecutive. Being asked to slow down
# is a statement about the upstream's load; the next poll that is not that
# statement ends the episode, whatever else went wrong with it.
# --------------------------------------------------------------------------
from cellartracker.const import NOT_LOGGED_REPONSE  # noqa: E402
from homeassistant.exceptions import ConfigEntryAuthFailed  # noqa: E402

OTHER_FAILURES = [
    pytest.param({"error": aiohttp.ClientConnectionError("boom")}, id="connection-error"),
    pytest.param({"raise_for_status": failing(404)}, id="not-found"),
    pytest.param({"raise_for_status": failing(403)}, id="forbidden"),
    pytest.param({"text": "<html>x</html>\n<p>not inventory</p>"}, id="malformed-200"),
    pytest.param({"text": f"<html>{NOT_LOGGED_REPONSE}</html>"}, id="auth-failure"),
]


def fail_otherwise(coordinator: WineCellarData, **session) -> None:
    coordinator.hass.session = FakeSession(**session)
    with pytest.raises((UpdateFailed, ConfigEntryAuthFailed)):
        asyncio.run(coordinator._async_update_data())


@pytest.mark.parametrize("session", OTHER_FAILURES)
def test_another_kind_of_failure_restores_the_configured_interval(session, no_jitter):
    coordinator = build()
    fail_once(coordinator, 503)
    assert seconds(coordinator) > CONFIGURED

    fail_otherwise(coordinator, **session)

    assert coordinator.update_interval == timedelta(seconds=CONFIGURED)


@pytest.mark.parametrize("session", OTHER_FAILURES)
def test_another_kind_of_failure_ends_the_streak(session, no_jitter):
    coordinator = build()
    fail_once(coordinator, 503)
    fail_once(coordinator, 503)
    assert coordinator.consecutive_backoffs == 2

    fail_otherwise(coordinator, **session)

    assert coordinator.consecutive_backoffs == 0


@pytest.mark.parametrize("session", OTHER_FAILURES)
def test_a_slow_down_after_another_failure_starts_from_the_bottom(session, no_jitter):
    """The reported symptom: the later 429/5xx was treated as consecutive."""
    coordinator = build()
    fail_once(coordinator, 503)
    fail_once(coordinator, 503)
    assert seconds(coordinator) == 3600

    fail_otherwise(coordinator, **session)
    fail_once(coordinator, 503)

    assert seconds(coordinator) == 1800


def test_a_timeout_also_ends_the_streak(monkeypatch, no_jitter):
    coordinator = build()
    fail_once(coordinator, 503)
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 0.05)
    fail_otherwise(coordinator, text=GOOD, delay=5)
    assert coordinator.consecutive_backoffs == 0
    assert coordinator.update_interval == timedelta(seconds=CONFIGURED)


def test_consecutive_slow_downs_still_grow_when_nothing_intervenes(no_jitter):
    """The control: a real streak must not be broken by this change."""
    coordinator = build()
    fail_once(coordinator, 503)
    fail_once(coordinator, 429)
    fail_once(coordinator, 503)
    assert seconds(coordinator) == 7200
    assert coordinator.consecutive_backoffs == 3


def test_ending_a_backoff_by_another_failure_says_so_quietly(caplog, no_jitter):
    coordinator = build()
    fail_once(coordinator, 503)
    with caplog.at_level("INFO"):
        fail_otherwise(coordinator, error=aiohttp.ClientConnectionError("boom"))
    assert "backoff has ended" in caplog.text


def test_another_failure_with_no_backoff_in_progress_says_nothing_new(caplog):
    coordinator = build()
    with caplog.at_level("INFO"):
        fail_otherwise(coordinator, error=aiohttp.ClientConnectionError("boom"))
    assert "backoff has ended" not in caplog.text


def test_a_parse_failure_after_a_backoff_counts_as_the_server_answering(no_jitter):
    """A 200 with garbage is not throttling: the upstream responded."""
    coordinator = build()
    fail_once(coordinator, 503)
    fail_otherwise(coordinator, text="<html>maintenance</html>\n<p>back soon</p>")
    assert coordinator.update_interval == timedelta(seconds=CONFIGURED)
