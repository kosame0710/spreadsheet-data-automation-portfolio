"""
config.py — Declarative cleaning configuration for the CSV cleaner.

Everything that is *business-specific* lives here so the engine in
`cleaner.py` stays generic and reusable across clients. To adapt this demo
to a new dataset you normally only touch this file, not the engine.
"""

from __future__ import annotations

# --- Canonical output schema -------------------------------------------------
# The clean, unified column order every input is mapped into.
CANONICAL_COLUMNS = [
    "order_id",
    "customer_name",
    "email",
    "order_date",
    "product",
    "quantity",
    "unit_price",
    "country",
]

# --- Header mapping ----------------------------------------------------------
# Maps the many real-world header spellings to our canonical names.
# Keys are normalized (lowercased, stripped, punctuation/space-collapsed) by
# the engine before lookup, so we only list normalized variants here.
HEADER_ALIASES = {
    "order_id": ["order id", "order_id", "orderid"],
    "customer_name": ["customer name", "customer", "client"],
    "email": ["email", "e mail", "e-mail", "contact email"],
    "order_date": ["order date", "date", "purchased on"],
    "product": ["product", "item", "sku product", "sku / product"],
    "quantity": ["qty", "quantity", "units"],
    "unit_price": ["unit price", "price", "amount per unit", "amount (per unit)"],
    "country": ["country", "region"],
}

# --- Country normalization ---------------------------------------------------
# Collapse the many spellings of a country into one canonical label.
COUNTRY_ALIASES = {
    "United States": ["usa", "united states", "u.s.a.", "u.s.", "us", "u s a"],
    "Germany": ["germany", "deutschland", "de"],
    "France": ["france", "fr"],
    "Italy": ["italy", "italia", "it"],
    "Spain": ["spain", "espana", "es"],
    "Netherlands": ["netherlands", "nl", "holland"],
    "Sweden": ["sweden", "se"],
    "Japan": ["japan", "jp"],
    "Korea": ["korea", "south korea", "kr"],
    "India": ["india", "in"],
    "Hong Kong": ["hong kong", "hk"],
    "Singapore": ["singapore", "sg"],
    "Vietnam": ["vietnam", "vn"],
}

# --- Currency ----------------------------------------------------------------
# Per-source currency. Real exports rarely tag currency, so we infer it from
# the source file (which is the honest, reproducible choice for a demo).
# Amounts are converted to a single reporting currency (USD) using a fixed,
# clearly-documented rate table — NOT a live feed — so results are deterministic.
SOURCE_CURRENCY = {
    "sales_region_us.csv": "USD",
    "sales_region_eu.csv": "EUR",
    "sales_region_apac.csv": "LOCAL",  # mixed; resolved per-country below
}

# APAC file mixes currencies by country; map country -> currency.
APAC_COUNTRY_CURRENCY = {
    "Japan": "JPY",
    "Korea": "KRW",
    "India": "INR",
    "Hong Kong": "HKD",
    "Singapore": "SGD",
    "Vietnam": "VND",
}

# Fixed demo FX rates -> USD. Documented as illustrative, not market data.
FX_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "JPY": 0.0067,
    "KRW": 0.00075,
    "INR": 0.012,
    "HKD": 0.128,
    "SGD": 0.74,
    "VND": 0.000041,
}

# --- Validation rules --------------------------------------------------------
MIN_QUANTITY = 1          # quantities below this are flagged as invalid
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# Reporting currency for the unified output.
REPORTING_CURRENCY = "USD"
