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

Each row is filed under its first brand word, which is the token the invoice
and the reference agree on most reliably. Everything finer - the variant
number, the release suffix, the pack - is what the matcher then has to weigh,
and it needs to see the alternatives side by side to do that honestly.

A query is more generous than that, because blocking decides what the matcher
never sees and its failures are silent: a name that reaches no candidates
reports "no product matches" about a product the index holds, and nothing on
the screen tells those two apart. So a lookup opens the block of every brand
word in the name rather than only the first (the reference lists LANZOL JUNIOR
as "Junior Lanzol"), and where that finds nothing it will try a block that
extends ours, that ours extends, or that is ours misspelled. Blocks are small -
the largest here holds 405 rows - so the extra reads are cheap, and none of
this relaxes a matching rule: it only puts rows in front of them.
"""

import ast
import csv
import os
import sqlite3
from typing import Iterator, Optional

from rapidfuzz import fuzz

from core.logger import logger
from enrichment.reference_match import block_key, split_name, strip_pack

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
    words = split_name(strip_pack(name)[0]).words
    if not words:
        return []

    rows = _rows_for_blocks(_query_blocks(words), connection)
    if not rows:
        rows = _neighbouring_blocks(words[0], connection)

    prepared, seen = [], set()
    for row in rows:
        item = dict(row)
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        item["_parts"] = split_name(item["brand_name"])
        prepared.append(item)
    return prepared


# How many of our own brand words are looked up. Blocks are small - the
# largest in this reference holds 405 rows and the median a handful - so the
# cost is a few indexed reads, and the words after the third are increasingly
# qualifiers rather than the name.
_MAX_QUERY_BLOCKS = 3
# Additional words must be this long to be worth a lookup of their own.
_MIN_EXTRA_BLOCK = 4


def _query_blocks(words: list[str]) -> list[str]:
    """The blocks to look this name up in: its first brand word, and its others.

    The reference does not always open a name with the same word the invoice
    does. LANZOL JUNIOR 15 is listed as "Junior Lanzol 15mg Tablet DT" - the
    same two words in the other order - so blocking on the first word alone
    put the row in a bucket the query never opened, and the block it DID open
    held the wrong-strength siblings. The result was not a poor match but a
    confident "no product matches".

    Word order is the one thing the matcher does not care about (it compares
    sorted tokens), so the index should not be the place that insists on it.
    """
    blocks = [words[0]]
    for word in words[1:]:
        if len(blocks) >= _MAX_QUERY_BLOCKS:
            break
        if len(word) >= _MIN_EXTRA_BLOCK and word not in blocks:
            blocks.append(word)
    return blocks


def _rows_for_blocks(blocks: list[str], connection: sqlite3.Connection) -> list:
    placeholders = ",".join("?" * len(blocks))
    return connection.execute(
        f"SELECT {_COLUMNS} FROM reference_product WHERE block IN ({placeholders})",
        blocks,
    ).fetchall()


# A block is only tried as a neighbour when it is this long. Below it, a shared
# opening says almost nothing - every three-letter prefix in this reference
# opens dozens of unrelated brands - and the scan stops being cheap.
_MIN_NEIGHBOUR_BLOCK = 5
# Enough to cover a brand's whole family several times over. A prefix that
# returns more than this is not identifying a product, it is a common stem.
_MAX_NEIGHBOUR_ROWS = 200


def _neighbouring_blocks(block: str, connection: sqlite3.Connection) -> list:
    """Rows whose block extends ours, or which ours extends.

    Exact blocking assumes the invoice and the reference open the name with
    the same word, and mostly they do. When they do not, the failure is total
    rather than partial: LASILACTON never sees Lasilactone, MOXITOB never sees
    Moxitobra, and the screen reports "no product matches" about a product the
    index holds. A truncated or misspelled first word is exactly the case a
    reference lookup exists to solve, so it cannot be the one case that
    returns nothing at all.

    This only widens what gets SCORED. Every candidate still has to survive
    the matcher's rules, which is where a genuinely different brand that
    happens to share an opening is thrown out.
    """
    if len(block) < _MIN_NEIGHBOUR_BLOCK:
        return []
    rows = connection.execute(
        f"""
        SELECT {_COLUMNS} FROM reference_product
        WHERE (block LIKE ? OR ? LIKE block || '%')
          AND length(block) >= ?
        LIMIT ?
        """,
        (f"{block}%", block, _MIN_NEIGHBOUR_BLOCK, _MAX_NEIGHBOUR_ROWS),
    ).fetchall()
    # Both fallbacks run, rather than the second only when the first is empty.
    # HYPONET-O found one row that way - the unrelated HYPON block, which its
    # name merely extends - and a single useless candidate was enough to hide
    # Hyponat-O, the product it was actually looking for.
    return [*rows, *_misread_blocks(block, connection)]


# How close a block must be to ours to be worth scoring. Deliberately the same
# threshold the matcher uses to forgive an OCR misread inside a name: a
# spelling the rules would accept has to be a spelling the index will surface,
# or the forgiveness never gets the chance to apply.
_MISREAD_RATIO = 85.0
# Candidate blocks are narrowed by a shared opening first, so the comparison
# runs over a dozen or so blocks rather than the reference's 118,000.
_MISREAD_PREFIX = 4


def _misread_blocks(block: str, connection: sqlite3.Connection) -> list:
    """Rows in a block that is our block misspelled.

    HYPONET-O 15 is "Hyponat-O 15 Tablet" in the reference - one letter apart,
    which `unexplained_words` forgives readily. But blocking never offered it
    the row, so the matcher's tolerance for a misread first word was
    unreachable in exactly the case it was written for.

    Neither containment test catches this: HYPONAT does not extend HYPONET and
    HYPONET does not extend HYPONAT. They simply differ in the middle, which is
    what OCR does.
    """
    near = [
        candidate for (candidate,) in connection.execute(
            "SELECT DISTINCT block FROM reference_product WHERE block LIKE ?",
            (f"{block[:_MISREAD_PREFIX]}%",),
        )
        if candidate != block and fuzz.ratio(block, candidate) >= _MISREAD_RATIO
    ]
    if not near:
        return []
    placeholders = ",".join("?" * len(near))
    return connection.execute(
        f"""
        SELECT {_COLUMNS} FROM reference_product
        WHERE block IN ({placeholders}) LIMIT ?
        """,
        (*near, _MAX_NEIGHBOUR_ROWS),
    ).fetchall()


def iter_meta(connection: sqlite3.Connection) -> Iterator[tuple[str, str]]:
    for row in connection.execute("SELECT key, value FROM reference_meta"):
        yield row["key"], row["value"]
