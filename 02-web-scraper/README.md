# Public-Data Web Scraper → Structured Dataset

> **Self-made portfolio sample** by a Data Automation specialist.
> Shows how I turn public web listings into a clean, structured dataset
> (CSV + JSON) with a **compliant, maintainable** scraper. This is a runnable
> *skeleton*: it ships with a synthetic local HTML page so it runs offline and
> scrapes nothing live. The architecture is production-shaped.

---

## The problem

A client needs data that exists on the web but only as **pages meant for human
eyes** — product catalogs, directories, public registries, listings. Copy-paste
is hopeless at scale, and a naive scraper is brittle and can get an IP blocked
or violate a site's terms.

## The solution

A scraper built around four cleanly separated stages, so each can be tested and
swapped independently:

```
   fetch(url)  ->  parse(html)  ->  normalize(records)  ->  export(csv/json)
```

with **compliance and politeness built in, not bolted on**:

- **robots.txt is checked before every fetch** (`is_allowed`) — a disallowed
  path is a hard stop.
- **Rate limiting** between requests and an **identifying User-Agent**.
- **Retry with exponential backoff** on transient network/HTTP errors.
- A **typed record schema** (`Product` dataclass) that is the single source of
  truth for the output columns, so fetch / parse / export never drift.

## What it demonstrates

- Clean **fetch / parse / normalize / export** separation.
- **Compliance-first** design (robots.txt, rate limiting, UA, backoff).
- Type/format **normalization** (price strings → floats, stock text → boolean,
  missing values → null, relative → absolute URLs).
- Dual output: **CSV** for spreadsheets, **JSON** for downstream code.
- Standard-library-only core (`urllib`, `html.parser`) so it runs anywhere.

## How to run (offline sample)

```bash
cd code
python scraper.py            # parses ../sample_data/sample_listing.html
```
Output is written to `../output/products.csv` and `../output/products.json`.

**Verified sample run:** 5 records extracted; price strings like `"1,299.00"`
normalized to `1299.0`, `data-stock="no"` → `in_stock: false`, and a product
with an empty price/rating correctly yields `null`. See `output/products.json`.

### Pointing it at a real site
```bash
python scraper.py --url "https://example.com/catalog" --output ./results
```
Two production swaps are documented inline in `scraper.py`:
1. Replace `fetch()` with a `requests.Session` (pooling, timeouts, proxies).
2. Replace the `html.parser`-based `ProductListParser` with
   BeautifulSoup/lxml + CSS selectors for the target site's markup.
The pipeline contract (`url -> html -> records -> files`) stays identical.

## Project layout

```
02-web-scraper/
├── README.md
├── code/scraper.py                 ← runnable skeleton (fetch/parse/normalize/export)
├── sample_data/sample_listing.html ← synthetic offline sample page
└── output/                         ← products.csv, products.json (example results)
```

## Scope of this sample (honest framing)

- This is a **skeleton + working offline demo**, not a finished scraper for a
  specific site. Real targets need site-specific selectors and pagination
  handling (the hook for which is marked in `crawl()`).
- I only scrape **public pages where it is permitted** (robots.txt + the site's
  terms), at a polite rate. I do not build tools to defeat anti-bot protections
  or to harvest personal data.

**AI disclosure:** Built with AI assistance under human supervision.
```
