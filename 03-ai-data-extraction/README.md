# AI-Powered Document → Structured JSON Extraction (with confidence + human-review flags)

> **Self-made portfolio sample** in my growth niche: **AI + data extraction /
> ETL**. It turns unstructured documents (invoices, emails, receipts) into
> **validated, structured JSON** ready for a database or spreadsheet — then
> **scores each extraction's confidence** and **flags low-confidence or
> boundary cases for human review** so a person checks only the uncertain rows.
> Runs **offline by default** with a deterministic mock extractor — **no API key
> and no spend** — while showing exactly where a real LLM call slots in.

---

## The problem

Huge amounts of business data are trapped in **unstructured text**: emailed
invoices, PDFs, receipts, support tickets. People re-key it into spreadsheets by
hand — slow, expensive, and error-prone. Naive automation breaks because every
document is laid out differently. And once you add an LLM, a new risk appears:
the model can be **confidently wrong**, so you can't just trust every row.

## The solution

A pipeline that treats the LLM as **one replaceable component** behind a clean
interface, with a hard **validation gate** so malformed output is never trusted,
and a **confidence + human-review layer** so the uncertain-but-valid rows get a
person's eyes before they reach your spreadsheet:

```
 load doc -> build prompt -> LLM client -> parse JSON -> VALIDATE vs schema -> SCORE confidence -> export
                              (swappable)                  (reject if invalid)   (flag for review)   + review subset
```

- **`LLMClient` interface** with two implementations:
  - `MockLLMClient` — deterministic, transparent heuristics for the offline demo.
  - `AnthropicLLMClient` — production path (sketched in code), reads the API key
    from the environment, never hard-coded.
- **JSON-schema validation of every extraction.** A document missing a required
  field (e.g. no invoice number) is moved to a `failed` list with the exact
  reason — it is *not* silently passed through. LLMs can hallucinate, so
  unvalidated extraction is a liability.
- **Confidence score on every valid extraction** — per field *and* overall —
  computed from deterministic signals (see below).
- **`needs_review` flag + reasons** on low-confidence or boundary rows, with the
  flagged subset **separated into its own key and file** so a reviewer opens only
  the rows that need judgment, not all of them.
- **Strongly-typed target schema** (`INVOICE_SCHEMA`) so the output contract is
  explicit and safe to load downstream.

### How confidence is computed (deterministic — no LLM needed)

Confidence is a **real, reproducible value**, not a guess: the same input always
yields the same score, with no model call and no randomness. Each field's score
comes from transparent signals:

| Signal | Example |
|---|---|
| **Presence** | Is the field there at all (non-null)? |
| **Pattern match** | Date is ISO 8601 `YYYY-MM-DD`; currency is a 3-letter ISO 4217 code; invoice number looks like an identifier; line items fully populated. |
| **Cross-check** | Does `total` reconcile with `Σ(quantity × unit_price)` within tolerance (tax/rounding allowed, but a total *below* the line-item sum is penalised)? |

The overall record confidence is a weighted mean of the field scores (`total`
and `invoice_number` weigh most — the costliest fields to get wrong). A record is
flagged **`needs_review`** when any of these fire, each recorded as a plain-text
reason:

- overall confidence below the review threshold (default **0.85**, `--review-threshold` to tune);
- a date that parsed but isn't ISO 8601;
- a currency that isn't a clean ISO 4217 code;
- a `total` that doesn't reconcile with the line-item sum;
- no line items captured;
- any individual field scoring below 0.5.

> When you wire up the real `AnthropicLLMClient`, model-reported token/logprob
> confidence can be folded into `field_confidence` too — the rest of the
> pipeline (validation, flagging, review subset, export) is unchanged.

## Before / After

| | **Before** (validation only) | **After** (this version) |
|---|---|---|
| Output | `extracted` + `failed` | adds per-record **`confidence`**, **`field_confidence`**, **`needs_review`**, **`review_reasons`**, a **`summary`**, and a separated **`needs_review`** subset |
| Trust model | binary: valid or rejected | graded: rejected ▸ valid-but-flagged ▸ auto-approved |
| Human review | none — every valid row trusted equally | reviewer opens only the flagged subset (`output/needs_review.json`) |
| Totals | not checked | cross-checked against line items; mismatches flagged |
| Tests | 5 | 14 |

This makes the demo actually show the **"confidence checks + a human-review
column"** the AI-extraction service is pitched on — previously that was described
but not implemented.

