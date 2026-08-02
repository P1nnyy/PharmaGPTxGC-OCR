"""A local index of public drug listings, built from published sitemaps.

Why an index instead of searching the site
------------------------------------------
The obvious implementation is to hit the reference site's search box with each
unknown item name. Both 1mg and PharmEasy disallow exactly that in robots.txt
(`Disallow: /search`, `Disallow: /search/all*`), while leaving product pages
and their sitemaps open. So the site's own crawl instructions rule out the
per-item-search design and permit this one.

It is also the better engineering. The sitemaps are crawled once into SQLite,
after which resolving an item is a local lookup: no network round trip per
product, nothing to rate-limit, no bot-detection to trip, and no dependency on
a search ranking that can change underneath the results. A reviewer working
through fifty new items makes zero outbound requests until they ask to pull
details for a specific match.

The slugs carry most of what is needed on their own:

    /drugs/dulohox-20mg-tablet-732600           brand + strength + form
    /drugs/cinnarise-d-15mg-20mg-tablet-636478  combination strengths
    /drugs/eromed-gel-240352                    no strength stated

so brand/strength/form matching happens entirely offline, and the product page
is fetched only for the one listing a human is actually considering.
"""

import os
import re
import sqlite3
from typing import Iterable, Iterator, Optional

from core.logger import logger
from extraction.normalizers.product_parser import normalize_name

DEFAULT_INDEX_PATH = os.path.join("datasets", "reference_catalogue.sqlite")

# Trailing id 1mg appends to every product slug. OTC listings prefix theirs
# with "otc" and no separator (…-lightening-otc321104), so a plain "-\d+$"
# leaves the id fused to the last brand token and every OTC row indexes under
# a key no invoice will ever spell.
_SLUG_ID_RE = re.compile(r"-?(?:otc)?(\d+)$", re.IGNORECASE)
_SLUG_STRENGTH_RE = re.compile(r"\b\d+(?:\.\d+)?(?:mcg|mg|iu|ml|gm|%)\b", re.IGNORECASE)
# A bare number sitting where a strength belongs: "lipigo-10-tablet" is
# Lipigo 10mg, not a brand called "Lipigo 10". Without this the correct
# listing scores identically to lipigo-20 and lipigo-5, which is worse than
# no match at all - the reviewer is shown three indistinguishable options and
# one of them is right.
_SLUG_BARE_STRENGTH_RE = re.compile(r"-(\d+(?:\.\d+)?)$")

_SLUG_FORMS = [
    "tablet-md", "tablet-dt", "tablet", "capsule", "injection", "syrup",
    "suspension", "solution", "eye-drop", "ear-drop", "nasal-spray", "drop",
    "cream", "ointment", "gel", "lotion", "powder", "sachet", "granules",
    "respule", "rotacap", "inhaler", "spray", "soap", "shampoo", "kit",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    slug        TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL,
    display     TEXT NOT NULL,
    brand_key   TEXT NOT NULL,
    strength    TEXT,
    form        TEXT
);
CREATE INDEX IF NOT EXISTS idx_brand_key ON listings(brand_key);
CREATE INDEX IF NOT EXISTS idx_source    ON listings(source);
"""


def slug_to_fields(slug: str) -> dict:
    """Reads brand, strength and form out of a product slug.

    Order matters: the strength and form tokens are removed before what
    remains is treated as the brand, otherwise "dulohox-20mg-tablet" would
    yield a brand of "dulohox 20mg tablet" and never match an invoice line
    that printed only "DULOHOX".
    """
    path = slug.rsplit("/", 1)[-1]
    path = _SLUG_ID_RE.sub("", path)

    strengths = _SLUG_STRENGTH_RE.findall(path)
    strength = "+".join(s.upper().replace(" ", "") for s in strengths) if strengths else None

    form = None
    for candidate in _SLUG_FORMS:
        if re.search(rf"(?:^|-){re.escape(candidate)}(?:-|$)", path):
            form = candidate.replace("-", " ").title()
            break

    brand = path
    brand = _SLUG_STRENGTH_RE.sub(" ", brand)
    if form:
        brand = re.sub(rf"(?:^|-){re.escape(form.lower().replace(' ', '-'))}(?:-|$)", " ", brand)
    # Strip whitespace as well as separators: removing the form leaves a space
    # behind, which would sit between the trailing number and the end of the
    # string and stop the anchored strength pattern below from ever matching.
    brand = re.sub(r"[-_\s]+", "-", brand).strip("-")

    # Only once the form has been removed can a trailing number be read as a
    # strength; before that, "tablet" would hide it.
    if strength is None:
        bare = _SLUG_BARE_STRENGTH_RE.search(brand)
        if bare:
            strength = bare.group(1)
            brand = brand[: bare.start()]

    brand = re.sub(r"[-_]+", " ", brand)
    brand = re.sub(r"\s+", " ", brand).strip()

    return {
        "display": re.sub(r"[-_]+", " ", path).strip(),
        "brand_key": normalize_name(brand),
        "strength": strength,
        "form": form,
    }


class ReferenceIndex:
    """SQLite-backed store of listings, safe to rebuild incrementally."""

    def __init__(self, path: str = DEFAULT_INDEX_PATH):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def add_urls(self, urls: Iterable[str], source: str, base_url: str = "") -> int:
        """Upserts listing URLs. Returns how many rows were written."""
        rows = []
        for url in urls:
            slug = url.replace(base_url, "") if base_url else url
            fields = slug_to_fields(slug)
            if not fields["brand_key"]:
                continue
            rows.append((
                slug, source, url, fields["display"],
                fields["brand_key"], fields["strength"], fields["form"],
            ))

        if not rows:
            return 0

        self.conn.executemany(
            """
            INSERT INTO listings (slug, source, url, display, brand_key, strength, form)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                display = excluded.display,
                brand_key = excluded.brand_key,
                strength = excluded.strength,
                form = excluded.form
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def count(self, source: Optional[str] = None) -> int:
        if source:
            cur = self.conn.execute("SELECT count(*) FROM listings WHERE source = ?", (source,))
        else:
            cur = self.conn.execute("SELECT count(*) FROM listings")
        return cur.fetchone()[0]

    def candidates(self, brand_key: str, limit: int = 400) -> list[dict]:
        """Narrows the index to plausible rows before fuzzy scoring.

        Scoring every row against every query would be far too slow at
        catalogue scale, so this pre-filters on the first token of the brand -
        the part invoices are most likely to render identically - and lets the
        matcher do the expensive comparison on what survives.
        """
        if not brand_key:
            return []

        head = brand_key.split(" ")[0]
        if len(head) < 3:
            head = brand_key[:3]

        cur = self.conn.execute(
            """
            SELECT slug, source, url, display, brand_key, strength, form
            FROM listings
            WHERE brand_key = ? OR brand_key LIKE ?
            LIMIT ?
            """,
            (brand_key, f"{head}%", limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def all_rows(self) -> Iterator[dict]:
        cur = self.conn.execute("SELECT * FROM listings")
        for row in cur:
            yield dict(row)


def open_index(path: Optional[str] = None) -> Optional[ReferenceIndex]:
    """Opens the index only if it has been built.

    Returns None rather than an empty index when the file is absent, so the
    API can tell the user "run the indexer" instead of silently reporting that
    nothing matched - which would look identical to a genuine miss.
    """
    path = path or DEFAULT_INDEX_PATH
    if not os.path.exists(path):
        logger.info(f"[ENRICH] No reference index at {path}")
        return None
    index = ReferenceIndex(path)
    if index.count() == 0:
        index.close()
        return None
    return index
