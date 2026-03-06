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
