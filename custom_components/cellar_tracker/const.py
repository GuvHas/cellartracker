"""Constants for the CellarTracker integration."""

import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "cellar_tracker"
PLATFORMS = ["sensor"]

# The dashboard page ships inside the integration directory so that a HACS
# download installs it - HACS copies custom_components/cellar_tracker and
# nothing else, so a page kept beside it was never present on the user's
# system. The integration serves it itself at DASHBOARD_URL; nothing has to be
# copied into <config>/www.
DASHBOARD_FILENAME = "cellar.html"
DASHBOARD_URL = f"/cellartracker/{DASHBOARD_FILENAME}"

# The columns the bundled dashboard renders. ``?view=compact`` on the inventory
# endpoint serves only these, which is roughly a tenth of the bytes: the export
# carries 66 columns and the page shows seven of them.
COMPACT_FIELDS = (
    "unique_bottle_id",
    "iWine",
    "Wine",
    "Vintage",
    "Location",
    "Bin",
    "BeginConsume",
    "EndConsume",
    "Valuation",
)

CONF_CURRENCY = "currency"
DEFAULT_CURRENCY = "USD"
DEFAULT_SCAN_INTERVAL = 21600
MIN_SCAN_INTERVAL = 900

CURRENCY_OPTIONS = {
    "USD": "USD ($)",
    "EUR": "EUR (€)",
    "GBP": "GBP (£)",
    "CHF": "CHF",
    "CAD": "CAD (CA$)",
    "AUD": "AUD (AU$)",
    "JPY": "JPY (¥)",
    "SEK": "SEK (kr)",
    "NOK": "NOK (kr)",
    "DKK": "DKK (kr)",
    "BRL": "BRL (R$)",
    "INR": "INR (₹)",
    "ZAR": "ZAR",
    "NZD": "NZD (NZ$)",
}

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CHF": "CHF",
    "CAD": "CA$",
    "AUD": "AU$",
    "JPY": "¥",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "BRL": "R$",
    "INR": "₹",
    "ZAR": "ZAR",
    "NZD": "NZ$",
}

LEGACY_CURRENCY_MAP = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "CA$": "CAD",
    "AU$": "AUD",
    "¥": "JPY",
    "kr": "SEK",
    "R$": "BRL",
    "₹": "INR",
    "NZ$": "NZD",
}


def normalize_currency(value: str | None) -> str:
    """Normalize currency values to ISO 4217-style codes used by HA monetary sensors."""
    if not value:
        return DEFAULT_CURRENCY

    value_upper = value.upper()
    if value_upper in CURRENCY_OPTIONS:
        return value_upper

    if value in LEGACY_CURRENCY_MAP:
        return LEGACY_CURRENCY_MAP[value]

    # Only reachable from entry data written before the flows constrained the
    # choice - which is exactly where labelling someone's cellar in the wrong
    # currency would go unnoticed.
    _LOGGER.warning(
        "Unrecognised CellarTracker currency %r; falling back to %s. Set the "
        "currency again in the integration options to correct it.",
        value,
        DEFAULT_CURRENCY,
    )
    return DEFAULT_CURRENCY
