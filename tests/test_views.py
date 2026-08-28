"""The REST endpoints serve the single configured account.

These replace the entry-scoping suite. That machinery - ``?entry_id=``,
``400 entry_id_required``, ``404 unknown_entry_id`` - existed only to
disambiguate between several accounts. The config flow now allows exactly one,
so there is nothing to disambiguate and the endpoints just serve it.

``?entry_id=`` is still accepted and ignored for that single account, so
dashboards configured against the previous release keep working unchanged. It
is honoured only on a legacy install that still holds two entries, where
ignoring it would answer for an account the caller did not ask for.
"""

from __future__ import annotations

import asyncio
import json
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
    """Return the real aiohttp Response the view produced."""
    return asyncio.run(view.get(FakeRequest(**query)))


def body(response):
    """Decode a real aiohttp json response."""
    return json.loads(response.body)


# --------------------------------------------------------------------------
# The configured account
# --------------------------------------------------------------------------
def test_inventory_serves_the_configured_account():
    inventory, _ = build({"a": FakeCoordinator(bottles=BOTTLES)})
    assert body(get(inventory)) == BOTTLES


def test_settings_serves_the_configured_currency():
    _, settings = build({"a": FakeCoordinator(currency="SEK")})
    payload = body(get(settings))
    assert payload["currency"] == "SEK"
    assert payload["currency_symbol"] == "kr"


def test_an_entry_with_no_data_yet_returns_empty():
    inventory, settings = build({"a": FakeCoordinator(currency="GBP", data=False)})
    assert body(get(inventory)) == []
    assert body(get(settings))["currency"] == "GBP", "currency is known before data is"


# --------------------------------------------------------------------------
# Nothing configured
# --------------------------------------------------------------------------
def test_no_entry_configured():
    inventory, settings = build({})
    assert body(get(inventory)) == []
    assert body(get(settings))["currency"] == "USD"


def test_domain_absent_entirely():
    hass = ViewHass({})
    assert body(get(CellarTrackerInventoryView(hass))) == []
    assert body(get(CellarTrackerSettingsView(hass)))["currency"] == "USD"


# --------------------------------------------------------------------------
# Backward compatibility: a stale ?entry_id= must not break an old dashboard
# --------------------------------------------------------------------------
@pytest.mark.parametrize("entry_id", ["a", "stale-id-from-an-old-card", "", "   "])
def test_entry_id_is_accepted_and_ignored(entry_id):
    inventory, settings = build({"a": FakeCoordinator(currency="EUR", bottles=BOTTLES)})
    assert body(get(inventory, entry_id=entry_id)) == BOTTLES
    assert body(get(settings, entry_id=entry_id))["currency"] == "EUR"


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
        payload = body(get(inventory))

    assert payload == BOTTLES, "must pick the lowest entry id, not dict order"
    assert body(get(settings))["currency"] == "USD", "both views must agree"
    assert "more than one" in caplog.text.lower()


def test_the_two_views_never_disagree():
    """The original bug: bottles from one entry priced in another's currency."""
    entries = {
        "aaa": FakeCoordinator(currency="USD", bottles=BOTTLES),
        "bbb": FakeCoordinator(currency="SEK", bottles=OTHER),
    }
    inventory, settings = build(entries)
    assert body(get(inventory)) == BOTTLES
    assert body(get(settings))["currency"] == "USD"


def test_a_legacy_second_entry_is_reachable_by_entry_id(caplog):
    """A /local/ dashboard still forwards ?entry_id=; it must not be ignored.

    Ignoring it here served the lowest entry id to every card, so a
    secondary-account dashboard silently showed another cellar's bottles
    priced in another cellar's currency.
    """
    entries = {
        "aaa": FakeCoordinator(currency="USD", bottles=BOTTLES),
        "bbb": FakeCoordinator(currency="SEK", bottles=OTHER),
    }
    inventory, settings = build(entries)

    with caplog.at_level(logging.WARNING, logger="cellar_tracker.views"):
        payload = body(get(inventory, entry_id="bbb"))

    assert payload == OTHER, "must serve the account that was asked for"
    assert body(get(settings, entry_id="bbb"))["currency"] == "SEK", "views must agree"
    assert caplog.text == "", "an unambiguous request is not worth warning about"


@pytest.mark.parametrize("entry_id", ["", "   ", "stale-id-from-an-old-card"])
def test_an_unusable_entry_id_still_falls_back_deterministically(entry_id, caplog):
    """Absent or stale ids keep the documented lowest-entry-id behaviour."""
    entries = {
        "bbb": FakeCoordinator(currency="SEK", bottles=OTHER),
        "aaa": FakeCoordinator(currency="USD", bottles=BOTTLES),
    }
    inventory, _ = build(entries)

    with caplog.at_level(logging.WARNING, logger="cellar_tracker.views"):
        payload = body(get(inventory, entry_id=entry_id))

    assert payload == BOTTLES
    assert "more than one" in caplog.text.lower()
