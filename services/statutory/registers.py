"""The purchase and sales registers: one row per document, never collapsed.

Registers are document-wise on purpose. An aggregate is what a return files; a
register is what somebody reconciles, and reconciliation happens invoice by
invoice - against GSTR-2B on the inward side, against the bill book on the
outward side. Collapsing either into a summary would leave the accountant
taking the total on trust, which is the thing this whole pack exists to avoid.

Both registers are computed in integer paise. The purchase side arrives as
floats and is converted at the repository boundary, so nothing here ever holds
a rupee.
"""

from typing import Optional

from services.statutory.itc_sources import EXCLUSION_NO_GSTIN, EXCLUSION_NO_TAX
from services.statutory.model import Drill, DrillKind, Figure, ReportRow

# ---------------------------------------------------------------- purchases


def purchase_register(invoices: list, rate_blocks: list) -> dict:
    """Invoice-wise inward supplies, with rate blocks and ITC eligibility.

    ITC eligibility uses the same rule as `services/reports/gst.py` - a
    supplier GSTIN and some tax - so the two registers cannot disagree about
    the same invoice. It is a necessary condition and not a sufficient one:
    what is actually claimable is capped by GSTR-2B, and a row marked eligible
    here is a row worth reconciling, not a row already claimed.
    """
    blocks_by_invoice: dict = {}
    for block in rate_blocks:
        invoice_id = block["invoice_id"]
        blocks_by_invoice.setdefault(invoice_id, []).append(
            {
                "gst_percent": block.get("gst_percent"),
                # Drills back to the invoice the block was summed from. A slab
                # figure with no route to its lines is the one somebody most
                # wants to open - "why is ₹10,000 sitting at 12%" is answered
                # by the invoice, not by the number.
                "taxable": Figure(
                    block.get("taxable_paise", 0),
                    Drill(kind=DrillKind.PURCHASES, filters={"ids": [invoice_id]}, count=1),
                ),
                "line_count": block.get("line_count", 0),
            }
        )

    rows = []
    eligible_tax = 0
    blocked_tax = 0

    for invoice in invoices:
        invoice_id = invoice["invoice_id"]
        tax = (
            invoice.get("cgst_paise", 0)
            + invoice.get("sgst_paise", 0)
            + invoice.get("igst_paise", 0)
        )
        has_gstin = bool(invoice.get("seller_gstin"))
        eligible = has_gstin and tax > 0

        if eligible:
            eligible_tax += tax
        else:
            blocked_tax += tax

        blocked_reason = None
        if not has_gstin:
            blocked_reason = EXCLUSION_NO_GSTIN
        elif tax == 0:
            blocked_reason = EXCLUSION_NO_TAX

        drill = Drill(kind=DrillKind.PURCHASES, filters={"ids": [invoice_id]}, count=1)
        flags = []
        if not eligible:
            flags.append("ITC_BLOCKED")
        if invoice.get("igst_paise") and (invoice.get("cgst_paise") or invoice.get("sgst_paise")):
            # Both on one invoice means the supply type was read two ways.
            flags.append("MIXED_SUPPLY_TYPE")

        rows.append(
            ReportRow(
                cells={
                    "invoice_id": invoice_id,
                    "invoice_number": invoice.get("invoice_number"),
                    "invoice_date": invoice.get("invoice_date"),
                    "seller_name": invoice.get("seller_name"),
                    "seller_gstin": invoice.get("seller_gstin"),
                    "status": invoice.get("status"),
                    "supply_type": "INTER" if invoice.get("igst_paise") else "INTRA",
                    "taxable": Figure(invoice.get("taxable_paise", 0), drill),
                    "discount": Figure(invoice.get("discount_paise", 0), drill),
                    "cgst": Figure(invoice.get("cgst_paise", 0), drill),
                    "sgst": Figure(invoice.get("sgst_paise", 0), drill),
                    "igst": Figure(invoice.get("igst_paise", 0), drill),
                    "tax_total": Figure(tax, drill),
                    "grand_total": Figure(invoice.get("grand_total_paise", 0), drill),
                    "itc_eligible": eligible,
                    "itc_blocked_reason": blocked_reason,
                    "rate_blocks": [
                        {**block, "taxable": block["taxable"].to_dict()}
                        for block in blocks_by_invoice.get(invoice_id, [])
                    ],
                },
                drill=drill,
                flags=tuple(flags),
            )
        )

    return {
        "rows": [r.to_dict() for r in rows],
        "row_count": len(rows),
        "totals": {
            "taxable": Figure(sum(i.get("taxable_paise", 0) for i in invoices)).to_dict(),
            "cgst": Figure(sum(i.get("cgst_paise", 0) for i in invoices)).to_dict(),
            "sgst": Figure(sum(i.get("sgst_paise", 0) for i in invoices)).to_dict(),
            "igst": Figure(sum(i.get("igst_paise", 0) for i in invoices)).to_dict(),
            "grand_total": Figure(sum(i.get("grand_total_paise", 0) for i in invoices)).to_dict(),
            "itc_eligible_tax": Figure(eligible_tax).to_dict(),
            "itc_blocked_tax": Figure(blocked_tax).to_dict(),
        },
        "blocked_invoice_count": sum(1 for r in rows if not r.cells["itc_eligible"]),
    }


