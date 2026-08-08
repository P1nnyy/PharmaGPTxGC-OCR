"""GST purchase register, HSN summary and rate-slab breakdown.

This is the report a pharmacy actually needs monthly: the register feeds the
input tax credit claim in GSTR-3B, and reconciles invoice-by-invoice against
GSTR-2B. Reconciliation is document-wise rather than aggregate, so the register
is returned as rows — one per invoice — and never collapsed into a summary the
accountant would have to take on trust.
"""

from typing import Optional

from db.repositories import reports_repository
from services.reports import calculations as calc
from services.reports.periods import Period

# Pharma sits almost entirely at 5% and 12%. A line outside these is usually
# either a misread rate or a non-medicine item, and worth a second look before
# it reaches a return.
EXPECTED_PHARMA_SLABS = {0.0, 5.0, 12.0, 18.0, 28.0}


def register(period: Period, statuses: Optional[list[str]]) -> dict:
    """Invoice-level purchase register for the period."""
    rows = reports_repository.gst_register(period.start, period.end, statuses)

    entries = []
    claimable = 0.0
    unclaimable = 0.0

    for row in rows:
        tax = calc.tax_total(row.get("cgst"), row.get("sgst"), row.get("igst"))
        supply = calc.supply_type(row.get("cgst"), row.get("sgst"), row.get("igst"))
        # No supplier GSTIN means no input credit, however clean the rest of the
        # invoice is. That distinction is the whole point of the report.
        has_gstin = bool(row.get("seller_gstin"))

        if tax is not None:
            if has_gstin:
                claimable += tax
            else:
                unclaimable += tax

        entries.append(
            {
                **row,
                "tax_total": tax,
                "supply_type": supply,
                "itc_eligible": has_gstin and tax is not None,
                "itc_blocked_reason": None if has_gstin else "Supplier GSTIN missing",
            }
        )

    return {
        "period": period.to_dict(),
        "rows": entries,
        "row_count": len(entries),
        "claimable_tax": round(claimable, 2),
        "blocked_tax": round(unclaimable, 2),
        "blocked_invoice_count": sum(1 for e in entries if not e["itc_eligible"]),
    }


def hsn_summary(period: Period, statuses: Optional[list[str]]) -> dict:
    """Taxable value by HSN code and GST slab, with slab anomalies flagged."""
    rows = reports_repository.hsn_summary(period.start, period.end, statuses)

    total = sum(float(r.get("taxable_value") or 0.0) for r in rows)
    by_slab: dict[float | None, dict] = {}
    entries = []

    for row in rows:
        slab = row.get("gst_percent")
        slab_key = float(slab) if slab is not None else None
        value = float(row.get("taxable_value") or 0.0)

        bucket = by_slab.setdefault(
            slab_key,
            {"gst_percent": slab_key, "taxable_value": 0.0, "line_count": 0, "hsn_count": 0},
        )
        bucket["taxable_value"] += value
        bucket["line_count"] += row.get("line_count", 0) or 0
        bucket["hsn_count"] += 1

        entries.append(
            {
                **row,
                "share": calc.share_of(value, total),
                "slab_is_expected": slab_key in EXPECTED_PHARMA_SLABS if slab_key is not None else None,
            }
        )

    slabs = sorted(
        (
            {**bucket, "taxable_value": round(bucket["taxable_value"], 2),
             "share": calc.share_of(bucket["taxable_value"], total)}
            for bucket in by_slab.values()
        ),
        key=lambda b: (b["gst_percent"] is None, b["gst_percent"] or 0),
    )

    # The same HSN under two different slabs is a strong signal of a misread
    # rate: an HSN code determines the slab, so it should map to exactly one.
    seen: dict[str, set] = {}
    for row in rows:
        seen.setdefault(row.get("hsn") or "unclassified", set()).add(row.get("gst_percent"))
    conflicts = [
        {"hsn": hsn, "slabs": sorted(s for s in slab_set if s is not None)}
        for hsn, slab_set in seen.items()
        if len({s for s in slab_set if s is not None}) > 1
    ]

    return {
        "period": period.to_dict(),
        "rows": entries,
        "slabs": slabs,
        "taxable_total": round(total, 2),
        "unclassified_line_count": sum(
            r.get("line_count", 0) or 0 for r in rows if r.get("hsn") == "unclassified"
        ),
        "slab_conflicts": conflicts,
    }
