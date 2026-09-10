"""Reads for the management reports.

Three of these reports are only possible because purchase cost, batch lineage
and sales sit in one graph. The queries here are where that shows: a batch's
cost comes from the movements an invoice created, its remaining quantity comes
from those movements net of sales, and its expiry came off the pack - and
joining those three is what turns "you have stock expiring" into "you have
₹18,400 of stock expiring in 46 days, of which ₹1,972 of input credit has to be
reversed permanently if you let it expire, and this distributor still takes
returns for another 16 days".

Everything is integer paise. Movements were written in paise from the start;
the `Invoice`/`LineItem` floats they were derived from stopped at the write
boundary and do not appear here.

Superseded generations are excluded everywhere. A corrected invoice leaves its
previous movements in the graph so the history survives, and a report that
counted them would double the stock it corrected.
"""

from typing import Optional

from core.tenancy import current_tenant
from db.graph_db import get_driver

# Every movement read filters on this. Written once here rather than repeated
# per query, because forgetting it in one place double-counts a corrected
# invoice in exactly one report - the hardest kind of bug to notice.
_LIVE = "m.superseded_by IS NULL"


def _run_read(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def batch_costs(pharmacy_id: Optional[str] = None) -> list:
    """Weighted average cost per (product, batch), from purchase movements.

    The average is taken over sums - total cost divided by total quantity -
    rather than by averaging each delivery's unit price. Two deliveries of the
    same batch at different prices weight by how much came in, which is what
    "weighted" means and what averaging unit prices would get wrong.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        f"""
        MATCH (m:StockMovement {{pharmacy_id: $pid, reason: 'PURCHASE'}})
        WHERE {_LIVE}
        RETURN m.product_id AS product_id,
               m.batch_number AS batch_number,
               sum(m.quantity_delta) AS quantity_in,
               sum(m.taxable_paise) AS cost_paise,
               sum(m.input_tax_paise) AS input_tax_paise,
               max(m.mrp_paise) AS mrp_paise,
               max(m.gst_rate_bp) AS gst_rate_bp,
               head(collect(m.expiry)) AS expiry,
               head(collect(m.vendor_id)) AS vendor_id,
               min(m.occurred_on) AS first_received_on,
               max(m.occurred_on) AS last_received_on
        """,
        pid=pharmacy_id,
    )


def batch_sales(pharmacy_id: Optional[str] = None) -> list:
    """Quantity sold per (product, batch), from sale movements."""
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        f"""
        MATCH (m:StockMovement {{pharmacy_id: $pid, reason: 'SALE'}})
        WHERE {_LIVE}
        RETURN m.product_id AS product_id,
               m.batch_number AS batch_number,
               sum(m.quantity_delta) AS quantity_out
        """,
        pid=pharmacy_id,
    )


def movements(
    start: Optional[str] = None,
    end: Optional[str] = None,
    product_id: Optional[str] = None,
    batch_number: Optional[str] = None,
    reason: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> list:
    """The movement history itself, oldest first.

    Ordered ascending because the ledger's whole purpose is a running balance,
    and a balance that runs backwards is not one.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        f"""
        MATCH (m:StockMovement {{pharmacy_id: $pid}})
        WHERE {_LIVE}
          AND ($start IS NULL OR m.occurred_on >= $start)
          AND ($end IS NULL OR m.occurred_on <= $end)
          AND ($product_id IS NULL OR m.product_id = $product_id)
          AND ($batch_number IS NULL OR m.batch_number = $batch_number)
          AND ($reason IS NULL OR m.reason = $reason)
        OPTIONAL MATCH (p:Product {{id: m.product_id}})
        RETURN m.id AS id, m.product_id AS product_id,
               p.canonical_name AS product_name,
               m.batch_number AS batch_number, m.expiry AS expiry,
               m.quantity_delta AS quantity_delta, m.reason AS reason,
               m.occurred_on AS occurred_on, m.recorded_at AS recorded_at,
               coalesce(m.taxable_paise, 0) AS taxable_paise,
               coalesce(m.input_tax_paise, 0) AS input_tax_paise,
               m.source_type AS source_type, m.source_id AS source_id,
               m.vendor_id AS vendor_id
        ORDER BY m.occurred_on, m.recorded_at
        """,
        pid=pharmacy_id, start=start, end=end,
        product_id=product_id, batch_number=batch_number, reason=reason,
    )


def sold_lines(start: str, end: str, pharmacy_id: Optional[str] = None) -> list:
    """Outward lines in the window, with the batch they came out of.

    Only documents that carry lines. A `DAY_TOTAL` declares a slab total and
    names no product, so it cannot contribute to a margin figure - the margin
    report says so in its empty state rather than quietly reporting a smaller
    number than the shop's actual sales.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pid, status: 'CONFIRMED'})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
        MATCH (s)-[:HAS_LINE]->(l:SaleLine)
        OPTIONAL MATCH (p:Product {id: l.product_id})
        RETURN s.id AS sale_id, s.sale_date AS sale_date,
               s.capture_mode AS capture_mode,
               coalesce(s.document_type, 'INVOICE') AS document_type,
               l.product_id AS product_id,
               coalesce(p.canonical_name, l.product_name) AS product_name,
               coalesce(l.batch_number, '') AS batch_number,
               coalesce(l.quantity, 0.0) AS quantity,
               coalesce(l.taxable_paise, 0) AS taxable_paise,
               coalesce(l.rate_bp, 0) AS rate_bp
        ORDER BY s.sale_date
        """,
        pid=pharmacy_id, start=start, end=end,
    )


