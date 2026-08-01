"""Catalogue master data: the layer that decides when two invoice lines are
the same item.

Why Product needed splitting in two
-----------------------------------
The original write path did this:

    MERGE (p:Product {normalized_name: $normalized})

which makes the invoice's spelling the identity. That fails in both
directions at once:

  * MONTICOPE SUSPENSION 60 ML and MONTICOPE SUSP 60ML are one SKU bought
    twice, but become two products - catalogue sprawl, split stock, split
    purchase history.
  * DONEP printed bare on two invoices becomes one product, even when one
    bill was 5mg strips and the other 10mg - two different medicines sharing
    a stock figure, which is the dangerous direction.

So identity is now separated from spelling:

    (:ProductAlias {normalized_name})-[:RESOLVES_TO]->(:Product {identity_key})

ProductAlias is one node per distinct string an invoice has ever printed. It
is always computable and never wrong, because it claims nothing beyond "this
text appeared". Product is the SKU - brand, strength, form, pack - and is
what stock and pricing hang off. Many aliases may resolve to one Product;
that relationship IS the merge.

Why it merges first and asks later
----------------------------------
identity_key collapses unknown components to '?', so two bare DONEPs do land
on one Product. That is deliberate. Most repeat items genuinely are the same
item, so merging is right far more often than not, and the failure is
recoverable: the merged product carries a missing_strength flag and, more
usefully, the spread of MRPs observed across its line items. A product seen
at Rs 45 and Rs 90 is announcing that it is two products. Splitting a wrongly
merged product is one click; finding two rows that should have been one among
four hundred lookalikes is not.

Nothing here is presented as established fact. Every parsed field carries a
confidence, and `confirmed_fields` records what a human actually approved -
so the UI can always distinguish "we guessed Tablet" from "the pharmacist
said Tablet".
"""

import uuid
from typing import Any, Optional

from core.config import settings
from core.logger import logger
from db.graph_db import get_driver
from extraction.normalizers.product_parser import (
    build_identity_key,
    normalize_name,
    parse_product_name,
)

# Catalogue-level fields a human may set. Batch/price/tax facts are NOT here:
# those belong to the invoice line that observed them and are shown on the
# product as read-only evidence, never retyped.
EDITABLE_FIELDS = {
    "canonical_name",
    "brand",
    "strength",
    "form",
    "pack_size",
    "pack_multiplier",
    "base_unit",
    "manufacturer",
    "hsn",
    "schedule",
    "notes",
}

# Fields that make a product usable downstream. Completeness is measured
# against these, and the review queue sorts by what is still missing.
REQUIRED_FIELDS = ("brand", "strength", "form", "pack_size", "pack_multiplier", "base_unit")

# Above this ratio, the price spread across a product's own line items is
# better explained by two different pack sizes or strengths having been
# merged than by an ordinary price revision.
MRP_SPLIT_RATIO = 1.5
# Between the two, it is most likely a genuine revision, worth showing but
# not worth alarming about.
MRP_DRIFT_RATIO = 1.15


def _serialize(node) -> dict:
    if node is None:
        return {}
    data = dict(node)
    for key, value in data.items():
        if hasattr(value, "iso_format"):
            data[key] = value.iso_format()
    return data


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Write path - called from the invoice save transaction
# --------------------------------------------------------------------------

