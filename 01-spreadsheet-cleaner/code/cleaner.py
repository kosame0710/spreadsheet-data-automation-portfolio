"""
cleaner.py — Generic cleaning/normalization engine.

The engine takes messy CSV exports (varying delimiters, headers, date and
number formats) and turns them into one tidy, validated dataset following the
canonical schema in `config.py`.

Design goals (kept deliberately boring and explicit so it is easy to hand off):
  * Pure functions where possible; each does one thing.
  * Every row that is dropped or repaired is recorded with a reason, so the
    transformation is auditable rather than a black box.
  * No business specifics hard-coded here — they live in config.py.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd

import config


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass
class CleanResult:
    """Everything produced by a cleaning run, ready for reporting/export."""

    clean: pd.DataFrame                          # validated, deduplicated rows
    rejected: pd.DataFrame                       # rows pulled out of the clean set
    issues: list[dict] = field(default_factory=list)  # per-issue audit log
    stats: dict = field(default_factory=dict)         # summary counters

    def log(self, source: str, row_id, column: str, problem: str, action: str) -> None:
        self.issues.append(
            {
                "source_file": source,
                "row_id": row_id,
                "column": column,
                "problem": problem,
                "action": action,
            }
        )


# --------------------------------------------------------------------------- #
# Small text helpers
# --------------------------------------------------------------------------- #
def _normalize_key(text: str) -> str:
    """Normalize a header/value for *matching* (lowercase, collapse punctuation)."""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii")  # drop accents for keys
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)  # punctuation -> space
    return re.sub(r"\s+", " ", text).strip()


def _clean_text(value) -> str:
    """Trim, collapse internal whitespace; return '' for null-ish values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _build_alias_lookup(alias_map: dict[str, list[str]]) -> dict[str, str]:
    """Invert a {canonical: [variants]} map into {normalized_variant: canonical}."""
    lookup: dict[str, str] = {}
    for canonical, variants in alias_map.items():
        for v in variants:
            lookup[_normalize_key(v)] = canonical
    return lookup


# --------------------------------------------------------------------------- #
# Field parsers
# --------------------------------------------------------------------------- #
# Accepted date formats, tried in order. Covers ISO, US, EU and textual styles.
_DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d",
    "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y",
    "%m/%d/%Y",
    "%b %d %Y", "%B %d %Y",
]


def parse_date(raw: str) -> Optional[date]:
    """Parse a date written in any of several common formats.

    Returns a ``date`` or ``None`` if nothing matches. We intentionally try a
    fixed list of formats instead of a fuzzy parser so behaviour is predictable
    and a genuinely invalid value (e.g. 2024-13-45) is rejected, not guessed.
    """
    raw = _clean_text(raw)
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_quantity(raw: str) -> Optional[int]:
    """Parse an integer quantity; return None if not a clean whole number."""
    raw = _clean_text(raw)
    if not raw:
        return None
    try:
        # Allow "3", "3.0" but reject "abc"/"impossible".
        value = float(raw)
    except ValueError:
        return None
    if value != int(value):
        return None
    return int(value)


def parse_amount(raw: str) -> Optional[float]:
    """Parse a monetary amount, stripping currency symbols and locale separators.

    Handles US style ($1,299.00) and European style (1.299,00 €) by detecting
    which of '.'/',' is the decimal separator from their positions.
    """
    raw = _clean_text(raw)
    if not raw:
        return None

    # Strip everything except digits, separators and a leading sign.
    cleaned = re.sub(r"[^0-9.,-]", "", raw)
    if cleaned in ("", "-", ".", ","):
        return None

    has_dot = "." in cleaned
    has_comma = "," in cleaned
    if has_dot and has_comma:
        # Whichever appears last is the decimal separator.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")  # EU: 1.299,00
        else:
            cleaned = cleaned.replace(",", "")                    # US: 1,299.00
    elif has_comma:
        # Lone comma: decimal if it looks like cents (",dd"), else a thousands sep.
        if re.search(r",\d{1,2}$", cleaned):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    # lone dot -> already valid

    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def is_valid_email(raw: str) -> bool:
    return bool(re.match(config.EMAIL_REGEX, _clean_text(raw)))


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def _sniff_delimiter(path: Path) -> str:
    """Detect the delimiter from the header line (comma vs semicolon vs tab)."""
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        sample = fh.readline()
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        # Fall back to the most common separator present in the header.
        return max([",", ";", "\t", "|"], key=sample.count)