def day_total_count(start: str, end: str, pharmacy_id: Optional[str] = None) -> int:
    """How many declared day totals sit in the window.

    The margin report needs this for its empty state: "no margin data" and "you
    have sales, but they were declared as day totals which carry no product
    lines" are different situations and only one of them is a problem.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pid, status: 'CONFIRMED'})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
          AND (s.capture_mode = 'DAY_TOTAL' OR coalesce(s.is_aggregate, false))
        RETURN count(s) AS total
        """,
        pid=pharmacy_id, start=start, end=end,
    )
    return int(rows[0]["total"]) if rows else 0


def sales_by_hour(start: str, end: str, pharmacy_id: Optional[str] = None) -> list:
    """Bills and value by hour of day.

    Uses `issued_at` - when the bill was actually rung up - rather than
    `sale_date`, which is only a date. A counter bill that syncs the next
    morning still belongs to the hour it was issued in, and a rush-hour chart
    built on sync time would describe the network rather than the shop.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pid, status: 'CONFIRMED'})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
          AND coalesce(s.document_type, 'INVOICE') = 'INVOICE'
        WITH s, CASE
            WHEN s.issued_at IS NULL THEN null
            ELSE toInteger(substring(s.issued_at, 11, 2))
        END AS hour
        RETURN hour,
               count(s) AS bill_count,
               sum(coalesce(s.grand_total_paise, 0)) AS value_paise
        ORDER BY hour
        """,
        pid=pharmacy_id, start=start, end=end,
    )


def sales_by_day(start: str, end: str, pharmacy_id: Optional[str] = None) -> list:
    """Bills and value per calendar day, for the trend and the comparison."""
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pid, status: 'CONFIRMED'})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
        WITH s, CASE WHEN coalesce(s.document_type, 'INVOICE') = 'CREDIT_NOTE'
                     THEN -1 ELSE 1 END AS sign
        RETURN s.sale_date AS day,
               sum(CASE WHEN sign = 1 THEN 1 ELSE 0 END) AS bill_count,
               sum(sign * coalesce(s.grand_total_paise, 0)) AS value_paise,
               sum(sign * coalesce(s.taxable_paise, 0)) AS taxable_paise
        ORDER BY day
        """,
        pid=pharmacy_id, start=start, end=end,
    )


def payment_split(start: str, end: str, pharmacy_id: Optional[str] = None) -> list:
    """What the till took, by method."""
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pid, status: 'CONFIRMED'})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
        MATCH (s)-[:PAID_BY]->(p:SalePayment)
        RETURN p.method AS method,
               count(p) AS payment_count,
               sum(coalesce(p.amount_paise, 0)) AS amount_paise
        ORDER BY amount_paise DESC
        """,
        pid=pharmacy_id, start=start, end=end,
    )


def purchases_by_day(start: str, end: str, pharmacy_id: Optional[str] = None) -> list:
    """What went out to distributors, per day, for the working-capital picture.

    Read from purchase movements rather than from invoice headers so it counts
    the same money the cost basis does, and so a corrected invoice moves both
    figures together.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        f"""
        MATCH (m:StockMovement {{pharmacy_id: $pid, reason: 'PURCHASE'}})
        WHERE {_LIVE} AND m.occurred_on >= $start AND m.occurred_on <= $end
        RETURN m.occurred_on AS day,
               sum(m.taxable_paise) AS cost_paise,
               sum(m.input_tax_paise) AS input_tax_paise,
               count(DISTINCT m.source_id) AS invoice_count
        ORDER BY day
        """,
        pid=pharmacy_id, start=start, end=end,
    )


def vendor_purchase_totals(
    start: str, end: str, pharmacy_id: Optional[str] = None
) -> list:
    """Per-distributor purchase value and credit, for the scorecard's shell."""
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pid})
        WHERE inv.invoice_date >= $start AND inv.invoice_date <= $end
          AND inv.status = 'verified'
        MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        RETURN v.id AS vendor_id, v.name AS name, v.gstin AS gstin,
               v.return_window_days AS return_window_days,
               count(inv) AS invoice_count,
               collect(DISTINCT inv.invoice_date) AS invoice_dates,
               sum(coalesce(inv.subtotal, 0.0)) AS taxable_rupees,
               sum(coalesce(inv.cgst, 0.0) + coalesce(inv.sgst, 0.0)
                   + coalesce(inv.igst, 0.0)) AS tax_rupees
        ORDER BY tax_rupees DESC
        """,
        pid=pharmacy_id, start=start, end=end,
    )
