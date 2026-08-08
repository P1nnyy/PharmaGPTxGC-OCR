"""Cypher aggregations behind the purchase reports.

Aggregation happens in the database, not the browser. Every report here is
line-item based, and shipping each invoice's lines to the client to add them up
there stops working somewhere in the low hundreds of invoices.

Two rules hold across the queries:

  * Period filters compare `invoice_date` as an ISO string. That is only safe
    because dates are normalised to `YYYY-MM-DD` on the way in; see
    `core.dates`. An invoice whose date could not be parsed is stored as null
    and is deliberately excluded from period reports rather than defaulted into
    one — it surfaces in the data-quality report instead.
  * Header figures and line figures are never summed in the same aggregation.
    A `MATCH` that fans out over line items repeats the header once per line,
    so header totals are collapsed per invoice first.
"""

from typing import Any, Optional

from core.config import settings
from db.graph_db import get_driver

# Reports cover verified invoices by default: an invoice still in review may
# have OCR errors in exactly the figures being totalled. Callers can widen this,
# and every report reports what it excluded.
DEFAULT_STATUSES = ["verified"]

# Applied wherever a query is scoped to a reporting window. Invoices with no
# readable date drop out here by design.
_PERIOD_FILTER = """
    inv.invoice_date IS NOT NULL
    AND inv.invoice_date >= $start
    AND inv.invoice_date <= $end
"""

_STATUS_FILTER = "($statuses IS NULL OR inv.status IN $statuses)"

# Collapses an invoice's line items to one row. Used wherever header and line
# figures appear together, to keep the header from being counted once per line.
_LINE_ROLLUP = """
    CALL {
        WITH inv
        OPTIONAL MATCH (inv)-[:CONTAINS]->(li:LineItem)
        RETURN
            sum(coalesce(li.amount, 0.0))          AS line_total,
            sum(coalesce(li.quantity, 0.0))        AS billed_units,
            sum(coalesce(li.free_quantity, 0.0))   AS free_units,
            sum(coalesce(li.discount, 0.0))        AS line_discount,
            sum(
                coalesce(li.rate, 0.0) *
                (coalesce(li.quantity, 0.0) + coalesce(li.free_quantity, 0.0))
            )                                       AS list_value,
            count(li)                               AS line_count,
            sum(CASE WHEN li.is_estimated_amount THEN 1 ELSE 0 END) AS estimated_lines
    }
"""


def _run(query: str, **params) -> list[dict]:
    params.setdefault("pharmacy_id", settings.DEFAULT_PHARMACY_ID)
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _scoped(statuses: Optional[list[str]]) -> Optional[list[str]]:
    """`None` means every status; anything else is passed through as a filter."""
    return None if statuses is None else list(statuses)


def period_summary(start: str, end: str, statuses: Optional[list[str]] = DEFAULT_STATUSES) -> dict:
    """Headline totals for a period, plus what the status filter left out.

    The excluded counts are returned alongside rather than dropped: a filtered
    total that looks like a complete one is worse than no total at all.
    """
    rows = _run(
        f"""
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        WHERE {_PERIOD_FILTER}
        {_LINE_ROLLUP}
        WITH inv, line_total, list_value, estimated_lines,
             {_STATUS_FILTER} AS included
        RETURN
            included,
            count(inv)                                   AS invoice_count,
            sum(coalesce(inv.grand_total, 0.0))          AS gross_total,
            sum(coalesce(inv.subtotal, 0.0))             AS taxable_total,
            sum(coalesce(inv.discount, 0.0))             AS discount_total,
            sum(coalesce(inv.cgst, 0.0))                 AS cgst_total,
            sum(coalesce(inv.sgst, 0.0))                 AS sgst_total,
            sum(coalesce(inv.igst, 0.0))                 AS igst_total,
            sum(line_total)                              AS line_total,
            sum(list_value)                              AS list_value_total,
            sum(estimated_lines)                         AS estimated_line_count,
            count(DISTINCT inv.seller_gstin)             AS vendor_count
        """,
        start=start,
        end=end,
        statuses=_scoped(statuses),
    )

    included = next((r for r in rows if r.get("included")), {})
    excluded = next((r for r in rows if not r.get("included")), {})
    return {
        "included": included,
        "excluded": {
            "invoice_count": excluded.get("invoice_count", 0) or 0,
            "gross_total": excluded.get("gross_total", 0.0) or 0.0,
        },
    }


