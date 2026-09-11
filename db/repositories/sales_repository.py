"""Sales: writing and reading the records that feed the outward return.

Two rules from the house rules shape every function here.

**Idempotency.** Every ingest path merges on a deterministic `dedupe_key`
rather than creating unconditionally. Re-posting the same day total, the same
photographed bill or the same imported row is a no-op that returns the record
already stored — it does not create a second declaration of the same output
tax, and it does not silently overwrite the first either. Overwriting would be
just as wrong as duplicating: a retry must not be able to quietly replace
figures a person entered and checked.

**The filing lock.** A record that feeds a filed return is immutable. Until the
period is filed a sale can be corrected in place; once filed, the period is
closed and a correction has to become a new document (a credit note or an
amendment), never an edit. `assert_period_open` is the guard, and every write
path calls it before touching anything.

Cypher lives here; business rules live in `services/sales/`.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from core.serials import SerialError, parse_serial
from core.tenancy import current_tenant
from core.tax_periods import period_label
from db.graph_db import get_driver


class PeriodFiledError(RuntimeError):
    """Raised when a write would change a record inside a filed period."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_write(query: str, **params) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: [r.data() for r in tx.run(query, **params)])


def _run_read(query: str, **params) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _period_key(pharmacy_id: str, period: str) -> str:
    return f"{pharmacy_id}::{period}"


# ---------------------------------------------------------------- the lock


# A period is OPEN until its return is produced and accepted, then CLOSED.
# Held as a status rather than inferred from a timestamp because "closed" is a
# decision somebody made, and a return that was produced but rejected has to be
# distinguishable from one that was never produced at all.
PERIOD_OPEN = "OPEN"
PERIOD_CLOSED = "CLOSED"


def get_period(period: str, pharmacy_id: Optional[str] = None) -> dict:
    """The filing state of one month. Always answers, even for a month that
    has never been touched - an absent node means OPEN, not missing."""
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (p:TaxPeriod {key: $key})
        RETURN p {.*} AS period
        """,
        key=_period_key(pharmacy_id, period),
    )
    if not rows or not rows[0].get("period"):
        return {"period": period, "status": PERIOD_OPEN, "closed_at": None}
    stored = dict(rows[0]["period"])
    # `filed_at` predates the status field. A period closed by the older code
    # is still closed, so it is read as such rather than silently reopening.
    if not stored.get("status"):
        stored["status"] = PERIOD_CLOSED if stored.get("filed_at") else PERIOD_OPEN
    return stored


def is_period_filed(period: str, pharmacy_id: Optional[str] = None) -> bool:
    """True once the return covering this period has been filed."""
    return get_period(period, pharmacy_id).get("status") == PERIOD_CLOSED


def assert_period_open(period: str, pharmacy_id: Optional[str] = None) -> None:
    """Raises if the period is filed. Called before every write."""
    if is_period_filed(period, pharmacy_id):
        raise PeriodFiledError(
            f"{period_label(period)} has been filed. A filed period cannot be "
            "edited — record a credit note or an amendment instead."
        )


def close_period(
    months: "list[str]",
    payload: dict,
    summary: dict,
    closed_by: Optional[str] = None,
    acknowledged: Optional["list[str]"] = None,
    pharmacy_id: Optional[str] = None,
) -> "list[dict]":
    """Closes every month a return covers, and keeps what was filed.

    Takes a list of months rather than one, because a QRMP shop files a single
    GSTR-1 for a quarter: closing only the month somebody clicked would leave
    the other two editable after their figures had gone to the portal, which is
    precisely the drift the lock exists to prevent.

    The payload is stored alongside the lock. A return that cannot be revised
    has to be reproducible - when the portal disagrees six months later, the
    question is what was actually sent, and recomputing it from records that
    have moved on since answers a different question.

    **Closing is not filing.** It prepares the return and locks the records
    behind it; nothing has gone to the portal. `filed_at` is deliberately not
    set here - it belongs to `compliance_repository.record_filing`, which wants
    an ARN, because the only evidence a return was actually filed is the
    acknowledgement number the portal gave back. Setting it on close would make
    every prepared period claim to have been filed, and the compliance timeline
    could never tell the two apart.

    Idempotent on `closed_at`: closing twice keeps the first timestamp, because
    the date a period was closed is a fact rather than a counter.
    """
    import json

    pharmacy_id = pharmacy_id or current_tenant()
    now = _now()
    return [
        _run_write(
            """
            MERGE (p:TaxPeriod {key: $key})
            ON CREATE SET p.period = $period, p.pharmacy_id = $pharmacy_id
            SET p.status = $status,
                p.closed_at = coalesce(p.closed_at, $now),
                p.closed_by = coalesce(p.closed_by, $closed_by),
                p.payload_json = coalesce(p.payload_json, $payload_json),
                p.summary_json = coalesce(p.summary_json, $summary_json),
                p.acknowledged = coalesce(p.acknowledged, $acknowledged),
                p.covers_months = $covers_months
            RETURN p {.*} AS period
            """,
            key=_period_key(pharmacy_id, month),
            period=month,
            pharmacy_id=pharmacy_id,
            status=PERIOD_CLOSED,
            now=now,
            closed_by=closed_by,
            payload_json=json.dumps(payload),
            summary_json=json.dumps(summary),
            acknowledged=list(acknowledged or []),
            covers_months=list(months),
        )[0]["period"]
        for month in months
    ]


def cancel_sale(
    sale_id: str, cancelled_by: Optional[str] = None, pharmacy_id: Optional[str] = None
) -> dict:
    """Cancels a bill without removing it.

    The number stays in the series and the document stays in the graph. Table
    13 reports it as issued-then-cancelled, which is what the portal
    cross-checks against; deleting it would show a gap the shop cannot account
    for. Refused once the period is filed - a cancellation after filing is an
    amendment, not an edit.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    existing = get_sale(sale_id, pharmacy_id)
    if existing is None:
        raise ValueError("That sale no longer exists.")
    assert_period_open(existing["tax_period"], pharmacy_id)
    rows = _run_write(
        """
        MATCH (s:Sale {id: $sale_id, pharmacy_id: $pharmacy_id})
        SET s.status = 'CANCELLED', s.cancelled_at = $now, s.cancelled_by = $cancelled_by
        RETURN s {.*} AS sale
        """,
        sale_id=sale_id,
        pharmacy_id=pharmacy_id,
        now=_now(),
        cancelled_by=cancelled_by,
    )
    return rows[0]["sale"] if rows else {}


