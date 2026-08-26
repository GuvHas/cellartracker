"""The REST endpoints serve the single configured account.

These replace the entry-scoping suite. That machinery - ``?entry_id=``,
``400 entry_id_required``, ``404 unknown_entry_id`` - existed only to
disambiguate between several accounts. The config flow now allows exactly one,
so there is nothing to disambiguate and the endpoints just serve it.

``?entry_id=`` is still accepted and ignored, so dashboards configured against
the previous release keep working unchanged.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from cellar_tracker.const import DOMAIN
from cellar_tracker.views import CellarTrackerInventoryView, CellarTrackerSettingsView
from conftest import FakeCoordinator, FakeRequest, ViewHass

BOTTLES = [{"iWine": "1", "Wine": "Barolo"}]
OTHER = [{"iWine": "2", "Wine": "Rioja"}]


def build(entries):
    hass = ViewHass({DOMAIN: dict(entries)})
    return CellarTrackerInventoryView(hass), CellarTrackerSettingsView(hass)


def get(view, **query):
    return asyncio.run(view.get(FakeRequest(**query)))


# --------------------------------------------------------------------------
# The configured account
# --------------------------------------------------------------------------
def test_inventory_serves_the_configured_account():
    inventory, _ = build({"a": FakeCoordinator(bottles=BOTTLES)})
    assert get(inventory).payload == BOTTLES


def test_settings_serves_the_configured_currency():
    _, settings = build({"a": FakeCoordinator(currency="SEK")})
    payload = get(settings).payload
    assert payload["currency"] == "SEK"
    assert payload["currency_symbol"] == "kr"


def test_an_entry_with_no_data_yet_returns_empty():
    inventory, settings = build({"a": FakeCoordinator(currency="GBP", data=False)})
    assert get(inventory).payload == []
    assert get(settings).payload["currency"] == "GBP", "currency is known before data is"


# --------------------------------------------------------------------------
# Nothing configured
# --------------------------------------------------------------------------
def test_no_entry_configured():
    inventory, settings = build({})
    assert get(inventory).payload == []
    assert get(settings).payload["currency"] == "USD"


def test_domain_absent_entirely():
    hass = ViewHass({})
    assert get(CellarTrackerInventoryView(hass)).payload == []
    assert get(CellarTrackerSettingsView(hass)).payload["currency"] == "USD"


# --------------------------------------------------------------------------
# Backward compatibility: a stale ?entry_id= must not break an old dashboard
# --------------------------------------------------------------------------
@pytest.mark.parametrize("entry_id", ["a", "stale-id-from-an-old-card", "", "   "])
def test_entry_id_is_accepted_and_ignored(entry_id):
    inventory, settings = build({"a": FakeCoordinator(currency="EUR", bottles=BOTTLES)})
    assert get(inventory, entry_id=entry_id).payload == BOTTLES
    assert get(settings, entry_id=entry_id).payload["currency"] == "EUR"


def test_no_error_statuses_remain():
    """The 400/404 disambiguation responses are gone."""
    inventory, _ = build({"a": FakeCoordinator(bottles=BOTTLES)})
    assert get(inventory).status == 200
    assert get(inventory, entry_id="anything").status == 200


# --------------------------------------------------------------------------
# A pre-existing install may still hold two entries. Be deterministic and say so.
# --------------------------------------------------------------------------
def test_a_legacy_second_entry_is_served_deterministically(caplog):
    entries = {
        "bbb": FakeCoordinator(currency="SEK", bottles=OTHER),
        "aaa": FakeCoordinator(currency="USD", bottles=BOTTLES),
    }
    inventory, settings = build(entries)

    with caplog.at_level(logging.WARNING, logger="cellar_tracker.views"):
        payload = get(inventory).payload

    assert payload == BOTTLES, "must pick the lowest entry id, not dict order"
    assert get(settings).payload["currency"] == "USD", "both views must agree"
    assert "more than one" in caplog.text.lower()


def test_the_two_views_never_disagree():
    """The original bug: bottles from one entry priced in another's currency."""
    entries = {
        "aaa": FakeCoordinator(currency="USD", bottles=BOTTLES),
        "bbb": FakeCoordinator(currency="SEK", bottles=OTHER),
    }
    inventory, settings = build(entries)
    assert get(inventory).payload == BOTTLES
    assert get(settings).payload["currency"] == "USD"
