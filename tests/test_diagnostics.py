"""P2-3: diagnostics, sequenced deliberately after P0-3.

A diagnostics file is routinely pasted into a public issue tracker, which makes
it exactly the code path that would have turned P0-3's latent credential
exposure into a live one. It lands only now that transport errors no longer
carry the request URL.

What must never appear: the password, obviously, but also the username - it is
half of a credential pair and identifies a real CellarTracker account - and the
entry title, which *is* the username. Per bottle, anything outside a fixed
allowlist: a denylist would have to be right about every column CellarTracker
adds in future, and the export carries free-form notes that can say anything.

What must appear: enough to diagnose the failures this integration actually
has. The column list is the important one - it tells us whether CellarTracker
changed its export schema, which is the class of bug that produces "no 'iWine'
column" reports.
"""

from __future__ import annotations

import asyncio
import json

from cellar_tracker.diagnostics import (
    SAMPLE_FIELDS,
    async_get_config_entry_diagnostics,
)
from conftest import ConfigEntry, ViewHass

PASSWORD = "hunter2-do-not-leak"
USERNAME = "alice@example.com"

BOTTLE = {
    "iWine": "1",
    "Wine": "Barolo",
    "Vintage": "2016",
    "Valuation": 45.50,
    "Barcode": "BC-77-4412",
    "Location": "Cellar under the stairs",
    "Bin": "A4",
    "BottleNote": "bought for Anna's 40th, keep for her",
    "CNotes": "cellar note naming the neighbour who has the spare key",
    "PNotes": "private note",
    "unique_bottle_id": "abcdef0123456789",
}


class _Coordinator:
    def __init__(self, data=None, last_update_success=True, **state):
        self.data = data
        self.currency = "SEK"
        self.last_update_success = last_update_success
        self.update_interval = "6:00:00"
        self.last_success = None
        # Resilience state; defaults describe a healthy, freshly polled coordinator.
        self.scan_interval = "6:00:00"
        self.serving_cached_data = False
        self.consecutive_backoffs = 0
        self.last_error = None
        for name, value in state.items():
            setattr(self, name, value)


def diagnostics(coordinator) -> dict:
    entry = ConfigEntry(
        entry_id="a",
        # async_step_user sets the title to the username. The double defaulted
        # to something else, which is why the leak below went unnoticed.
        title=USERNAME,
        data={"username": USERNAME, "password": PASSWORD, "currency": "SEK"},
        options={"scan_interval": 21600},
    )
    entry.runtime_data = coordinator
    return asyncio.run(async_get_config_entry_diagnostics(ViewHass(), entry))


def stocked() -> dict:
    return {"total_bottles": 1, "total_value": 45.50, "bottles": [dict(BOTTLE)]}


def rendered(report: dict) -> str:
    """What actually reaches the issue tracker."""
    return json.dumps(report, default=str)


def test_the_password_never_appears():
    assert PASSWORD not in rendered(diagnostics(_Coordinator(stocked())))


def test_the_username_never_appears():
    """Half a credential pair, and it names a real account."""
    assert USERNAME not in rendered(diagnostics(_Coordinator(stocked())))


def test_the_bottle_sample_hides_where_the_wine_lives():
    report = diagnostics(_Coordinator(stocked()))
    sample = report["sample_bottle"]

    # Absent rather than redacted: the sample is an allowlist, so these were
    # never copied in. Asserted field by field because a substring search over
    # the rendered report gives false positives - a short Bin like "A4"
    # appears inside plenty of innocent text.
    for field in ("Barcode", "Location", "Bin"):
        assert field not in sample, f"{field} must not reach the report"

    assert "Cellar under the stairs" not in rendered(report)


def test_the_sample_keeps_what_makes_it_useful():
    sample = diagnostics(_Coordinator(stocked()))["sample_bottle"]
    assert sample["Wine"] == "Barolo"
    assert sample["Vintage"] == "2016"


def test_the_column_list_is_reported():
    """The schema-drift signal: 'no iWine column' reports start here."""
    report = diagnostics(_Coordinator(stocked()))
    assert "Barcode" in report["columns"]
    assert report["columns"] == sorted(report["columns"])


def test_the_totals_are_reported():
    report = diagnostics(_Coordinator(stocked()))
    assert report["totals"] == {"total_bottles": 1, "total_value": 45.50}


def test_the_coordinator_state_is_reported():
    report = diagnostics(_Coordinator(stocked(), last_update_success=False))
    assert report["coordinator"]["last_update_success"] is False
    assert report["coordinator"]["currency"] == "SEK"


def test_an_empty_cellar_produces_a_report_rather_than_an_error():
    report = diagnostics(_Coordinator({"total_bottles": 0, "total_value": 0.0, "bottles": []}))
    assert report["columns"] == []
    assert report["sample_bottle"] is None


def test_a_coordinator_that_never_refreshed_produces_a_report():
    """Diagnostics are most often pulled precisely when setup is failing."""
    report = diagnostics(_Coordinator(None, last_update_success=False))
    assert report["totals"]["total_bottles"] is None
    assert report["sample_bottle"] is None


# --------------------------------------------------------------------------
# Reported by Codex on #18
# --------------------------------------------------------------------------
def test_the_entry_title_does_not_leak_the_username():
    """The title *is* the username for every entry this integration creates."""
    report = diagnostics(_Coordinator(stocked()))
    assert USERNAME not in rendered(report)
    assert report["entry"]["title"] == "**REDACTED**"


