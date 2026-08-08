import uuid
from typing import Any, Optional

from core.config import settings
from core.dates import normalize_expiry, normalize_invoice_date
from core.logger import logger
from db import product_repository
from db.graph_db import get_driver
from extraction.normalizers.canonical_invoice import CanonicalInvoice
from extraction.normalizers.quantity_check import check_free_quantity


def _serialize_node(node) -> dict:
    """Converts a Neo4j node to a plain dict, stringifying temporal properties
    (neo4j.time.DateTime/Date) that don't serialize cleanly through FastAPI's
    default JSON encoder."""
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


def _as_image_key_list(image_object_key: Any) -> list[str]:
    """Accepts either a single object key or a list of them (one per page of a
    multi-page invoice) and returns a clean list."""
    if image_object_key is None:
        return []
    if isinstance(image_object_key, str):
        return [image_object_key]
    return [k for k in image_object_key if k]


def save_invoice(
    invoice: CanonicalInvoice,
    image_object_key: Any = None,
    pharmacy_id: Optional[str] = None,
    user_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
) -> str:
    """Persists a CanonicalInvoice into the graph and returns the Invoice id.

    image_object_key may be a single key or a list of keys, one per page, in
    page order.
    """
    pharmacy_id = pharmacy_id or settings.DEFAULT_PHARMACY_ID
    user_id = user_id or settings.DEFAULT_USER_ID
    invoice_id = invoice_id or str(uuid.uuid4())
    image_keys = _as_image_key_list(image_object_key)

    driver = get_driver()
    with driver.session() as session:
        session.execute_write(_write_invoice_tx, invoice_id, pharmacy_id, user_id, image_keys, invoice)

    logger.info(
        f"[NEO4J] Saved invoice {invoice_id} ({len(invoice.line_items)} line items, "
        f"{len(image_keys)} page image(s)) for pharmacy {pharmacy_id}"
    )
    return invoice_id


