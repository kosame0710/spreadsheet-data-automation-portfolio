# Multi-CSV Cleaner & Merger → Polished Excel Report

> **Self-made portfolio demo** by a Spreadsheet & Data Automation specialist.
> This is not client work — it is a working sample built to demonstrate how I
> turn messy, inconsistent spreadsheets into one clean, validated, report-ready
> dataset. All input data is synthetic and anonymized.

---

## The problem (Before)

Almost every growing business ends up with the **same sales data exported from
several different places** — one file per region, per store, or per system.
They never line up:

- **Different layouts**: `Order ID` vs `OrderID` vs `order_id`; columns in a
  different order; extra columns nobody needs.
- **Different file formats**: comma-separated vs semicolon-separated (common in
  European Excel exports), stray byte-order marks, quoted fields with commas.
- **Different date styles**: `2024-01-05`, `01/06/2024`, `05.01.2024`,
  `Jan 8 2024` — and the occasional impossible date like `2024-13-45`.
- **Different money formats**: `$1,299.00` (US) vs `1.299,00 €` (EU) vs bare
  numbers in local currency (`2980` JPY, `99000` INR).
- **Dirty values**: leading/trailing spaces, random capitalization, `USA` /
  `U.S.A.` / `us` for the same country.
- **Bad records**: invalid emails (`jane@@example.com`), non-numeric quantities
  (`abc`, `impossible`), negative or zero quantities, missing fields.
- **Duplicates**: the exact same order exported twice, or the same sale
  re-stated under a different ID / locale.

Cleaning this by hand is slow, error-prone, and has to be redone every time a
new export arrives.

## The solution (After)

A single command reads **every CSV in a folder**, regardless of layout or
locale, and produces:

1. **`cleaned_sales.xlsx`** — a formatted workbook with four sheets:
   - **Summary** — run statistics and total revenue at a glance.
   - **Clean Data** — the unified, validated, deduplicated dataset, with every
     amount converted to one reporting currency (USD).
   - **Rejected Rows** — every record that failed a validation rule, kept
     separately so nothing is silently lost.
   - **Issue Log** — a full audit trail: what was wrong, in which row, and what
     the tool did about it.
2. **`cleaned_sales.csv`** / **`rejected_rows.csv`** — the same data as plain
   text for git diffs or downstream tools.
3. **`run_report.txt`** — a human-readable summary of the run.

The transformation is **deterministic and auditable** — no value is "magically"
guessed. A genuinely invalid date is rejected and logged, not silently coerced.

---

## What it demonstrates

- Robust ingestion of **heterogeneous CSVs** (delimiter sniffing, header
  alias-mapping, encoding handling).
- Locale-aware parsing of **dates** and **money** (US vs European conventions).
- **Validation with an audit trail** — clean / rejected split, every decision
  logged.
- **Content-based de-duplication** that catches re-exports and cross-system
  duplicates, not just byte-identical rows.
- **Currency normalization** to a single reporting unit.
- Clean, **formatted Excel output** (styled headers, frozen panes, currency
  formatting, multiple sheets).
- A **config-driven design**: business specifics (schema, header aliases,
  country/currency maps, FX rates) live in `config.py`, so adapting it to a new
  client's files normally means editing config only — not the engine.

---

## How to use it

### Requirements
- Python 3.10+ (verified on **Python 3.13.1**)
- `pandas` and `openpyxl` (see `code/requirements.txt`)

```bash
cd code
pip install -r requirements.txt
```

### Run on the bundled sample data
```bash
python main.py
```
This reads the three messy CSVs in `../sample_data/` and writes all
deliverables to `../output/`.

### Run on your own files
```bash
python main.py --input "path/to/your/csvs" --output "path/to/results"
```
Every `.csv` in the input folder is read and merged. To support new column
names, currencies or countries, edit `code/config.py`.

### Run the tests
```bash
python -m unittest discover -p "test_*.py" -v
```

---

## Before / After (from the bundled sample)

**Before** — 3 incompatible files, 22 raw rows. A representative slice:

| File | Header style | Date | Price | Problems present |
|------|--------------|------|-------|------------------|
| `sales_region_us.csv`   | `Order ID, Customer Name, …` (comma) | `01/06/2024`, `Jan 8 2024` | `$1,299.00` | dup row, `jane@@`, qty `-1`/`0` |
| `sales_region_eu.csv`   | `order_id;customer;e-mail;…` (semicolon) | `05.01.2024` | `1.299,00 €` | qty `abc`, `invalid-email`, dup |
| `sales_region_apac.csv` | `OrderID, Client, …` (comma) | `2024-13-45` (invalid) | bare local currency | `impossible` amount, missing email, cross-format dup |

**After** — one clean dataset (`output/cleaned_sales.csv`), every price in USD,
quantities as integers, countries normalized:

| order_id | customer_name | order_date | product | qty | unit_price_usd | line_total_usd | country |
|----------|---------------|------------|---------|----:|---------------:|---------------:|---------|
| 1001 | John Smith    | 2024-01-05 | Wireless Mouse | 2 | 19.99 | 39.98 | United States |
| 2001 | Müller GmbH   | 2024-01-05 | Wireless Mouse | 4 | 21.59 | 86.36 | Germany |
| 2003 | Rossi SPA     | 2024-01-07 | Laptop Stand   | 2 | 1402.92 | 2805.84 | Italy |
| 3003 | Sharma Pvt Ltd| 2024-01-07 | Laptop Stand   | 1 | 1188.00 | 1188.00 | India |

**Verified run result (reproducible):**

```
 Rows read (raw)     : 22
 Rows clean          : 9
 Rows rejected       : 10
 Duplicates removed  : 3
 Issues logged       : 17
 Total revenue (USD) : 4,522.19
```

The full run log is in [`output/run_report.txt`](output/run_report.txt); the
formatted workbook is [`output/cleaned_sales.xlsx`](output/cleaned_sales.xlsx).

---

## Project layout

```
01-spreadsheet-cleaner/
├── README.md                  ← this file
├── code/
│   ├── main.py                ← CLI entry point
│   ├── cleaner.py             ← generic cleaning/validation engine
│   ├── report.py             ← Excel + text-report writers
│   ├── config.py              ← business config (schema, aliases, FX rates)
│   ├── test_cleaner.py        ← unit tests for the parsing logic
│   └── requirements.txt
├── sample_data/               ← three deliberately messy input CSVs
│   ├── sales_region_us.csv
│   ├── sales_region_eu.csv
│   └── sales_region_apac.csv
└── output/                    ← generated deliverables (committed as examples)
    ├── cleaned_sales.xlsx
    ├── cleaned_sales.csv
    ├── rejected_rows.csv
    └── run_report.txt
```

## Notes & honest limitations

- The **FX rates in `config.py` are fixed, illustrative values**, not a live
  market feed. This keeps the demo deterministic. In a real engagement I would
  wire in the client's preferred rate source (a dated rate table, or an API).
- Currency is **inferred per source file / per country** because the sample
  exports don't carry a currency column — the honest, reproducible choice for a
  sample. Real files often have an explicit currency field, which is trivial to
  map in config.
- The validation rules (e.g. minimum quantity of 1, email format) are examples;
  they are centralized in `config.py` and adjusted per client.

**AI disclosure:** This sample was built with AI assistance (code generation and
review) under human supervision, consistent with a transparent, modern
development workflow.
```
