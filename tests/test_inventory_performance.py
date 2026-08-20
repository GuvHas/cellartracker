"""F-05: inventory parsing must be linear and must not block the event loop.

Two separate defects share this code path:

1. The duplicate-id resolver restarts its probe at 0 for every duplicate, so
   resolving a group of N identical bottles costs O(N^2). The id key is
   iWine + PurchaseDate + Barcode + Location + Bin - exactly the fields a case
   of 12 identical bottles shares - so duplicate groups are the normal case.

2. Only the HTTP call was handed to an executor; parsing ran on the event loop.

Measured on the pre-fix code: 500 bottles 12.6 ms, 1000 51.1 ms, 2000 198.7 ms,
4000 791.2 ms - a clean 4x per doubling.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass


def build_coordinator(*, returns=None) -> WineCellarData:
    entry = ConfigEntry(data={"username": "alice", "password": "secret"})
    coordinator = WineCellarData(FakeHass(), entry)

    class _Client:
        def get_inventory(self):
            return returns

    coordinator._client = _Client()
    return coordinator


def identical_bottles(count: int) -> list[dict]:
    """A case of the same wine: every id-relevant field matches."""
    return [
        {
            "iWine": "42",
            "PurchaseDate": "2024-01-01",
            "Barcode": "",
            "Location": "Rack",
            "Bin": "A",
            "Valuation": "50",
        }
        for _ in range(count)
    ]


def process(rows, previous=None):
    return build_coordinator()._process_inventory(rows, previous=previous)


def time_process(count: int) -> float:
    rows = identical_bottles(count)
    start = time.perf_counter()
    process(rows)
    return time.perf_counter() - start


# --------------------------------------------------------------------------
# Complexity
# --------------------------------------------------------------------------
def test_duplicate_resolution_scales_linearly():
    """Quadratic growth would make this ~16x, linear is ~4x."""
    time_process(200)  # warm up
    baseline = max(time_process(1000), 1e-6)
    scaled = time_process(4000)
    ratio = scaled / baseline
    assert ratio < 8, (
        f"4x the rows took {ratio:.1f}x longer, which indicates quadratic scaling"
    )


def test_a_large_cellar_parses_quickly():
    """Absolute bound; generous so it is not flaky on slow CI."""
    assert time_process(5000) < 1.0


# --------------------------------------------------------------------------
# The refactor must not change the ids it produces
# --------------------------------------------------------------------------
def test_duplicate_ids_are_dense_and_ordered():
    """Suffixes stay allocated as base, base_1, base_2 ... with no gaps."""
    result = process(identical_bottles(4))
    ids = [bottle["unique_bottle_id"] for bottle in result["bottles"]]
    base = ids[0]
    assert "_" not in base, "the first of a group keeps the bare hash"
    assert ids == [base, f"{base}_1", f"{base}_2", f"{base}_3"]


def test_distinct_bottles_keep_distinct_ids():
    rows = [
        {"iWine": "1", "Bin": "A", "Valuation": "10"},
        {"iWine": "2", "Bin": "B", "Valuation": "20"},
    ]
    ids = [b["unique_bottle_id"] for b in process(rows)["bottles"]]
    assert len(set(ids)) == 2
    assert all("_" not in bottle_id for bottle_id in ids)


def test_totals_are_unaffected_by_the_refactor():
    result = process(identical_bottles(12))
    assert result["total_bottles"] == 12
    assert result["total_value"] == 600.0


# --------------------------------------------------------------------------
# The event loop must stay free
# --------------------------------------------------------------------------
def test_parsing_is_handed_to_the_executor():
    coordinator = build_coordinator(returns=identical_bottles(10))
    asyncio.run(coordinator._async_update_data())
    assert "_process_inventory" in coordinator._hass.executor_jobs, (
        "parsing ran on the event loop; only get_inventory was offloaded"
    )


def test_update_still_returns_the_processed_result():
    """Offloading must not change what the coordinator returns."""
    coordinator = build_coordinator(returns=identical_bottles(3))
    result = asyncio.run(coordinator._async_update_data())
    assert result["total_bottles"] == 3
    assert result["total_value"] == 150.0


def test_errors_from_the_executor_still_propagate():
    """UpdateFailed raised inside the executor must reach the caller."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = build_coordinator(returns=[{"NotAWine": "x"}])
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
