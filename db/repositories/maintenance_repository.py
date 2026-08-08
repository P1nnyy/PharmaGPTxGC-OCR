"""One-off data migrations against the graph.

Separate from the feature repositories on purpose: these queries write, they run
rarely, and they exist to repair rows written before a rule was introduced.
Nothing in the request path should import this module.
"""

from typing import Any

from core.config import settings
from db.graph_db import get_driver


def _read(query: str, **params) -> list[dict]:
    params.setdefault("pharmacy_id", settings.DEFAULT_PHARMACY_ID)
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _write(query: str, **params) -> list[dict]:
    params.setdefault("pharmacy_id", settings.DEFAULT_PHARMACY_ID)
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: [r.data() for r in tx.run(query, **params)])


def stored_invoice_dates() -> list[dict]:
    """Every stored invoice date, for the backfill to normalise off-database.

    Parsing happens in Python rather than Cypher because the date rules live in
    `core.dates` and must not be reimplemented in a second dialect.
    """
    return _read(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        WHERE inv.invoice_date IS NOT NULL
        RETURN inv.id AS invoice_id, inv.invoice_date AS invoice_date
        """
    )


def stored_expiries() -> list[dict]:
    """Every stored batch expiry, alongside the line items that mirror it."""
    return _read(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        MATCH (inv)-[:CONTAINS]->(li:LineItem)
        OPTIONAL MATCH (li)-[:OF_BATCH]->(b:Batch)
        WHERE li.expiry IS NOT NULL OR b.expiry_date IS NOT NULL
        RETURN li.id AS line_item_id, li.expiry AS line_expiry,
               b.id AS batch_id, b.expiry_date AS batch_expiry
        """
    )


def apply_invoice_dates(updates: list[dict[str, Any]]) -> int:
    """Rewrites invoice dates in one batch. Returns the number of rows touched."""
    if not updates:
        return 0
    rows = _write(
        """
        UNWIND $updates AS row
        MATCH (inv:Invoice {id: row.invoice_id})
        SET inv.invoice_date = row.invoice_date
        RETURN count(inv) AS updated
        """,
        updates=updates,
    )
    return rows[0]["updated"] if rows else 0


def apply_expiries(line_updates: list[dict], batch_updates: list[dict]) -> dict:
    """Rewrites line-item and batch expiries in one batch each."""
    touched = {"line_items": 0, "batches": 0}

    if line_updates:
        rows = _write(
            """
            UNWIND $updates AS row
            MATCH (li:LineItem {id: row.line_item_id})
            SET li.expiry = row.expiry
            RETURN count(li) AS updated
            """,
            updates=line_updates,
        )
        touched["line_items"] = rows[0]["updated"] if rows else 0

    if batch_updates:
        rows = _write(
            """
            UNWIND $updates AS row
            MATCH (b:Batch {id: row.batch_id})
            SET b.expiry_date = row.expiry
            RETURN count(b) AS updated
            """,
            updates=batch_updates,
        )
        touched["batches"] = rows[0]["updated"] if rows else 0

    return touched
