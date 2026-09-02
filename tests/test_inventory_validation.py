"""F-03: upstream garbage must not be published as a real zero reading.

``cellartracker`` feeds *any* response body to ``csv.DictReader``. A maintenance
or Cloudflare page therefore parses into rows that carry no ``iWine`` column,
every row is skipped, and the coordinator reports 0 bottles / 0.00 value as if
that were a genuine reading.

Because ``TotalValueSensor`` is a ``state_class = TOTAL`` monetary sensor, that
zero is written into Home Assistant's *long-term statistics* - a permanent notch
in the recorded cellar value, not a transient blip.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from cellartracker.cellartracker import _parse_data
from homeassistant.helpers.update_coordinator import UpdateFailed

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass

MULTILINE_ERROR_PAGE = (
    "<html><head><title>503 Service Unavailable</title></head>\n"
    "<body>Origin unreachable</body></html>"
)
SINGLE_LINE_ERROR_PAGE = "<html><title>503 Service Unavailable</title></html>"

STOCKED = {"total_bottles": 412, "total_value": 9000.0, "bottles": []}
def inventory_of(data: dict) -> dict:
    """The payload without the poll timestamp.

    Every successful poll carries ``last_success`` so the coordinator's payload
    comparison always differs; these tests are about the inventory it describes.
    """
    return {key: value for key, value in data.items() if key != "last_success"}


EMPTY = {
    "total_bottles": 0,
    "total_value": 0.0,
    "bottles": [],
    # An empty cellar has nothing ready and nothing overdue; the counters are
    # present rather than absent so consumers never have to guess.
    "ready_to_drink": 0,
    "past_drink_window": 0,
}

REAL_ROWS = [
    {"iWine": "1", "Valuation": "12.50"},
    {"iWine": "2", "Valuation": "7.50"},
]


def build_coordinator(*, raises=None, returns=None, previous=None) -> WineCellarData:
    entry = ConfigEntry(data={"username": "alice", "password": "secret"})
    coordinator = WineCellarData(FakeHass(), entry)

    class _Client:
        def get_inventory(self):
            if raises is not None:
                raise raises
            return returns

    coordinator._client = _Client()
    coordinator.data = previous
    return coordinator


def process(rows, previous=None):
    coordinator = build_coordinator()
    return coordinator._process_inventory(rows, previous=previous)


# --------------------------------------------------------------------------
# Rows that parsed but are not inventory
# --------------------------------------------------------------------------
def test_html_error_page_is_rejected():
    """A multi-line error page yields rows with no 'iWine' column."""
    rows = _parse_data(MULTILINE_ERROR_PAGE)
    assert rows, "precondition: the page must parse into at least one row"
    with pytest.raises(UpdateFailed):
        process(rows)


def test_schema_change_dropping_iwine_is_rejected():
    """If upstream renames the key column, that is an error, not an empty cellar."""
    rows = [{"WineId": "1", "Valuation": "12.50"}]
    with pytest.raises(UpdateFailed):
        process(rows)


# --------------------------------------------------------------------------
# Zero rows: ambiguous without history
# --------------------------------------------------------------------------
def test_single_line_error_page_parses_to_nothing():
    """Documents why the history guard below is necessary."""
    assert _parse_data(SINGLE_LINE_ERROR_PAGE) == []


def test_zero_rows_after_a_stocked_cellar_is_rejected():
    """A stocked cellar does not empty itself between polls."""
    with pytest.raises(UpdateFailed):
        process([], previous=STOCKED)


def test_zero_rows_with_no_history_is_an_empty_cellar():
    """First poll of a genuinely empty account must succeed, not error."""
    assert process([], previous=None) == EMPTY


def test_empty_cellar_stays_empty_across_polls():
    """An account that was empty and is still empty must not raise."""
    assert process([], previous=EMPTY) == EMPTY


# --------------------------------------------------------------------------
# Valid data must keep working
# --------------------------------------------------------------------------
def test_valid_inventory_is_processed():
    result = process(REAL_ROWS)
    assert result["total_bottles"] == 2
    assert result["total_value"] == 20.0


def test_shrinking_to_zero_bottles_is_rejected_even_with_rows():
    """Rows present but none usable, after a stocked cellar."""
    with pytest.raises(UpdateFailed):
        process([{"NotAWine": "x"}], previous=STOCKED)


def test_a_large_unexplained_drop_is_logged(caplog):
    """A truncated response can still yield *some* valid rows."""
    with caplog.at_level(logging.WARNING, logger="cellar_tracker.cellar_data"):
        result = process(REAL_ROWS, previous=STOCKED)
    assert result["total_bottles"] == 2
    assert "412" in caplog.text and "2" in caplog.text


def test_a_normal_drop_is_not_logged(caplog):
    """Drinking a few bottles must not produce warnings."""
    previous = {"total_bottles": 2, "total_value": 20.0, "bottles": []}
    with caplog.at_level(logging.WARNING, logger="cellar_tracker.cellar_data"):
        process(REAL_ROWS[:1], previous=previous)
    assert caplog.text == ""


# --------------------------------------------------------------------------
# A cellar really can be emptied. Rejecting zero forever would strand the
# sensor as unavailable, so an ambiguous zero is tolerated only briefly.
# --------------------------------------------------------------------------
def test_a_persistent_zero_is_eventually_accepted():
    """Drinking the last bottle must not break the sensor permanently."""
    coordinator = build_coordinator(returns=[], previous=STOCKED)

    with pytest.raises(UpdateFailed):
        coordinator._process_inventory([], previous=STOCKED)

    # Still reported empty on the next poll: believe it.
    assert coordinator._process_inventory([], previous=STOCKED) == EMPTY


def test_recovery_resets_the_suspicion_streak():
    """A good poll between two zeros must clear the tolerance counter."""
    coordinator = build_coordinator()

    with pytest.raises(UpdateFailed):
        coordinator._process_inventory([], previous=STOCKED)

    coordinator._process_inventory(REAL_ROWS, previous=STOCKED)

    # Streak reset, so the next zero is treated as suspicious again.
    with pytest.raises(UpdateFailed):
        coordinator._process_inventory([], previous=STOCKED)


def test_unrecognised_rows_are_never_accepted():
    """Rows without 'iWine' are unambiguous garbage - no tolerance applies."""
    coordinator = build_coordinator()
    rows = _parse_data(MULTILINE_ERROR_PAGE)
    for _ in range(5):
        with pytest.raises(UpdateFailed):
            coordinator._process_inventory(rows, previous=STOCKED)


def test_last_bottle_drunk_recovers_within_two_polls():
    """End-to-end version of the single-bottle case."""
    one_bottle = {"total_bottles": 1, "total_value": 12.5, "bottles": []}
    coordinator = build_coordinator(returns=[], previous=one_bottle)

    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
    assert inventory_of(asyncio.run(coordinator._async_update_data())) == EMPTY


# --------------------------------------------------------------------------
# Wiring: the coordinator must feed its own last-good data in as `previous`
# --------------------------------------------------------------------------
def test_coordinator_passes_previous_data_through():
    """End-to-end: a stocked coordinator receiving garbage must raise."""
    coordinator = build_coordinator(returns=[], previous=STOCKED)
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_coordinator_first_poll_of_empty_account_succeeds():
    coordinator = build_coordinator(returns=[], previous=None)
    assert inventory_of(asyncio.run(coordinator._async_update_data())) == EMPTY
