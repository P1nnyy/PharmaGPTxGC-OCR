"""Reads for the statutory report pack, in integer paise.

The purchase side of this codebase predates the integer-paise rule and stores
rupees as floats. This module is the boundary where that stops: every money
column is converted once on the way out, and no float reaches a report.

Conversion happens here rather than in the services for the same reason the
Cypher does - so there is exactly one place where a purchase figure becomes a
paise figure, and a report cannot accidentally add a rupee to a paisa. The
services above never see the stored representation at all.

The sales side already stores paise and is read through
`db/repositories/gstr1_repository.py`; only payments are read here, because
`OutwardDocument` is the GSTR-1 contract and does not carry them.
"""

from typing import Optional

from core.money import paise_from_legacy_rupees as _paise
from core.tenancy import current_tenant
from db.graph_db import get_driver

# Which invoice statuses count as real records. Mirrors the default the
# existing reports use, so the statutory pack and the older reports cannot
# disagree about which invoices exist.
DEFAULT_STATUSES = ["verified"]


def _run_read(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _money(row: dict, *fields: str) -> dict:
    """Converts the named rupee columns to `<field>_paise`, dropping the float.

    The original is removed rather than kept alongside. Two representations of
    the same amount in one dict is an invitation for the wrong one to be
    summed, and the whole point of this boundary is that only one survives it.
    """
    out = dict(row)
    for field_name in fields:
        out[f"{field_name}_paise"] = _paise(out.pop(field_name, None)) or 0
    return out


def purchase_invoices(
    start: str,
    end: str,
    vendor: Optional[str] = None,
    statuses: Optional[list] = None,
    pharmacy_id: Optional[str] = None,
) -> list:
    """Invoice-wise inward supplies for the window, in paise.

    Ordered by date then number so a register pulled twice reads the same way
    both times - one pulled in a different order each time is useless for
    reconciling against last month's copy.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        WHERE inv.invoice_date >= $start AND inv.invoice_date <= $end
          AND ($statuses IS NULL OR inv.status IN $statuses)
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        WITH inv, v
        WHERE $vendor IS NULL
           OR toLower(coalesce(inv.seller_name, v.name, '')) CONTAINS toLower($vendor)
           OR coalesce(inv.seller_gstin, v.gstin, '') = $vendor
        RETURN
            inv.id             AS invoice_id,
            inv.invoice_number AS invoice_number,
            inv.invoice_date   AS invoice_date,
            coalesce(inv.seller_name, v.name)   AS seller_name,
            coalesce(inv.seller_gstin, v.gstin) AS seller_gstin,
            inv.status         AS status,
            inv.subtotal       AS taxable,
            inv.discount       AS discount,
            inv.cgst           AS cgst,
            inv.sgst           AS sgst,
            inv.igst           AS igst,
            inv.roundoff       AS roundoff,
            inv.grand_total    AS grand_total
        ORDER BY invoice_date, invoice_number
        """,
        pharmacy_id=pharmacy_id,
        start=start,
        end=end,
        vendor=vendor,
        statuses=list(statuses) if statuses is not None else DEFAULT_STATUSES,
    )
    return [
        _money(row, "taxable", "discount", "cgst", "sgst", "igst", "roundoff", "grand_total")
        for row in rows
    ]


def purchase_rate_blocks(
    start: str,
    end: str,
    vendor: Optional[str] = None,
    statuses: Optional[list] = None,
    pharmacy_id: Optional[str] = None,
) -> list:
    """Each invoice's taxable value grouped by GST slab.

    The register reports rate blocks per invoice, and the invoice header only
    carries totals - so the blocks are summed from the lines. A line with no
    rate is grouped under a null slab rather than dropped, because an
    unclassified line still carries value that has to reconcile to the header.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        WHERE inv.invoice_date >= $start AND inv.invoice_date <= $end
          AND ($statuses IS NULL OR inv.status IN $statuses)
        OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        WITH inv, v
        WHERE $vendor IS NULL
           OR toLower(coalesce(inv.seller_name, v.name, '')) CONTAINS toLower($vendor)
           OR coalesce(inv.seller_gstin, v.gstin, '') = $vendor
        MATCH (inv)-[:CONTAINS]->(li:LineItem)
        RETURN inv.id AS invoice_id,
               li.gst_percent AS gst_percent,
               sum(coalesce(li.amount, 0.0)) AS taxable,
               count(li) AS line_count
        ORDER BY invoice_id, gst_percent
        """,
        pharmacy_id=pharmacy_id,
        start=start,
        end=end,
        vendor=vendor,
        statuses=list(statuses) if statuses is not None else DEFAULT_STATUSES,
    )
    return [_money(row, "taxable") for row in rows]


