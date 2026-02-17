"""Constants for the CellarTracker integration."""

DOMAIN = "cellar_tracker"
PLATFORMS = ["sensor"]

CONF_CURRENCY = "currency"
DEFAULT_CURRENCY = "$"

CURRENCY_OPTIONS = {
    "$": "USD ($)",
    "€": "EUR (€)",
    "£": "GBP (£)",
    "CHF": "CHF",
    "CA$": "CAD (CA$)",
    "AU$": "AUD (AU$)",
    "¥": "JPY (¥)",
    "kr": "SEK/NOK/DKK (kr)",
    "R$": "BRL (R$)",
    "₹": "INR (₹)",
    "ZAR": "ZAR",
    "NZ$": "NZD (NZ$)",
}