def mark_period_filed(
    period: str, filed_by: Optional[str] = None, pharmacy_id: Optional[str] = None
) -> dict:
    """Closes a period. Idempotent: filing twice keeps the first timestamp,
    because the date a return was filed is a fact, not a counter."""
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_write(
        """
        MERGE (p:TaxPeriod {key: $key})
        ON CREATE SET p.period = $period, p.pharmacy_id = $pharmacy_id,
                      p.filed_at = $now, p.filed_by = $filed_by
        ON MATCH SET  p.filed_at = coalesce(p.filed_at, $now),
                      p.filed_by = coalesce(p.filed_by, $filed_by)
        SET p.status = 'CLOSED'
        RETURN p.period AS period, p.filed_at AS filed_at, p.filed_by AS filed_by
        """,
        key=_period_key(pharmacy_id, period),
        period=period,
        pharmacy_id=pharmacy_id,
        now=_now(),
        filed_by=filed_by,
    )
    return rows[0] if rows else {}


def reopen_period(period: str, pharmacy_id: Optional[str] = None) -> None:
    """Undoes a filing that had not actually happened.

    Deliberately separate from `mark_period_filed` and never called by an
    ingest path: reopening a genuinely filed period is how a filed return and
    the records behind it drift apart, so it has to be an explicit act.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    _run_write(
        """
        MATCH (p:TaxPeriod {key: $key})
        SET p.status = 'OPEN', p.filed_at = null, p.filed_by = null,
            p.closed_at = null, p.closed_by = null
        """,
        key=_period_key(pharmacy_id, period),
    )


# --------------------------------------------------------------- writing


_SALE_FIELDS = """
    s.capture_mode = $capture_mode,
    s.document_class = $document_class,
    s.status = $status,
    s.sale_date = $sale_date,
    s.tax_period = $tax_period,
    s.taxable_paise = $taxable_paise,
    s.cgst_paise = $cgst_paise,
    s.sgst_paise = $sgst_paise,
    s.igst_paise = $igst_paise,
    s.place_of_supply_state_code = $place_of_supply_state_code,
    s.customer_gstin = $customer_gstin,
    s.document_type = $document_type,
    s.series_prefix = $series_prefix,
    s.serial_sequence = $serial_sequence,
    s.reverses_document_id = $reverses_document_id,
    s.exempt_paise = $exempt_paise,
    s.nil_rated_paise = $nil_rated_paise,
    s.non_gst_paise = $non_gst_paise,
    s.round_off_paise = $round_off_paise,
    s.grand_total_paise = $grand_total_paise,
    s.rate_source = $rate_source,
    s.is_aggregate = $is_aggregate,
    s.bill_number = $bill_number,
    s.source_file_hash = $source_file_hash,
    s.source_image_ref = $source_image_ref,
    s.source_format = $source_format,
    s.notes = $notes