def _write_invoice_tx(tx, invoice_id: str, pharmacy_id: str, user_id: str, image_keys: list[str], inv: CanonicalInvoice):
    vendor_id = _resolve_vendor(tx, inv)

    # MERGE (not MATCH) for the tenant nodes: if the Pharmacy/User were ever
    # wiped externally (e.g. a manual reset in the Aura console), a plain
    # MATCH silently returns zero rows and the whole CREATE below becomes a
    # no-op — the write reports success but nothing is actually persisted.
    # Self-heal instead of silently dropping the invoice.
    record = tx.run(
        """
        MERGE (ph:Pharmacy {id: $pharmacy_id})
        ON CREATE SET ph.name = $pharmacy_id, ph.created_at = datetime()
        MERGE (u:User {id: $user_id})
        ON CREATE SET u.email = $user_id, u.role = 'owner', u.created_at = datetime()
        CREATE (inv:Invoice {
            id: $invoice_id,
            invoice_number: $invoice_number,
            invoice_date: $invoice_date,
            seller_name: $seller_name,
            seller_gstin: $seller_gstin,
            seller_address: $seller_address,
            seller_phone: $seller_phone,
            drug_license: $drug_license,
            buyer_name: $buyer_name,
            buyer_gstin: $buyer_gstin,
            subtotal: $subtotal,
            discount: $discount,
            discount_breakdown_labels: $discount_breakdown_labels,
            discount_breakdown_amounts: $discount_breakdown_amounts,
            cgst: $cgst,
            sgst: $sgst,
            igst: $igst,
            grand_total: $grand_total,
            roundoff: $roundoff,
            confidence: $confidence,
            extraction_engine: $extraction_engine,
            page_angle: $page_angle,
            page_angles: $page_angles,
            status: 'needs_review',
            source_image_ref: $image_ref,
            source_image_refs: $image_refs,
            page_count: $page_count,
            created_at: datetime()
        })
        CREATE (inv)-[:BELONGS_TO]->(ph)
        CREATE (inv)-[:UPLOADED_BY]->(u)
        RETURN inv.id AS id
        """,
        pharmacy_id=pharmacy_id,
        user_id=user_id,
        invoice_id=invoice_id,
        invoice_number=inv.invoice_number,
        # Dates are canonicalised on the way in, not on the way out: reports
        # filter periods with an ISO string comparison, so a row stored as
        # "03/08/2026" would silently match no period at all.
        invoice_date=normalize_invoice_date(inv.invoice_date),
        seller_name=inv.seller_name,
        seller_gstin=inv.seller_gstin,
        seller_address=inv.seller_address,
        seller_phone=inv.seller_phone,
        drug_license=inv.drug_license,
        buyer_name=inv.buyer_name,
        buyer_gstin=inv.buyer_gstin,
        subtotal=inv.subtotal,
        discount=inv.discount,
        # Neo4j properties can't hold a list of maps, so the breakdown travels
        # as two parallel lists and is zipped back into {label, amount} pairs
        # on read (_get_invoice_tx).
        discount_breakdown_labels=[str(d.get("label")) for d in (inv.discount_breakdown or [])],
        discount_breakdown_amounts=[float(d.get("amount")) for d in (inv.discount_breakdown or [])],
        cgst=inv.cgst,
        sgst=inv.sgst,
        igst=inv.igst,
        grand_total=inv.grand_total,
        roundoff=inv.roundoff,
        confidence=inv.confidence,
        extraction_engine=inv.extraction_engine,
        page_angle=inv.page_angle,
        page_angles=[float(a) for a in (inv.page_angles or [])],
        # source_image_ref stays as page 1 so records written before
        # multi-page support, and any reader still expecting a single key,
        # keep working unchanged.
        image_ref=image_keys[0] if image_keys else None,
        image_refs=image_keys,
        page_count=len(image_keys),
    ).single()

    if record is None:
        raise RuntimeError(
            f"Invoice CREATE for {invoice_id} returned no rows — the write "
            f"silently no-op'd (pharmacy_id={pharmacy_id!r}, user_id={user_id!r})."
        )

    if vendor_id:
        tx.run(
            """
            MATCH (inv:Invoice {id: $invoice_id})
            MATCH (v:Vendor {id: $vendor_id})
            CREATE (inv)-[:SUPPLIED_BY]->(v)
            """,
            invoice_id=invoice_id,
            vendor_id=vendor_id,
        )

    for row_index, item in enumerate(inv.line_items):
        _write_line_item(tx, invoice_id, item.model_dump(), row_index, vendor_id)


def _resolve_vendor(tx, inv: CanonicalInvoice) -> Optional[str]:
    if inv.seller_gstin:
        record = tx.run(
            """
            MERGE (v:Vendor {gstin: $gstin})
            ON CREATE SET v.id = randomUUID(), v.name = $name, v.address = $address,
                          v.phone = $phone, v.drug_license = $drug_license
            ON MATCH SET v.name = coalesce($name, v.name)
            RETURN v.id AS id
            """,
            gstin=inv.seller_gstin,
            name=inv.seller_name,
            address=inv.seller_address,
            phone=inv.seller_phone,
            drug_license=inv.drug_license,
        ).single()
        return record["id"]

    if inv.seller_name:
        # MERGE on the name, not CREATE. A supplier that prints no GSTIN used to
        # get a fresh Vendor node per invoice, so "the same vendor" was never the
        # same node twice - which silently defeats anything keyed on vendor
        # identity, the item cross-reference below most of all.
        record = tx.run(
            """
            MERGE (v:Vendor {name_key: $name_key})
            ON CREATE SET v.id = randomUUID(), v.name = $name, v.address = $address,
                          v.phone = $phone, v.drug_license = $drug_license
            ON MATCH SET v.address = coalesce(v.address, $address),
                         v.phone = coalesce(v.phone, $phone),
                         v.drug_license = coalesce(v.drug_license, $drug_license)
            RETURN v.id AS id
            """,
            name_key=product_repository.vendor_name_key(inv.seller_name),
            name=inv.seller_name,
            address=inv.seller_address,
            phone=inv.seller_phone,
            drug_license=inv.drug_license,
        ).single()
        return record["id"]

    return None


