# Spreadsheet & Data Automation — Portfolio Samples

Self-made demos showcasing **spreadsheet/data automation** and **AI-powered data extraction**.

> These are **demonstration samples built to show capability — not client work.**
> No real client data, names, or logos are included. All sample data is synthetic.
> Built with AI assistance under human review.

## Projects

### 1. [`01-spreadsheet-cleaner`](01-spreadsheet-cleaner) — Messy multi-CSV → clean, merged, validated Excel
Fully working. Reads inconsistent CSV exports (different columns, delimiters, date/currency
formats), then cleans, validates, de-duplicates, and merges them into one report-ready Excel
workbook (Summary / Clean / Rejected / Issue Log). Every repaired or rejected row is logged
with a reason. **Python (pandas, openpyxl), config-driven, with unit tests.** Sample input and
generated output included.

### 2. [`02-web-scraper`](02-web-scraper) — Public web listings → structured CSV + JSON
A compliant scraper with cleanly separated stages (fetch → parse → normalize → export).
**robots.txt is checked before every request,** with rate limiting, an identifying User-Agent,
and retry-with-backoff. Working skeleton that runs offline against a bundled sample page.

### 3. [`03-ai-data-extraction`](03-ai-data-extraction) — Documents → schema-validated JSON (AI)
Turns unstructured documents (invoices, emails) into validated, structured JSON. An LLM sits
behind a clean interface inside a testable pipeline, with a **strict JSON-schema validation
gate**: incomplete extractions are rejected with a reason, never passed silently. Runs offline
with a deterministic stand-in (no API key, no cost); documents where a real model plugs in.

## How I work
- **Quality gate:** tested against real sample data before delivery.
- **Auditable:** every fix or rejection is logged with a reason — nothing breaks silently.
- **Transparent about AI:** modern tools used to work faster, with human review on every deliverable.

Each project folder has its own README, source code, sample data, and generated output.