# ------------------------------------------------------------------- sales


def _document_rates(document) -> list:
    """The distinct GST rates on a document, for filtering and display."""
    if document.has_lines:
        return sorted({l.rate_bp for l in document.lines if l.rate_bp})
    return sorted({b.rate_bp for b in document.rate_blocks if b.rate_bp})


def sales_register(
    documents: list,
    payments: list,
    rate_bp: Optional[int] = None,
    capture_mode: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> dict:
    """Bill-wise outward supplies, filterable the way a shop actually asks.

    The filters are applied here rather than in Cypher because three of the
    four are properties of the document's *contents* - which rates it carries,
    how it was paid - and pushing them into the query would mean either a much
    larger query or four of them. The window itself is filtered in the
    repository, so the set being scanned is one period's bills.

    Drafts and cancellations are kept and flagged rather than dropped. A
    register that silently omits a cancelled bill is a register that disagrees
    with the bill book somebody is reconciling it against.
    """
    payments_by_sale: dict = {}
    for payment in payments:
        payments_by_sale.setdefault(payment["sale_id"], []).append(payment)

    rows = []
    taxable = tax = untaxed = 0

    for document in documents:
        rates = _document_rates(document)
        sale_payments = payments_by_sale.get(document.document_id, [])
        methods = sorted({p["method"] for p in sale_payments if p.get("method")})

        if rate_bp is not None and rate_bp not in rates:
            continue
        if capture_mode and document.capture_mode != capture_mode:
            continue
        if payment_method and payment_method not in methods:
            continue

        drill = Drill(kind=DrillKind.SALES, filters={"ids": [document.document_id]}, count=1)
        sign = document.sign

        if document.is_reportable:
            taxable += sign * document.taxable_paise
            tax += sign * document.tax_paise
            untaxed += sign * document.untaxed_paise

        flags = []
        if not document.is_reportable:
            flags.append(document.status)
        if document.document_type == "CREDIT_NOTE":
            flags.append("CREDIT_NOTE")
        if not document.place_of_supply_state_code:
            flags.append("NO_PLACE_OF_SUPPLY")

        rows.append(
            ReportRow(
                cells={
                    "document_id": document.document_id,
                    "bill_number": document.bill_number,
                    "sale_date": document.sale_date,
                    "tax_period": document.tax_period,
                    "capture_mode": document.capture_mode,
                    "document_type": document.document_type,
                    "document_class": document.document_class,
                    "status": document.status,
                    "customer_name": document.customer_name,
                    "customer_gstin": document.customer_gstin,
                    "place_of_supply": document.place_of_supply_state_code,
                    "supply_type": document.supply_type,
                    "rates": [r / 100 for r in rates],
                    "payment_methods": methods,
                    "taxable": Figure(document.taxable_paise, drill),
                    "cgst": Figure(document.cgst_paise, drill),
                    "sgst": Figure(document.sgst_paise, drill),
                    "igst": Figure(document.igst_paise, drill),
                    "untaxed": Figure(document.untaxed_paise, drill),
                    "round_off": Figure(document.round_off_paise, drill),
                    "grand_total": Figure(document.grand_total_paise, drill),
                    "counts_in_return": document.is_reportable,
                },
                drill=drill,
                flags=tuple(flags),
            )
        )

    return {
        "rows": [r.to_dict() for r in rows],
        "row_count": len(rows),
        "totals": {
            "taxable": Figure(taxable).to_dict(),
            "tax": Figure(tax).to_dict(),
            "untaxed": Figure(untaxed).to_dict(),
            "supplies": Figure(taxable + untaxed).to_dict(),
        },
        "filters_applied": {
            "rate": rate_bp / 100 if rate_bp is not None else None,
            "capture_mode": capture_mode,
            "payment_method": payment_method,
        },
        "available_filters": {
            "rates": sorted({r / 100 for d in documents for r in _document_rates(d)}),
            "capture_modes": sorted({d.capture_mode for d in documents if d.capture_mode}),
            "payment_methods": sorted({p["method"] for p in payments if p.get("method")}),
        },
    }
