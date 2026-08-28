"""Single-account enforcement.

The integration supports exactly one CellarTracker account per installation.
Before this, ``async_set_unique_id`` was keyed on the *username*, so a second
entry for a different account was accepted - and everything downstream had to
carry multi-account machinery to cope with it.

The unique id is now the domain itself, which makes any second entry a
duplicate regardless of which account it names.
"""

from __future__ import annotations

import asyncio

import pytest

from cellar_tracker.config_flow import CellarTrackerConfigFlow
from cellar_tracker.const import DOMAIN
from conftest import ConfigEntry, FakeHass, FakeSession

ROWS = "iWine\tValuation\n1\t12.50"

USER_INPUT = {
    "username": "alice",
    "password": "secret",
    "scan_interval": 21600,
    "currency": "USD",
}


def build_flow(existing=(), **session_kwargs):
    flow = CellarTrackerConfigFlow()
    flow.hass = FakeHass()
    flow.hass.session = FakeSession(**(session_kwargs or {"text": ROWS}))
    flow._existing_entries = list(existing)
    return flow


def run_user_step(flow, user_input=None):
    return asyncio.run(flow.async_step_user(dict(user_input or USER_INPUT)))


# --------------------------------------------------------------------------
# The first account still sets up normally
# --------------------------------------------------------------------------
def test_the_first_account_is_accepted():
    flow = build_flow()
    result = run_user_step(flow)
    assert result["type"] == "create_entry"
    assert result["data"]["username"] == "alice"


def test_the_unique_id_is_the_domain_not_the_username():
    """Keying on the username let a second, different account through."""
    flow = build_flow()
    run_user_step(flow)
    assert flow.unique_id == DOMAIN
    assert flow.unique_id != "alice"


# --------------------------------------------------------------------------
# A second account is refused, whoever it belongs to
# --------------------------------------------------------------------------
def test_a_second_account_is_refused():
    existing = ConfigEntry(entry_id="a", title="alice")
    existing.unique_id = DOMAIN
    flow = build_flow([existing])

    result = run_user_step(flow, {**USER_INPUT, "username": "bob"})
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


def test_the_same_account_twice_is_refused():
    existing = ConfigEntry(entry_id="a", title="alice")
    existing.unique_id = DOMAIN
    flow = build_flow([existing])

    result = run_user_step(flow)
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


def test_a_legacy_entry_keyed_on_the_username_still_blocks():
    """Installs predating this have unique_id == the username, not the domain."""
    legacy = ConfigEntry(entry_id="a", title="alice")
    legacy.unique_id = "alice"
    flow = build_flow([legacy])

    result = run_user_step(flow, {**USER_INPUT, "username": "bob"})
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


def test_the_refusal_happens_before_any_network_call():
    """Rejecting a duplicate must not hit CellarTracker to validate it."""
    existing = ConfigEntry(entry_id="a")
    existing.unique_id = DOMAIN
    flow = build_flow([existing])

    result = run_user_step(flow)
    assert result["reason"] == "single_instance_allowed"
    assert flow.hass.session.requests == [], "a duplicate must not be validated upstream"


# --------------------------------------------------------------------------
# The abort reason must be translated, or the user sees a raw key
# --------------------------------------------------------------------------
def test_the_abort_reason_is_translated():
    import json
    import pathlib

    strings = json.loads(
        (
            pathlib.Path(__file__).resolve().parent.parent
            / "custom_components" / "cellar_tracker" / "strings.json"
        ).read_text()
    )
    assert "single_instance_allowed" in strings["config"]["abort"]


# --------------------------------------------------------------------------
# Reauth must keep working - it targets the one existing entry
# --------------------------------------------------------------------------
def test_reauth_is_not_blocked_by_the_single_instance_guard():
    entry = ConfigEntry(entry_id="a", data={"username": "alice", "password": "old"})
    entry.unique_id = DOMAIN

    flow = CellarTrackerConfigFlow()
    flow.hass = FakeHass({entry.entry_id: entry})
    flow._existing_entries = [entry]
    flow.context = {"source": "reauth", "entry_id": entry.entry_id}

    flow.hass.session = FakeSession(text=ROWS)
    result = asyncio.run(flow.async_step_reauth_confirm({"password": "new-pw"}))

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-pw"


@pytest.mark.parametrize("step", ["async_step_user", "async_step_reauth_confirm"])
def test_flow_steps_are_still_coroutines(step):
    assert asyncio.iscoroutinefunction(getattr(CellarTrackerConfigFlow, step))
