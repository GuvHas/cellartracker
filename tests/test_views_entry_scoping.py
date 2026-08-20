"""F-06: the HTTP views must resolve exactly one, explicitly chosen config entry.

Both views iterated ``hass.data[DOMAIN]`` and returned whatever came first, with
no way for a caller to say which cellar it wanted. With two CellarTracker
accounts configured, every dashboard rendered whichever entry happened to load
first and the second was unreachable.

Worse, the two views disagreed about *which* entry to pick: the inventory view
skipped entries whose ``coordinator.data`` was still falsy, while the settings
view returned on the first entry unconditionally. During startup, or whenever
one account failed to refresh, the dashboard could therefore render one entry's
bottles priced in another entry's currency.
"""

from __future__ import annotations

import asyncio

import pytest

from cellar_tracker.const import DOMAIN
from cellar_tracker.views import CellarTrackerInventoryView, CellarTrackerSettingsView
from conftest import FakeCoordinator, FakeRequest, ViewHass

BOTTLES_A = [{"iWine": "1", "Wine": "Barolo"}]
BOTTLES_B = [{"iWine": "2", "Wine": "Rioja"}]


def build(entries):
    """entries: {entry_id: FakeCoordinator}. Includes the registration sentinel."""
    data = {DOMAIN: {**entries, "_view_registered": True}}
    hass = ViewHass(data)
    return CellarTrackerInventoryView(hass), CellarTrackerSettingsView(hass)


def get(view, **query):
    return asyncio.run(view.get(FakeRequest(**query)))


# --------------------------------------------------------------------------
# Single entry: the common case must keep working with no query parameter
# --------------------------------------------------------------------------
def test_single_entry_needs_no_entry_id():
    inventory, settings = build({"a": FakeCoordinator(currency="EUR", bottles=BOTTLES_A)})

    assert get(inventory).payload == BOTTLES_A
    assert get(settings).payload["currency"] == "EUR"


def test_single_entry_accepts_its_own_entry_id():
    inventory, _ = build({"a": FakeCoordinator(bottles=BOTTLES_A)})
    assert get(inventory, entry_id="a").payload == BOTTLES_A


# --------------------------------------------------------------------------
# Multiple entries: the caller must choose
# --------------------------------------------------------------------------
def test_entry_id_selects_the_requested_cellar():
    inventory, settings = build(
        {
            "a": FakeCoordinator(currency="USD", bottles=BOTTLES_A),
            "b": FakeCoordinator(currency="SEK", bottles=BOTTLES_B),
        }
    )

    assert get(inventory, entry_id="a").payload == BOTTLES_A
    assert get(inventory, entry_id="b").payload == BOTTLES_B
    assert get(settings, entry_id="a").payload["currency"] == "USD"
    assert get(settings, entry_id="b").payload["currency"] == "SEK"


def test_ambiguous_request_is_rejected_rather_than_guessed():
    inventory, settings = build(
        {"a": FakeCoordinator(bottles=BOTTLES_A), "b": FakeCoordinator(bottles=BOTTLES_B)}
    )

    for view in (inventory, settings):
        response = get(view)
        assert response.status == 400
        assert sorted(response.payload["entries"]) == ["a", "b"]


def test_unknown_entry_id_is_rejected():
    inventory, _ = build({"a": FakeCoordinator(bottles=BOTTLES_A)})
    response = get(inventory, entry_id="does-not-exist")
    assert response.status == 404
    assert response.payload != BOTTLES_A


# --------------------------------------------------------------------------
# The two views must always describe the same entry
# --------------------------------------------------------------------------
def test_views_agree_when_the_chosen_entry_has_no_data_yet():
    """The pre-fix inventory view skipped entry 'a' and served 'b' instead."""
    inventory, settings = build(
        {
            "a": FakeCoordinator(currency="USD", data=False),
            "b": FakeCoordinator(currency="SEK", bottles=BOTTLES_B),
        }
    )

    assert get(inventory, entry_id="a").payload == [], "must not fall through to 'b'"
    assert get(settings, entry_id="a").payload["currency"] == "USD"


def test_single_entry_without_data_returns_empty_not_defaults():
    inventory, settings = build({"a": FakeCoordinator(currency="GBP", data=False)})
    assert get(inventory).payload == []
    assert get(settings).payload["currency"] == "GBP"


# --------------------------------------------------------------------------
# Degenerate states
# --------------------------------------------------------------------------
def test_no_entries_configured():
    inventory, settings = build({})
    assert get(inventory).payload == []
    assert get(settings).payload["currency"] == "USD"


def test_domain_absent_entirely():
    hass = ViewHass({})
    inventory = CellarTrackerInventoryView(hass)
    settings = CellarTrackerSettingsView(hass)
    assert get(inventory).payload == []
    assert get(settings).payload["currency"] == "USD"


def test_registration_sentinel_is_never_treated_as_an_entry():
    """`_view_registered` is a bool stored alongside coordinators."""
    inventory, settings = build({"a": FakeCoordinator(bottles=BOTTLES_A)})

    assert get(inventory).payload == BOTTLES_A
    assert "_view_registered" not in get(settings, entry_id="nope").payload.get("entries", [])


def test_settings_response_includes_the_symbol():
    _, settings = build({"a": FakeCoordinator(currency="SEK")})
    payload = get(settings).payload
    assert payload["currency"] == "SEK"
    assert payload["currency_symbol"] == "kr"


@pytest.mark.parametrize("entry_id", ["", "   "])
def test_blank_entry_id_is_treated_as_absent(entry_id):
    inventory, _ = build({"a": FakeCoordinator(bottles=BOTTLES_A)})
    assert get(inventory, entry_id=entry_id).payload == BOTTLES_A
