"""P2-4 and P3-4: currency changes and unrecognised currency codes.

P2-4: the value sensor is MONETARY with state_class TOTAL, so it generates
long-term statistics. The unit is read from options at setup and the entry
reloads when options change, so the entity returns with a new unit against the
same unique_id - which Home Assistant treats as an error on an existing
statistic, logging a mismatch and refusing to record further.

The statistic is worth keeping: cellar value over time is the reason to have
the sensor at all. So the sensor is left alone and the *change* is made loud,
at the moment the user makes it and can act on it. This is a relabelling, not
a conversion - the valuations still arrive in whatever currency the
CellarTracker account uses.

P3-4: normalize_currency's final fallback turned an unrecognised code into USD
silently, labelling a cellar in dollars with no warning. Only reachable from
legacy entry data, since the flows constrain input - which is exactly where a
silent relabel is least likely to be noticed.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from cellar_tracker.config_flow import CellarTrackerOptionsFlowHandler
from cellar_tracker.const import DEFAULT_CURRENCY, normalize_currency
from conftest import ConfigEntry


def options_flow(current: str) -> CellarTrackerOptionsFlowHandler:
    flow = CellarTrackerOptionsFlowHandler()
    flow.config_entry = ConfigEntry(
        data={"username": "alice", "password": "x", "currency": current},
        options={"currency": current, "scan_interval": 21600},
    )
    return flow


def submit(flow, currency: str):
    return asyncio.run(
        flow.async_step_init({"currency": currency, "scan_interval": 21600})
    )


# --------------------------------------------------------------------------
# P2-4: changing currency is worth saying out loud
# --------------------------------------------------------------------------
def test_changing_the_currency_warns_about_statistics(caplog):
    flow = options_flow("USD")

    with caplog.at_level(logging.WARNING, logger="cellar_tracker.config_flow"):
        result = submit(flow, "SEK")

    assert result["type"] == "create_entry"
    assert "statistic" in caplog.text.lower()
    assert "USD" in caplog.text and "SEK" in caplog.text


def test_keeping_the_currency_says_nothing(caplog):
    flow = options_flow("USD")

    with caplog.at_level(logging.WARNING, logger="cellar_tracker.config_flow"):
        submit(flow, "USD")

    assert caplog.text == ""


def test_the_options_form_explains_the_consequence():
    """The warning is after the fact; the form has to say it beforehand."""
    import json
    import pathlib

    component = (
        pathlib.Path(__file__).resolve().parent.parent
        / "custom_components"
        / "cellar_tracker"
    )
    strings = json.loads((component / "strings.json").read_text())
    init = strings["options"]["step"]["init"]

    assert "statistic" in json.dumps(init).lower(), (
        "the options form should warn before the user changes currency"
    )


# --------------------------------------------------------------------------
# P3-4: an unrecognised code must not quietly become dollars
# --------------------------------------------------------------------------
def test_an_unrecognised_currency_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="cellar_tracker.const"):
        assert normalize_currency("XYZ") == DEFAULT_CURRENCY

    assert "XYZ" in caplog.text
    assert DEFAULT_CURRENCY in caplog.text


@pytest.mark.parametrize("value", ["USD", "sek", "EUR"])
def test_a_recognised_code_is_silent(value, caplog):
    with caplog.at_level(logging.WARNING, logger="cellar_tracker.const"):
        assert normalize_currency(value) == value.upper()
    assert caplog.text == ""


@pytest.mark.parametrize("legacy", ["$", "€", "kr"])
def test_a_legacy_symbol_is_silent(legacy, caplog):
    """Mapped, not guessed: no warning is warranted."""
    with caplog.at_level(logging.WARNING, logger="cellar_tracker.const"):
        assert normalize_currency(legacy) in ("USD", "EUR", "SEK")
    assert caplog.text == ""


def test_no_value_is_silent(caplog):
    """An unset currency is a default, not a failed lookup."""
    with caplog.at_level(logging.WARNING, logger="cellar_tracker.const"):
        assert normalize_currency(None) == DEFAULT_CURRENCY
    assert caplog.text == ""