"""


def _outward_params(computed: dict, bill_number: Optional[str], existing: Optional[dict] = None) -> dict:
    """The fields an outward return needs, defaulted for A1's writers.

    All optional. The day-total and import paths predate the return and set
    none of them, and they have to keep working; a sale that says nothing about
    its place of supply is reported as saying nothing, and the validation
    report raises it. Defaulting to the shop's own state here would file an
    inter-state supply as CGST plus SGST, which is the one failure this whole
    engine exists to prevent.

    The series is derived from the bill number rather than stored twice.
    Table 13 needs to sort and find gaps in a series, which needs the sequence
    as an integer, and re-parsing it on every read would be the same work done
    repeatedly against data that cannot change.
    """
    existing = existing or {}
    series_prefix, serial_sequence = None, None
    if bill_number:
        try:
            series_prefix, serial_sequence = parse_serial(bill_number)
        except SerialError:
            # A bill number that does not end in a sequence - a photographed
            # bill numbered "INV/A" - cannot be placed in a series. Table 13
            # reports it as having none rather than guessing at one.
            pass
    return {
        "igst_paise": computed.get("igst_paise", existing.get("igst_paise")) or 0,
        "place_of_supply_state_code": computed.get(
            "place_of_supply_state_code", existing.get("place_of_supply_state_code")
        ),
        "customer_gstin": computed.get("customer_gstin", existing.get("customer_gstin")),
        "document_type": computed.get("document_type", existing.get("document_type")) or "INVOICE",
        "series_prefix": series_prefix,
        "serial_sequence": serial_sequence,
        "reverses_document_id": computed.get(
            "reverses_document_id", existing.get("reverses_document_id")
        ),
    }


def upsert_sale(
    dedupe_key: str,
    computed: dict,
    capture_mode: str,
    document_class: str,
    status: str,
    created_by: Optional[str] = None,
    bill_number: Optional[str] = None,
    source_file_hash: Optional[str] = None,
    source_image_ref: Optional[str] = None,
    source_format: Optional[str] = None,
    notes: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
    allow_filed_period: bool = False,
) -> "tuple[dict, bool]":
    """Stores a sale, once. Returns `(sale, created)`.

    `created` is False when this exact document had already been ingested. The
    caller surfaces that as "already recorded" rather than as an error: a
    client retrying after a timeout has done nothing wrong, and the right
    answer is the record that already exists.

    The rate blocks and payments are replaced wholesale on an edit rather than
    merged row by row, because a correction that removes a slab has to remove
    it — a merge would leave the old block behind and the header would stop
    reconciling to its own parts.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    # `allow_filed_period` exists for exactly one caller: a bill that was
    # issued offline and is only now syncing. It already exists in a
    # customer's hand and nothing here can un-issue it, so it is recorded and
    # flagged for amendment rather than refused - refusing it would lose it.
    # Every other path is refused, which is what makes a filed period
    # immutable in the repository rather than only in the UI.
    if not allow_filed_period:
        assert_period_open(computed["tax_period"], pharmacy_id)

    rows = _run_write(
        f"""
        MERGE (s:Sale {{dedupe_key: $dedupe_key}})
        ON CREATE SET s.id = $new_id, s.pharmacy_id = $pharmacy_id,
                      s.created_at = $now, s.created_by = $created_by,
                      s.was_created = true,
                      {_SALE_FIELDS}
        ON MATCH SET  s.was_created = false
        WITH s, s.was_created AS created
        REMOVE s.was_created
        WITH s, created
        CALL {{
            WITH s, created
            WITH s WHERE created
            MATCH (ph:Pharmacy {{id: s.pharmacy_id}})
            MERGE (s)-[:BELONGS_TO]->(ph)
            RETURN count(*) AS linked
        }}
        RETURN s {{.*}} AS sale, created
        """,
        dedupe_key=dedupe_key,
        new_id=str(uuid.uuid4()),
        pharmacy_id=pharmacy_id,
        now=_now(),
        created_by=created_by,
        capture_mode=capture_mode,
        document_class=document_class,
        status=status,
        sale_date=computed["sale_date"],
        tax_period=computed["tax_period"],
        taxable_paise=computed["taxable_paise"],
        cgst_paise=computed["cgst_paise"],
        sgst_paise=computed["sgst_paise"],
        exempt_paise=computed["exempt_paise"],
        nil_rated_paise=computed["nil_rated_paise"],
        non_gst_paise=computed["non_gst_paise"],
        round_off_paise=computed["round_off_paise"],
        grand_total_paise=computed["grand_total_paise"],
        rate_source=computed.get("rate_source"),
        is_aggregate=bool(computed.get("is_aggregate", False)),
        **_outward_params(computed, bill_number),
        bill_number=bill_number,
        source_file_hash=source_file_hash,
        source_image_ref=source_image_ref,
        source_format=source_format,
        notes=notes,
    )
    if not rows:
        raise RuntimeError("Sale write returned nothing.")

    sale, created = rows[0]["sale"], rows[0]["created"]
    if created:
        _replace_children(sale["id"], computed)
    return sale, bool(created)


