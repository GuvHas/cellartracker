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


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CellarTrackerConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    bottles = [] if data is None else data.get("bottles") or []

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_success": coordinator.last_success,
            "update_interval": str(coordinator.update_interval),
            "currency": coordinator.currency,
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
