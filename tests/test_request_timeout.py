"""F-04: a hung request must not park an executor thread unbounded.

``cellartracker`` calls ``requests.get(url, params)`` with no ``timeout=``
(api.py:21), so the socket inherits the blocking default. A server that accepts
the connection and then never replies leaves the worker in ``recv()`` until TCP
keepalive gives up - ``tcp_keepalive_time`` is 7200s by default, so roughly two
hours per poll.

An ``asyncio.timeout`` bounds what Home Assistant sees, so the coordinator fails
cleanly and recovers on schedule instead of stalling. It cannot cancel the
thread itself; that needs ``timeout=`` upstream in the library.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from cellar_tracker import cellar_data
from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass

ROWS = [{"iWine": "1", "Valuation": "10"}]


class SlowHass(FakeHass):
    """Executor double whose jobs take `delay` seconds to complete."""

    def __init__(self, delay):
        super().__init__()
        self.delay = delay

    async def async_add_executor_job(self, func, *args):
        await asyncio.sleep(self.delay)
        return await super().async_add_executor_job(func, *args)


def build_coordinator(*, hass=None, returns=ROWS, raises=None) -> WineCellarData:
    entry = ConfigEntry(data={"username": "alice", "password": "secret"})
    coordinator = WineCellarData(hass or FakeHass(), entry)

    class _Client:
        def get_inventory(self):
            if raises is not None:
                raise raises
            return returns

    coordinator._client = _Client()
    return coordinator


def test_a_request_timeout_is_configured():
    assert 0 < cellar_data.REQUEST_TIMEOUT <= 300


def test_a_hanging_request_gives_up_instead_of_waiting(monkeypatch):
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 0.01)
    coordinator = build_coordinator(hass=SlowHass(delay=5))

    started = time.perf_counter()
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
    elapsed = time.perf_counter() - started

    assert elapsed < 2, f"waited {elapsed:.1f}s; the timeout did not apply"


def test_a_timeout_is_not_reported_as_bad_credentials(monkeypatch):
    """A slow network must never trigger a reauth prompt."""
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 0.01)
    coordinator = build_coordinator(hass=SlowHass(delay=5))

    try:
        asyncio.run(coordinator._async_update_data())
    except ConfigEntryAuthFailed:  # pragma: no cover - the failure we guard against
        pytest.fail("a timeout was misreported as an authentication failure")
    except UpdateFailed:
        pass


def test_a_prompt_request_is_unaffected(monkeypatch):
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 5)
    coordinator = build_coordinator()
    assert asyncio.run(coordinator._async_update_data())["total_bottles"] == 1


def test_an_explicit_timeout_error_becomes_update_failed():
    coordinator = build_coordinator(raises=TimeoutError())
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