def _write_line_item(tx, invoice_id: str, item: dict, row_index: int,
                     vendor_id: Optional[str] = None):
    """item is a plain dict with CanonicalLineItem-shaped keys (name, pack, batch,
    expiry, hsn, quantity, free_quantity, mrp, rate, discount, gst_percent, amount,
    bounding_box) — shared by both the initial extraction write and PATCH updates.
    row_index records the item's position in the caller's list — Neo4j doesn't
    preserve relationship or node creation order on retrieval, so without this
    the printed line-item order would be lost as soon as it's re-read."""
    item_id = str(uuid.uuid4())
    name = item.get("name")
    pack = item.get("pack")
    batch = item.get("batch")
    hsn = item.get("hsn")
    # Pharma expiry is month-precision ("08/26" means good through August), so
    # it resolves to the last day of that month. Storing the 1st instead would
    # write stock off a month early in the near-expiry report.
    expiry = normalize_expiry(item.get("expiry"))

    tx.run(
        """
        MATCH (inv:Invoice {id: $invoice_id})
        CREATE (li:LineItem {
            id: $item_id,
            row_index: $row_index,
            quantity: $quantity,
            free_quantity: $free_quantity,
            mrp: $mrp,
            rate: $rate,
            discount: $discount,
            discount_percent: $discount_percent,
            gst_percent: $gst_percent,
            amount: $amount,
            bounding_box: $bounding_box,
            is_estimated_amount: $is_estimated_amount,
            hsn: $hsn,
            batch: $batch,
            expiry: $expiry,
            manufacturer: $manufacturer,
            pack: $pack
        })
        CREATE (inv)-[:CONTAINS]->(li)
        """,
        invoice_id=invoice_id,
        row_index=row_index,
        item_id=item_id,
        # The pack column as printed. Previously it was consumed by the parser
        # and discarded, so when the parser later improved there was nothing
        # left to re-read - the codes carrying dosage form and units per pack
        # had already been thrown away.
        pack=str(pack).strip() if pack else None,
        hsn=str(hsn).strip() if hsn else None,
        batch=str(batch).strip() if batch else None,
        # expiry is the normalized value, not the raw cell: the reports layer
        # groups by it, and two spellings of one date would split a group.
        expiry=expiry,
        manufacturer=item.get("manufacturer"),
        quantity=_to_float(item.get("quantity")),
        free_quantity=_to_float(item.get("free_quantity")),
        mrp=_to_float(item.get("mrp")),
        rate=_to_float(item.get("rate")),
        discount=_to_float(item.get("discount")),
        discount_percent=_to_float(item.get("discount_percent")),
        gst_percent=_to_float(item.get("gst_percent")),
        amount=_to_float(item.get("amount")),
        bounding_box=item.get("bounding_box"),
        is_estimated_amount=bool(item.get("is_estimated_amount")),
    )

    # Catalogue resolution: the spelling this invoice used is recorded as a
    # ProductAlias, and the alias points at the SKU it appears to describe.
    # Keeping the two apart is what lets "MONTICOPE SUSP" and "MONTICOPE
    # SUSPENSION 60 ML" become one item without hard-coding either spelling
    # as the truth. See db/product_repository for why.
    match = product_repository.resolve_line_item_product(
        tx,
        vendor_id=vendor_id,
        name=name,
        pack=pack,
        hsn=hsn,
        manufacturer=item.get("manufacturer"),
    )
    alias_id, product_id = match.alias_id, match.product_id

    # Recorded on the line, not just returned, so the review page can say why a
    # row was filled in for you - and so "auto-matched" survives a page reload.
    tx.run(
        """
        MATCH (li:LineItem {id: $item_id})
        SET li.match_tier = $tier, li.match_status = $status,
            li.match_note = $note, li.match_times_seen = $times_seen
        """,
        item_id=item_id,
        tier=match.tier,
        status=match.status,
        note=match.note,
        times_seen=match.times_seen,
    )

    if product_id:
        tx.run(
            """
            MATCH (li:LineItem {id: $item_id})
            MATCH (p:Product {id: $product_id})
            CREATE (li)-[:OF_PRODUCT]->(p)
            """,
            item_id=item_id,
            product_id=product_id,
        )

        # The line keeps a pointer to the exact spelling it arrived under, so
        # a mis-merged product can later be split by moving just the rows that
        # came in under one name.
        if alias_id:
            tx.run(
                """
                MATCH (li:LineItem {id: $item_id})
                MATCH (a:ProductAlias {id: $alias_id})
                CREATE (li)-[:OF_ALIAS]->(a)
                """,
                item_id=item_id,
                alias_id=alias_id,
            )

        if hsn and str(hsn).strip():
            tx.run(
                """
                MATCH (p:Product {id: $product_id})
                MERGE (h:HSNCode {code: $code})
                MERGE (p)-[:CLASSIFIED_AS]->(h)
                """,
                product_id=product_id,
                code=str(hsn).strip(),
            )

    if product_id and batch and str(batch).strip():
        batch_number = str(batch).strip()
        batch_key = f"{product_id}::{batch_number}"
        tx.run(
            """
            MATCH (p:Product {id: $product_id})
            MERGE (b:Batch {id: $batch_key})
            ON CREATE SET b.batch_number = $batch_number, b.expiry_date = $expiry
            MERGE (b)-[:OF_PRODUCT]->(p)
            WITH b
            MATCH (li:LineItem {id: $item_id})
            CREATE (li)-[:OF_BATCH]->(b)
            """,
            product_id=product_id,
            batch_key=batch_key,
            batch_number=batch_number,
            expiry=expiry,
            item_id=item_id,
        )


