"""P1-3: a throttled cellar must back off rather than keep knocking.

HTTP 429 currently becomes ClientResponseError, then CannotConnect, then
UpdateFailed, and the coordinator simply tries again at the next interval. At
the six-hour default that is harmless. At the 900-second floor the options flow
allows, an integration that is being throttled keeps knocking every fifteen
minutes and tells the user nothing about why.

P0-3 already had to separate 429 from other transport failures to keep the
request URL out of the exception, so the status is available here for free.

Two rules the backoff must respect: never poll *sooner* than the user asked
for, and never let a server's Retry-After park the integration indefinitely.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import aiohttp
import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from yarl import URL

from cellar_tracker.cellar_data import MAX_BACKOFF, WineCellarData
from conftest import ConfigEntry, FakeHass, FakeSession

HEADER = "iWine\tWine\tValuation"
GOOD = "\n".join([HEADER, "1\tBarolo\t45.50"])
SCAN_INTERVAL = 900


def throttled(retry_after: str | None = None) -> aiohttp.ClientResponseError:
    url = URL("https://www.cellartracker.com/xlquery.asp?User=a&Password=b")
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return aiohttp.ClientResponseError(
        aiohttp.RequestInfo(url, "GET", (), url),
        (),
        status=429,
        message="Too Many Requests",
        headers=headers,
    )


def build(**session_kwargs) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(**session_kwargs)
    entry = ConfigEntry(
        data={"username": "alice", "password": "s3cret", "scan_interval": SCAN_INTERVAL}
    )
    return WineCellarData(hass, entry)


def refresh(coordinator) -> None:
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_retry_after_defers_the_next_poll():
    coordinator = build(raise_for_status=throttled("1800"))
    assert coordinator.update_interval == timedelta(seconds=SCAN_INTERVAL)

    refresh(coordinator)

    assert coordinator.update_interval == timedelta(seconds=1800)


def test_a_shorter_retry_after_never_polls_sooner_than_configured():
    """The server asking for 60s does not override the user's 900s."""
    coordinator = build(raise_for_status=throttled("60"))
    refresh(coordinator)
    assert coordinator.update_interval == timedelta(seconds=SCAN_INTERVAL)


def test_an_absurd_retry_after_is_capped():
    """A server must not be able to park the integration for a week."""
    coordinator = build(raise_for_status=throttled("604800"))
    refresh(coordinator)
    assert coordinator.update_interval == timedelta(seconds=MAX_BACKOFF)


@pytest.mark.parametrize("header", [None, "", "soon", "Wed, 21 Oct 2026 07:28:00 GMT"])
def test_an_unusable_retry_after_still_backs_off(header):
    """Missing or unparseable - including the HTTP-date form we do not read."""
    coordinator = build(raise_for_status=throttled(header))
    refresh(coordinator)
    assert coordinator.update_interval > timedelta(seconds=SCAN_INTERVAL)
    assert coordinator.update_interval <= timedelta(seconds=MAX_BACKOFF)


def test_the_interval_is_restored_after_a_successful_poll():
    coordinator = build(raise_for_status=throttled("1800"))
    refresh(coordinator)
    assert coordinator.update_interval == timedelta(seconds=1800)

    coordinator.hass.session = FakeSession(text=GOOD)
    asyncio.run(coordinator._async_update_data())

    assert coordinator.update_interval == timedelta(seconds=SCAN_INTERVAL)


def test_a_plain_connection_failure_does_not_change_the_interval():
    """Only throttling backs off; an unreachable host keeps its schedule."""
    coordinator = build(error=aiohttp.ClientConnectorError(None, OSError("refused")))
    refresh(coordinator)
    assert coordinator.update_interval == timedelta(seconds=SCAN_INTERVAL)


def test_throttling_is_logged_without_alarm(caplog):
    """A throttled cellar is normal operation, not a fault to warn about."""
    coordinator = build(raise_for_status=throttled("1800"))

    with caplog.at_level("INFO"):
        refresh(coordinator)

    assert "429" in caplog.text
    assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]


# --------------------------------------------------------------------------
# Reported by Codex on #18: the cap must never undercut the configured interval
# --------------------------------------------------------------------------
DAILY = 86400


def daily(**session_kwargs) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(**session_kwargs)
    entry = ConfigEntry(
        data={"username": "alice", "password": "s3cret", "scan_interval": DAILY}
    )
    return WineCellarData(hass, entry)


def test_a_daily_schedule_is_not_shortened_by_the_cap():
    """The options schema sets a floor, not a ceiling, so this is reachable.

    Capping at MAX_BACKOFF turned a 24-hour schedule into a six-hourly one
    *while being rate limited* - four times the requests, and the exact
    opposite of backing off.
    """
    coordinator = daily(raise_for_status=throttled("1800"))
    refresh(coordinator)
    assert coordinator.update_interval >= timedelta(seconds=DAILY)


def test_a_daily_schedule_with_no_retry_after_is_not_shortened():
    coordinator = daily(raise_for_status=throttled(None))
    refresh(coordinator)
    assert coordinator.update_interval >= timedelta(seconds=DAILY)


def test_a_server_still_cannot_extend_a_daily_schedule_without_bound():
    """The cap still applies on top of the configured interval, not under it."""
    coordinator = daily(raise_for_status=throttled("604800"))
    refresh(coordinator)
    assert coordinator.update_interval == timedelta(seconds=DAILY)
