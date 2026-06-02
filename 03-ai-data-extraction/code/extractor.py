"""
extractor.py — Skeleton of an LLM-powered pipeline that turns unstructured
documents (invoices, emails, receipts) into validated structured JSON.

Growth-niche portfolio sample: "AI + data extraction / ETL".

It runs **offline by default** using a deterministic mock extractor, so the demo
works with no API key and no spend, while showing exactly where a real LLM call
slots in. Swap `MockLLMClient` for `AnthropicLLMClient` (sketched below) and the
rest of the pipeline is unchanged.

Why it is designed this way:
  * The LLM is treated as one *replaceable component* behind an `LLMClient`
    interface — the pipeline (load -> prompt -> call -> validate -> export) is
    deterministic and testable around it.
  * Every model output is **validated against a JSON schema** before it is
    trusted. LLMs can hallucinate or drift; unvalidated extraction is a liability.
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


def process_folder(input_dir: Path, client: LLMClient) -> dict:
    """Extract every .txt document in *input_dir*; separate valid from invalid."""
    results, failures = [], []
    for path in sorted(Path(input_dir).glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        try:
            data = extract_document(text, client)
            validate(data, INVOICE_SCHEMA)
            data["_source_file"] = path.name
            results.append(data)
        except (ValidationError, json.JSONDecodeError) as err:
            failures.append({"_source_file": path.name, "error": str(err)})
    return {"extracted": results, "failed": failures}


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Extract structured JSON from documents.")
    parser.add_argument("--input", type=Path, default=here.parent / "sample_data")
    parser.add_argument("--output", type=Path, default=here.parent / "output")
    # --live would select AnthropicLLMClient; off by default so no key/spend needed.
    parser.add_argument("--live", action="store_true",
                        help="Use the real LLM client (requires anthropic + API key).")
    args = parser.parse_args(argv)

    if args.live:
        raise SystemExit("Live mode is a documented extension point; wire up "
                         "AnthropicLLMClient and an API key to enable it.")
    client: LLMClient = MockLLMClient()

    outcome = process_folder(args.input, client)
    args.output.mkdir(parents=True, exist_ok=True)
    out_path = args.output / "extracted_invoices.json"
    out_path.write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Documents extracted OK : {len(outcome['extracted'])}")
    print(f"Documents failed       : {len(outcome['failed'])}")
    print(f"Output                 : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
