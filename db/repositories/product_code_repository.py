"""Scanned codes bound to products.

    (:Product)-[:HAS_CODE]->(:ProductCode {value, type, first_seen_at})

The point of this table is the learning loop. A pack whose code we have never
seen is unrecognisable the first time and instant every time after, because the
user told us once what it was. Nothing else in the scanner needs to change for
that to work — the parser keeps returning the same raw payload, and this is what
gives the payload a meaning.

**Scoped per workspace, deliberately.** `Product` nodes are shared across
pharmacies in this schema, so a binding could have been global too, and a GTIN
does genuinely identify the same product everywhere. It is scoped anyway,
because a binding is a *user's assertion* rather than something read off a
document: one shop mis-binding a code would otherwise silently resolve to the
wrong product on every other shop's counter, with no review path and no way for
them to see where it came from. A shared GTIN registry is a reasonable thing to
build later, on top of many workspaces agreeing — not by trusting the first one.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from core.tenancy import current_tenant
from db.graph_db import get_driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(pharmacy_id: str, value: str) -> str:
    return f"{pharmacy_id}::{normalise(value)}"


def normalise(value: str) -> str:
    """The form a code is stored and looked up under.

    Only whitespace is stripped. Case is *not* folded and nothing else is
    touched: a batch-bearing GS1 payload is case-sensitive, and two codes that
    differ only in case are two codes.
    """
    return (value or "").strip()


def _run_read(query: str, **params) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _run_write(query: str, **params) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: [r.data() for r in tx.run(query, **params)])


def resolve(value: str, pharmacy_id: Optional[str] = None) -> Optional[dict]:
    """The product a scanned code is bound to, or None.

    The whole hot path of the feature: one indexed lookup on an exact string.
    """
    code = normalise(value)
    if not code:
        return None
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (c:ProductCode {key: $key})<-[:HAS_CODE]-(p:Product)
        RETURN p {.*} AS product, c {.*} AS code
        """,
        key=_key(pharmacy_id, code),
    )
    if not rows:
        return None
    return {"product": rows[0]["product"], "code": rows[0]["code"]}


def bind(
    product_id: str,
    value: str,
    code_type: str,
    pharmacy_id: Optional[str] = None,
    bound_by: Optional[str] = None,
) -> dict:
    """Binds a code to a product, or rebinds it if it was pointing elsewhere.

    Idempotent on the code: binding the same code to the same product twice is
    a no-op that keeps the original `first_seen_at`, because when we first saw
    the code is a fact and not a counter.

    Rebinding to a *different* product replaces the edge rather than adding a
    second one. A code identifies one product; leaving both edges in place would
    make the next scan ambiguous, which is worse than the original mistake.
    """
    code = normalise(value)
    if not code:
        raise ValueError("A code cannot be empty.")
    pharmacy_id = pharmacy_id or current_tenant()

    rows = _run_write(
        """
        MATCH (p:Product {id: $product_id})
        MERGE (c:ProductCode {key: $key})
        ON CREATE SET c.id = $new_id, c.value = $value, c.type = $type,
                      c.pharmacy_id = $pharmacy_id, c.first_seen_at = $now,
                      c.bound_by = $bound_by
        ON MATCH SET  c.type = coalesce($type, c.type), c.rebound_at = $now,
                      c.bound_by = coalesce($bound_by, c.bound_by)
        WITH p, c
        // One product per code. An old edge to a different product is removed
        // rather than left beside the new one.
        OPTIONAL MATCH (other:Product)-[old:HAS_CODE]->(c) WHERE other.id <> p.id
        DELETE old
        WITH p, c
        MERGE (p)-[:HAS_CODE]->(c)
        RETURN c {.*} AS code, p {.*} AS product
        """,
        product_id=product_id,
        key=_key(pharmacy_id, code),
        new_id=str(uuid.uuid4()),
        value=code,
        type=code_type,
        pharmacy_id=pharmacy_id,
        now=_now(),
        bound_by=bound_by,
    )
    if not rows:
        raise LookupError(f"No product {product_id}.")
    return rows[0]


def unbind(value: str, pharmacy_id: Optional[str] = None) -> bool:
    """Removes a binding. Mistyped bindings have to be undoable."""
    code = normalise(value)
    if not code:
        return False
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_write(
        """
        MATCH (c:ProductCode {key: $key})
        DETACH DELETE c
        RETURN count(*) AS removed
        """,
        key=_key(pharmacy_id, code),
    )
    return bool(rows and rows[0].get("removed"))


def codes_for_product(product_id: str, pharmacy_id: Optional[str] = None) -> list[dict]:
    """Every code bound to a product, for the catalogue screen to show."""
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (p:Product {id: $product_id})-[:HAS_CODE]->(c:ProductCode {pharmacy_id: $pharmacy_id})
        RETURN c {.*} AS code
        ORDER BY code.first_seen_at
        """,
        product_id=product_id,
        pharmacy_id=pharmacy_id,
    )
    return [row["code"] for row in rows]
