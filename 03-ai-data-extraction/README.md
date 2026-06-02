# AI-Powered Document → Structured JSON Extraction

> **Self-made portfolio sample** in my growth niche: **AI + data extraction /
> ETL**. It turns unstructured documents (invoices, emails, receipts) into
> **validated, structured JSON** ready for a database or spreadsheet.
> Runs **offline by default** with a deterministic mock extractor — **no API key
> and no spend** — while showing exactly where a real LLM call slots in.

---

## The problem

Huge amounts of business data are trapped in **unstructured text**: emailed
invoices, PDFs, receipts, support tickets. People re-key it into spreadsheets by
hand — slow, expensive, and error-prone. Naive automation breaks because every
document is laid out differently.

## The solution

A pipeline that treats the LLM as **one replaceable component** behind a clean
interface, with a hard **validation gate** so model output is never trusted
blindly:

```
 load doc -> build prompt -> LLM client -> parse JSON -> VALIDATE vs schema -> export
                              (swappable)                  (reject if invalid)
```

- **`LLMClient` interface** with two implementations:
  - `MockLLMClient` — deterministic, transparent heuristics for the offline demo.
  - `AnthropicLLMClient` — production path (sketched in code), reads the API key
    from the environment, never hard-coded.
- **JSON-schema validation of every extraction.** A document missing a required
  field (e.g. no total) is moved to a `failed` list with the exact reason —
  it is *not* silently passed through. This is the key reliability property:
  LLMs can hallucinate, so unvalidated extraction is a liability.
- **Strongly-typed target schema** (`INVOICE_SCHEMA`) so the output contract is
  explicit and safe to load downstream.

## What it demonstrates

- Designing an **LLM-in-the-loop ETL pipeline** that stays deterministic and
  testable around a non-deterministic model.
- **Schema-validated extraction** (the trust boundary every serious LLM data
  product needs).
- A clean **swap from mock → real model** with zero pipeline changes.
- Honest handling of **partial/garbage documents** (separated, with reasons).
- **API-key safety**: secrets come from the environment, never the codebase.

## How to run (offline, no key required)

```bash
cd code
python extractor.py        # extracts from ../sample_data/*.txt using the mock client
python -m unittest discover -p "test_*.py"   # 5 tests
```

**Verified sample run** over three documents of different shapes (a formatted
invoice, an email-style invoice, and an incomplete quote):

```
Documents extracted OK : 2
Documents failed       : 1
```
- `invoice_01.txt` → `INV-2024-0481`, total **1538.97** (correctly picks the
  grand total over the subtotal), 3 line items.
- `invoice_02.txt` (email prose) → `GLX-99213`, total **281.00**, 2 line items.
- `invoice_03_incomplete.txt` (a quote with no total) → **rejected** by schema
  validation: `$.total: required field is missing/null`.

Full output: `output/extracted_invoices.json`.

### Switching to a real LLM
1. `pip install anthropic` and set `ANTHROPIC_API_KEY` in your environment.
2. Un-comment / instantiate `AnthropicLLMClient` in `extractor.py` (the class is
   sketched and the `--live` flag is wired as the entry point).
3. Everything else — prompt, validation, export — is unchanged.

In production I also use the `jsonschema` library instead of the small
self-contained validator bundled here (kept dependency-free so the demo runs
anywhere).

## Project layout

```
03-ai-data-extraction/
├── README.md
├── code/
│   ├── extractor.py        ← pipeline + LLMClient interface + schema validator
│   └── test_extractor.py   ← validation + end-to-end tests
├── sample_data/            ← three unstructured sample documents (.txt)
└── output/extracted_invoices.json   ← example results (2 extracted, 1 rejected)
```

## Scope of this sample (honest framing)

- This is a **working skeleton + offline demo**. The bundled extractor uses
  transparent regex heuristics as a stand-in for the model so results are
  reproducible without an API key. **Real extraction accuracy comes from the
  LLM**, which is the documented production swap.
- Inputs here are plain text. For PDFs/scans I add a text-extraction / OCR step
  ahead of this pipeline (out of scope for the offline sample).

**AI disclosure:** This sample is *about* using AI for extraction, and was also
built with AI assistance under human supervision.
```
