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

import re
import uuid
from dataclasses import dataclass
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

# --------------------------------------------------------------------------
# Vendor item cross-reference - "the same item, arriving a second time"
# --------------------------------------------------------------------------
#
# This is the supplier item cross-reference every ERP keeps (SAP's vendor
# material number, JD Edwards' supplier cross-reference, Business Central's
# item references): a mapping from what one supplier calls a thing to what we
# call it. Map it once by hand, match it automatically ever after.
#
# Those systems key the mapping on the supplier's own item code. Our suppliers
# print none - none of the invoice formats in the corpus carries a code column
# - so the key is the supplier's printed description instead. That works
# because a distributor's software prints the same string for the same product
# every time; the variation this system fights is between vendors, not within
# one vendor's own bills.
#
# The key is deliberately the whole set of indicators the vendor showed, not
# just the name, because vendors differ in WHERE they put things: one spells
# the pack inside the item name, the next gives it its own column. Keying on
# the name alone would make
#
#     STERIVON H/S 100 ML   and   STERIVON H/S 200 ML
#
# the same item as soon as one vendor moved the size out of the name - a
# silent, confident match onto the wrong SKU, which then corrupts every stock
# and rate figure derived from it. So a changed indicator does not auto-match;
# it asks.

VENDOR_EXACT = "vendor_exact"          # same vendor, every indicator identical
VENDOR_CHANGED = "vendor_changed"      # same vendor + name, an indicator moved
ALIAS_MATCH = "alias"                  # spelling already routed to a SKU
NEW_PRODUCT = "new"                    # nothing matched

AUTO_CONFIRMED = "auto_confirmed"
NEEDS_CONFIRMATION = "needs_confirmation"
UNSEEN = "new"


@dataclass
class ProductMatch:
    """How a line item found its SKU, so the UI can say why."""

    alias_id: Optional[str] = None
    product_id: Optional[str] = None
    tier: str = NEW_PRODUCT
    status: str = UNSEEN
    note: Optional[str] = None
    times_seen: int = 0


