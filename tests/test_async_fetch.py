"""The inventory fetch is non-blocking.

The upstream library calls ``requests.get(url, params)`` with no ``timeout=``,
so the socket has no deadline. ``asyncio.timeout`` around an executor job bounds
what Home Assistant waits for, but ``concurrent.futures`` cannot interrupt a
thread that is already running: the worker stays parked in ``recv()`` until the
OS gives up, which for a server that accepts and never replies means the TCP
keepalive interval (7200s by default).

The fetch now uses Home Assistant's shared aiohttp session, so the timeout
genuinely cancels and no thread is involved at all. The library is still the
source of the endpoint URL, the not-logged-in marker, and the exception types.
"""

from __future__ import annotations

import asyncio
import time

import aiohttp
import pytest
from cellartracker.const import BASE_URL, NOT_LOGGED_REPONSE
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from cellar_tracker import cellar_data
from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass, FakeSession

HEADER = "iWine\tWine\tVintage\tValuation\tLocation\tBin\tBeginConsume\tEndConsume"
TWO_BOTTLES = "\n".join(
    [
        HEADER,
        "1\tBarolo\t2016\t45.50\tRack\tA\t2022\t2035",
        "2\tRioja\t2018\t22.00\tRack\tB\t2021\t2030",
    ]
)


def build(**session_kwargs) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(**session_kwargs)
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret", "currency": "USD"})
    return WineCellarData(hass, entry)


def update(coordinator):
    return asyncio.run(coordinator._async_update_data())


# --------------------------------------------------------------------------
# No executor thread is used for the HTTP call
# --------------------------------------------------------------------------
def test_the_http_call_does_not_go_through_an_executor():
    coordinator = build(text=TWO_BOTTLES)
    update(coordinator)
    assert "get_inventory" not in coordinator._hass.executor_jobs, (
        "the blocking client is still being used"
    )


def test_parsing_still_runs_in_the_executor():
    """CPU-bound work stays off the event loop even though I/O no longer needs it."""
    coordinator = build(text=TWO_BOTTLES)
    update(coordinator)
    assert coordinator._hass.executor_jobs == ["_parse_and_process"], (
        "parsing must be the only executor job, and must still be one"
    )


# --------------------------------------------------------------------------
# The request itself
# --------------------------------------------------------------------------
def test_the_request_targets_the_library_endpoint():
    coordinator = build(text=TWO_BOTTLES)
    update(coordinator)
    assert coordinator._hass.session.requests[0]["url"] == BASE_URL


def test_the_request_carries_the_expected_query():
    coordinator = build(text=TWO_BOTTLES)
    update(coordinator)
    params = coordinator._hass.session.requests[0]["params"]
    assert params["User"] == "alice"
    assert params["Password"] == "s3cret"
    assert params["Table"] == "Inventory"
    assert params["Format"] == "tab", "the export is tab-separated, not XML"


def test_a_valid_payload_is_parsed():
    result = update(build(text=TWO_BOTTLES))
    assert result["total_bottles"] == 2
    assert result["total_value"] == 67.5


def test_an_empty_cellar_parses_to_zero():
    result = update(build(text=HEADER))
    assert result["total_bottles"] == 0
    assert result["total_value"] == 0.0


# --------------------------------------------------------------------------
# Failure modes must map to the same exceptions as before
# --------------------------------------------------------------------------
def test_the_not_logged_in_marker_is_an_auth_failure():
    """CellarTracker answers 200 with a marker in the body, not a 401."""
    coordinator = build(text=f"<html>{NOT_LOGGED_REPONSE}</html>")
    with pytest.raises(ConfigEntryAuthFailed):
        update(coordinator)


def test_a_client_error_becomes_update_failed():
    coordinator = build(error=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(UpdateFailed):
        update(coordinator)


def test_an_http_error_status_becomes_update_failed():
    coordinator = build(
        raise_for_status=aiohttp.ClientResponseError(None, None, status=503)
    )
    with pytest.raises(UpdateFailed):
        update(coordinator)


def test_an_error_page_is_still_rejected():
    """A 200 that is not inventory data must not publish as zero bottles."""
    coordinator = build(text="<html><title>503</title></html>\n<body>down</body>")
    coordinator.data = {"total_bottles": 12, "total_value": 100.0, "bottles": []}
    with pytest.raises(UpdateFailed):
        update(coordinator)


# --------------------------------------------------------------------------
# The timeout must actually cancel, not just stop waiting
# --------------------------------------------------------------------------
def test_a_slow_response_times_out(monkeypatch):
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 0.05)
    coordinator = build(text=TWO_BOTTLES, delay=5)

    started = time.perf_counter()
    with pytest.raises(UpdateFailed):
        update(coordinator)
    elapsed = time.perf_counter() - started

    assert elapsed < 2, f"waited {elapsed:.1f}s; the timeout did not cancel the request"


def test_a_timeout_is_not_reported_as_bad_credentials(monkeypatch):
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 0.05)
    coordinator = build(text=TWO_BOTTLES, delay=5)
    with pytest.raises(UpdateFailed):
        update(coordinator)


def test_the_timeout_is_still_configured():
    assert 0 < cellar_data.REQUEST_TIMEOUT <= 300
