"""Credential validation uses the same non-blocking transport as the coordinator.

The coordinator moved to aiohttp, but the config flow was still validating via
``cellartracker.CellarTracker(...).get_inventory()`` on an executor thread. That
is the same no-timeout ``requests.get()`` the coordinator was moved off: setup
and reauth could still park a worker for the TCP keepalive interval, holding the
password the user had just typed.

Both paths now share one fetch.
"""

from __future__ import annotations

import asyncio
import inspect
import time

import aiohttp
import pytest
from cellartracker.const import NOT_LOGGED_REPONSE

from cellar_tracker import cellar_data, config_flow
from cellar_tracker.config_flow import CellarTrackerConfigFlow
from conftest import ConfigEntry, FakeHass, FakeSession

ROWS = "iWine\tValuation\n1\t12.50"

USER_INPUT = {
    "username": "alice",
    "password": "s3cret",
    "scan_interval": 21600,
    "currency": "USD",
}


def build_flow(**session_kwargs):
    flow = CellarTrackerConfigFlow()
    flow.hass = FakeHass()
    flow.hass.session = FakeSession(**session_kwargs)
    flow._existing_entries = []
    return flow


def run_user_step(flow):
    return asyncio.run(flow.async_step_user(dict(USER_INPUT)))


# --------------------------------------------------------------------------
# The blocking client is gone from this module entirely
# --------------------------------------------------------------------------
def test_the_config_flow_no_longer_imports_the_blocking_client():
    source = inspect.getsource(config_flow)
    assert "get_inventory" not in source, (
        "credential validation still uses the library's requests-based client"
    )


def test_validation_does_not_use_an_executor():
    flow = build_flow(text=ROWS)
    run_user_step(flow)
    assert flow.hass.executor_jobs == [], "validation still runs on a worker thread"


def test_validation_shares_the_coordinator_fetch():
    """One implementation, so the two paths cannot drift apart."""
    assert hasattr(cellar_data, "async_fetch_inventory_payload")


# --------------------------------------------------------------------------
# The request, and the outcomes it maps to
# --------------------------------------------------------------------------
def test_valid_credentials_create_the_entry():
    flow = build_flow(text=ROWS)
    result = run_user_step(flow)
    assert result["type"] == "create_entry"
    assert flow.hass.session.requests[0]["params"]["User"] == "alice"


def test_the_not_logged_in_marker_is_invalid_auth():
    flow = build_flow(text=f"<html>{NOT_LOGGED_REPONSE}</html>")
    assert run_user_step(flow)["errors"] == {"base": "invalid_auth"}


def test_a_client_error_is_cannot_connect():
    flow = build_flow(error=aiohttp.ClientConnectionError("boom"))
    assert run_user_step(flow)["errors"] == {"base": "cannot_connect"}


def test_an_http_error_status_is_cannot_connect():
    flow = build_flow(raise_for_status=aiohttp.ClientResponseError(None, None, status=503))
    assert run_user_step(flow)["errors"] == {"base": "cannot_connect"}


# --------------------------------------------------------------------------
# A hung server must not stall setup
# --------------------------------------------------------------------------
def test_a_slow_server_times_out_rather_than_hanging(monkeypatch):
    monkeypatch.setattr(cellar_data, "REQUEST_TIMEOUT", 0.05)
    flow = build_flow(text=ROWS, delay=5)

    started = time.perf_counter()
    result = run_user_step(flow)
    elapsed = time.perf_counter() - started

    assert elapsed < 2, f"setup blocked for {elapsed:.1f}s"
    assert result["errors"] == {"base": "cannot_connect"}


# --------------------------------------------------------------------------
# Reauth goes through the same path
# --------------------------------------------------------------------------
def test_reauth_validates_without_an_executor():
    entry = ConfigEntry(entry_id="a", data={"username": "alice", "password": "old"})
    flow = CellarTrackerConfigFlow()
    flow.hass = FakeHass({entry.entry_id: entry})
    flow.hass.session = FakeSession(text=ROWS)
    flow.context = {"source": "reauth", "entry_id": entry.entry_id}

    result = asyncio.run(flow.async_step_reauth_confirm({"password": "new-pw"}))

    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-pw"
    assert flow.hass.executor_jobs == []


def test_reauth_validates_against_the_stored_username():
    entry = ConfigEntry(entry_id="a", data={"username": "alice", "password": "old"})
    flow = CellarTrackerConfigFlow()
    flow.hass = FakeHass({entry.entry_id: entry})
    flow.hass.session = FakeSession(text=ROWS)
    flow.context = {"source": "reauth", "entry_id": entry.entry_id}

    asyncio.run(flow.async_step_reauth_confirm({"password": "new-pw"}))

    params = flow.hass.session.requests[0]["params"]
    assert params["User"] == "alice"
    assert params["Password"] == "new-pw"


@pytest.mark.parametrize("step", ["async_step_user", "async_step_reauth_confirm"])
def test_flow_steps_are_coroutines(step):
    assert asyncio.iscoroutinefunction(getattr(CellarTrackerConfigFlow, step))
