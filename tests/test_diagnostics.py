"""P2-3: diagnostics, sequenced deliberately after P0-3.

A diagnostics file is routinely pasted into a public issue tracker, which makes
it exactly the code path that would have turned P0-3's latent credential
exposure into a live one. It lands only now that transport errors no longer
carry the request URL.

What must never appear: the password, obviously, but also the username - it is
half of a credential pair and identifies a real CellarTracker account. Nor the
per-bottle Barcode, Location and Bin, which describe someone's home and are not
ours to publish.

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
    def __init__(self, data=None, last_update_success=True):
        self.data = data
        self.currency = "SEK"
        self.last_update_success = last_update_success
        self.update_interval = "6:00:00"
        self.last_success = None


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