class EmptyLineItemsError(RuntimeError):
    """A save asked to replace every line item on an invoice with nothing.

    The review UI resends the whole table on every save, so an empty array is
    indistinguishable at this layer from "the user deleted all 16 rows" and
    "something went wrong upstream and sent us nothing" — a save fired before
    the fetch resolved, a failed reload, a lost response. Those look identical
    on the wire and one of them silently destroys a verified invoice.

    So an empty replacement is refused by default and the caller must opt in
    via allow_empty_line_items, which is the one thing an accidental payload
    will not do.
    """

    def __init__(self, invoice_id: str, existing_count: int):
        self.invoice_id = invoice_id
        self.existing_count = existing_count
        super().__init__(
            f"Refusing to delete all {existing_count} line item(s) on invoice "
            f"{invoice_id}: the update carried an empty line_items array. Pass "
            f"allow_empty_line_items=True if clearing the table is intended."
        )


def update_invoice(
    invoice_id: str,
    header: dict,
    line_items: Optional[list] = None,
    status: Optional[str] = None,
    allow_empty_line_items: bool = False,
) -> bool:
    """Applies a partial update to an invoice's header fields/status, and — if
    line_items is provided — replaces the invoice's line items wholesale (matching
    how the review UI always resends the full edited table).

    Raises EmptyLineItemsError if that replacement would wipe existing items and
    allow_empty_line_items is not set. Nothing is written in that case, header
    fields included: the transaction is rolled back whole rather than leaving an
    invoice whose totals no longer describe its rows."""
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(
            _update_invoice_tx, invoice_id, header, line_items, status, allow_empty_line_items
        )


_EDITABLE_HEADER_FIELDS = {
    "invoice_number", "invoice_date", "seller_name", "seller_gstin",
    "seller_address", "seller_phone", "drug_license", "buyer_gstin",
    "subtotal", "discount", "cgst", "sgst", "igst", "grand_total", "roundoff",
}


