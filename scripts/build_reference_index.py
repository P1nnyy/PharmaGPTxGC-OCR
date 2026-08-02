"""Builds the local reference-catalogue index from published sitemaps.

Run this once (and occasionally after) before using catalogue enrichment:

    python scripts/build_reference_index.py --limit 5     # sample, ~1 minute
    python scripts/build_reference_index.py               # full index

Only sitemap files are fetched, which is what sitemaps exist for. The site's
search endpoints are disallowed by its robots.txt and are never touched - see
enrichment/index.py for why the design is shaped this way.

Requests are issued one at a time with a delay between them. Nothing here
needs to be fast: it is an occasional bulk job, and being a considerate client
of someone else's servers matters more than finishing a minute sooner.
"""

import argparse
import gzip
import io
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

sys.path.insert(0, ".")

from enrichment.index import ReferenceIndex  # noqa: E402

SITEMAP_INDEX = "https://www.1mg.com/sitemap.xml"
BASE_URL = "https://www.1mg.com"
SOURCE = "1mg"

# Only the product families the catalogue can use. Language variants (hi/ta/
# te/mr/gu) describe the same SKUs in another language and would just add
# duplicate rows for the matcher to wade through.
WANTED = re.compile(r"sitemap_(drugs|otc|generics)_\d+\.xml$")

HEADERS = {
    "User-Agent": (
        "PharmaGPTCatalogueIndexer/1.0 (pharmacy inventory reconciliation; "
        "contact: admin@pharmagpt.co)"
    )
}

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def fetch(url: str, session: requests.Session, timeout: int = 30) -> bytes:
    response = session.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    content = response.content
    if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
        content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
    return content


def parse_locs(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    return [el.text.strip() for el in root.findall(".//sm:loc", NS) if el.text]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="only process this many child sitemaps (0 = all)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds between requests")
    parser.add_argument("--index-path", default=None)
    args = parser.parse_args()

    session = requests.Session()

    print(f"Fetching sitemap index: {SITEMAP_INDEX}")
    children = [u for u in parse_locs(fetch(SITEMAP_INDEX, session)) if WANTED.search(u)]
    print(f"  {len(children)} product sitemaps to read")

    if args.limit:
        children = children[: args.limit]
        print(f"  limited to {len(children)}")

    index = ReferenceIndex(args.index_path) if args.index_path else ReferenceIndex()
    total = 0
    failed = 0

    try:
        for i, child in enumerate(children, 1):
            try:
                urls = parse_locs(fetch(child, session))
                written = index.add_urls(urls, source=SOURCE, base_url=BASE_URL)
                total += written
                print(f"  [{i}/{len(children)}] {child.rsplit('/', 1)[-1]}: "
                      f"{written} listings (running total {total})")
            except Exception as e:
                # One bad sitemap should not discard the work already done -
                # the index is upserted incrementally and can be re-run.
                failed += 1
                print(f"  [{i}/{len(children)}] {child.rsplit('/', 1)[-1]}: FAILED {type(e).__name__}: {e}")
            time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nInterrupted — index keeps everything written so far; re-run to continue.")

    print(f"\nIndex now holds {index.count()} listings ({failed} sitemap(s) failed).")
    print(f"Stored at: {index.path}")
    index.close()


if __name__ == "__main__":
    main()
