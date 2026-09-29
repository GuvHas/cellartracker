"""The coordinator's processed payload carries the analytics.

These are non-entity metrics: they ride in ``coordinator.data`` for the HTTP
views, the services and diagnostics. The five sensors are unchanged.
"""

from __future__ import annotations

import asyncio

import pytest

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass, FakeSession

HEADER = "iWine\tWine\tLocation\tBin\tValuation\tBeginConsume\tEndConsume"


def tsv(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


def build(text: str, year: int = 2026) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(text=text)
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})
    coordinator = WineCellarData(hass, entry)
    coordinator._current_year = lambda: year  # type: ignore[method-assign]
    return coordinator


def update(coordinator: WineCellarData):
    return asyncio.run(coordinator._async_update_data())


CELLAR = tsv(
    "1\tBarolo\tCellar\tA1\t50\t2020\t2040",  # ready + peak
    "2\tRioja\tCellar\tA1\t20\t2020\t2030",  # ready
    "3\tPort\tCellar\tB2\t30\t2030\t2050",  # needs aging
    "4\tChablis\tFridge\tA1\t10\t2010\t2020",  # past
    "5\tMystery\t\t\t5\t\t",  # no window, unplaced
)


def test_payload_carries_every_drink_window_count():
    data = update(build(CELLAR))
    assert data["ready_to_drink"] == 2
    assert data["past_drink_window"] == 1
    assert data["needs_aging"] == 1
    assert data["peak_drinking"] == 1


def test_the_sensor_counts_are_unchanged_by_the_new_metrics():
    """ready/past are the rules the sensors and dashboard already share."""
    data = update(build(CELLAR))
    assert (data["ready_to_drink"], data["past_drink_window"]) == (2, 1)


def test_an_empty_cellar_carries_zeroed_analytics():
    data = update(build(HEADER))
    assert data["needs_aging"] == 0
    assert data["peak_drinking"] == 0
    assert data["location_index"] == {}


def test_payload_carries_the_location_bin_index():
    data = update(build(CELLAR))
    index = data["location_index"]
    assert [data["bottles"][i]["Wine"] for i in index["Cellar"]["A1"]] == ["Barolo", "Rioja"]
    assert [data["bottles"][i]["Wine"] for i in index["Fridge"]["A1"]] == ["Chablis"]
    assert [data["bottles"][i]["Wine"] for i in index[""][""]] == ["Mystery"]


@pytest.mark.parametrize(("year", "aging", "ready"), [(2026, 1, 2), (2031, 0, 2)])
def test_the_year_used_is_the_polls_year(year, aging, ready):
    data = update(build(CELLAR, year=year))
    assert data["needs_aging"] == aging
    assert data["ready_to_drink"] == ready


# --------------------------------------------------------------------------
# last_error: why the last poll failed, for diagnostics
# --------------------------------------------------------------------------
import aiohttp  # noqa: E402
from cellartracker.const import NOT_LOGGED_REPONSE  # noqa: E402
from homeassistant.exceptions import ConfigEntryAuthFailed  # noqa: E402
from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402


def failing_build(**session) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(**session)
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})
    return WineCellarData(hass, entry)


def test_a_healthy_coordinator_has_no_error():
    coordinator = build(CELLAR)
    update(coordinator)
    assert coordinator.last_error is None


def test_a_failed_poll_records_why():
    coordinator = failing_build(error=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(UpdateFailed):
        update(coordinator)
    assert coordinator.last_error


def test_the_recorded_error_carries_no_credentials():
    coordinator = failing_build(error=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(UpdateFailed):
        update(coordinator)
    assert "s3cret" not in coordinator.last_error
    assert "alice" not in coordinator.last_error


def test_an_authentication_failure_is_recorded():
    coordinator = failing_build(text=f"<html>{NOT_LOGGED_REPONSE}</html>")
    with pytest.raises(ConfigEntryAuthFailed):
        update(coordinator)
    assert coordinator.last_error


def test_a_success_clears_the_error():
    coordinator = failing_build(error=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(UpdateFailed):
        update(coordinator)
    coordinator.hass.session = FakeSession(text=CELLAR)
    update(coordinator)
    assert coordinator.last_error is None


def test_the_configured_interval_is_exposed_apart_from_the_current_one():
    """At the 6h default a backoff lands on the cap, so use a short schedule."""
    from yarl import URL

    url = URL("https://www.cellartracker.com/xlquery.asp")
    hass = FakeHass()
    hass.session = FakeSession(
        raise_for_status=aiohttp.ClientResponseError(
            aiohttp.RequestInfo(url, "GET", (), url), (), status=503
        )
    )
    entry = ConfigEntry(data={"username": "a", "password": "b", "scan_interval": 900})
    coordinator = WineCellarData(hass, entry)

    with pytest.raises(UpdateFailed):
        update(coordinator)

    assert coordinator.update_interval > coordinator.scan_interval
    assert coordinator.scan_interval.total_seconds() == 900
