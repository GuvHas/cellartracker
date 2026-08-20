"""F-01 (setup side) + F-02: reauth support.

F-01: a wrong password during setup must report ``invalid_auth``, not ``unknown``.
F-02: raising ``ConfigEntryAuthFailed`` makes Home Assistant call
``async_step_reauth``. Without that step the flow raises ``UnknownStep`` and the
UI shows "Config flow could not be loaded: 500 Internal Server Error".
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from cellartracker.errors import AuthenticationError, CannotConnect

from cellar_tracker.config_flow import CellarTrackerConfigFlow
from conftest import ConfigEntry, FakeHass

GET_INVENTORY = "cellartracker.cellartracker.CellarTracker.get_inventory"

USER_INPUT = {
    "username": "alice",
    "password": "secret",
    "scan_interval": 21600,
    "currency": "USD",
}


def build_flow(entry: ConfigEntry | None = None) -> CellarTrackerConfigFlow:
    entries = {entry.entry_id: entry} if entry else {}
    flow = CellarTrackerConfigFlow()
    flow.hass = FakeHass(entries)
    if entry:
        flow.context = {"source": "reauth", "entry_id": entry.entry_id}
    return flow


# --------------------------------------------------------------------------
# F-01: initial setup must distinguish auth failures from everything else
# --------------------------------------------------------------------------
def test_wrong_password_reports_invalid_auth():
    flow = build_flow()
    with patch(GET_INVENTORY, side_effect=AuthenticationError()):
        result = asyncio.run(flow.async_step_user(dict(USER_INPUT)))
    assert result["errors"] == {"base": "invalid_auth"}


def test_network_failure_reports_cannot_connect():
    flow = build_flow()
    with patch(GET_INVENTORY, side_effect=CannotConnect()):
        result = asyncio.run(flow.async_step_user(dict(USER_INPUT)))
    assert result["errors"] == {"base": "cannot_connect"}


def test_unexpected_error_reports_unknown():
    flow = build_flow()
    with patch(GET_INVENTORY, side_effect=RuntimeError("boom")):
        result = asyncio.run(flow.async_step_user(dict(USER_INPUT)))
    assert result["errors"] == {"base": "unknown"}


def test_valid_credentials_create_the_entry():
    flow = build_flow()
    with patch(GET_INVENTORY, return_value=[]):
        result = asyncio.run(flow.async_step_user(dict(USER_INPUT)))
    assert result["type"] == "create_entry"
    assert result["data"]["username"] == "alice"


# --------------------------------------------------------------------------
# F-02: reauth
# --------------------------------------------------------------------------
def test_reauth_step_exists():
    """Without this, ConfigEntryAuthFailed produces UnknownStep -> HTTP 500."""
    assert hasattr(CellarTrackerConfigFlow, "async_step_reauth")


def test_reauth_shows_a_password_form():
    entry = ConfigEntry(data={"username": "alice", "password": "old"})
    flow = build_flow(entry)
    result = asyncio.run(flow.async_step_reauth(entry.data))
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"


def test_reauth_with_a_valid_password_updates_the_entry():
    entry = ConfigEntry(data={"username": "alice", "password": "old"})
    flow = build_flow(entry)
    with patch(GET_INVENTORY, return_value=[]):
        result = asyncio.run(flow.async_step_reauth_confirm({"password": "new-pw"}))
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-pw"
    assert entry.data["username"] == "alice", "username must be preserved"


def test_reauth_with_a_still_wrong_password_re_prompts():
    entry = ConfigEntry(data={"username": "alice", "password": "old"})
    flow = build_flow(entry)
    with patch(GET_INVENTORY, side_effect=AuthenticationError()):
        result = asyncio.run(flow.async_step_reauth_confirm({"password": "nope"}))
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data["password"] == "old", "entry must not be updated on failure"


def test_reauth_validates_against_the_stored_username():
    """Reauth only asks for a password; the username comes from the entry."""
    entry = ConfigEntry(data={"username": "alice", "password": "old"})
    flow = build_flow(entry)
    seen = {}

    def _capture(self):
        seen["user"] = self.client._username
        return []

    with patch(GET_INVENTORY, autospec=True, side_effect=_capture):
        asyncio.run(flow.async_step_reauth_confirm({"password": "new-pw"}))
    assert seen["user"] == "alice"


@pytest.mark.parametrize("step", ["async_step_reauth", "async_step_reauth_confirm"])
def test_reauth_steps_are_coroutines(step):
    assert asyncio.iscoroutinefunction(getattr(CellarTrackerConfigFlow, step))
