"""Local SQLite index over the Indian pharmaceutical product reference.

Why an index rather than reading the CSV
----------------------------------------
The source is a 69MB, ~254,000-row CSV. Parsing it per lookup is out of the
question, and holding it in the API process costs hundreds of megabytes for
data that never changes between builds. So it is normalised once into SQLite,
with the expensive part of matching - splitting each name into brand words,
variant numbers and inline strengths - done at build time and stored.

A lookup is then one indexed read of a few hundred rows, entirely local. That
matters beyond speed: because there is no network call and no third party
being asked, filling in a whole catalogue is a local operation rather than
several hundred requests to someone else's servers. The batch route exists
because of this file.

The blocking key is the first brand word, which is the token the invoice and
the reference agree on most reliably. Everything finer - the variant number,
the release suffix, the pack - is what the matcher then has to weigh, and it
needs to see the alternatives side by side to do that honestly.
"""

import ast
import csv
import os
import sqlite3
from typing import Iterator, Optional

from core.logger import logger
from enrichment.reference_match import block_key, split_name

DEFAULT_PATH = os.path.join("datasets", "product_reference.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_product (
    id INTEGER PRIMARY KEY,
    brand_name TEXT NOT NULL,
    block TEXT NOT NULL,
    manufacturer TEXT,
    dosage_form TEXT,
    pack_size REAL,
    pack_unit TEXT,
    primary_strength TEXT,
    ingredient_count INTEGER,
    composition TEXT,
    -- Each ingredient's strength, pipe-joined in listed order. Stored
    -- separately from the rendered composition because the matcher needs the
    -- numbers: a combination's strength can often be pinned by the figure the
    -- invoice itself printed, and that needs comparing values, not prose.
    ingredient_strengths TEXT,
    therapeutic_class TEXT,
    price_inr REAL,
    discontinued INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_reference_block ON reference_product(block);
CREATE TABLE IF NOT EXISTS reference_meta (key TEXT PRIMARY KEY, value TEXT);
"""

_COLUMNS = (
    "id, brand_name, manufacturer, dosage_form, pack_size, pack_unit, "
    "primary_strength, ingredient_count, composition, ingredient_strengths, "
    "therapeutic_class, price_inr, discontinued"
)


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    path = path or os.environ.get("PRODUCT_REFERENCE_PATH") or DEFAULT_PATH
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def is_available(path: Optional[str] = None) -> bool:
    """True when an index exists and holds rows.

    Checked rather than assumed: the index is a build artefact that lives in a
    gitignored directory, so a fresh clone or a new deployment has none, and
    the catalogue has to say "reference data is not installed" rather than
    failing as though the lookup went wrong.
    """
    path = path or os.environ.get("PRODUCT_REFERENCE_PATH") or DEFAULT_PATH
    if not os.path.exists(path):
        return False
    try:
        with connect(path) as connection:
            return connection.execute("SELECT 1 FROM reference_product LIMIT 1").fetchone() is not None
    except sqlite3.Error:
        return False


def read_ingredients(raw: Optional[str]) -> list[dict]:
    """Parses the source's ingredient list.

    The CSV stores a Python literal, not JSON: single-quoted keys, so
    json.loads rejects every row. literal_eval reads it, and anything
    malformed yields an empty list rather than raising - one unreadable
    composition is not worth failing a 254,000-row build over.
    """
    if not raw:
        return []
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def describe_composition(raw: Optional[str]) -> Optional[str]:
    """Renders the source's ingredient list as a readable line.

    The CSV stores a Python literal, not JSON: single-quoted keys, so
    json.loads rejects every row. literal_eval reads it, and anything
    malformed is dropped rather than raised - a composition is descriptive
    text on a suggestion, and losing one is not worth failing a build over.
    """
    parts = []
    for item in read_ingredients(raw):
        name, strength = item.get("name"), item.get("strength")
        parts.append(f"{name} {strength}".strip() if strength else str(name or "").strip())
    return " + ".join(p for p in parts if p) or None


def ingredient_strengths(raw: Optional[str]) -> Optional[str]:
    """Every ingredient's strength, in listed order, pipe-joined."""
    values = [str(i.get("strength") or "").strip() for i in read_ingredients(raw)]
    return "|".join(values) if any(values) else None


def build(csv_path: str, index_path: Optional[str] = None, batch: int = 5000) -> dict:
    """(Re)builds the index from the source CSV. Returns a summary."""
    index_path = index_path or DEFAULT_PATH
    os.makedirs(os.path.dirname(index_path) or ".", exist_ok=True)

    if os.path.exists(index_path):
        os.remove(index_path)

    csv.field_size_limit(10_000_000)
    written = skipped = 0

    with connect(index_path) as connection:
        connection.executescript(SCHEMA)
        with open(csv_path, newline="", encoding="utf-8") as handle:
            rows: list[tuple] = []
            for record in csv.DictReader(handle):
                name = (record.get("brand_name") or "").strip()
                block = block_key(name)
                if not name or not block:
                    skipped += 1
                    continue
                rows.append((
                    name,
                    block,
                    (record.get("manufacturer") or "").strip() or None,
                    (record.get("dosage_form") or "").strip().lower() or None,
                    _number(record.get("pack_size")),
                    (record.get("pack_unit") or "").strip() or None,
                    (record.get("primary_strength") or "").strip() or None,
                    int(_number(record.get("num_active_ingredients")) or 1),
                    describe_composition(record.get("active_ingredients")),
                    ingredient_strengths(record.get("active_ingredients")),
                    (record.get("therapeutic_class") or "").strip() or None,
                    _number(record.get("price_inr")),
                    1 if str(record.get("is_discontinued")).strip().lower() == "true" else 0,
                ))
                if len(rows) >= batch:
                    _insert(connection, rows)
                    written += len(rows)
                    rows = []
            if rows:
                _insert(connection, rows)
                written += len(rows)

        connection.execute(
            "INSERT OR REPLACE INTO reference_meta(key, value) VALUES ('source', ?)",
            (os.path.basename(csv_path),),
        )
        connection.execute(
            "INSERT OR REPLACE INTO reference_meta(key, value) VALUES ('rows', ?)",
            (str(written),),
        )
        connection.commit()

    logger.info(f"[REFERENCE] Indexed {written} products from {csv_path} ({skipped} skipped)")
    return {"indexed": written, "skipped": skipped, "path": index_path}


def _insert(connection: sqlite3.Connection, rows: list[tuple]) -> None:
    connection.executemany(
        """
        INSERT INTO reference_product
            (brand_name, block, manufacturer, dosage_form, pack_size, pack_unit,
             primary_strength, ingredient_count, composition, ingredient_strengths,
             therapeutic_class, price_inr, discontinued)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _number(value) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def candidates_for(name: Optional[str], connection: sqlite3.Connection) -> list[dict]:
    """Every reference row in this name's block, ready for scoring.

    The name split is recomputed here rather than stored: it is cheap for a
    few hundred rows, and keeping one implementation means the matcher's
    tokenising rules can change without the index going stale underneath them.
    """
    block = block_key(name)
    if not block:
        return []
    rows = connection.execute(
        f"SELECT {_COLUMNS} FROM reference_product WHERE block = ?", (block,)
    ).fetchall()
    prepared = []
    for row in rows:
        item = dict(row)
        item["_parts"] = split_name(item["brand_name"])
        prepared.append(item)
    return prepared


def iter_meta(connection: sqlite3.Connection) -> Iterator[tuple[str, str]]:
    for row in connection.execute("SELECT key, value FROM reference_meta"):
        yield row["key"], row["value"]