def purchase_hsn_lines(
    start: str,
    end: str,
    statuses: Optional[list] = None,
    pharmacy_id: Optional[str] = None,
) -> list:
    """Inward lines grouped by HSN and slab, for the inward HSN summary.

    `pack` comes back because it is the only thing on an inward line that
    resembles a unit - there is no UQC field on `LineItem`. The summary reports
    what it can make of it and says plainly when it can make nothing.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
        WHERE inv.invoice_date >= $start AND inv.invoice_date <= $end
          AND ($statuses IS NULL OR inv.status IN $statuses)
        MATCH (inv)-[:CONTAINS]->(li:LineItem)
        WITH coalesce(li.hsn, '') AS hsn,
             li.gst_percent AS gst_percent,
             coalesce(li.pack, '') AS pack,
             li, inv
        RETURN hsn,
               gst_percent,
               pack,
               count(li) AS line_count,
               sum(coalesce(li.amount, 0.0)) AS taxable,
               sum(coalesce(li.quantity, 0.0)) AS quantity,
               collect(DISTINCT inv.id)[0..25] AS invoice_ids
        ORDER BY hsn, gst_percent
        """,
        pharmacy_id=pharmacy_id,
        start=start,
        end=end,
        statuses=list(statuses) if statuses is not None else DEFAULT_STATUSES,
    )
    return [_money(row, "taxable") for row in rows]


def payments_for_window(
    start: str, end: str, pharmacy_id: Optional[str] = None
) -> list:
    """How each sale in the window was paid for.

    Read separately from the sale itself: `OutwardDocument` is the GSTR-1
    contract and has no business carrying a payment method. The sales register
    joins the two, and the turnover-versus-payments cross-check compares them.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pharmacy_id})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
        MATCH (s)-[:PAID_BY]->(p:SalePayment)
        RETURN s.id AS sale_id,
               s.status AS status,
               coalesce(s.document_type, 'INVOICE') AS document_type,
               p.method AS method,
               coalesce(p.amount_paise, 0) AS amount_paise,
               p.reference AS reference
        ORDER BY sale_id
        """,
        pharmacy_id=pharmacy_id,
        start=start,
        end=end,
    )
    # Already paise on the sales side - no conversion, and none wanted.
    return [dict(row) for row in rows]


def documents_by_id(kind: str, ids: list, pharmacy_id: Optional[str] = None) -> list:
    """The records behind a figure, for the drill-through.

    One place rather than one endpoint per report, because "show me what makes
    up this number" is the same question whatever number was clicked.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    ids = [i for i in (ids or []) if i]
    if not ids:
        return []

    if kind == "PURCHASES":
        rows = _run_read(
            """
            MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pharmacy_id})
            WHERE inv.id IN $ids
            OPTIONAL MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
            RETURN inv.id AS id, inv.invoice_number AS number,
                   inv.invoice_date AS date,
                   coalesce(inv.seller_name, v.name) AS party,
                   coalesce(inv.seller_gstin, v.gstin) AS party_gstin,
                   inv.status AS status,
                   inv.subtotal AS taxable, inv.cgst AS cgst,
                   inv.sgst AS sgst, inv.igst AS igst,
                   inv.grand_total AS grand_total
            ORDER BY date, number
            """,
            pharmacy_id=pharmacy_id, ids=ids,
        )
        return [_money(r, "taxable", "cgst", "sgst", "igst", "grand_total") for r in rows]

    if kind == "ITC_REVERSALS":
        rows = _run_read(
            """
            MATCH (r:ItcReversal {pharmacy_id: $pharmacy_id})
            WHERE r.id IN $ids
            OPTIONAL MATCH (r)-[:SOURCE_DOCUMENT]->(inv:Invoice)
            RETURN r {.*} AS reversal, inv.invoice_number AS source_invoice_number
            ORDER BY reversal.recorded_at
            """,
            pharmacy_id=pharmacy_id, ids=ids,
        )
        return [
            {**row["reversal"], "source_invoice_number": row.get("source_invoice_number")}
            for row in rows
        ]

    # Sales, and anything that resolves to a Sale node.
    rows = _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pharmacy_id})
        WHERE s.id IN $ids
        RETURN s.id AS id,
               coalesce(s.bill_number, s.serial) AS number,
               s.sale_date AS date,
               s.customer_name AS party,
               s.customer_gstin AS party_gstin,
               s.status AS status,
               coalesce(s.taxable_paise, 0) AS taxable_paise,
               coalesce(s.cgst_paise, 0) AS cgst_paise,
               coalesce(s.sgst_paise, 0) AS sgst_paise,
               coalesce(s.igst_paise, 0) AS igst_paise,
               coalesce(s.grand_total_paise, 0) AS grand_total_paise,
               s.capture_mode AS capture_mode,
               coalesce(s.document_type, 'INVOICE') AS document_type
        ORDER BY date, number
        """,
        pharmacy_id=pharmacy_id, ids=ids,
    )
    return [dict(row) for row in rows]