## What it demonstrates

- Designing an **LLM-in-the-loop ETL pipeline** that stays deterministic and
  testable around a non-deterministic model.
- **Schema-validated extraction** (the trust boundary every serious LLM data
  product needs).
- **Confidence scoring + human-in-the-loop triage** from transparent,
  deterministic signals — the uncertain rows are separated for review.
- A clean **swap from mock → real model** with zero pipeline changes.
- Honest handling of **partial/garbage documents** (separated, with reasons).
- **API-key safety**: secrets come from the environment, never the codebase.

## How to run (offline, no key required)

```bash
cd code
python extractor.py        # extracts from ../sample_data/*.txt using the mock client
python extractor.py --review-threshold 0.95   # stricter: flag more rows for review
python -m unittest discover -p "test_*.py"     # 14 tests
```

**Verified sample run** over three documents of different shapes (a formatted
invoice, an email-style invoice, and an incomplete quote):

```
Documents extracted OK : 2
  auto-approved        : 1
  needs human review   : 1
Documents failed       : 1
```

- `invoice_01.txt` → `INV-2024-0481`, total **1538.97**, 3 line items.
  **Auto-approved**, confidence **0.993** (the total reconciles with the line
  items once 8% tax is allowed within tolerance).
- `invoice_02.txt` (email prose) → `GLX-99213`, total **329.00**, 2 line items.
  **Flagged `needs_review`**, confidence **0.837** — the stated total (which
  includes un-itemized rush shipping) doesn't reconcile with the line-item sum
  of 281.00, so a human should confirm it before it's trusted.
- `invoice_03_incomplete.txt` (a quote with no invoice number/total) →
  **rejected** by schema validation: `$.invoice_number: required field is missing/null`.

Full output: `output/extracted_invoices.json`. The flagged subset on its own:
`output/needs_review.json`.

**Example flagged record** (from `output/needs_review.json`):

```json
{
  "invoice_number": "GLX-99213",
  "invoice_date": "2024-02-18",
  "vendor": "Globex International",
  "currency": "USD",
  "total": 329.0,
  "line_items": [
    { "description": "HDMI Adapter 4K", "quantity": 3.0, "unit_price": 12.0 },
    { "description": "Webcam", "quantity": 5.0, "unit_price": 49.0 }
  ],
  "_source_file": "invoice_02.txt",
  "confidence": 0.837,
  "field_confidence": {
    "invoice_number": 1.0, "invoice_date": 1.0, "vendor": 0.95,
    "currency": 1.0, "total": 0.3, "line_items": 1.0
  },
  "needs_review": true,
  "review_reasons": [
    "low-confidence field(s): total",
    "total 329.0 does not reconcile with line-item sum 281.0",
    "overall confidence 0.837 below review threshold 0.85"
  ]
}
```

### Switching to a real LLM
1. `pip install anthropic` and set `ANTHROPIC_API_KEY` in your environment.
2. Un-comment / instantiate `AnthropicLLMClient` in `extractor.py` (the class is
   sketched and the `--live` flag is wired as the entry point).
3. Everything else — prompt, validation, confidence scoring, review flagging,
   export — is unchanged.

In production I also use the `jsonschema` library instead of the small
self-contained validator bundled here (kept dependency-free so the demo runs
anywhere).

## Project layout

```
03-ai-data-extraction/
├── README.md
├── code/
│   ├── extractor.py        ← pipeline + LLMClient interface + schema validator + confidence/review scoring
│   └── test_extractor.py   ← validation + confidence/review + end-to-end tests (14)
├── sample_data/            ← three unstructured sample documents (.txt)
└── output/
    ├── extracted_invoices.json   ← full results (2 extracted, 1 flagged, 1 rejected) + summary
    └── needs_review.json         ← just the flagged subset, for a reviewer
```

## Scope of this sample (honest framing)

- This is a **working skeleton + offline demo**. The bundled extractor uses
  transparent regex heuristics as a stand-in for the model so results are
  reproducible without an API key. **Real extraction accuracy comes from the
  LLM**, which is the documented production swap. The **confidence scoring and
  human-review flagging are fully implemented and run offline** — they are
  deterministic and don't depend on the LLM.
- Inputs here are plain text. For PDFs/scans I add a text-extraction / OCR step
  ahead of this pipeline (out of scope for the offline sample).

**AI disclosure:** This sample is *about* using AI for extraction, and was also
built with AI assistance under human supervision.