def read_source(path: Path) -> pd.DataFrame:
    """Read one CSV into a DataFrame with canonical column names.

    Unknown columns are dropped; missing canonical columns are added as empty
    so every source yields the same shape downstream.
    """
    delimiter = _sniff_delimiter(path)
    df = pd.read_csv(
        path,
        sep=delimiter,
        dtype=str,                # keep raw text; we parse types ourselves
        encoding="utf-8-sig",
        keep_default_na=False,    # treat blanks as "" not NaN, so logs are clean
        skipinitialspace=True,
    )

    header_lookup = _build_alias_lookup(config.HEADER_ALIASES)
    rename = {}
    for col in df.columns:
        canonical = header_lookup.get(_normalize_key(col))
        if canonical:
            rename[col] = canonical
    df = df.rename(columns=rename)

    # Keep only known columns; add any missing canonical ones as blank.
    df = df[[c for c in df.columns if c in config.CANONICAL_COLUMNS]]
    for col in config.CANONICAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[config.CANONICAL_COLUMNS].copy()
    df["source_file"] = path.name
    return df


# --------------------------------------------------------------------------- #
# Currency resolution
# --------------------------------------------------------------------------- #
def _resolve_currency(source_file: str, country: str) -> str:
    """Pick the source currency for a row (per-file, or per-country for APAC)."""
    base = config.SOURCE_CURRENCY.get(source_file, "USD")
    if base == "LOCAL":
        return config.APAC_COUNTRY_CURRENCY.get(country, "USD")
    return base


# --------------------------------------------------------------------------- #
# Main cleaning pipeline
# --------------------------------------------------------------------------- #
def clean_frame(raw: pd.DataFrame, result: CleanResult) -> pd.DataFrame:
    """Normalize, validate and type-convert every row of the combined frame.

    Rows that fail a hard validation rule (unparseable date/amount, invalid or
    missing email, quantity below the minimum) are tagged and later moved to the
    rejected set. Everything is logged for the audit report.
    """
    country_lookup = _build_alias_lookup(config.COUNTRY_ALIASES)
    out_rows = []

    for _, row in raw.iterrows():
        src = row["source_file"]
        rid = _clean_text(row["order_id"]) or "(blank)"
        reasons: list[str] = []

        # --- text fields ---
        customer = _clean_text(row["customer_name"])
        if not customer:
            result.log(src, rid, "customer_name", "missing customer name", "flagged")
            reasons.append("missing customer_name")

        email_raw = _clean_text(row["email"]).lower()
        if not email_raw:
            result.log(src, rid, "email", "missing email", "rejected")
            reasons.append("missing email")
        elif not is_valid_email(email_raw):
            result.log(src, rid, "email", f"invalid email '{email_raw}'", "rejected")
            reasons.append("invalid email")

        product = _clean_text(row["product"])

        # --- country (normalize spelling) ---
        country_norm = country_lookup.get(_normalize_key(row["country"]))
        country = country_norm or _clean_text(row["country"]).title()
        if not country_norm and _clean_text(row["country"]):
            result.log(src, rid, "country",
                       f"unrecognized country '{_clean_text(row['country'])}'",
                       "title-cased as-is")

        # --- date ---
        order_date = parse_date(row["order_date"])
        if row["order_date"].strip() == "":
            result.log(src, rid, "order_date", "missing date", "rejected")
            reasons.append("missing date")
        elif order_date is None:
            result.log(src, rid, "order_date",
                       f"unparseable date '{_clean_text(row['order_date'])}'", "rejected")
            reasons.append("unparseable date")

        # --- quantity ---
        qty = parse_quantity(row["quantity"])
        if qty is None:
            result.log(src, rid, "quantity",
                       f"non-numeric quantity '{_clean_text(row['quantity'])}'", "rejected")
            reasons.append("invalid quantity")
        elif qty < config.MIN_QUANTITY:
            result.log(src, rid, "quantity",
                       f"quantity {qty} below minimum {config.MIN_QUANTITY}", "rejected")
            reasons.append("quantity below minimum")

        # --- amount + FX to reporting currency ---
        currency = _resolve_currency(src, country)
        unit_price_local = parse_amount(row["unit_price"])
        unit_price_usd = None
        if unit_price_local is None:
            result.log(src, rid, "unit_price",
                       f"unparseable amount '{_clean_text(row['unit_price'])}'", "rejected")
            reasons.append("invalid unit_price")
        else:
            rate = config.FX_TO_USD.get(currency)
            if rate is None:
                result.log(src, rid, "unit_price",
                           f"no FX rate for currency '{currency}'", "rejected")
                reasons.append("missing FX rate")
            else:
                unit_price_usd = round(unit_price_local * rate, 2)

        line_total_usd = (
            round(unit_price_usd * qty, 2)
            if (unit_price_usd is not None and qty is not None)
            else None
        )

        out_rows.append(
            {
                "order_id": rid,
                "customer_name": customer,
                "email": email_raw,
                "order_date": order_date,
                "product": product,
                "quantity": qty,
                "currency_original": currency,
                "unit_price_original": unit_price_local,
                "unit_price_usd": unit_price_usd,
                "line_total_usd": line_total_usd,
                "country": country,
                "source_file": src,
                "_reject_reasons": "; ".join(reasons),
            }
        )

    return pd.DataFrame(out_rows)