def _update_invoice_tx(
    tx,
    invoice_id: str,
    header: dict,
    line_items: Optional[list],
    status: Optional[str],
    allow_empty_line_items: bool = False,
) -> bool:
    exists = tx.run("MATCH (inv:Invoice {id: $id}) RETURN inv.id AS id", id=invoice_id).single()
    if not exists:
        return False

    # Checked before any write so the raise below rolls back an untouched
    # transaction rather than one that has already rewritten the header.
    if line_items is not None and not line_items and not allow_empty_line_items:
        existing_count = tx.run(
            """
            MATCH (:Invoice {id: $id})-[:CONTAINS]->(li:LineItem)
            RETURN count(li) AS n
            """,
            id=invoice_id,
        ).single()["n"]
        # An invoice with no rows yet has nothing to lose; only a destructive
        # replacement is worth blocking.
        if existing_count > 0:
            raise EmptyLineItemsError(invoice_id, existing_count)

    set_clauses = []
    params: dict = {"id": invoice_id}
    for key, value in header.items():
        if key in _EDITABLE_HEADER_FIELDS:
            set_clauses.append(f"inv.{key} = ${key}")
            # The review UI is the other door values come in through, and a date
            # typed by hand is no more canonical than one read by OCR.
            params[key] = normalize_invoice_date(value) if key == "invoice_date" else value

    if status:
        set_clauses.append("inv.status = $status")
        params["status"] = status

    if set_clauses:
        tx.run(f"MATCH (inv:Invoice {{id: $id}}) SET {', '.join(set_clauses)}", **params)

    if line_items is not None:
        tx.run(
            """
            MATCH (:Invoice {id: $id})-[:CONTAINS]->(li:LineItem)
            DETACH DELETE li
            """,
            id=invoice_id,
        )
        vendor_record = tx.run(
            """
            MATCH (:Invoice {id: $id})-[:SUPPLIED_BY]->(v:Vendor)
            RETURN v.id AS id
            """,
            id=invoice_id,
        ).single()
        vendor_id = vendor_record["id"] if vendor_record else None
        for row_index, item in enumerate(line_items):
            _write_line_item(tx, invoice_id, item, row_index, vendor_id)

    if status == "verified":
        _record_vendor_items(tx, invoice_id)

    return True


def _record_vendor_items(tx, invoice_id: str) -> None:
    """Teaches the catalogue this vendor's names, once a human has signed off.

    Verification is the trigger rather than upload, because the cross-reference
    is the user's judgement made reusable. Writing it from an unreviewed scan
    would let a single OCR misread teach itself to every future invoice from
    that supplier - the failure mode being automated away here, reintroduced
    one layer down.
    """
    rows = tx.run(
        """
        MATCH (inv:Invoice {id: $id})-[:SUPPLIED_BY]->(v:Vendor)
        MATCH (inv)-[:CONTAINS]->(li:LineItem)-[:OF_PRODUCT]->(p:Product)
        OPTIONAL MATCH (li)-[:OF_ALIAS]->(a:ProductAlias)
        RETURN v.id AS vendor_id, p.id AS product_id,
               coalesce(a.raw_name, p.canonical_name) AS name,
               li.pack AS pack, li.manufacturer AS manufacturer, li.hsn AS hsn
        """,
        id=invoice_id,
    )
    for row in rows:
        product_repository.record_vendor_item(
            tx,
            vendor_id=row["vendor_id"],
            product_id=row["product_id"],
            name=row["name"],
            pack=row["pack"],
            manufacturer=row["manufacturer"],
            hsn=row["hsn"],
        )


def update_line_item_amounts(amounts: dict[str, float]) -> int:
    """Writes derived Amounts onto existing line items, by line item id.

    Deliberately narrow. The general update path replaces an invoice's line
    items wholesale, which is right when the review screen resends the whole
    edited table but wrong for a backfill: it would rewrite every field of
    every row to correct one column, and any field the read path does not
    round-trip would be silently dropped on the way through.
    """
    if not amounts:
        return 0

    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(
            lambda tx: tx.run(
                """
                UNWIND $rows AS row
                MATCH (li:LineItem {id: row.id})
                SET li.amount = row.amount, li.is_estimated_amount = true
                RETURN count(li) AS updated
                """,
                rows=[{"id": k, "amount": v} for k, v in amounts.items()],
            ).single()["updated"]
        )


