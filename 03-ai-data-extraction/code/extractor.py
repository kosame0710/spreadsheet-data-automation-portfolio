"""
extractor.py — Skeleton of an LLM-powered pipeline that turns unstructured
documents (invoices, emails, receipts) into validated structured JSON, scores
each extraction with a deterministic **confidence**, and flags low-confidence or
boundary cases for **human review**.

Growth-niche portfolio sample: "AI + data extraction / ETL".

It runs **offline by default** using a deterministic mock extractor, so the demo
works with no API key and no spend, while showing exactly where a real LLM call
slots in. Swap `MockLLMClient` for `AnthropicLLMClient` (sketched below) and the
rest of the pipeline is unchanged.

Why it is designed this way:
  * The LLM is treated as one *replaceable component* behind an `LLMClient`
    interface — the pipeline (load -> prompt -> call -> validate -> score ->
    export) is deterministic and testable around it.
  * Every model output is **validated against a JSON schema** before it is
    trusted. LLMs can hallucinate or drift; unvalidated extraction is a liability.
  * Every *valid* extraction is then **scored** for confidence from transparent,
    deterministic signals (field presence, pattern match, and a totals
    cross-check). Anything low-confidence or on a validation boundary is flagged
    `needs_review` with a human-readable reason, and split into a separate
    review subset — so a person checks the uncertain rows, not all of them.
  * Strong typing of the target schema makes the contract explicit and the
    output safe to load into a database or spreadsheet.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, Protocol

# --------------------------------------------------------------------------- #
# Target schema — what we want to pull out of every document.
# --------------------------------------------------------------------------- #
INVOICE_SCHEMA = {
    "type": "object",
    "required": ["invoice_number", "invoice_date", "vendor", "total", "currency", "line_items"],
    "properties": {
        "invoice_number": {"type": "string"},
        "invoice_date": {"type": "string"},          # ISO 8601 (YYYY-MM-DD)
        "vendor": {"type": "string"},
        "currency": {"type": "string"},               # ISO 4217, e.g. USD
        "total": {"type": "number"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["description", "quantity", "unit_price"],
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                },
            },
        },
    },
}

EXTRACTION_PROMPT = """You are a precise data-extraction engine. Read the document\
 below and return ONLY a JSON object matching this schema (no prose, no markdown):

{schema}

Rules:
- Dates must be ISO 8601 (YYYY-MM-DD).
- Numbers must be plain numbers (no currency symbols or thousands separators).
- currency must be a 3-letter ISO 4217 code.
- If a field is genuinely absent, use null. Do not invent values.

DOCUMENT:
\"\"\"
{document}
\"\"\"
"""

# Default cutoff: an extraction scoring below this is flagged for human review.
DEFAULT_REVIEW_THRESHOLD = 0.85

# Totals are considered "reconciled" if the stated total is within this relative
# tolerance of the line-item sum (covers tax/rounding without being naive).
TOTAL_TOLERANCE = 0.10

# Regex shapes used both for extraction quality scoring and review checks.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_INVOICE_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]*\d[A-Za-z0-9\-]*$")


# --------------------------------------------------------------------------- #
# LLM client abstraction
# --------------------------------------------------------------------------- #
class LLMClient(Protocol):
    """Anything that can turn a prompt into a model response string."""
    def complete(self, prompt: str) -> str: ...


class MockLLMClient:
    """Deterministic stand-in for a real LLM, used for the offline demo.

    It applies simple, transparent regex rules to the sample invoices so the
    pipeline produces real, validatable output without any API call. This is
    NOT how production extraction works — it exists only so the demo is
    runnable and reproducible. The production path is `AnthropicLLMClient`.
    """

    def complete(self, prompt: str) -> str:
        doc = prompt.split('DOCUMENT:', 1)[-1]
        result = {
            "invoice_number": _extract_invoice_number(doc),
            "invoice_date": _normalize_date(
                _search(r"Date\s*[:\-]?\s*([0-9A-Za-z ,/\.\-]+)", doc)
            ),
            "vendor": _search(r"(?:From|Vendor|Seller)\s*[:\-]?\s*(.+)", doc),
            "currency": _guess_currency(doc),
            "total": _extract_total(doc),
            "line_items": _extract_line_items(doc),
        }
        return json.dumps(result)


# Production client (sketch — left uninstantiated so the demo needs no SDK/key):
#
# class AnthropicLLMClient:
#     """Real extraction via the Anthropic API. Requires `anthropic` + an API key
#     supplied through the environment (never hard-coded)."""
#     def __init__(self, model: str = "claude-3-5-sonnet-latest"):
#         import anthropic                       # imported lazily
#         self._client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env
#         self._model = model
#
#     def complete(self, prompt: str) -> str:
#         msg = self._client.messages.create(
#             model=self._model,
#             max_tokens=1024,
#             messages=[{"role": "user", "content": prompt}],
#         )
#         return msg.content[0].text