def gst_register(start: str, end: str, statuses: Optional[list[str]] = DEFAULT_STATUSES) -> list[dict]:
    """Invoice-level rows for the GST purchase register.

    Ordered by date then invoice number so the export is stable across runs —
    a register that reshuffles between pulls is useless for reconciliation
    against a previous month's copy.
    """
    return _run(
        f"""
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        WHERE {_PERIOD_FILTER} AND {_STATUS_FILTER}
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        RETURN
            inv.id             AS invoice_id,
            inv.invoice_date   AS invoice_date,
            inv.invoice_number AS invoice_number,
            coalesce(inv.seller_name, v.name)     AS seller_name,
            coalesce(inv.seller_gstin, v.gstin)   AS seller_gstin,
            inv.subtotal       AS taxable_value,
            inv.discount       AS discount,
            inv.cgst           AS cgst,
            inv.sgst           AS sgst,
            inv.igst           AS igst,
            inv.roundoff       AS roundoff,
            inv.grand_total    AS grand_total,
            inv.status         AS status
        ORDER BY inv.invoice_date, inv.invoice_number
        """,
        start=start,
        end=end,
        statuses=_scoped(statuses),
    )


def hsn_summary(start: str, end: str, statuses: Optional[list[str]] = DEFAULT_STATUSES) -> list[dict]:
    """Taxable value grouped by HSN code and GST slab.

    Grouped by both because the pair is what a return needs, and because the
    same HSN appearing under two slabs is a reliable sign of a misread rate.
    """
    return _run(
        f"""
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        WHERE {_PERIOD_FILTER} AND {_STATUS_FILTER}
        MATCH (inv)-[:CONTAINS]->(li:LineItem)
        WITH coalesce(li.hsn, 'unclassified') AS hsn,
             li.gst_percent                   AS gst_percent,
             li
        RETURN
            hsn,
            gst_percent,
            count(li)                              AS line_count,
            sum(coalesce(li.amount, 0.0))          AS taxable_value,
            sum(coalesce(li.quantity, 0.0))        AS quantity,
            count(DISTINCT li.batch)               AS batch_count
        ORDER BY taxable_value DESC
        """,
        start=start,
        end=end,
        statuses=_scoped(statuses),
    )


def vendor_breakdown(start: str, end: str, statuses: Optional[list[str]] = DEFAULT_STATUSES) -> list[dict]:
    """Per-vendor spend, scheme volume and list value for the period.

    Line figures come from the per-invoice rollup so the header totals are not
    multiplied by each vendor's line count.
    """
    return _run(
        f"""
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        WHERE {_PERIOD_FILTER} AND {_STATUS_FILTER}
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        {_LINE_ROLLUP}
        WITH
            coalesce(v.gstin, inv.seller_gstin)                    AS gstin,
            coalesce(v.name, inv.seller_name, 'Unidentified supplier') AS vendor_name,
            inv, line_total, billed_units, free_units, line_discount, list_value
        RETURN
            vendor_name,
            gstin,
            count(inv)                          AS invoice_count,
            sum(coalesce(inv.grand_total, 0.0)) AS gross_total,
            sum(coalesce(inv.subtotal, 0.0))    AS taxable_total,
            sum(line_total)                     AS line_total,
            sum(list_value)                     AS list_value_total,
            sum(billed_units)                   AS billed_units,
            sum(free_units)                     AS free_units,
            sum(line_discount)                  AS line_discount,
            max(inv.invoice_date)               AS last_purchase_date
        ORDER BY gross_total DESC
        """,
        start=start,
        end=end,
        statuses=_scoped(statuses),
    )


def monthly_spend(start: str, end: str, statuses: Optional[list[str]] = DEFAULT_STATUSES) -> list[dict]:
    """Spend per calendar month inside the period.

    The month key is sliced from the ISO date rather than parsed into a temporal
    type, because `invoice_date` is stored as a string. Months with no purchases
    do not appear here at all — the service layer fills the gaps, so an empty
    month reads as zero rather than vanishing from the axis.
    """
    return _run(
        f"""
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        WHERE {_PERIOD_FILTER} AND {_STATUS_FILTER}
        WITH substring(inv.invoice_date, 0, 7) AS month, inv
        RETURN
            month,
            count(inv)                          AS invoice_count,
            sum(coalesce(inv.grand_total, 0.0)) AS gross_total,
            sum(coalesce(inv.subtotal, 0.0))    AS taxable_total
        ORDER BY month
        """,
        start=start,
        end=end,
        statuses=_scoped(statuses),
    )