def list_invoices(pharmacy_id: Optional[str] = None) -> list[dict]:
    pharmacy_id = pharmacy_id or settings.DEFAULT_PHARMACY_ID
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(_list_invoices_tx, pharmacy_id)


def _list_invoices_tx(tx, pharmacy_id: str) -> list[dict]:
    result = tx.run(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        RETURN inv, v.name AS vendor_name
        ORDER BY inv.created_at DESC
        """,
        pharmacy_id=pharmacy_id,
    )
    invoices = []
    for record in result:
        data = _serialize_node(record["inv"])
        if not data.get("seller_name"):
            data["seller_name"] = record["vendor_name"]
        invoices.append(data)
    return invoices


def delete_invoice(invoice_id: str) -> Optional[dict]:
    """Deletes an Invoice and its LineItems, then cleans up any Vendor/Product/
    Batch nodes that were only referenced by this invoice (orphans left behind
    by the delete). Nodes still referenced by other invoices are left intact.
    Returns {"image_ref": ..., "image_refs": [...]} for R2 cleanup by the
    caller - image_refs covers every page of a multi-page invoice - or None if
    the invoice didn't exist (distinct from "existed but had no image")."""
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(_delete_invoice_tx, invoice_id)


def _delete_invoice_tx(tx, invoice_id: str) -> Optional[dict]:
    record = tx.run(
        """
        MATCH (inv:Invoice {id: $id})
        WITH inv, inv.source_image_ref AS image_ref, inv.source_image_refs AS image_refs
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        OPTIONAL MATCH (inv)-[:CONTAINS]->(li:LineItem)
        OPTIONAL MATCH (li)-[:OF_PRODUCT]->(p:Product)
        OPTIONAL MATCH (li)-[:OF_BATCH]->(b:Batch)
        RETURN image_ref, image_refs, v.id AS vendor_id,
               collect(DISTINCT p.id) AS product_ids,
               collect(DISTINCT b.id) AS batch_ids
        """,
        id=invoice_id,
    ).single()
    if record is None:
        return None

    tx.run(
        """
        MATCH (inv:Invoice {id: $id})
        OPTIONAL MATCH (inv)-[:CONTAINS]->(li:LineItem)
        DETACH DELETE inv, li
        """,
        id=invoice_id,
    )

    # Orphan cleanup: delete Vendor/Product/Batch nodes left with no
    # remaining invoice/line-item pointing to them. Nodes still shared by
    # other invoices are untouched.
    if record["vendor_id"]:
        tx.run(
            """
            MATCH (v:Vendor {id: $vendor_id})
            WHERE NOT (v)<-[:SUPPLIED_BY]-(:Invoice)
            DETACH DELETE v
            """,
            vendor_id=record["vendor_id"],
        )

    product_ids = [pid for pid in record["product_ids"] if pid]
    if product_ids:
        # A product left with no line items takes its spellings with it -
        # an alias pointing at a deleted product would otherwise keep the
        # name in the catalogue with nothing behind it, and would silently
        # re-adopt the next product that happened to reuse the identity.
        tx.run(
            """
            UNWIND $product_ids AS pid
            MATCH (p:Product {id: pid})
            WHERE NOT (p)<-[:OF_PRODUCT]-(:LineItem)
            OPTIONAL MATCH (p)<-[:RESOLVES_TO]-(a:ProductAlias)
            WHERE NOT (a)<-[:OF_ALIAS]-(:LineItem)
            DETACH DELETE p, a
            """,
            product_ids=product_ids,
        )

    # Spellings whose observations are all gone, including any left dangling
    # by an earlier partial delete.
    tx.run(
        """
        MATCH (a:ProductAlias)
        WHERE NOT (a)<-[:OF_ALIAS]-(:LineItem) AND NOT (a)-[:RESOLVES_TO]->(:Product)
        DETACH DELETE a
        """
    )

    batch_ids = [bid for bid in record["batch_ids"] if bid]
    if batch_ids:
        tx.run(
            """
            UNWIND $batch_ids AS bid
            MATCH (b:Batch {id: bid})
            WHERE NOT (b)<-[:OF_BATCH]-(:LineItem)
            DETACH DELETE b
            """,
            batch_ids=batch_ids,
        )

    # Fall back to the legacy single ref for invoices written before
    # multi-page support, so their image is still cleaned up.
    image_refs = record["image_refs"] or ([record["image_ref"]] if record["image_ref"] else [])
    return {"image_ref": record["image_ref"], "image_refs": image_refs}


def get_invoice(invoice_id: str) -> Optional[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(_get_invoice_tx, invoice_id)


def _get_invoice_tx(tx, invoice_id: str) -> Optional[dict]:
    record = tx.run(
        """
        MATCH (inv:Invoice {id: $invoice_id})
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        OPTIONAL MATCH (inv)-[:CONTAINS]->(li:LineItem)
        OPTIONAL MATCH (li)-[:OF_PRODUCT]->(p:Product)
        OPTIONAL MATCH (li)-[:OF_ALIAS]->(al:ProductAlias)
        OPTIONAL MATCH (li)-[:OF_BATCH]->(b:Batch)
        WITH inv, v, li, p, al, b
        ORDER BY coalesce(li.row_index, 0)
        RETURN inv, v, collect({item: li, product: p, alias: al, batch: b}) AS rows
        """,
        invoice_id=invoice_id,
    ).single()

    if not record:
        return None

    data = _serialize_node(record["inv"])
    vendor = _serialize_node(record["v"]) if record["v"] else None
    data["seller"] = vendor
    if not data.get("seller_name") and vendor:
        data["seller_name"] = vendor.get("name")

    # Rebuild {label, amount} pairs from the two parallel lists they were
    # stored as (see save_invoice). zip stops at the shorter list, so a
    # count mismatch degrades to fewer rows rather than an index error.
    breakdown_labels = data.pop("discount_breakdown_labels", None) or []
    breakdown_amounts = data.pop("discount_breakdown_amounts", None) or []
    data["discount_breakdown"] = [
        {"label": label, "amount": amount}
        for label, amount in zip(breakdown_labels, breakdown_amounts)
    ]

    line_items = []
    for row in record["rows"]:
        if row["item"] is None:
            continue
        li = _serialize_node(row["item"])
        product = row["product"] or {}
        alias = row["alias"] or {}
        # The review screen shows the invoice back to the person who scanned
        # it, so the name is the spelling THIS bill printed - not the
        # catalogue's canonical name, which may have been edited since or
        # shared with a differently-worded sibling line.
        li["product_name"] = alias.get("raw_name") or product.get("canonical_name")
        li["pack"] = product.get("pack_size") or li.get("pack")
        # Catalogue linkage, so the review page can jump to the product and
        # show whether this item is still awaiting classification.
        li["product_id"] = product.get("id")
        li["product_review_status"] = product.get("review_status")
        # Batch/expiry: prefer the shared Batch node (canonical), fall back
        # to the LineItem's own denormalized copy if no Batch link exists.
        li["batch_number"] = row["batch"].get("batch_number") if row["batch"] else li.get("batch")
        li["expiry_date"] = row["batch"].get("expiry_date") if row["batch"] else li.get("expiry")
        line_items.append(li)

    # Computed on read rather than stored: it is a reading of the row, not a
    # fact about it, so it must reflect whatever the row currently holds -
    # including edits a reviewer just made. Stored, it would go stale the
    # moment someone corrected the quantity by hand.
    for li in line_items:
        suggestion = check_free_quantity(li)
        li["quantity_suggestion"] = suggestion.model_dump() if suggestion else None

    data["line_items"] = line_items

    return data