# --------------------------------------------------------------------------- #
# Mock-extractor helpers (regex heuristics — demo only)
# --------------------------------------------------------------------------- #
def _search(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _to_number(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.replace(",", "").strip()
    try:
        return round(float(value), 2)
    except ValueError:
        return None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _normalize_date(value: Optional[str]) -> Optional[str]:
    """Best-effort conversion of a date string to ISO 8601."""
    if not value:
        return None
    value = value.strip()
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if iso:
        return iso.group(0)
    # e.g. "March 5, 2024" / "Mar 5 2024"
    m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", value)
    if m and m.group(1)[:3].lower() in _MONTHS:
        month = _MONTHS[m.group(1)[:3].lower()]
        return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(2)):02d}"
    return value  # leave as-is; schema validation will flag if unusable


def _extract_invoice_number(doc: str) -> Optional[str]:
    """Find an invoice identifier (a token containing at least one digit).

    Requires the matched token to contain a digit, so prose like
    'invoice details' is not mistaken for an invoice number.
    """
    m = re.search(r"Invoice\s*#?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-]*\d[A-Za-z0-9\-]*)",
                  doc, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _extract_total(doc: str) -> Optional[float]:
    """Find the grand total, preferring an explicit 'Total' over a subtotal.

    Handles both label-first ('Total: 1538.97') and prose
    ('the total amount due is 281.00 USD') phrasings. 'Subtotal' is excluded so
    we don't mistake it for the final amount.
    """
    candidates = []
    for m in re.finditer(
        r"(?<!sub)(?:total|amount due)\D{0,20}?([0-9][0-9.,]*)", doc, re.IGNORECASE
    ):
        num = _to_number(m.group(1))
        if num is not None:
            candidates.append(num)
    if not candidates:
        return None
    # The grand total is the largest of the matched totals (>= subtotal/tax).
    return max(candidates)


def _guess_currency(doc: str) -> Optional[str]:
    if "$" in doc or re.search(r"\bUSD\b", doc):
        return "USD"
    if "€" in doc or re.search(r"\bEUR\b", doc):
        return "EUR"
    if re.search(r"\bGBP\b", doc) or "£" in doc:
        return "GBP"
    return None


def _extract_line_items(doc: str) -> list[dict]:
    """Parse 'qty x description @ price' style lines from the sample invoices."""
    items = []
    for line in doc.splitlines():
        m = re.match(r"\s*(\d+)\s*x\s*(.+?)\s*@\s*\$?([0-9.,]+)", line, re.IGNORECASE)
        if m:
            items.append(
                {
                    "description": m.group(2).strip(),
                    "quantity": float(m.group(1)),
                    "unit_price": _to_number(m.group(3)),
                }
            )
    return items


# --------------------------------------------------------------------------- #
# Validation (minimal JSON-schema checker — no third-party dependency)
# --------------------------------------------------------------------------- #
class ValidationError(Exception):
    pass


def validate(instance, schema, path: str = "$") -> None:
    """Validate *instance* against a small subset of JSON Schema.

    Supports the keywords this pipeline uses: type, required, properties, items.
    In production I use the `jsonschema` library; this self-contained checker
    keeps the demo dependency-free while still proving the *principle* that no
    model output is trusted until it conforms to the contract.
    """
    expected = schema.get("type")
    type_map = {
        "object": dict, "array": list, "string": str,
        "number": (int, float), "boolean": bool,
    }
    if expected and not isinstance(instance, type_map[expected]):
        if not (expected == "number" and isinstance(instance, bool) is False
                and isinstance(instance, (int, float))):
            raise ValidationError(f"{path}: expected {expected}, got {type(instance).__name__}")

    if expected == "object":
        for key in schema.get("required", []):
            if instance.get(key) is None:
                raise ValidationError(f"{path}.{key}: required field is missing/null")
        for key, subschema in schema.get("properties", {}).items():
            if key in instance and instance[key] is not None:
                validate(instance[key], subschema, f"{path}.{key}")

    if expected == "array":
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(instance):
                validate(item, item_schema, f"{path}[{i}]")


# --------------------------------------------------------------------------- #
# Confidence scoring + human-review flagging
# --------------------------------------------------------------------------- #
# These run only on extractions that already PASSED schema validation. They
# answer a different question than validation: not "is it well-formed?" but
# "how much should we trust it, and does a human need to look?".
#
# Scores are deterministic: the same input always yields the same confidence,
# with no LLM call and no randomness. Each field score is built from transparent
# signals (presence + pattern match), and `total` gets an extra cross-check
# against the line-item sum — a strong, real signal that the number hangs
# together. This is exactly the "confidence checks + a human-review column"
# the pipeline advertises, implemented in a way that also works for the offline
# stand-in. A real LLM client can additionally feed model-reported token/logprob
# confidence into `field_confidence` without changing the rest of the pipeline.

# Per-field weights when combining into an overall record confidence. `total`
# and `invoice_number` carry the most weight because they are the costliest to
# get wrong on an invoice.
_FIELD_WEIGHTS = {
    "invoice_number": 1.5,
    "invoice_date": 1.0,
    "vendor": 1.0,
    "currency": 0.75,
    "total": 1.5,
    "line_items": 1.0,
}


def _line_items_sum(line_items: list[dict]) -> Optional[float]:
    """Sum quantity * unit_price across line items, or None if not computable."""
    if not line_items:
        return None
    subtotal = 0.0
    for item in line_items:
        qty = item.get("quantity")
        price = item.get("unit_price")
        if qty is None or price is None:
            return None
        subtotal += qty * price
    return round(subtotal, 2)


def _totals_reconcile(total: Optional[float], line_items: list[dict]) -> Optional[bool]:
    """Does the stated total agree with the line-item sum (within tolerance)?

    Returns True/False when both are available, or None when there is nothing to
    compare (e.g. no line items), so callers can distinguish "checked and OK"
    from "could not check".
    """
    subtotal = _line_items_sum(line_items)
    if total is None or subtotal is None:
        return None
    if total <= 0:
        return False
    # A grand total is >= subtotal (tax/fees added). Allow a tolerance band and
    # never reward a total that is *below* the line-item sum.
    if subtotal - total > TOTAL_TOLERANCE * max(subtotal, 1.0):
        return False
    return (total - subtotal) <= TOTAL_TOLERANCE * max(subtotal, total)


def field_confidence(record: dict) -> dict:
    """Per-field confidence in [0, 1] from deterministic signals.

    Each field starts from presence (is it there at all?) and is adjusted by how
    well the value matches the shape we expect for that field.
    """
    scores: dict[str, float] = {}

    # invoice_number: present + matches an identifier pattern (has a digit).
    inv = record.get("invoice_number")
    if not inv:
        scores["invoice_number"] = 0.0
    elif _INVOICE_NO_RE.match(inv):
        scores["invoice_number"] = 1.0
    else:
        scores["invoice_number"] = 0.6

    # invoice_date: present + normalized to ISO 8601 (un-normalized => low).
    date = record.get("invoice_date")
    if not date:
        scores["invoice_date"] = 0.0
    elif _ISO_DATE_RE.match(date):
        scores["invoice_date"] = 1.0
    else:
        scores["invoice_date"] = 0.4  # parsed something, but not ISO — verify it

    # vendor: present and not suspiciously short.
    vendor = record.get("vendor")
    if not vendor:
        scores["vendor"] = 0.0
    elif len(vendor.strip()) >= 3:
        scores["vendor"] = 0.95
    else:
        scores["vendor"] = 0.6

    # currency: present + valid ISO 4217 shape.
    currency = record.get("currency")
    if not currency:
        scores["currency"] = 0.0
    elif _ISO_CURRENCY_RE.match(currency):
        scores["currency"] = 1.0
    else:
        scores["currency"] = 0.5

    # total: present + reconciles with the line-item sum (the key cross-check).
    total = record.get("total")
    line_items = record.get("line_items") or []
    if total is None:
        scores["total"] = 0.0
    else:
        reconciled = _totals_reconcile(total, line_items)
        if reconciled is True:
            scores["total"] = 1.0
        elif reconciled is False:
            scores["total"] = 0.3   # number present but doesn't add up — check it
        else:
            scores["total"] = 0.7   # present, but no line items to cross-check

    # line_items: present and each row fully populated.
    if not line_items:
        scores["line_items"] = 0.3   # valid to have none, but worth a glance
    else:
        complete = all(
            i.get("description") and i.get("quantity") is not None
            and i.get("unit_price") is not None
            for i in line_items
        )
        scores["line_items"] = 1.0 if complete else 0.6

    return {k: round(v, 3) for k, v in scores.items()}


def record_confidence(field_scores: dict) -> float:
    """Weighted mean of field confidences -> overall record confidence."""
    num = sum(field_scores[k] * _FIELD_WEIGHTS.get(k, 1.0) for k in field_scores)
    den = sum(_FIELD_WEIGHTS.get(k, 1.0) for k in field_scores)
    return round(num / den, 3) if den else 0.0


def review_reasons(record: dict, field_scores: dict, threshold: float) -> list[str]:
    """Human-readable reasons an extraction should be reviewed (may be empty).

    These are the boundary/quality conditions a person should eyeball before the
    row is trusted downstream — kept explicit so the spreadsheet shows *why* a
    row is flagged, not just that it is.
    """
    reasons: list[str] = []

    # Per-field low confidence -> name the weak fields explicitly.
    weak = sorted(f for f, s in field_scores.items() if s < 0.5)
    if weak:
        reasons.append("low-confidence field(s): " + ", ".join(weak))

    # Date present but not normalized to ISO 8601.
    date = record.get("invoice_date")
    if date and not _ISO_DATE_RE.match(date):
        reasons.append(f"date not normalized to ISO 8601: {date!r}")

    # Currency present but not a clean ISO 4217 code.
    currency = record.get("currency")
    if currency and not _ISO_CURRENCY_RE.match(currency):
        reasons.append(f"currency not a valid ISO 4217 code: {currency!r}")

    # Totals cross-check failed (stated total disagrees with line-item sum).
    line_items = record.get("line_items") or []
    if _totals_reconcile(record.get("total"), line_items) is False:
        subtotal = _line_items_sum(line_items)
        reasons.append(
            f"total {record.get('total')} does not reconcile with line-item sum {subtotal}"
        )

    # No line items captured (the body may not have parsed).
    if not line_items:
        reasons.append("no line items extracted")

    # Overall score under the configured cutoff.
    overall = record_confidence(field_scores)
    if overall < threshold:
        reasons.append(
            f"overall confidence {overall} below review threshold {threshold}"
        )

    # De-duplicate while preserving order.
    seen, unique = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def score_record(record: dict, threshold: float = DEFAULT_REVIEW_THRESHOLD) -> dict:
    """Attach confidence, needs_review and review_reasons to a validated record."""
    field_scores = field_confidence(record)
    overall = record_confidence(field_scores)
    reasons = review_reasons(record, field_scores, threshold)
    record["confidence"] = overall
    record["field_confidence"] = field_scores
    record["needs_review"] = bool(reasons)
    record["review_reasons"] = reasons
    return record


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def extract_document(text: str, client: LLMClient) -> dict:
    """Run one document through the LLM client and parse its JSON response."""
    prompt = EXTRACTION_PROMPT.format(
        schema=json.dumps(INVOICE_SCHEMA, indent=2), document=text
    )
    raw = client.complete(prompt)
    # Models sometimes wrap JSON in prose/markdown; extract the JSON object.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValidationError("model response contained no JSON object")
    return json.loads(match.group(0))


def process_folder(
    input_dir: Path,
    client: LLMClient,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
) -> dict:
    """Extract every .txt document in *input_dir*; validate, score, and triage.

    Output keys:
      * ``extracted``   — every extraction that passed schema validation, each
                          carrying ``confidence`` / ``needs_review`` / reasons.
      * ``needs_review``— the subset of ``extracted`` flagged for a human
                          (separated out so reviewers see only the uncertain rows).
      * ``failed``      — documents rejected by the validation gate, with reasons.
      * ``summary``     — counts for a quick at-a-glance read.
    """
    results, failures = [], []
    for path in sorted(Path(input_dir).glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        try:
            data = extract_document(text, client)
            validate(data, INVOICE_SCHEMA)        # hard gate: reject if invalid
            data["_source_file"] = path.name
            score_record(data, review_threshold)  # confidence + review flagging
            results.append(data)
        except (ValidationError, json.JSONDecodeError) as err:
            failures.append({"_source_file": path.name, "error": str(err)})

    review_subset = [r for r in results if r["needs_review"]]
    return {
        "summary": {
            "extracted": len(results),
            "needs_review": len(review_subset),
            "auto_approved": len(results) - len(review_subset),
            "failed": len(failures),
            "review_threshold": review_threshold,
        },
        "extracted": results,
        "needs_review": review_subset,
        "failed": failures,
    }


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Extract structured JSON from documents.")
    parser.add_argument("--input", type=Path, default=here.parent / "sample_data")
    parser.add_argument("--output", type=Path, default=here.parent / "output")
    parser.add_argument("--review-threshold", type=float, default=DEFAULT_REVIEW_THRESHOLD,
                        help="Confidence below which a row is flagged for human review "
                             f"(default {DEFAULT_REVIEW_THRESHOLD}).")
    # --live would select AnthropicLLMClient; off by default so no key/spend needed.
    parser.add_argument("--live", action="store_true",
                        help="Use the real LLM client (requires anthropic + API key).")
    args = parser.parse_args(argv)

    if args.live:
        raise SystemExit("Live mode is a documented extension point; wire up "
                         "AnthropicLLMClient and an API key to enable it.")
    client: LLMClient = MockLLMClient()

    outcome = process_folder(args.input, client, args.review_threshold)
    args.output.mkdir(parents=True, exist_ok=True)
    out_path = args.output / "extracted_invoices.json"
    out_path.write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding="utf-8")

    # A separate file holds just the review subset, so a reviewer can open the
    # uncertain rows without wading through the auto-approved ones.
    review_path = args.output / "needs_review.json"
    review_path.write_text(
        json.dumps(outcome["needs_review"], indent=2, ensure_ascii=False), encoding="utf-8"
    )

    s = outcome["summary"]
    print(f"Documents extracted OK : {s['extracted']}")
    print(f"  auto-approved        : {s['auto_approved']}")
    print(f"  needs human review   : {s['needs_review']}")
    print(f"Documents failed       : {s['failed']}")
    print(f"Output                 : {out_path}")
    print(f"Review subset          : {review_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