def _replace_children(sale_id: str, computed: dict) -> None:
    """Rewrites a sale's rate blocks and payments to match `computed`."""
    _run_write(
        """
        MATCH (s:Sale {id: $sale_id})
        OPTIONAL MATCH (s)-[:HAS_RATE_BLOCK]->(b:SaleRateBlock)
        DETACH DELETE b
        WITH s
        OPTIONAL MATCH (s)-[:PAID_BY]->(p:SalePayment)
        DETACH DELETE p
        """,
        sale_id=sale_id,
    )
    _run_write(
        """
        MATCH (s:Sale {id: $sale_id})
        WITH s
        UNWIND $blocks AS block
        CREATE (b:SaleRateBlock {
            id: randomUUID(),
            rate_bp: block.rate_bp,
            gross_paise: block.gross_paise,
            taxable_paise: block.taxable_paise,
            cgst_paise: block.cgst_paise,
            sgst_paise: block.sgst_paise
        })
        CREATE (s)-[:HAS_RATE_BLOCK]->(b)
        """,
        sale_id=sale_id,
        blocks=computed["rate_blocks"],
    )
    if computed.get("payments"):
        _run_write(
            """
            MATCH (s:Sale {id: $sale_id})
            WITH s
            UNWIND $payments AS payment
            CREATE (p:SalePayment {
                id: randomUUID(),
                method: payment.method,
                amount_paise: payment.amount_paise,
                reference: payment.reference
            })
            CREATE (s)-[:PAID_BY]->(p)
            """,
            sale_id=sale_id,
            payments=computed["payments"],
        )


