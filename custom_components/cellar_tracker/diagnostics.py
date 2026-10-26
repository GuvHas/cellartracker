"""Diagnostics for the CellarTracker integration.

A diagnostics download is routinely pasted into a public issue, so the question
is not only what would help us but what the user would regret publishing.

Redacted: the password, the username, and the entry title - which is the
username, because that is what the config flow names the entry after. Per
bottle, everything outside a small allowlist, so a column nobody reviewed
cannot walk into a public issue.

Kept: the column list, which is the signal that matters. Every "no 'iWine'
column" report comes down to CellarTracker having changed its export, and the
column names are how we see that without asking for a copy of the cellar.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .cellar_data import CellarTrackerConfigEntry

# "title" as well as the credential keys: async_step_user names the entry
# after the account, so the title *is* the username for every entry this
# integration creates. Redacting only the username field would have published
# it one line further down.
TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "title"}

# The sample bottle is an allowlist rather than a denylist. A denylist has to
# be right about every column CellarTracker has today and every one it adds
# later, and the export already carries free-form prose - tasting and cellar
# notes - that can say anything at all about anyone. These are the fields the
# integration itself reads or derives, which is what debugging it needs.
#
# Nothing is lost by omitting the rest: "columns" below still lists every
# column name, which is the signal schema drift actually needs.
SAMPLE_FIELDS = (
    "iWine",
    "Wine",
    "Vintage",
    "Valuation",
    "BeginConsume",
    "EndConsume",
    "unique_bottle_id",
)


_REDACTED = "**REDACTED**"

# The export endpoint takes the account as query parameters, so anything that
# carried a request URL would carry these. None of our own messages do - they
# are built from the status and the exception's type - but this is free text
# in a file people paste into public issues, so it is scrubbed regardless.
_QUERY_CREDENTIAL = re.compile(r"\b(User|Password)=[^&\s]*", re.IGNORECASE)


def _scrub(text: str | None, secrets: tuple[str, ...]) -> str | None:
    """Remove the account's credentials, and URL-shaped ones, from free text."""
    if text is None:
        return None
    # Longest first, so a secret that contains another is removed whole.
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    return _QUERY_CREDENTIAL.sub(lambda match: f"{match.group(1)}={_REDACTED}", text)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CellarTrackerConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    bottles = [] if data is None else data.get("bottles") or []
    secrets = (entry.data.get(CONF_PASSWORD, ""), entry.data.get(CONF_USERNAME, ""))

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_success": coordinator.last_success,
            "update_interval": str(coordinator.update_interval),
            "currency": coordinator.currency,
            "last_error": _scrub(coordinator.last_error, secrets),
        },
        # Whether what is on show came from disk, and how old it is: the first
        # question after "why is it not updating".
        "cache": {
            "serving_cached_data": coordinator.serving_cached_data,
            "cached_at": (
                coordinator.last_success.isoformat()
                if coordinator.serving_cached_data and coordinator.last_success
                else None
            ),
        },
        "backoff": {
            "consecutive_backoffs": coordinator.consecutive_backoffs,
            "configured_interval": str(coordinator.scan_interval),
            "current_interval": str(coordinator.update_interval),
        },
        # Counts only. The location index is deliberately not reported: its keys
        # are the user's rack names, which the sample allowlist already keeps
        # out. Absent keys are None, not zero: a payload from before a metric
        # existed has not said the answer is nothing.
        "drink_window": {
            key: None if data is None else data.get(key)
            for key in ("ready_to_drink", "past_drink_window", "needs_aging", "peak_drinking")
        },
        "totals": {
            "total_bottles": None if data is None else data.get("total_bottles"),
            "total_value": None if data is None else data.get("total_value"),
        },
        # Sorted so two reports can be diffed when a schema change is suspected.
        "columns": sorted(bottles[0]) if bottles else [],
        # One row is enough to show how the export is shaped. Shipping the whole
        # cellar would be both useless and a privacy problem.
        "sample_bottle": (
            {field: bottles[0][field] for field in SAMPLE_FIELDS if field in bottles[0]}
            if bottles
            else None
        ),
    }
