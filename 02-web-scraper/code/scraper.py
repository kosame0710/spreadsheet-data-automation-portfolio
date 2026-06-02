"""
scraper.py — Skeleton of a polite public-data scraper that turns HTML
listings into a clean, structured dataset (CSV/JSON).

This is a *portfolio skeleton*: the architecture, error handling and output
contract are real and runnable, but it is wired to a local sample HTML file by
default so it runs offline and scrapes nothing live. Point `--url` at a real,
scraping-permitted page and swap the parser to use it for real.

Design principles demonstrated:
  * Separation of fetch / parse / normalize / export (each independently
    testable and replaceable).
  * Politeness & compliance hooks: robots.txt check, rate limiting,
    identifying User-Agent, retry with backoff.
  * A typed record schema so the output is predictable.
  * Standard-library-only core (urllib + html.parser), so it runs anywhere; a
    note shows where requests + BeautifulSoup/lxml would slot in for production.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

USER_AGENT = "PortfolioDemoScraper/1.0 (+contact: demo@example.com)"
REQUEST_DELAY_SECONDS = 1.0   # rate limit between requests (be a good citizen)
MAX_RETRIES = 3


def _is_local(url: str) -> bool:
    """True if *url* points at the local filesystem rather than the web.

    Handles file:// URLs and bare paths, including Windows drive paths like
    ``C:\\dir\\file.html`` (where urlparse would otherwise read ``C`` as a
    scheme).
    """
    scheme = urlparse(url).scheme
    if scheme in ("", "file"):
        return True
    if len(scheme) == 1 and scheme.isalpha():  # Windows drive letter, e.g. "c"
        return True
    return False


# --------------------------------------------------------------------------- #
# Output schema
# --------------------------------------------------------------------------- #
@dataclass
class Product:
    """One structured record. Keep this as the single source of truth for the
    output columns so fetch/parse/export never drift apart."""
    name: str
    price: Optional[float]
    currency: str
    in_stock: bool
    rating: Optional[float]
    url: str


# --------------------------------------------------------------------------- #
# Compliance / politeness
# --------------------------------------------------------------------------- #
def is_allowed(url: str, user_agent: str = USER_AGENT) -> bool:
    """Respect robots.txt. Never scrape a path the site disallows.

    Returning False here is a hard stop in `crawl()` — compliance is not
    optional. (For the offline sample, local file URLs are treated as allowed.)
    """
    if _is_local(url):
        return True
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        # If robots.txt can't be read, the conservative default is to NOT scrape.
        return False
    return rp.can_fetch(user_agent, url)


def fetch(url: str, *, retries: int = MAX_RETRIES) -> str:
    """Fetch a URL's HTML with an identifying UA and retry-with-backoff.

    Production note: swap this for `requests.Session` with connection pooling,
    timeouts and proxy support. The interface (url -> html string) stays the
    same so nothing downstream changes.
    """
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except Exception as err:  # network/HTTP errors: back off and retry
            last_err = err
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts: {last_err}")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
class ProductListParser(HTMLParser):
    """Extract product records from a listing page.

    Looks for the simple, explicit markup used by the bundled sample:
        <div class="product" data-name=".." data-price=".." data-currency=".."
             data-stock=".." data-rating=".." data-url="..">
    Real sites need site-specific selectors; in production this class is where a
    BeautifulSoup/lxml/CSS-selector implementation would live. The rest of the
    pipeline is agnostic to how parsing happens.
    """

    def __init__(self) -> None:
        super().__init__()
        self.products: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag != "div":
            return
        a = dict(attrs)
        if a.get("class") == "product":
            self.products.append(
                {
                    "name": a.get("data-name", ""),
                    "price": a.get("data-price", ""),
                    "currency": a.get("data-currency", ""),
                    "stock": a.get("data-stock", ""),
                    "rating": a.get("data-rating", ""),
                    "url": a.get("data-url", ""),
                }
            )


def parse_products(html: str, base_url: str) -> list[Product]:
    """Parse + normalize raw HTML into typed Product records."""
    parser = ProductListParser()
    parser.feed(html)

    records: list[Product] = []
    for raw in parser.products:
        records.append(
            Product(
                name=raw["name"].strip(),
                price=_to_float(raw["price"]),
                currency=(raw["currency"] or "").strip().upper(),
                in_stock=str(raw["stock"]).strip().lower() in ("1", "true", "yes", "in stock"),
                rating=_to_float(raw["rating"]),
                url=urljoin(base_url, raw["url"]) if raw["url"] else base_url,
            )
        )
    return records


def _to_float(value: str) -> Optional[float]:
    value = (value or "").replace(",", "").strip()
    try:
        return round(float(value), 2)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Orchestration + export
# --------------------------------------------------------------------------- #
def crawl(url: str) -> list[Product]:
    """Fetch one page (skeleton handles a single page; pagination hook below)."""
    if not is_allowed(url):
        raise PermissionError(f"robots.txt disallows scraping: {url}")
    html = _read_local(url) if _is_local(url) else fetch(url)
    records = parse_products(html, base_url=url)
    time.sleep(REQUEST_DELAY_SECONDS)  # rate limit before any next request
    # Pagination would go here: find "next" link, repeat crawl(), extend records.
    return records


def _read_local(url: str) -> str:
    """Read a local sample file (lets the skeleton run offline)."""
    if url.startswith("file:"):
        path = Path(urlparse(url).path)
    else:
        path = Path(url)
    return path.read_text(encoding="utf-8")


def export(records: Iterable[Product], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    records = list(records)

    csv_path = out_dir / "products.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=[f.name for f in Product.__dataclass_fields__.values()])
        writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))

    json_path = out_dir / "products.json"
    json_path.write_text(
        json.dumps([asdict(r) for r in records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"csv": csv_path, "json": json_path}


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Scrape a product listing into structured data.")
    parser.add_argument("--url", default=str(here.parent / "sample_data" / "sample_listing.html"),
                        help="Page URL or local HTML path (defaults to bundled sample).")
    parser.add_argument("--output", type=Path, default=here.parent / "output")
    args = parser.parse_args(argv)

    records = crawl(args.url)
    paths = export(records, args.output)
    print(f"Scraped {len(records)} records.")
    for label, p in paths.items():
        print(f"  - {label}: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