def update_sale(
    sale_id: str,
    computed: dict,
    updated_by: Optional[str] = None,
    notes: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> dict:
    """Corrects a sale in place. Refused once the period is filed.

    Both the period the sale is currently in and the period it would move to
    are checked: re-dating a sale out of a filed month would otherwise be a way
    to edit a filed return without touching it.
    """
    pharmacy_id = pharmacy_id or current_tenant()

    existing = get_sale(sale_id, pharmacy_id)
    if existing is None:
        raise LookupError(f"No sale {sale_id} in this workspace.")

    assert_period_open(existing["tax_period"], pharmacy_id)
    if computed["tax_period"] != existing["tax_period"]:
        assert_period_open(computed["tax_period"], pharmacy_id)

    rows = _run_write(
        f"""
        MATCH (s:Sale {{id: $sale_id, pharmacy_id: $pharmacy_id}})
        SET s.updated_at = $now, s.updated_by = $updated_by,
            {_SALE_FIELDS}
        RETURN s {{.*}} AS sale
        """,
        sale_id=sale_id,
        pharmacy_id=pharmacy_id,
        now=_now(),
        updated_by=updated_by,
        capture_mode=existing["capture_mode"],
        document_class=existing["document_class"],
        status=existing["status"],
        sale_date=computed["sale_date"],
        tax_period=computed["tax_period"],
        taxable_paise=computed["taxable_paise"],
        cgst_paise=computed["cgst_paise"],
        sgst_paise=computed["sgst_paise"],
        exempt_paise=computed["exempt_paise"],
        nil_rated_paise=computed["nil_rated_paise"],
        non_gst_paise=computed["non_gst_paise"],
        round_off_paise=computed["round_off_paise"],
        grand_total_paise=computed["grand_total_paise"],
        rate_source=computed.get("rate_source"),
        is_aggregate=bool(computed.get("is_aggregate", existing.get("is_aggregate", False))),
        **_outward_params(computed, existing.get("bill_number"), existing),
        bill_number=existing.get("bill_number"),
        source_file_hash=existing.get("source_file_hash"),
        source_image_ref=existing.get("source_image_ref"),
        source_format=existing.get("source_format"),
        notes=notes if notes is not None else existing.get("notes"),
    )
    _replace_children(sale_id, computed)
    return rows[0]["sale"] if rows else {}


# --------------------------------------------------------------- reading


def get_sale(sale_id: str, pharmacy_id: Optional[str] = None) -> Optional[dict]:
    """One sale with its blocks and payments, or None."""
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (s:Sale {id: $sale_id, pharmacy_id: $pharmacy_id})
        OPTIONAL MATCH (s)-[:HAS_RATE_BLOCK]->(b:SaleRateBlock)
        OPTIONAL MATCH (s)-[:PAID_BY]->(p:SalePayment)
        RETURN s {.*} AS sale,
               collect(DISTINCT b {.*}) AS rate_blocks,
               collect(DISTINCT p {.*}) AS payments
        """,
        sale_id=sale_id,
        pharmacy_id=pharmacy_id,
    )
    if not rows or not rows[0].get("sale"):
        return None
    return _shape(rows[0])


def find_by_dedupe_key(dedupe_key: str, pharmacy_id: Optional[str] = None) -> Optional[dict]:
    """The sale a given document already produced, if it has been ingested."""
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (s:Sale {dedupe_key: $dedupe_key, pharmacy_id: $pharmacy_id})
        OPTIONAL MATCH (s)-[:HAS_RATE_BLOCK]->(b:SaleRateBlock)
        OPTIONAL MATCH (s)-[:PAID_BY]->(p:SalePayment)
        RETURN s {.*} AS sale,
               collect(DISTINCT b {.*}) AS rate_blocks,
               collect(DISTINCT p {.*}) AS payments
        """,
        dedupe_key=dedupe_key,
        pharmacy_id=pharmacy_id,
    )
    if not rows or not rows[0].get("sale"):
        return None
    return _shape(rows[0])


def find_by_source_file_hash(
    source_file_hash: str, pharmacy_id: Optional[str] = None
) -> list[dict]:
    """Sales already produced by a given file or image.

    A list rather than one row: an import file legitimately produces many
    sales, and a photograph normally produces one. Callers decide what a second
    match means for them.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (s:Sale {source_file_hash: $source_file_hash, pharmacy_id: $pharmacy_id})
        OPTIONAL MATCH (s)-[:HAS_RATE_BLOCK]->(b:SaleRateBlock)
        OPTIONAL MATCH (s)-[:PAID_BY]->(p:SalePayment)
        RETURN s {.*} AS sale,
               collect(DISTINCT b {.*}) AS rate_blocks,
               collect(DISTINCT p {.*}) AS payments
        ORDER BY sale.created_at
        """,
        source_file_hash=source_file_hash,
        pharmacy_id=pharmacy_id,
    )
    return [_shape(row) for row in rows]


