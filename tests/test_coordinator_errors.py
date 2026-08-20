"""F-01: the coordinator must classify upstream failures by exception type.

``cellartracker`` raises ``AuthenticationError`` / ``CannotConnect`` with **no
message**, so classifying on ``str(err)`` never matches and auth failures never
reach ``ConfigEntryAuthFailed``.
"""

from __future__ import annotations

import asyncio

import pytest
from cellartracker.errors import AuthenticationError, CannotConnect
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass


def build_coordinator(*, raises=None, returns=None) -> WineCellarData:
    """Real coordinator with a stubbed CellarTracker client."""
    entry = ConfigEntry(data={"username": "alice", "password": "secret"})
    coordinator = WineCellarData(FakeHass(), entry)

    class _Client:
        def get_inventory(self):
            if raises is not None:
                raise raises
            return returns

    coordinator._client = _Client()
    return coordinator


def update(coordinator: WineCellarData):
    return asyncio.run(coordinator._async_update_data())


def test_authentication_error_raises_config_entry_auth_failed():
    """A bad password must trigger Home Assistant's reauth path."""
    with pytest.raises(ConfigEntryAuthFailed):
        update(build_coordinator(raises=AuthenticationError()))


def test_cannot_connect_raises_update_failed():
    """A network failure is transient - retry, do not ask for credentials."""
    with pytest.raises(UpdateFailed):
        update(build_coordinator(raises=CannotConnect()))


def test_parse_error_is_not_mistaken_for_an_auth_failure():
    """'invalid' appears in many non-auth messages; it must not force a reauth."""
    err = ValueError("invalid literal for int() with base 10: 'x'")
    with pytest.raises(UpdateFailed):
        update(build_coordinator(raises=err))


def test_successful_fetch_returns_processed_inventory():
    """The happy path must keep working."""
    rows = [{"iWine": "1", "Valuation": "12.50"}, {"iWine": "2", "Valuation": "7.50"}]
    result = update(build_coordinator(returns=rows))
    assert result["total_bottles"] == 2
    assert result["total_value"] == 20.0
