"""Constants for the CellarTracker integration."""

DOMAIN = "cellar_tracker"
PLATFORMS = ["sensor"]

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

    return LEGACY_CURRENCY_MAP.get(value, DEFAULT_CURRENCY)