def list_sales(
    start: str,
    end: str,
    capture_modes: Optional[list[str]] = None,
    statuses: Optional[list[str]] = None,
    pharmacy_id: Optional[str] = None,
) -> list[dict]:
    """Sales in a date window, newest first."""
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pharmacy_id})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
          AND ($capture_modes IS NULL OR s.capture_mode IN $capture_modes)
          AND ($statuses IS NULL OR s.status IN $statuses)
        OPTIONAL MATCH (s)-[:HAS_RATE_BLOCK]->(b:SaleRateBlock)
        OPTIONAL MATCH (s)-[:PAID_BY]->(p:SalePayment)
        RETURN s {.*} AS sale,
               collect(DISTINCT b {.*}) AS rate_blocks,
               collect(DISTINCT p {.*}) AS payments
        ORDER BY sale.sale_date DESC
        """,
        pharmacy_id=pharmacy_id,
        start=start,
        end=end,
        capture_modes=capture_modes,
        statuses=statuses,
    )
    return [_shape(row) for row in rows]


# ------------------------------------------------- remembered import mappings


def get_import_mapping(format_name: str, pharmacy_id: Optional[str] = None) -> Optional[dict]:
    """The column mapping this workspace last confirmed for a format.

    Remembered per workspace rather than globally: two shops on the same
    billing package can still export different column sets, and one shop's
    correction must not silently re-map another's file.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (m:ImportMapping {key: $key})
        RETURN m.mapping_json AS mapping_json, m.updated_at AS updated_at
        """,
        key=f"{pharmacy_id}::{format_name}",
    )
    if not rows or not rows[0].get("mapping_json"):
        return None
    import json

    try:
        return json.loads(rows[0]["mapping_json"])
    except (TypeError, ValueError):
        return None


def save_import_mapping(
    format_name: str, mapping: dict, pharmacy_id: Optional[str] = None
) -> None:
    """Records a mapping the user confirmed, so the next file starts from it."""
    import json

    pharmacy_id = pharmacy_id or current_tenant()
    _run_write(
        """
        MERGE (m:ImportMapping {key: $key})
        SET m.pharmacy_id = $pharmacy_id, m.format_name = $format_name,
            m.mapping_json = $mapping_json, m.updated_at = $now
        """,
        key=f"{pharmacy_id}::{format_name}",
        pharmacy_id=pharmacy_id,
        format_name=format_name,
        mapping_json=json.dumps(mapping),
        now=_now(),
    )


def _shape(row: dict[str, Any]) -> dict:
    sale = dict(row["sale"])
    sale["rate_blocks"] = sorted(
        (dict(b) for b in row.get("rate_blocks") or [] if b),
        key=lambda b: b.get("rate_bp") or 0,
    )
    sale["payments"] = [dict(p) for p in row.get("payments") or [] if p]
    return sale


# ------------------------------------------------------- counter sales


def available_stock(
    holdings: "list[dict]", pharmacy_id: Optional[str] = None
) -> "dict[str, float]":
    """Stock on hand for specific product/batch holdings.

    Received, from verified purchase invoices, less everything the movement
    ledger has taken out since. Keyed `"<product_id>::<batch>"`.

    Derived on read rather than kept as a running total, matching how
    `inventory_repository` already works: a figure recomputed from its sources
    cannot drift from them, and there is nothing to re-sync when a purchase
    invoice is corrected.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    if not holdings:
        return {}

    rows = _run_read(
        """
        UNWIND $holdings AS holding
        OPTIONAL MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        WHERE inv.status = 'verified'
        OPTIONAL MATCH (inv)-[:CONTAINS]->(li:LineItem)-[:OF_PRODUCT]->(p:Product {id: holding.product_id})
        WHERE coalesce(li.batch, '') = holding.batch
        WITH holding, sum(coalesce(li.quantity, 0.0) + coalesce(li.free_quantity, 0.0)) AS received
        OPTIONAL MATCH (m:StockMovement {pharmacy_id: $pharmacy_id,
                                        product_id: holding.product_id,
                                        batch_number: holding.batch})
        WITH holding, received, sum(coalesce(m.quantity_delta, 0.0)) AS moved
        RETURN holding.product_id AS product_id, holding.batch AS batch,
               received + moved AS available
        """,
        pharmacy_id=pharmacy_id,
        holdings=holdings,
    )
    return {f"{r['product_id']}::{r['batch']}": float(r["available"] or 0.0) for r in rows}