def vendor_name_key(name: Optional[str]) -> str:
    """Stable identity for a supplier that prints no GSTIN."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _indicator(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def vendor_item_fingerprint(
    name: Optional[str],
    pack: Optional[str],
    manufacturer: Optional[str],
    hsn: Optional[str],
) -> tuple[str, str]:
    """(name_key, fingerprint) - the cross-reference's two lookup keys.

    name_key alone finds "this vendor has billed this name before"; the
    fingerprint additionally pins every other indicator the vendor printed, and
    only an exact fingerprint hit is safe to apply without asking.
    """
    name_key = normalize_name(name or "")
    fingerprint = "|".join([
        name_key,
        _indicator(pack),
        _indicator(manufacturer),
        _indicator(hsn),
    ])
    return name_key, fingerprint


def _describe_change(previous: dict, pack, manufacturer, hsn) -> str:
    """Names the indicator that moved, for the confirmation prompt."""
    changes = []
    for label, was, now in (
        ("pack", previous.get("pack"), _indicator(pack)),
        ("manufacturer", previous.get("manufacturer"), _indicator(manufacturer)),
        ("HSN", previous.get("hsn"), _indicator(hsn)),
    ):
        if (was or "") != (now or ""):
            changes.append(f"{label} {was or '—'} → {now or '—'}")
    return "; ".join(changes) or "an indicator changed"


def _lookup_vendor_item(tx, vendor_id: str, name_key: str) -> list[dict]:
    result = tx.run(
        """
        MATCH (v:Vendor {id: $vendor_id})-[s:SUPPLIES]->(p:Product)
        WHERE s.name_key = $name_key
        RETURN p.id AS product_id, s.fingerprint AS fingerprint,
               s.pack AS pack, s.manufacturer AS manufacturer, s.hsn AS hsn,
               coalesce(s.times_seen, 0) AS times_seen
        """,
        vendor_id=vendor_id,
        name_key=name_key,
    )
    return [dict(record) for record in result]


def record_vendor_item(
    tx,
    vendor_id: Optional[str],
    product_id: Optional[str],
    name: Optional[str],
    pack: Optional[str] = None,
    manufacturer: Optional[str] = None,
    hsn: Optional[str] = None,
) -> None:
    """Writes the cross-reference. Called when a human verifies an invoice.

    Verification is the whole trigger: this mapping is the user's judgement
    made reusable, so it must not be created by merely uploading a scan. An
    unreviewed OCR misread that wrote a cross-reference would auto-apply itself
    to every future invoice from that vendor.
    """
    if not (vendor_id and product_id and name):
        return

    name_key, fingerprint = vendor_item_fingerprint(name, pack, manufacturer, hsn)
    if not name_key:
        return

    tx.run(
        """
        MATCH (v:Vendor {id: $vendor_id})
        MATCH (p:Product {id: $product_id})
        MERGE (v)-[s:SUPPLIES {fingerprint: $fingerprint}]->(p)
        ON CREATE SET s.name_key = $name_key, s.pack = $pack,
                      s.manufacturer = $manufacturer, s.hsn = $hsn,
                      s.first_confirmed = datetime(), s.times_seen = 0
        SET s.times_seen = coalesce(s.times_seen, 0) + 1,
            s.last_confirmed = datetime()
        """,
        vendor_id=vendor_id,
        product_id=product_id,
        fingerprint=fingerprint,
        name_key=name_key,
        pack=_indicator(pack),
        manufacturer=_indicator(manufacturer),
        hsn=_indicator(hsn),
    )


def unlink_vendor_item(tx, vendor_id: str, name: str, pack=None, manufacturer=None, hsn=None) -> bool:
    """Undoes one cross-reference - the escape hatch behind "not this item".

    An automatic action the user cannot reverse is worse than no automation.
    """
    _, fingerprint = vendor_item_fingerprint(name, pack, manufacturer, hsn)
    record = tx.run(
        """
        MATCH (:Vendor {id: $vendor_id})-[s:SUPPLIES {fingerprint: $fingerprint}]->(:Product)
        DELETE s
        RETURN count(*) AS removed
        """,
        vendor_id=vendor_id,
        fingerprint=fingerprint,
    ).single()
    return bool(record and record["removed"])


def resolve_line_item_product(
    tx,
    vendor_id: Optional[str],
    name: Optional[str],
    pack: Optional[str] = None,
    hsn: Optional[str] = None,
    manufacturer: Optional[str] = None,
) -> ProductMatch:
    """The match funnel, most certain evidence first.

    Tier 1  same vendor, identical indicators  -> apply, tell the user
    Tier 2  same vendor, an indicator moved    -> resolve normally, ASK
    Tier 3  spelling already routed to a SKU   -> apply
    Tier 4  nothing matched                    -> new SKU, for review
    """
    if not name or not str(name).strip():
        return ProductMatch()

    name_key, fingerprint = vendor_item_fingerprint(name, pack, manufacturer, hsn)

    if vendor_id and name_key:
        rows = _lookup_vendor_item(tx, vendor_id, name_key)
        exact = next((r for r in rows if r["fingerprint"] == fingerprint), None)
        if exact:
            alias_id, _ = _upsert_alias(tx, name)
            _bind_alias(tx, alias_id, exact["product_id"])
            _fill_missing_manufacturer(tx, exact["product_id"], manufacturer)
            return ProductMatch(
                alias_id=alias_id,
                product_id=exact["product_id"],
                tier=VENDOR_EXACT,
                status=AUTO_CONFIRMED,
                note=None,
                times_seen=exact["times_seen"],
            )
        if rows:
            # The vendor has billed this name before, but something about it
            # moved. Resolving normally is right - identity_key already splits
            # on pack, so a genuinely new size lands on its own SKU - but the
            # user is told rather than the change being absorbed in silence.
            alias_id, product_id = resolve_alias_and_product(tx, name, pack, hsn, manufacturer)
            return ProductMatch(
                alias_id=alias_id,
                product_id=product_id,
                tier=VENDOR_CHANGED,
                status=NEEDS_CONFIRMATION,
                note=_describe_change(rows[0], pack, manufacturer, hsn),
            )

    existing = _alias_target(tx, name)
    alias_id, product_id = resolve_alias_and_product(tx, name, pack, hsn, manufacturer)
    if existing:
        return ProductMatch(
            alias_id=alias_id, product_id=product_id,
            tier=ALIAS_MATCH, status=AUTO_CONFIRMED,
        )
    return ProductMatch(
        alias_id=alias_id, product_id=product_id,
        tier=NEW_PRODUCT, status=UNSEEN,
    )


def _alias_target(tx, name: str) -> Optional[str]:
    """The SKU this spelling already routes to, if any - read before writing."""
    normalized = normalize_name(str(name).strip())
    if not normalized:
        return None
    record = tx.run(
        """
        MATCH (a:ProductAlias {normalized_name: $normalized})-[:RESOLVES_TO]->(p:Product)
        RETURN p.id AS product_id
        """,
        normalized=normalized,
    ).single()
    return record["product_id"] if record else None


def _upsert_alias(tx, name: str) -> tuple[Optional[str], Optional[str]]:
    raw = str(name).strip()
    normalized = normalize_name(raw)
    if not normalized:
        return None, None
    record = tx.run(
        """
        MERGE (a:ProductAlias {normalized_name: $normalized})
        ON CREATE SET a.id = randomUUID(), a.raw_name = $raw,
                      a.status = 'new', a.first_seen = datetime(), a.times_seen = 0
        SET a.times_seen = coalesce(a.times_seen, 0) + 1, a.last_seen = datetime()
        WITH a
        OPTIONAL MATCH (a)-[:RESOLVES_TO]->(p:Product)
        RETURN a.id AS alias_id, p.id AS product_id
        """,
        normalized=normalized,
        raw=raw,
    ).single()
    return record["alias_id"], record["product_id"]


def _bind_alias(tx, alias_id: Optional[str], product_id: Optional[str]) -> None:
    """Routes a spelling to a SKU, but only if it is not already routed.

    An alias resolving to two Products is a corrupt state - reads pick one
    arbitrarily, so stock and history silently split. A plain MERGE would not
    stop it, because MERGE only dedupes the edge to the SAME product: a
    cross-reference pointing somewhere other than where this spelling already
    resolves would quietly add a second edge. Where the two disagree the
    existing routing wins, since a human may have set it deliberately.
    """
    if not (alias_id and product_id):
        return
    tx.run(
        """
        MATCH (a:ProductAlias {id: $alias_id})
        WHERE NOT (a)-[:RESOLVES_TO]->(:Product)
        MATCH (p:Product {id: $product_id})
        MERGE (a)-[:RESOLVES_TO]->(p)
        """,
        alias_id=alias_id,
        product_id=product_id,
    )


def resolve_alias_and_product(
    tx,
    name: Optional[str],
    pack: Optional[str],
    hsn: Optional[str] = None,
    manufacturer: Optional[str] = None,
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
        _fill_missing_manufacturer(tx, product_id, manufacturer)
        return alias_id, product_id

    product_id = _merge_product_by_identity(tx, parsed, raw, hsn, manufacturer)
    # The identity may have resolved to a product that already existed, in
    # which case ON CREATE did not run and the maker is still blank.
    _fill_missing_manufacturer(tx, product_id, manufacturer)

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


# The supplier naming the maker in its own column is a direct statement rather
# than an inference, so it is scored like a field the name stated outright. It
# is still a proposal a reviewer confirms.
MANUFACTURER_CONFIDENCE = 0.8


def _fill_missing_manufacturer(
    tx, product_id: Optional[str], manufacturer: Optional[str]
) -> None:
    """Records the maker on a product that has none.

    Most of the catalogue predates this field, and those products are reached
    through the alias shortcut above, which never runs the create path. Without
    this they would read "Manufacturer not recorded" forever despite their
    invoices stating it plainly.

    Fills only - a value already present, or one the pharmacist confirmed, is
    left alone. Same rule as everywhere else here: a parse never outranks a
    human decision.
    """
    if not product_id or not manufacturer:
        return
    tx.run(
        """
        MATCH (p:Product {id: $product_id})
        WHERE p.manufacturer IS NULL
          AND NOT 'manufacturer' IN coalesce(p.confirmed_fields, [])
        SET p.manufacturer = $manufacturer,
            p.manufacturer_confidence = $confidence
        """,
        product_id=product_id,
        manufacturer=manufacturer,
        confidence=MANUFACTURER_CONFIDENCE,
    )


def _merge_product_by_identity(
    tx, parsed, raw_name: str, hsn: Optional[str], manufacturer: Optional[str] = None
) -> str:
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
                      p.manufacturer = $manufacturer,
                      p.manufacturer_confidence = $manufacturer_confidence,
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
        manufacturer=manufacturer,
        manufacturer_confidence=MANUFACTURER_CONFIDENCE if manufacturer else 0.0,
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

# The catalogue is master data, so only invoices a human has actually checked
# may contribute to it. Extraction runs before anyone has looked at the
# result, and a bad read produces convincing-looking rows - a tax footer line
# came through as the product "VEE 2980.89*2.5+2.5%=74.51SGST+74.51CGST" -
# which would otherwise be written into the permanent catalogue by the act of
# uploading alone.
#
# Applied as a read filter rather than by withholding the write: the graph
# still records what each invoice said, so verifying an invoice later surfaces
# its products immediately with their full history intact, and un-verifying
# one takes them back out. Nothing has to be replayed either way.
VERIFIED_ONLY = "inv.status = 'verified'"


def _aggregate_query(single: bool = False) -> str:
    """Rolls a product up with the invoice evidence behind it.

    Scoped to one pharmacy's VERIFIED invoices: Product nodes are shared
    across tenants, but "how many times have I bought this and at what price"
    is emphatically not - and neither figure should count purchases nobody has
    confirmed yet.
    """
    selector = "(p:Product {id: $product_id})" if single else "(p:Product)"
    return f"""
