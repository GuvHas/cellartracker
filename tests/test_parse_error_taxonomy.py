"""P1-1: parsing failures must go through the same error taxonomy as fetching.

``_async_update_data`` wraps the fetch in a careful try/except that classifies
every failure - auth, transport, timeout, unknown - and the block ends before
the parse. Anything the parser raises therefore escapes unclassified: the
coordinator's catch-all logs a full traceback under "Unexpected error", which
is the outcome the module's error handling exists to prevent.

This is reachable in production. ``csv`` enforces ``field_size_limit``, 131,072
characters by default, so one wine with a long enough tasting note raises
``_csv.Error: field larger than field limit`` and the user gets a stack trace
instead of an explanation.

The deliberate ``UpdateFailed`` raises inside ``_process_inventory`` must keep
their own messages - re-wrapping them would bury the reasoning they carry.
"""

from __future__ import annotations

import asyncio
import csv

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass, FakeSession

HEADER = "iWine\tWine\tValuation"
GOOD = "\n".join([HEADER, "1\tBarolo\t45.50", "2\tRioja\t22.00"])

# One field past csv's default limit: a plausible tasting note, not an attack.
OVERSIZED = "\n".join([HEADER, "1\t" + "x" * (csv.field_size_limit() + 1) + "\t10.00"])


def build(text: str) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(text=text)
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})
    return WineCellarData(hass, entry)


def test_an_oversized_field_is_reported_as_a_malformed_export():
    coordinator = build(OVERSIZED)

    with pytest.raises(UpdateFailed) as caught:
        asyncio.run(coordinator._async_update_data())

    assert "malformed" in str(caught.value).lower()


def test_the_underlying_csv_error_is_kept_as_the_cause():
    """Classified for the user, still diagnosable for us.

    Safe to chain here, unlike the transport errors of P0-3: a csv failure
    describes the payload's shape and never carries the request URL.
    """
    coordinator = build(OVERSIZED)

    with pytest.raises(UpdateFailed) as caught:
        asyncio.run(coordinator._async_update_data())

    assert isinstance(caught.value.__cause__, csv.Error)


def test_a_deliberate_update_failure_is_not_rewrapped():
    """_process_inventory's own reasons must survive verbatim."""
    coordinator = build("\n".join([HEADER, "1\tBarolo\t45.50"]))
    coordinator.data = asyncio.run(coordinator._async_update_data())
    assert coordinator.data["total_bottles"] == 1

    # An empty response after the cellar held stock: rejected on the first poll.
    coordinator._hass.session = FakeSession(text=HEADER)
    with pytest.raises(UpdateFailed) as caught:
        asyncio.run(coordinator._async_update_data())

    assert "upstream error" in str(caught.value)
    assert caught.value.__cause__ is None, "a deliberate raise must not be rewrapped"


def test_a_healthy_payload_is_unaffected():
    coordinator = build(GOOD)
    data = asyncio.run(coordinator._async_update_data())
    assert data["total_bottles"] == 2
    assert data["total_value"] == 67.50
