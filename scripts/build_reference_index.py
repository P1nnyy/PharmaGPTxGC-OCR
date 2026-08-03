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

# Each source: where its sitemap index lives, which child sitemaps are worth
# reading, and the prefix to strip so slugs are stored consistently.
#
# Only product families the catalogue can use. Language variants (hi/ta/te/
# mr/gu) describe the same SKUs in another language and would add duplicate
# rows for the matcher to wade through; doctors, blogs, diagnostics and city
# landing pages are not products at all.
SOURCES = {
    "1mg": {
        "index": "https://www.1mg.com/sitemap.xml",
        "base": "https://www.1mg.com",
        "wanted": re.compile(r"sitemap_(drugs|otc|generics)_\d+\.xml$"),
    },
    "PharmEasy": {
        "index": "https://pharmeasy.in/sitemap.xml",
        "base": "https://pharmeasy.in",
        # PharmEasy nests one level deeper than 1mg: the top index points at
        # per-category indexes, which then point at the actual URL sets. The
        # walk below is recursive for that reason, so this pattern has to
        # admit both the intermediate indexes and the leaves they contain.
        "wanted": re.compile(
            r"sitemap-(prescription-medicines?|otc-products?)(-\d+)?\.xml$"
        ),
    },
}

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


def parse_sitemap(xml_bytes: bytes) -> tuple[str, list[str]]:
    """Returns ("index"|"urlset", locs) so the caller knows whether the
    entries are more sitemaps to follow or the product URLs themselves."""
    root = ET.fromstring(xml_bytes)
    kind = "index" if root.tag.endswith("sitemapindex") else "urlset"
    return kind, [el.text.strip() for el in root.findall(".//sm:loc", NS) if el.text]


def collect_leaf_sitemaps(entry: str, wanted, session, delay: float, depth: int = 0) -> list[str]:
    """Walks sitemap indexes down to the ones that actually list product URLs.

    Recursive because the two sources nest differently: 1mg's top-level index
    points straight at URL sets, while PharmEasy's points at per-category
    indexes which then point at the URL sets. Hard-coding either depth would
    silently index nothing for the other.
    """
    if depth > 3:
        return []

    try:
        kind, locs = parse_sitemap(fetch(entry, session))
    except Exception as e:
        print(f"    ! could not read {entry.rsplit('/', 1)[-1]}: {type(e).__name__}: {e}")
        return []

    if kind == "urlset":
        return [entry]

    leaves: list[str] = []
    for child in locs:
        if not wanted.search(child):
            continue
        time.sleep(delay)
        leaves.extend(collect_leaf_sitemaps(child, wanted, session, delay, depth + 1))
    return leaves


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="only process this many leaf sitemaps per source (0 = all)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds between requests")
    parser.add_argument("--index-path", default=None)
    parser.add_argument("--source", default=None, choices=list(SOURCES),
                        help="only crawl this source (default: all)")
    args = parser.parse_args()

    session = requests.Session()
    index = ReferenceIndex(args.index_path) if args.index_path else ReferenceIndex()
    failed = 0

    try:
        for name, cfg in SOURCES.items():
            if args.source and name != args.source:
                continue

            print(f"\n=== {name} ===")
            print(f"Fetching sitemap index: {cfg['index']}")
            leaves = collect_leaf_sitemaps(cfg["index"], cfg["wanted"], session, args.delay)
            print(f"  {len(leaves)} product sitemaps to read")

            if args.limit:
                leaves = leaves[: args.limit]
                print(f"  limited to {len(leaves)}")

            total = 0
            for i, leaf in enumerate(leaves, 1):
                try:
                    _, urls = parse_sitemap(fetch(leaf, session))
                    written = index.add_urls(urls, source=name, base_url=cfg["base"])
                    total += written
                    print(f"  [{i}/{len(leaves)}] {leaf.rsplit('/', 1)[-1]}: "
                          f"{written} listings (running total {total})")
                except Exception as e:
                    # One bad sitemap should not discard the work already
                    # done - the index is upserted incrementally and the whole
                    # job can be re-run.
                    failed += 1
                    print(f"  [{i}/{len(leaves)}] {leaf.rsplit('/', 1)[-1]}: "
                          f"FAILED {type(e).__name__}: {e}")
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nInterrupted — index keeps everything written so far; re-run to continue.")

    print(f"\nIndex now holds {index.count()} listings ({failed} sitemap(s) failed).")
    for name in SOURCES:
        print(f"  {name}: {index.count(name)}")
    print(f"Stored at: {index.path}")
    index.close()


if __name__ == "__main__":
    main()
