"""Diagnostics for the CellarTracker integration.

A diagnostics download is routinely pasted into a public issue, so the question
is not only what would help us but what the user would regret publishing.

Redacted: the password, and the username too - it is half of a credential pair
and names a real CellarTracker account. Per bottle, the Barcode, Location and
Bin, which describe someone's home and are no use in diagnosing a parsing bug.

Kept: the column list, which is the signal that matters. Every "no 'iWine'
column" report comes down to CellarTracker having changed its export, and the
column names are how we see that without asking for a copy of the cellar.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}

BOTTLE_REDACT = {"Barcode", "Location", "Bin"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    bottles = data.get("bottles") or []

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_success": coordinator.last_success,
            "update_interval": str(coordinator.update_interval),
            "currency": coordinator.currency,
        },
        "totals": {
            "total_bottles": data.get("total_bottles"),
            "total_value": data.get("total_value"),
        },
        # Sorted so two reports can be diffed when a schema change is suspected.
        "columns": sorted(bottles[0]) if bottles else [],
        # One row is enough to show how the export is shaped. Shipping the whole
        # cellar would be both useless and a privacy problem.
        "sample_bottle": (
            async_redact_data(bottles[0], BOTTLE_REDACT) if bottles else None
        ),
    }