def split_and_dedupe(df: pd.DataFrame, result: CleanResult) -> None:
    """Split into clean vs rejected, then drop duplicate orders from the clean set.

    Duplicates are matched on the *business content* of the row
    (customer, product, date, quantity, normalized USD price) rather than the
    order_id. This deliberately catches both exact re-exports and the same sale
    re-stated under a different ID or locale format — a very common artefact when
    the same data is pulled from two systems. The first occurrence is kept.
    """
    rejected = df[df["_reject_reasons"] != ""].copy()
    clean = df[df["_reject_reasons"] == ""].copy()

    dup_keys = ["customer_name", "product", "order_date", "quantity", "unit_price_usd"]
    dup_mask = clean.duplicated(subset=dup_keys, keep="first")
    for _, row in clean[dup_mask].iterrows():
        result.log(row["source_file"], row["order_id"], "(row)",
                   "duplicate order", "removed (kept first occurrence)")

    duplicates_removed = int(dup_mask.sum())
    clean = clean[~dup_mask].copy()

    # Tidy column order for the clean output (drop internal helper column).
    clean = clean.drop(columns=["_reject_reasons"]).sort_values(
        ["order_date", "order_id"], na_position="last"
    ).reset_index(drop=True)

    # Render quantity as a clean nullable integer (avoids "2.0" in outputs).
    clean["quantity"] = clean["quantity"].astype("Int64")
    rejected = rejected.reset_index(drop=True)

    result.clean = clean
    result.rejected = rejected
    result.stats["duplicates_removed"] = duplicates_removed


def run(input_dir: Path) -> CleanResult:
    """Top-level entry point: read every CSV in *input_dir*, clean, return result."""
    result = CleanResult(clean=pd.DataFrame(), rejected=pd.DataFrame())

    csv_paths = sorted(Path(input_dir).glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No CSV files found in {input_dir}")

    frames = [read_source(p) for p in csv_paths]
    combined = pd.concat(frames, ignore_index=True)
    result.stats["source_files"] = [p.name for p in csv_paths]
    result.stats["rows_in"] = int(len(combined))

    processed = clean_frame(combined, result)
    split_and_dedupe(processed, result)

    result.stats["rows_clean"] = int(len(result.clean))
    result.stats["rows_rejected"] = int(len(result.rejected))
    result.stats["issues_logged"] = int(len(result.issues))
    result.stats["total_revenue_usd"] = round(
        float(result.clean["line_total_usd"].fillna(0).sum()), 2
    )
    return result