def resolve_alias_and_product(
    tx, name: Optional[str], pack: Optional[str], hsn: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """Records the spelling, finds or creates the SKU, returns (alias_id, product_id).

    Runs inside the caller's invoice transaction so an invoice and the
    catalogue rows it implies commit together or not at all.
    """
    if not name or not str(name).strip():
        return None, None

    raw = str(name).strip()
    normalized = normalize_name(raw)
    if not normalized:
        return None, None

    parsed = parse_product_name(raw, pack)

    alias_record = tx.run(
        """
        MERGE (a:ProductAlias {normalized_name: $normalized})
        ON CREATE SET a.id = randomUUID(),
                      a.raw_name = $raw,
                      a.status = 'new',
                      a.first_seen = datetime(),
                      a.times_seen = 0
        SET a.times_seen = coalesce(a.times_seen, 0) + 1,
            a.last_seen = datetime()
        WITH a
        OPTIONAL MATCH (a)-[:RESOLVES_TO]->(p:Product)
        RETURN a.id AS alias_id, p.id AS product_id
        """,
        normalized=normalized,
        raw=raw,
    ).single()

    alias_id = alias_record["alias_id"]
    product_id = alias_record["product_id"]

    # A spelling already routed to a SKU stays routed there - including when a
    # human moved it. Re-deriving the identity on every invoice would silently
    # undo their correction the next time the same name arrives.
    if product_id:
        return alias_id, product_id

    product_id = _merge_product_by_identity(tx, parsed, raw, hsn)

    tx.run(
        """
        MATCH (a:ProductAlias {id: $alias_id})
        MATCH (p:Product {id: $product_id})
        MERGE (a)-[:RESOLVES_TO]->(p)
        """,
        alias_id=alias_id,
        product_id=product_id,
    )
    return alias_id, product_id


def _merge_product_by_identity(tx, parsed, raw_name: str, hsn: Optional[str]) -> str:
    """Finds or creates the Product for a parse, seeding it with the guesses.

    ON CREATE only: an existing product's fields are never overwritten by a
    later invoice's parse, because the existing one may have been corrected by
    a human and a fresh guess must not outrank that.
    """
    record = tx.run(
        """
        MERGE (p:Product {identity_key: $identity_key})
        ON CREATE SET p.id = randomUUID(),
                      p.canonical_name = $canonical_name,
                      p.brand = $brand,
                      p.strength = $strength,
                      p.form = $form,
                      p.pack_size = $pack_size,
                      p.pack_multiplier = $pack_multiplier,
                      p.base_unit = $base_unit,
                      p.hsn = $hsn,
                      p.brand_confidence = $brand_confidence,
                      p.strength_confidence = $strength_confidence,
                      p.form_confidence = $form_confidence,
                      p.pack_size_confidence = $pack_size_confidence,
                      p.pack_multiplier_confidence = $pack_multiplier_confidence,
                      p.base_unit_confidence = $base_unit_confidence,
                      p.confirmed_fields = [],
                      p.review_status = 'needs_review',
                      p.created_at = datetime()
        RETURN p.id AS id
        """,
        identity_key=parsed.identity_key,
        canonical_name=raw_name,
        brand=parsed.brand.value,
        strength=parsed.strength.value,
        form=parsed.form.value,
        pack_size=parsed.pack_size.value,
        pack_multiplier=parsed.pack_multiplier.value,
        base_unit=parsed.base_unit.value,
        hsn=str(hsn).strip() if hsn else None,
        brand_confidence=parsed.brand.confidence,
        strength_confidence=parsed.strength.confidence,
        form_confidence=parsed.form.confidence,
        pack_size_confidence=parsed.pack_size.confidence,
        pack_multiplier_confidence=parsed.pack_multiplier.confidence,
        base_unit_confidence=parsed.base_unit.confidence,
    ).single()
    return record["id"]


# --------------------------------------------------------------------------
# Ambiguity analysis - pure, so it can be tested without a database
# --------------------------------------------------------------------------

def compute_flags(product: dict) -> list[dict]:
    """Turns a product's aggregated evidence into the warnings the UI acts on.

    Severity drives ordering in the review queue, so it reflects downstream
    damage rather than how odd the data looks: a missing pack multiplier
    corrupts every derived stock figure, while a missing schedule is a blank
    the pharmacist fills in at leisure.
    """
    flags: list[dict] = []
    confirmed = set(product.get("confirmed_fields") or [])

    def missing(field: str) -> bool:
        return product.get(field) in (None, "", [])

    if missing("pack_multiplier"):
        flags.append({
            "code": "missing_pack_multiplier",
            "severity": "high",
            "field": "pack_multiplier",
            "message": "Units per pack unknown — tablet-level stock cannot be calculated.",
        })
    if missing("strength"):
        flags.append({
            "code": "missing_strength",
            "severity": "high",
            "field": "strength",
            "message": "No strength on any invoice — different strengths of this brand would merge into one item.",
        })
    if missing("form"):
        flags.append({
            "code": "missing_form",
            "severity": "medium",
            "field": "form",
            "message": "Dosage form unknown — is this a tablet, a sachet, a vial?",
        })
    if missing("base_unit"):
        flags.append({
            "code": "missing_base_unit",
            "severity": "medium",
            "field": "base_unit",
            "message": "Dispensing unit unknown — stock has no unit to count in.",
        })
    if missing("pack_size"):
        flags.append({
            "code": "missing_pack_size",
            "severity": "medium",
            "field": "pack_size",
            "message": "Pack size never printed on an invoice.",
        })
    if missing("hsn"):
        flags.append({
            "code": "missing_hsn",
            "severity": "medium",
            "field": "hsn",
            "message": "No HSN code — GSTR-2B reconciliation needs one.",
        })
    if missing("schedule"):
        flags.append({
            "code": "missing_schedule",
            "severity": "low",
            "field": "schedule",
            "message": "Schedule not set — required for regulated-sale records.",
        })
    if missing("manufacturer"):
        flags.append({
            "code": "missing_manufacturer",
            "severity": "low",
            "field": "manufacturer",
            "message": "Manufacturer not recorded.",
        })

    # Price spread across this product's own line items.
    mrps = sorted({m for m in (_to_float(v) for v in product.get("observed_mrps") or []) if m})
    if len(mrps) > 1:
        ratio = mrps[-1] / mrps[0] if mrps[0] else 0
        if ratio >= MRP_SPLIT_RATIO:
            flags.append({
                "code": "mrp_conflict",
                "severity": "high",
                "field": "pack_size",
                "message": (
                    f"MRP ranges from ₹{mrps[0]:.2f} to ₹{mrps[-1]:.2f} on the same item — "
                    f"these are probably different pack sizes or strengths merged together."
                ),
            })
        elif ratio >= MRP_DRIFT_RATIO:
            flags.append({
                "code": "mrp_drift",
                "severity": "low",
                "field": "mrp",
                "message": f"MRP moved from ₹{mrps[0]:.2f} to ₹{mrps[-1]:.2f} across invoices.",
            })

    hsns = {h for h in (product.get("observed_hsns") or []) if h}
    if len(hsns) > 1:
        flags.append({
            "code": "hsn_conflict",
            "severity": "medium",
            "field": "hsn",
            "message": f"Invoices disagree on HSN code ({', '.join(sorted(hsns))}).",
        })

    aliases = product.get("aliases") or []
    new_aliases = [a for a in aliases if a.get("status") == "new"]
    if product.get("review_status") == "confirmed" and new_aliases:
        names = ", ".join(a.get("raw_name", "") for a in new_aliases[:3])
        flags.append({
            "code": "new_alias",
            "severity": "medium",
            "field": None,
            "message": f"New spelling seen since this item was confirmed: {names}",
        })

    # Report confirmed-but-still-empty fields as informational rather than
    # nagging: the pharmacist may know the invoice genuinely never states it.
    for field in REQUIRED_FIELDS:
        if missing(field) and field in confirmed:
            for flag in flags:
                if flag.get("field") == field:
                    flag["severity"] = "low"
                    flag["message"] += " (acknowledged)"

    return flags


def compute_completeness(product: dict) -> float:
    """Fraction of the fields that make a product usable which are filled."""
    filled = sum(1 for f in REQUIRED_FIELDS if product.get(f) not in (None, "", []))
    return round(filled / len(REQUIRED_FIELDS), 2)


def _decorate(product: dict) -> dict:
    product["flags"] = compute_flags(product)
    product["completeness"] = compute_completeness(product)
    product["needs_attention"] = any(f["severity"] == "high" for f in product["flags"])
    return product


# --------------------------------------------------------------------------
# Read path
# --------------------------------------------------------------------------

def _aggregate_query(single: bool = False) -> str:
    """Rolls a product up with the invoice evidence behind it.

    Scoped to one pharmacy's invoices: Product nodes are shared across
    tenants, but "how many times have I bought this and at what price" is
    emphatically not.
    """
    selector = "(p:Product {id: $product_id})" if single else "(p:Product)"
    return f"""
MATCH {selector}<-[:OF_PRODUCT]-(li:LineItem)<-[:CONTAINS]-(inv:Invoice)
      -[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
OPTIONAL MATCH (p)<-[:RESOLVES_TO]-(a:ProductAlias)
OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
OPTIONAL MATCH (li)-[:OF_BATCH]->(b:Batch)
WITH p,
     collect(DISTINCT a)         AS alias_nodes,
     collect(DISTINCT li)        AS items,
     collect(DISTINCT inv)       AS invoices,
     collect(DISTINCT v.name)    AS vendors,
     collect(DISTINCT b)         AS batches
RETURN p, alias_nodes, items, invoices, vendors, batches
"""


def _shape_product(record) -> dict:
    product = _serialize(record["p"])
    items = [_serialize(i) for i in record["items"] if i]
    invoices = [_serialize(i) for i in record["invoices"] if i]
    batches = [_serialize(b) for b in record["batches"] if b]

    product["aliases"] = sorted(
        (_serialize(a) for a in record["alias_nodes"] if a),
        key=lambda a: a.get("raw_name") or "",
    )
    product["observed_mrps"] = sorted({m for m in (_to_float(i.get("mrp")) for i in items) if m})
    product["observed_rates"] = sorted({r for r in (_to_float(i.get("rate")) for i in items) if r})
    product["observed_hsns"] = sorted({str(i["hsn"]).strip() for i in items if i.get("hsn")})
    product["observed_gst"] = sorted({g for g in (_to_float(i.get("gst_percent")) for i in items) if g is not None})
    product["vendors"] = sorted({v for v in record["vendors"] if v})
    product["times_seen"] = len(items)
    product["invoice_count"] = len(invoices)
    product["batch_count"] = len(batches)
    product["total_quantity"] = sum(_to_float(i.get("quantity")) or 0 for i in items)

    dates = sorted(d for d in (i.get("created_at") for i in invoices) if d)
    product["first_seen"] = dates[0] if dates else product.get("created_at")
    product["last_seen"] = dates[-1] if dates else product.get("created_at")

    # Units of individual medicine implied by pack multiplier, which is the
    # whole reason the multiplier is worth chasing down.
    multiplier = _to_float(product.get("pack_multiplier"))
    product["total_base_units"] = (
        round(product["total_quantity"] * multiplier, 2) if multiplier else None
    )
    return _decorate(product)


def list_products(pharmacy_id: Optional[str] = None) -> list[dict]:
    pharmacy_id = pharmacy_id or settings.DEFAULT_PHARMACY_ID
    driver = get_driver()
    with driver.session() as session:
        records = session.execute_read(
            lambda tx: list(tx.run(_aggregate_query(), pharmacy_id=pharmacy_id))
        )
    products = [_shape_product(r) for r in records]
    # Most incomplete and most-flagged first: the queue should open on the
    # item that is costing the most to leave unresolved.
    products.sort(
        key=lambda p: (
            p.get("review_status") == "confirmed",
            p["completeness"],
            -len([f for f in p["flags"] if f["severity"] == "high"]),
            p.get("canonical_name") or "",
        )
    )
    return products


def get_product(product_id: str, pharmacy_id: Optional[str] = None) -> Optional[dict]:
    """Full detail including every line item that fed this product, so the
    reviewer can see the actual invoice rows behind a merge before trusting it."""
    pharmacy_id = pharmacy_id or settings.DEFAULT_PHARMACY_ID
    driver = get_driver()
    with driver.session() as session:
        record = session.execute_read(
            lambda tx: tx.run(
                _aggregate_query(single=True),
                pharmacy_id=pharmacy_id,
                product_id=product_id,
            ).single()
        )
        if record is None:
            return None
        product = _shape_product(record)
        product["observations"] = session.execute_read(_observations_tx, product_id, pharmacy_id)
    return product


def _observations_tx(tx, product_id: str, pharmacy_id: str) -> list[dict]:
    result = tx.run(
        """
        MATCH (p:Product {id: $product_id})<-[:OF_PRODUCT]-(li:LineItem)
              <-[:CONTAINS]-(inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        OPTIONAL MATCH (li)-[:OF_ALIAS]->(a:ProductAlias)
        OPTIONAL MATCH (li)-[:OF_BATCH]->(b:Batch)
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        RETURN li, a.raw_name AS alias_name, a.id AS alias_id,
               b.batch_number AS batch_number, b.expiry_date AS expiry_date,
               inv.id AS invoice_id, inv.invoice_number AS invoice_number,
               inv.invoice_date AS invoice_date,
               coalesce(inv.seller_name, v.name) AS seller_name
        ORDER BY inv.created_at DESC, li.row_index
        """,
        product_id=product_id,
        pharmacy_id=pharmacy_id,
    )
    observations = []
    for record in result:
        item = _serialize(record["li"])
        item.update({
            "alias_name": record["alias_name"],
            "alias_id": record["alias_id"],
            "batch_number": record["batch_number"] or item.get("batch"),
            "expiry_date": record["expiry_date"] or item.get("expiry"),
            "invoice_id": record["invoice_id"],
            "invoice_number": record["invoice_number"],
            "invoice_date": record["invoice_date"],
            "seller_name": record["seller_name"],
        })
        observations.append(item)
    return observations


# --------------------------------------------------------------------------
# Mutations
# --------------------------------------------------------------------------

def update_product(
    product_id: str,
    fields: dict,
    confirm: bool = False,
    allow_merge: bool = False,
) -> Optional[dict]:
    """Applies human edits.

    Every field the caller sets is added to confirmed_fields, which is how the
    UI later tells an approved value from a parsed guess.

    Editing strength/form/pack changes what SKU this is, so identity_key is
    recomputed. If that lands on a product that already exists, the edit has
    revealed a duplicate: with allow_merge the two are merged, without it the
    conflict is returned so the user can decide rather than having records
    silently combined underneath them.
    """
    driver = get_driver()
    with driver.session() as session:
        result = session.execute_write(_update_product_tx, product_id, fields, confirm, allow_merge)
    if result is None:
        return None
    if result.get("conflict"):
        return result
    return get_product(result["id"])


def _update_product_tx(tx, product_id: str, fields: dict, confirm: bool, allow_merge: bool):
    existing = tx.run("MATCH (p:Product {id: $id}) RETURN p", id=product_id).single()
    if not existing:
        return None
    current = dict(existing["p"])

    updates = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    merged = {**current, **updates}

    new_key = build_identity_key(
        merged.get("brand"), merged.get("strength"), merged.get("form"), merged.get("pack_size")
    )

    conflict = None
    if new_key != current.get("identity_key"):
        clash = tx.run(
            "MATCH (o:Product {identity_key: $key}) WHERE o.id <> $id RETURN o LIMIT 1",
            key=new_key,
            id=product_id,
        ).single()
        if clash:
            if allow_merge:
                target_id = clash["o"]["id"]
                _apply_fields(tx, product_id, updates, confirm)
                _merge_products_tx(tx, [product_id], target_id)
                return {"id": target_id, "merged_into": target_id}
            conflict = _serialize(clash["o"])
            new_key = None  # leave identity alone until the user chooses

    _apply_fields(tx, product_id, updates, confirm, identity_key=new_key)

    if conflict:
        return {"id": product_id, "conflict": conflict}
    return {"id": product_id}


def _apply_fields(tx, product_id: str, updates: dict, confirm: bool, identity_key: Optional[str] = None):
    set_clauses = [f"p.{key} = ${key}" for key in updates]
    params: dict = {"id": product_id, **updates}

    if identity_key:
        set_clauses.append("p.identity_key = $identity_key")
        params["identity_key"] = identity_key

    # A field a human typed is no longer a guess. The union is computed here
    # rather than in Cypher because set operations on list properties need
    # APOC, which is not available on every Aura tier.
    existing_confirmed = tx.run(
        "MATCH (p:Product {id: $id}) RETURN coalesce(p.confirmed_fields, []) AS c", id=product_id
    ).single()["c"]
    set_clauses.append("p.confirmed_fields = $confirmed_fields")
    params["confirmed_fields"] = sorted(set(existing_confirmed) | set(updates.keys()))

    if confirm:
        set_clauses.append("p.review_status = 'confirmed'")
        set_clauses.append("p.confirmed_at = datetime()")

    set_clauses.append("p.updated_at = datetime()")

    tx.run(f"MATCH (p:Product {{id: $id}}) SET {', '.join(set_clauses)}", **params)

    if confirm:
        # Confirming the product also settles every spelling currently
        # pointing at it; a spelling that arrives later comes in as 'new' and
        # brings the product back to the queue.
        tx.run(
            """
            MATCH (:Product {id: $id})<-[:RESOLVES_TO]-(a:ProductAlias)
            SET a.status = 'confirmed'
            """,
            id=product_id,
        )


def merge_products(source_ids: list[str], target_id: str) -> Optional[dict]:
    """Folds source products into target: aliases, line items, batches, HSN."""
    sources = [s for s in source_ids if s and s != target_id]
    if not sources:
        return get_product(target_id)
    driver = get_driver()
    with driver.session() as session:
        ok = session.execute_write(_merge_products_tx, sources, target_id)
    if not ok:
        return None
    logger.info(f"[CATALOGUE] Merged {len(sources)} product(s) into {target_id}")
    return get_product(target_id)


def _merge_products_tx(tx, source_ids: list[str], target_id: str) -> bool:
    target = tx.run("MATCH (p:Product {id: $id}) RETURN p", id=target_id).single()
    if not target:
        return False
    target_props = dict(target["p"])

    # Each of these moves one relationship type across, one row at a time.
    # Deliberately no aggregation: a collect()/FOREACH formulation reads more
    # compactly but makes the row cardinality (and therefore what actually
    # gets rewritten) depend on how the optional matches expand, which is
    # exactly the kind of subtlety that should not sit under a destructive
    # operation. A query matching nothing simply produces no rows.
    tx.run(
        """
        UNWIND $source_ids AS sid
        MATCH (a:ProductAlias)-[r:RESOLVES_TO]->(:Product {id: sid})
        MATCH (t:Product {id: $target_id})
        DELETE r
        MERGE (a)-[:RESOLVES_TO]->(t)
        """,
        source_ids=source_ids,
        target_id=target_id,
    )

    tx.run(
        """
        UNWIND $source_ids AS sid
        MATCH (li:LineItem)-[r:OF_PRODUCT]->(:Product {id: sid})
        MATCH (t:Product {id: $target_id})
        DELETE r
        MERGE (li)-[:OF_PRODUCT]->(t)
        """,
        source_ids=source_ids,
        target_id=target_id,
    )

    # Batch nodes are keyed per product, so a merge can leave the target with
    # two nodes carrying the same batch_number. They are left as they are:
    # each still points at the invoice line that observed it, and collapsing
    # them would mean choosing which receipt's expiry date survives.
    tx.run(
        """
        UNWIND $source_ids AS sid
        MATCH (b:Batch)-[r:OF_PRODUCT]->(:Product {id: sid})
        MATCH (t:Product {id: $target_id})
        DELETE r
        MERGE (b)-[:OF_PRODUCT]->(t)
        """,
        source_ids=source_ids,
        target_id=target_id,
    )

    tx.run(
        """
        UNWIND $source_ids AS sid
        MATCH (:Product {id: sid})-[r:CLASSIFIED_AS]->(h:HSNCode)
        MATCH (t:Product {id: $target_id})
        DELETE r
        MERGE (t)-[:CLASSIFIED_AS]->(h)
        """,
        source_ids=source_ids,
        target_id=target_id,
    )

    # Fill the target's blanks from the sources rather than discarding facts
    # the losing records happened to carry.
    for source_id in source_ids:
        source = tx.run("MATCH (p:Product {id: $id}) RETURN p", id=source_id).single()
        if not source:
            continue
        gaps = {
            field: dict(source["p"]).get(field)
            for field in EDITABLE_FIELDS
            if target_props.get(field) in (None, "", []) and dict(source["p"]).get(field) not in (None, "", [])
        }
        if gaps:
            target_props.update(gaps)
            tx.run(
                f"MATCH (p:Product {{id: $id}}) SET {', '.join(f'p.{k} = ${k}' for k in gaps)}",
                id=target_id,
                **gaps,
            )

    tx.run("UNWIND $source_ids AS sid MATCH (s:Product {id: sid}) DETACH DELETE s", source_ids=source_ids)

    # The merged record is a new claim about identity, so it goes back through
    # review rather than inheriting the target's confirmation.
    tx.run(
        """
        MATCH (p:Product {id: $id})
        SET p.review_status = 'needs_review', p.updated_at = datetime()
        """,
        id=target_id,
    )
    return True


def split_alias(alias_id: str, overrides: Optional[dict] = None) -> Optional[dict]:
    """Detaches one spelling into its own product, taking its line items with it.

    This is the escape hatch for the merge-first default: when two strengths
    of the same brand were printed identically and got fused, splitting the
    spelling apart is how the reviewer separates them.
    """
    driver = get_driver()
    with driver.session() as session:
        new_id = session.execute_write(_split_alias_tx, alias_id, overrides or {})
    if not new_id:
        return None
    logger.info(f"[CATALOGUE] Split alias {alias_id} into product {new_id}")
    return get_product(new_id)


def _split_alias_tx(tx, alias_id: str, overrides: dict) -> Optional[str]:
    record = tx.run(
        """
        MATCH (a:ProductAlias {id: $alias_id})
        OPTIONAL MATCH (a)-[r:RESOLVES_TO]->(p:Product)
        RETURN a, p, r IS NOT NULL AS linked
        """,
        alias_id=alias_id,
    ).single()
    if not record:
        return None

    alias = dict(record["a"])
    parsed = parse_product_name(alias.get("raw_name"), overrides.get("pack_size"))

    fields = {
        "canonical_name": alias.get("raw_name"),
        "brand": parsed.brand.value,
        "strength": parsed.strength.value,
        "form": parsed.form.value,
        "pack_size": parsed.pack_size.value,
        "pack_multiplier": parsed.pack_multiplier.value,
        "base_unit": parsed.base_unit.value,
    }
    fields.update({k: v for k, v in overrides.items() if k in EDITABLE_FIELDS})

    identity_key = build_identity_key(
        fields.get("brand"), fields.get("strength"), fields.get("form"), fields.get("pack_size")
    )
    # A split that lands back on the identity it came from would be a no-op,
    # so it gets a unique suffix until the reviewer supplies what distinguishes
    # it - otherwise "split" would silently do nothing.
    if identity_key == (dict(record["p"]).get("identity_key") if record["p"] else None):
        identity_key = f"{identity_key}#{uuid.uuid4().hex[:8]}"

    new_id = tx.run(
        """
        MERGE (p:Product {identity_key: $identity_key})
        ON CREATE SET p.id = randomUUID(), p.created_at = datetime(),
                      p.confirmed_fields = [], p.review_status = 'needs_review'
        SET p.canonical_name = $canonical_name, p.brand = $brand, p.strength = $strength,
            p.form = $form, p.pack_size = $pack_size, p.pack_multiplier = $pack_multiplier,
            p.base_unit = $base_unit, p.updated_at = datetime()
        RETURN p.id AS id
        """,
        identity_key=identity_key,
        **fields,
    ).single()["id"]

    tx.run(
        """
        MATCH (a:ProductAlias {id: $alias_id})
        OPTIONAL MATCH (a)-[r:RESOLVES_TO]->(:Product)
        DELETE r
        WITH a
        MATCH (p:Product {id: $new_id})
        MERGE (a)-[:RESOLVES_TO]->(p)
        SET a.status = 'new'
        """,
        alias_id=alias_id,
        new_id=new_id,
    )

    # Only the observations that came in under THIS spelling move. That is the
    # whole point of recording the alias on the line: without it a split could
    # only guess which rows belonged to which of the fused products.
    tx.run(
        """
        MATCH (li:LineItem)-[:OF_ALIAS]->(:ProductAlias {id: $alias_id})
        MATCH (p:Product {id: $new_id})
        OPTIONAL MATCH (li)-[old:OF_PRODUCT]->(:Product)
        DELETE old
        MERGE (li)-[:OF_PRODUCT]->(p)
        """,
        alias_id=alias_id,
        new_id=new_id,
    )

    # Batches follow the lines that observed them.
    tx.run(
        """
        MATCH (:ProductAlias {id: $alias_id})<-[:OF_ALIAS]-(li:LineItem)-[:OF_BATCH]->(b:Batch)
        MATCH (p:Product {id: $new_id})
        MERGE (b)-[:OF_PRODUCT]->(p)
        """,
        alias_id=alias_id,
        new_id=new_id,
    )
    return new_id


def delete_orphan_products() -> int:
    """Removes catalogue rows no invoice references any more."""
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(
            lambda tx: tx.run(
                """
                MATCH (p:Product) WHERE NOT (p)<-[:OF_PRODUCT]-(:LineItem)
                OPTIONAL MATCH (p)<-[:RESOLVES_TO]-(a:ProductAlias)
                DETACH DELETE p, a
                RETURN count(p) AS removed
                """
            ).single()["removed"]
        )


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------

def migrate_legacy_products() -> int:
    """Brings Products written by the name-keyed schema into the alias model.

    Legacy rows identify by normalized_name and have no alias and no
    identity_key, so without this the new write path would MERGE on
    identity_key, miss them, and create a second product for every item
    already in the catalogue. Idempotent: rows that already have an
    identity_key are skipped.
    """
    driver = get_driver()
    with driver.session() as session:
        legacy = session.execute_read(
            lambda tx: [
                _serialize(r["p"])
                for r in tx.run(
                    "MATCH (p:Product) WHERE p.identity_key IS NULL RETURN p"
                )
            ]
        )
        if not legacy:
            return 0

        migrated = 0
        for product in legacy:
            session.execute_write(_migrate_one_tx, product)
            migrated += 1

    logger.info(f"[CATALOGUE] Migrated {migrated} legacy product(s) to the alias model.")
    return migrated


def _migrate_one_tx(tx, product: dict):
    raw_name = product.get("canonical_name") or product.get("normalized_name") or ""
    parsed = parse_product_name(raw_name, product.get("pack"))
    normalized = normalize_name(raw_name)

    # If another product already holds this identity, the legacy row is a
    # duplicate of it and folds in rather than fighting for the key.
    existing = tx.run(
        "MATCH (o:Product {identity_key: $key}) WHERE o.id <> $id RETURN o.id AS id LIMIT 1",
        key=parsed.identity_key,
        id=product["id"],
    ).single()

    if normalized:
        tx.run(
            """
            MERGE (a:ProductAlias {normalized_name: $normalized})
            ON CREATE SET a.id = randomUUID(), a.raw_name = $raw, a.status = 'new',
                          a.first_seen = datetime(), a.times_seen = 1
            WITH a
            MATCH (p:Product {id: $product_id})
            MERGE (a)-[:RESOLVES_TO]->(p)
            WITH a, p
            MATCH (li:LineItem)-[:OF_PRODUCT]->(p)
            MERGE (li)-[:OF_ALIAS]->(a)
            """,
            normalized=normalized,
            raw=raw_name,
            product_id=product["id"],
        )

    tx.run(
        """
        MATCH (p:Product {id: $id})
        SET p.identity_key = $identity_key,
            p.brand = coalesce(p.brand, $brand),
            p.strength = coalesce(p.strength, $strength),
            p.form = coalesce(p.form, $form),
            p.pack_size = coalesce(p.pack_size, $pack_size),
            p.pack_multiplier = coalesce(p.pack_multiplier, $pack_multiplier),
            p.base_unit = coalesce(p.base_unit, $base_unit),
            p.review_status = coalesce(p.review_status, 'needs_review'),
            p.confirmed_fields = coalesce(p.confirmed_fields, [])
        REMOVE p.normalized_name
        """,
        id=product["id"],
        identity_key=parsed.identity_key if not existing else f"{parsed.identity_key}#legacy-{product['id'][:8]}",
        brand=parsed.brand.value,
        strength=parsed.strength.value,
        form=parsed.form.value,
        pack_size=parsed.pack_size.value,
        pack_multiplier=parsed.pack_multiplier.value,
        base_unit=parsed.base_unit.value,
    )

    if existing:
        _merge_products_tx(tx, [product["id"]], existing["id"])