def test_free_form_notes_never_reach_the_report():
    """Tasting and cellar notes are prose someone wrote; they can say anything."""
    sample = diagnostics(_Coordinator(stocked()))["sample_bottle"]

    for field in ("BottleNote", "CNotes", "PNotes"):
        assert field not in sample, f"{field} is free-form and must not be published"


def test_the_sample_is_an_allowlist_not_a_denylist():
    """A denylist ships every column CellarTracker adds in future, unreviewed."""
    sample = diagnostics(_Coordinator(stocked()))["sample_bottle"]
    assert set(sample) <= set(SAMPLE_FIELDS)


def test_an_unknown_column_is_omitted_rather_than_published():
    bottle = {**BOTTLE, "SomeColumnAddedNextYear": "who knows what this holds"}
    report = diagnostics(
        _Coordinator({"total_bottles": 1, "total_value": 0.0, "bottles": [bottle]})
    )

    assert "SomeColumnAddedNextYear" not in report["sample_bottle"]
    # ...but its existence is still visible, which is what schema drift needs.
    assert "SomeColumnAddedNextYear" in report["columns"]


# --------------------------------------------------------------------------
# Resilience state: cache, backoff, last error, analytics
# --------------------------------------------------------------------------
from datetime import UTC, datetime  # noqa: E402

CACHED_AT = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)


def with_analytics() -> dict:
    return {
        **stocked(),
        "ready_to_drink": 4,
        "past_drink_window": 2,
        "needs_aging": 7,
        "peak_drinking": 3,
        # Rack names: exactly what the sample allowlist keeps out of a report.
        "location_index": {"Cellar under the stairs": {"A4": [0]}},
    }


def test_the_cache_state_is_reported():
    coordinator = _Coordinator(stocked(), serving_cached_data=True, last_success=CACHED_AT)
    report = diagnostics(coordinator)
    assert report["cache"]["serving_cached_data"] is True
    assert report["cache"]["cached_at"] == CACHED_AT.isoformat()


def test_a_live_coordinator_reports_no_cache_age():
    report = diagnostics(_Coordinator(stocked(), last_success=CACHED_AT))
    assert report["cache"]["serving_cached_data"] is False
    assert report["cache"]["cached_at"] is None


def test_the_backoff_state_is_reported():
    coordinator = _Coordinator(stocked(), consecutive_backoffs=3)
    coordinator.update_interval = "12:00:00"
    report = diagnostics(coordinator)
    assert report["backoff"] == {
        "consecutive_backoffs": 3,
        "configured_interval": "6:00:00",
        "current_interval": "12:00:00",
    }


def test_the_drink_window_breakdown_is_reported():
    report = diagnostics(_Coordinator(with_analytics()))
    assert report["drink_window"] == {
        "ready_to_drink": 4,
        "past_drink_window": 2,
        "needs_aging": 7,
        "peak_drinking": 3,
    }


def test_a_payload_that_predates_the_analytics_still_reports():
    """A cache or an older poll may lack keys added later."""
    report = diagnostics(_Coordinator(stocked()))
    assert report["drink_window"] == {
        "ready_to_drink": None,
        "past_drink_window": None,
        "needs_aging": None,
        "peak_drinking": None,
    }


def test_the_last_error_is_reported():
    report = diagnostics(_Coordinator(stocked(), last_error="HTTP 503 from CellarTracker"))
    assert report["coordinator"]["last_error"] == "HTTP 503 from CellarTracker"


def test_no_error_is_reported_as_none():
    assert diagnostics(_Coordinator(stocked()))["coordinator"]["last_error"] is None


# --- scrubbing --------------------------------------------------------------
def test_a_credential_inside_the_last_error_is_scrubbed():
    coordinator = _Coordinator(
        stocked(), last_error=f"login failed for {USERNAME} using {PASSWORD}"
    )
    report = rendered(diagnostics(coordinator))
    assert PASSWORD not in report
    assert USERNAME not in report


def test_a_query_string_credential_is_scrubbed_even_if_it_is_not_ours():
    """Defence in depth: whatever text ends up here, URL-shaped secrets go."""
    leaked = "GET https://www.cellartracker.com/xlquery.asp?User=bob&Password=whatever&Table=x"
    report = rendered(diagnostics(_Coordinator(stocked(), last_error=leaked)))
    assert "whatever" not in report
    assert "User=bob" not in report
    assert "Table=x" in report, "only the credential parameters may be removed"


def test_scrubbing_leaves_an_ordinary_message_intact():
    message = "Cannot reach CellarTracker: ClientConnectionError"
    report = diagnostics(_Coordinator(stocked(), last_error=message))
    assert report["coordinator"]["last_error"] == message


# --- what must stay out -----------------------------------------------------
def test_rack_names_do_not_leak_through_the_analytics():
    report = rendered(diagnostics(_Coordinator(with_analytics())))
    assert "Cellar under the stairs" not in report
    assert "location_index" not in report


def test_the_cached_payload_is_never_exported():
    coordinator = _Coordinator(stocked(), _cached_payload="iWine\tBottleNote\n1\tsecret note")
    assert "secret note" not in rendered(diagnostics(coordinator))