def save_counter_sale(
    serial: str,
    dedupe_key_value: str,
    sale_date: str,
    tax_period: str,
    financial_year: int,
    lines: "list[dict]",
    totals: dict,
    payments: "list[dict]",
    device_id: str,
    issued_at: str,
    prescription_image_ref: Optional[str] = None,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    created_by: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> "tuple[dict, bool, list[dict]]":
    """Stores a bill that was issued on a device. Returns `(sale, created, issues)`.

    Two rules shape this and they both point the same way: **the bill already
    exists.** It was printed offline and handed to a customer minutes or hours
    ago. Nothing the server discovers about it can un-issue it.

    So a shortfall against stock does not reject the sale. The sale is written,
    the movement is written, and the shortfall comes back as an `issue` for
    someone to reconcile — because the alternative is a bill in a customer's
    hand that does not exist in the books, which is far worse than a stock
    figure that needs explaining.

    The same applies to a bill that arrives for a period already filed. It
    cannot be added to a filed return, so it is stored and flagged for
    amendment rather than refused. Refusing it would lose it.

    Idempotent on the serial: a retry after a timeout returns the stored sale
    with `created=False` rather than issuing it twice.
    """
    pharmacy_id = pharmacy_id or current_tenant()

    existing = find_by_dedupe_key(dedupe_key_value, pharmacy_id)
    if existing is not None:
        return existing, False, []

    issues: list[dict] = []

    # A late bill for a closed period. Recorded, flagged, never dropped.
    if is_period_filed(tax_period, pharmacy_id):
        issues.append(
            {
                "kind": "period_filed",
                "line_id": None,
                "detail": (
                    f"{period_label(tax_period)} has already been filed. This bill is "
                    "recorded but is not in that return — it needs an amendment."
                ),
            }
        )

    holdings = [
        {"product_id": line["product_id"], "batch": line.get("batch_number") or ""}
        for line in lines
        if line.get("product_id")
    ]
    available = available_stock(holdings, pharmacy_id)
    for line in lines:
        key = f"{line.get('product_id')}::{line.get('batch_number') or ''}"
        have = available.get(key)
        if have is None:
            continue
        if line.get("quantity", 0) > have:
            issues.append(
                {
                    "kind": "insufficient_stock",
                    "line_id": line.get("line_id"),
                    "detail": (
                        f"{line.get('product_name')} batch {line.get('batch_number') or '—'}: "
                        f"sold {line.get('quantity')}, stock showed {have:g}."
                    ),
                }
            )

    sale, created = upsert_sale(
        dedupe_key=dedupe_key_value,
        computed={
            "sale_date": sale_date,
            "tax_period": tax_period,
            **{k: totals.get(k) for k in (
                "taxable_paise", "cgst_paise", "sgst_paise", "exempt_paise",
                "nil_rated_paise", "non_gst_paise", "round_off_paise", "grand_total_paise",
            )},
            "rate_blocks": totals.get("rate_blocks") or [],
            "payments": payments,
            "rate_source": "counter",
            "is_aggregate": False,
        },
        capture_mode="COUNTER",
        document_class="INVOICE_CUM_BILL_OF_SUPPLY",
        status="CONFIRMED",
        created_by=created_by,
        bill_number=serial,
        pharmacy_id=pharmacy_id,
        # The bill was printed offline and handed over before this call. If
        # the period has since been filed it is recorded and flagged above,
        # never refused - the issue list already carries the amendment note.
        allow_filed_period=True,
    )

    _write_sale_lines(sale["id"], lines, pharmacy_id)
    _write_stock_movements(sale["id"], lines, sale_date, pharmacy_id)

    _run_write(
        """
        MATCH (s:Sale {id: $sale_id})
        SET s.serial = $serial, s.financial_year = $financial_year,
            s.device_id = $device_id, s.issued_at = $issued_at,
            s.prescription_image_ref = $prescription_image_ref,
            s.customer_name = $customer_name, s.customer_phone = $customer_phone,
            s.needs_reconciliation = $needs_reconciliation,
            s.reconciliation_notes = $notes
        """,
        sale_id=sale["id"],
        serial=serial,
        financial_year=financial_year,
        device_id=device_id,
        issued_at=issued_at,
        prescription_image_ref=prescription_image_ref,
        customer_name=customer_name,
        customer_phone=customer_phone,
        needs_reconciliation=bool(issues),
        notes=[issue["detail"] for issue in issues],
    )

    stored = get_sale(sale["id"], pharmacy_id) or sale
    return stored, created, issues


def _write_sale_lines(sale_id: str, lines: "list[dict]", pharmacy_id: str) -> None:
    """The bill's lines, including the scanned payload each came from."""
    if not lines:
        return
    _run_write(
        """
        MATCH (s:Sale {id: $sale_id})
        WITH s
        UNWIND $lines AS line
        CREATE (l:SaleLine {
            id: randomUUID(),
            line_id: line.line_id,
            product_id: line.product_id,
            product_name: line.product_name,
            hsn: line.hsn,
            batch_number: line.batch_number,
            expiry: line.expiry,
            quantity: line.quantity,
            unit_price_paise: line.unit_price_paise,
            taxable_paise: line.taxable_paise,
            cgst_paise: line.cgst_paise,
            sgst_paise: line.sgst_paise,
            igst_paise: coalesce(line.igst_paise, 0),
            // The unit as the portal names it, and what kind of supply the
            // line is. Table 12 needs a UQC per HSN, and Table 8 needs nil
            // rated kept apart from exempt - neither of which can be worked
            // out later from a quantity and a rate.
            uqc: line.uqc,
            supply_class: coalesce(line.supply_class, 'TAXABLE'),
            rate_bp: line.rate_bp,
            line_total_paise: line.line_total_paise,
            // Kept whatever the parser made of it. An unrecognised code stored
            // against the line it produced is the only record of what was
            // physically on the pack.
            scanned_code_raw: line.scanned_code_raw
        })
        CREATE (s)-[:HAS_LINE]->(l)
        WITH l, line
        OPTIONAL MATCH (p:Product {id: line.product_id})
        FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
            CREATE (l)-[:OF_PRODUCT]->(p)
        )
        """,
        sale_id=sale_id,
        lines=lines,
    )


def _write_stock_movements(
    sale_id: str, lines: "list[dict]", occurred_on: str, pharmacy_id: str
) -> None:
    """Append-only ledger rows for what left the shelf.

    Never an update to a stock figure — the house rules make this ledger
    append-only, and a movement that can be edited is a movement that cannot be
    audited. Each row carries an edge back to the sale that caused it, so every
    stock figure derived from these traces to a document.
    """
    movements = [
        {
            "product_id": line.get("product_id"),
            "batch_number": line.get("batch_number") or "",
            # Negative: a sale takes stock out.
            "quantity_delta": -abs(float(line.get("quantity") or 0)),
            "line_id": line.get("line_id"),
        }
        for line in lines
        if line.get("product_id")
    ]
    if not movements:
        return

    _run_write(
        """
        MATCH (s:Sale {id: $sale_id})
        WITH s
        UNWIND $movements AS movement
        CREATE (m:StockMovement {
            id: randomUUID(),
            pharmacy_id: $pharmacy_id,
            product_id: movement.product_id,
            batch_number: movement.batch_number,
            quantity_delta: movement.quantity_delta,
            reason: 'SALE',
            occurred_on: $occurred_on,
            recorded_at: $now,
            source_type: 'Sale',
            source_id: $sale_id,
            source_line_id: movement.line_id
        })
        CREATE (m)-[:CAUSED_BY]->(s)
        """,
        sale_id=sale_id,
        pharmacy_id=pharmacy_id,
        movements=movements,
        occurred_on=occurred_on,
        now=_now(),
    )