def expiring_batches(statuses: Optional[list[str]] = DEFAULT_STATUSES) -> list[dict]:
    """Every batch with a known expiry, valued at what was paid for it.

    Deliberately not scoped to a reporting period: stock bought in March can
    expire in September, and a period filter would hide exactly the batches this
    report exists to surface. Valued at purchase rate rather than MRP, because
    the loss on expired stock is what it cost, not what it might have sold for.
    """
    return _run(
        f"""
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        WHERE {_STATUS_FILTER}
        MATCH (inv)-[:CONTAINS]->(li:LineItem)-[:OF_BATCH]->(b:Batch)
        WHERE b.expiry_date IS NOT NULL
        OPTIONAL MATCH (li)-[:OF_PRODUCT]->(p:Product)
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        RETURN
            b.expiry_date   AS expiry_date,
            b.batch_number  AS batch_number,
            p.canonical_name AS product_name,
            p.pack          AS pack,
            li.quantity     AS quantity,
            li.free_quantity AS free_quantity,
            li.rate         AS rate,
            li.mrp          AS mrp,
            li.amount       AS amount,
            li.gst_percent  AS gst_percent,
            inv.id          AS invoice_id,
            inv.invoice_number AS invoice_number,
            inv.invoice_date   AS invoice_date,
            coalesce(v.name, inv.seller_name) AS vendor_name
        ORDER BY b.expiry_date
        """,
        statuses=_scoped(statuses),
    )


def product_purchase_history(
    start: str, end: str, statuses: Optional[list[str]] = DEFAULT_STATUSES
) -> list[dict]:
    """One row per purchase of a product, for price-variance analysis.

    Returned unaggregated because variance needs the sequence: the same product
    bought three times at three rates is the signal, and any rollup destroys it.
    """
    return _run(
        f"""
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        WHERE {_PERIOD_FILTER} AND {_STATUS_FILTER}
        MATCH (inv)-[:CONTAINS]->(li:LineItem)-[:OF_PRODUCT]->(p:Product)
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        RETURN
            p.id             AS product_id,
            p.canonical_name AS product_name,
            p.pack           AS pack,
            li.rate          AS rate,
            li.mrp           AS mrp,
            li.quantity      AS quantity,
            li.free_quantity AS free_quantity,
            li.amount        AS amount,
            li.gst_percent   AS gst_percent,
            inv.invoice_date AS invoice_date,
            inv.id           AS invoice_id,
            inv.invoice_number AS invoice_number,
            coalesce(v.name, inv.seller_name, 'Unidentified supplier') AS vendor_name
        ORDER BY p.canonical_name, inv.invoice_date
        """,
        start=start,
        end=end,
        statuses=_scoped(statuses),
    )


def data_quality_rows(start: str, end: str) -> list[dict]:
    """Invoices in the period with the fields the quality checks need.

    Runs across every status, not just verified: an invoice with no readable
    GSTIN is exactly the thing that should be flagged before someone verifies
    it. Invoices with an unreadable date are picked up separately.
    """
    return _run(
        f"""
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {{id: $pharmacy_id}})
        WHERE {_PERIOD_FILTER}
        {_LINE_ROLLUP}
        RETURN
            inv.id             AS invoice_id,
            inv.invoice_number AS invoice_number,
            inv.invoice_date   AS invoice_date,
            inv.seller_name    AS seller_name,
            inv.seller_gstin   AS seller_gstin,
            inv.subtotal       AS subtotal,
            inv.discount       AS discount,
            inv.cgst           AS cgst,
            inv.sgst           AS sgst,
            inv.igst           AS igst,
            inv.roundoff       AS roundoff,
            inv.grand_total    AS grand_total,
            inv.status         AS status,
            inv.confidence     AS confidence,
            line_total, line_count, estimated_lines
        ORDER BY inv.invoice_date
        """,
        start=start,
        end=end,
    )


def undated_invoices() -> list[dict]:
    """Invoices whose date could not be read, and which therefore appear in no
    period report. Surfaced so the gap is visible rather than silent."""
    return _run(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        WHERE inv.invoice_date IS NULL
        RETURN
            inv.id             AS invoice_id,
            inv.invoice_number AS invoice_number,
            inv.seller_name    AS seller_name,
            inv.grand_total    AS grand_total,
            inv.status         AS status
        """
    )


def duplicate_candidates() -> list[dict]:
    """Invoices sharing a supplier GSTIN and invoice number.

    An OCR product generates these structurally — re-uploads, retried runs,
    multi-page invoices split by mistake — and each one is a double payment and
    a double ITC claim waiting to happen.
    """
    return _run(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        WHERE inv.invoice_number IS NOT NULL AND inv.seller_gstin IS NOT NULL
        WITH inv.seller_gstin AS gstin, inv.invoice_number AS invoice_number,
             collect({
                 invoice_id: inv.id,
                 invoice_date: inv.invoice_date,
                 grand_total: inv.grand_total,
                 status: inv.status,
                 seller_name: inv.seller_name
             }) AS invoices
        WHERE size(invoices) > 1
        RETURN gstin, invoice_number, invoices, size(invoices) AS occurrence_count
        ORDER BY occurrence_count DESC
        """
    )