MATCH {selector}<-[:OF_PRODUCT]-(li:LineItem)<-[:CONTAINS]-(inv:Invoice)
      -[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
WHERE {VERIFIED_ONLY}
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


# Every catalogue field the API promises to return, so a consumer can rely on
# the shape. Neo4j does not store null properties at all - an unset form is an
# absent key, not a null one - so without this the response silently drops
# whichever fields happen to be empty, which is precisely the set a review
# screen most needs to ask about.
_DECLARED_FIELDS = (
    *EDITABLE_FIELDS,
    "identity_key",
    "review_status",
    "brand_confidence",
    "strength_confidence",
    "form_confidence",
    "pack_size_confidence",
    "pack_multiplier_confidence",
    "base_unit_confidence",
)


def _shape_product(record) -> dict:
    product = _serialize(record["p"])
    for field in _DECLARED_FIELDS:
        product.setdefault(field, None)
    product.setdefault("confirmed_fields", [])
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

    # An HSN code printed on the invoice is read data, not a guess, so when
    # every line that ever mentioned this product agreed on one code it stands
    # as the product's code. Disagreement is left blank and raised as
    # hsn_conflict instead, because picking a winner there would be inventing
    # a tax classification.
    if not product.get("hsn") and len(product["observed_hsns"]) == 1:
        product["hsn"] = product["observed_hsns"][0]

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
        f"""
        MATCH (p:Product {{id: $product_id}})<-[:OF_PRODUCT]-(li:LineItem)
              <-[:CONTAINS]-(inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        // Same verified-only rule as the summary above. Without it a
        // product's price range would mix confirmed purchases with unreviewed
        // ones, and an unreviewed misread price would raise a price-conflict
        // flag against data nobody has stood behind.
        WHERE {VERIFIED_ONLY}
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


def _apply_item_type_rules(tx, updates: dict, merged: dict) -> None:
    """Makes the admin's item-type definitions bind on the product itself.

    Two rules, both derived from the type rather than hardcoded here:

      * the dispensing unit must be one the type actually supports - a cream
        measured in TABLET is not a data-entry preference, it is wrong, and it
        silently corrupts every stock figure derived from it;
      * changing the form to one whose current unit no longer fits adopts that
        type's own unit instead of leaving a stale one behind.

    A form with no matching item type is left alone. Types can be switched off
    while products still carry their name, and refusing to save those products
    would strand them.
    """
    from db import item_type_repository

    form = merged.get("form")
    if not form:
        return

    rules = item_type_repository.units_for_form(tx, form)
    if not rules:
        return

    supported = rules.get("supported_units") or []
    if not supported:
        return

    unit = merged.get("base_unit")
    if "base_unit" in updates and unit and unit not in supported:
        raise ValueError(
            f"{form} is measured in {', '.join(supported)} — {unit} is not one of them. "
            f"Add {unit} to the {form} item type in Settings if that is intended."
        )

    # Form changed (or the unit was never set) and what is there does not fit:
    # take the type's own unit rather than keeping a unit from a different form.
    if unit not in supported:
        updates["base_unit"] = rules.get("base_unit") or supported[0]
        merged["base_unit"] = updates["base_unit"]


def _update_product_tx(tx, product_id: str, fields: dict, confirm: bool, allow_merge: bool):
    existing = tx.run("MATCH (p:Product {id: $id}) RETURN p", id=product_id).single()
    if not existing:
        return None
    current = dict(existing["p"])

    updates = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    merged = {**current, **updates}

    _apply_item_type_rules(tx, updates, merged)

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


def reparse_products(pharmacy_id: Optional[str] = None) -> dict:
    """Re-reads every product's own invoice text with the current parser.

    The parser improves - it learned to read the TA/CA/T/M pack codes that
    most of this catalogue was written with - but products already stored keep
    whatever the parser understood on the day they were created. Without this
    the improvement only ever reaches items scanned from now on, and the
    existing catalogue stays permanently worse than the code that serves it.

    Human decisions are never overwritten: a field listed in confirmed_fields
    is left exactly as the pharmacist set it, even when the parser now
    disagrees. Only guesses are re-made.
    """
    pharmacy_id = pharmacy_id or settings.DEFAULT_PHARMACY_ID
    driver = get_driver()

    with driver.session() as session:
        rows = session.execute_read(
            lambda tx: [
                dict(r)
                for r in tx.run(
                    """
                    MATCH (p:Product)<-[:OF_PRODUCT]-(li:LineItem)
                          <-[:CONTAINS]-(inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
                    // Verified only, matching the read path: re-parsing a
                    // product nobody can see would report work done on rows
                    // that are not in the catalogue yet.
                    WHERE inv.status = 'verified'
                    OPTIONAL MATCH (p)<-[:RESOLVES_TO]-(a:ProductAlias)
                    WITH p, collect(DISTINCT a.raw_name) AS names,
                         collect(DISTINCT li.pack) AS packs
                    RETURN p, names, packs
                    """,
                    pharmacy_id=pharmacy_id,
                )
            ]
        )

        changed, skipped = 0, 0
        details = []

        for row in rows:
            product = dict(row["p"])
            names = [n for n in row["names"] if n] or [product.get("canonical_name")]
            # Prefer the pack column the invoice printed; fall back to the
            # stored pack_size, which still holds the raw text for exactly the
            # rows the old parser could not read.
            packs = [p for p in row["packs"] if p]
            pack = packs[0] if packs else product.get("pack_size")

            if not names or not names[0]:
                skipped += 1
                continue

            parsed = parse_product_name(names[0], pack)
            confirmed = set(product.get("confirmed_fields") or [])

            updates = {}
            for field, guess in (
                ("strength", parsed.strength),
                ("form", parsed.form),
                ("pack_size", parsed.pack_size),
                ("pack_multiplier", parsed.pack_multiplier),
                ("base_unit", parsed.base_unit),
            ):
                if field in confirmed or not guess.known:
                    continue
                if product.get(field) != guess.value:
                    updates[field] = guess.value

            if not updates:
                skipped += 1
                continue

            session.execute_write(_apply_reparse_tx, product["id"], updates)
            changed += 1
            details.append({
                "id": product["id"],
                "name": names[0],
                "pack": pack,
                "updated": updates,
            })

    logger.info(f"[CATALOGUE] Re-parsed {len(rows)} product(s): {changed} updated, {skipped} unchanged")
    return {"examined": len(rows), "updated": changed, "unchanged": skipped, "details": details}


def _apply_reparse_tx(tx, product_id: str, updates: dict):
    set_clauses = [f"p.{key} = ${key}" for key in updates]
    tx.run(
        f"MATCH (p:Product {{id: $id}}) SET {', '.join(set_clauses)}, p.updated_at = datetime()",
        id=product_id,
        **updates,
    )

    # Identity depends on brand/strength/form/pack, so a better parse can move
    # a product onto a key another record already holds. That is a genuine
    # duplicate, but merging records as a side effect of a maintenance pass is
    # not this function's call - the key is left alone and the pair surfaces
    # in the review queue for a person to merge deliberately.
    record = tx.run("MATCH (p:Product {id: $id}) RETURN p", id=product_id).single()
    product = dict(record["p"])
    new_key = build_identity_key(
        product.get("brand"), product.get("strength"), product.get("form"), product.get("pack_size")
    )
    if new_key == product.get("identity_key"):
        return

    clash = tx.run(
        "MATCH (o:Product {identity_key: $key}) WHERE o.id <> $id RETURN o.id AS id LIMIT 1",
        key=new_key,
        id=product_id,
    ).single()
    if not clash:
        tx.run("MATCH (p:Product {id: $id}) SET p.identity_key = $key", id=product_id, key=new_key)


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
