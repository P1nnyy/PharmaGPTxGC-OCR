"""HSN summary, both directions, with the UQC status stated per row.

Outward comes from the GSTR-1 engine, which recomputes it from line items.
Inward is summarised here from purchase lines.

The two are not symmetrical, and pretending otherwise would be the mistake.
An outward line carries a unit because the counter records one; an inward line
does not - `LineItem` has a `pack` column as printed on the supplier's invoice
("10x10", "1x100ML") and no unit field at all. So the inward summary reports
what it can make of the pack string and says plainly when it can make nothing,
rather than filing `OTH` and calling it done.

That distinction matters at filing time: Table 12 needs a UQC per HSN, and a
row whose unit is unknown is a row that will be rejected. Knowing which rows
those are before the return goes is the whole point of the column.
"""

from core.hsn import describe, is_known, normalize_hsn, normalize_uqc
from services.statutory.model import Drill, DrillKind, Figure, ReportRow

# What is known about a row's unit.
UQC_VALID = "VALID"          # a GSTN unit code, ready to file
UQC_UNMAPPED = "UNMAPPED"    # something was recorded, but it is not a UQC
UQC_MISSING = "MISSING"      # nothing was recorded at all

HSN_VALID = "VALID"
HSN_NOT_IN_MASTER = "NOT_IN_MASTER"
HSN_MISSING = "MISSING"


def _hsn_status(code: str) -> str:
    if not code:
        return HSN_MISSING
    return HSN_VALID if is_known(code) else HSN_NOT_IN_MASTER


def outward_summary(gstr1, months: tuple) -> dict:
    """Table 12 as the return will file it, with validation status per row."""
    summary = gstr1.tables["hsn"]

    def section(rows: list, is_b2b: bool) -> list:
        out = []
        for row in rows:
            drill = Drill(
                kind=DrillKind.SALES,
                filters={"ids": list(row.document_ids)},
                count=len(row.document_ids),
            )
            uqc_status = (
                UQC_VALID if row.uqc and normalize_uqc(row.uqc) else
                UQC_UNMAPPED if row.uqc else UQC_MISSING
            )
            hsn_status = _hsn_status(row.hsn)
            flags = []
            if uqc_status != UQC_VALID:
                flags.append(f"UQC_{uqc_status}")
            if hsn_status != HSN_VALID:
                flags.append(f"HSN_{hsn_status}")

            out.append(
                ReportRow(
                    cells={
                        "hsn": row.hsn,
                        "description": describe(row.hsn),
                        "uqc": row.uqc,
                        "uqc_status": uqc_status,
                        "hsn_status": hsn_status,
                        "rate": row.rate_bp / 100,
                        "quantity": float(row.quantity),
                        "taxable": Figure(row.taxable_paise, drill),
                        "cgst": Figure(row.cgst_paise, drill),
                        "sgst": Figure(row.sgst_paise, drill),
                        "igst": Figure(row.igst_paise, drill),
                        "total_value": Figure(row.total_value_paise, drill),
                        "is_b2b": is_b2b,
                    },
                    drill=drill,
                    flags=tuple(flags),
                ).to_dict()
            )
        return out

    b2b = section(summary.b2b, True)
    b2c = section(summary.b2c, False)
    every = b2b + b2c
    return {
        "b2b": b2b,
        "b2c": b2c,
        "totals": {
            "taxable": Figure(
                sum(r.taxable_paise for r in summary.b2b + summary.b2c)
            ).to_dict(),
        },
        "unfilable_row_count": sum(1 for r in every if r["flags"]),
        "lines_without_hsn": len(summary.lines_without_hsn),
        "lines_without_uqc": len(summary.lines_without_uqc),
        "documents_without_lines": list(summary.documents_without_lines),
    }


def inward_summary(lines: list) -> dict:
    """Inward HSN summary from purchase lines.

    Grouped on HSN and slab together, the same way the outward summary is, so
    the two can be read side by side. The unit is derived from the pack string
    where that is possible and reported as MISSING where it is not - which for
    most suppliers' invoices is most rows, and is worth knowing rather than
    papering over.
    """
    grouped: dict = {}

    for line in lines:
        code = normalize_hsn(line.get("hsn"))
        rate = line.get("gst_percent")
        uqc = normalize_uqc(line.get("pack"))
        key = (code, rate, uqc)

        bucket = grouped.setdefault(
            key,
            {
                "hsn": code,
                "rate": rate,
                "uqc": uqc,
                "pack_seen": line.get("pack") or None,
                "quantity": 0.0,
                "taxable_paise": 0,
                "line_count": 0,
                "invoice_ids": [],
            },
        )
        bucket["quantity"] += float(line.get("quantity") or 0)
        bucket["taxable_paise"] += int(line.get("taxable_paise") or 0)
        bucket["line_count"] += int(line.get("line_count") or 0)
        for invoice_id in line.get("invoice_ids") or []:
            if invoice_id not in bucket["invoice_ids"]:
                bucket["invoice_ids"].append(invoice_id)

    rows = []
    for key in sorted(grouped, key=lambda k: (k[0] or "", k[1] or 0, k[2] or "")):
        bucket = grouped[key]
        drill = Drill(
            kind=DrillKind.PURCHASES,
            filters={"ids": bucket["invoice_ids"]},
            count=len(bucket["invoice_ids"]),
        )
        uqc_status = (
            UQC_VALID if bucket["uqc"] else
            UQC_UNMAPPED if bucket["pack_seen"] else UQC_MISSING
        )
        hsn_status = _hsn_status(bucket["hsn"])
        flags = []
        if uqc_status != UQC_VALID:
            flags.append(f"UQC_{uqc_status}")
        if hsn_status != HSN_VALID:
            flags.append(f"HSN_{hsn_status}")

        rows.append(
            ReportRow(
                cells={
                    "hsn": bucket["hsn"] or None,
                    "description": describe(bucket["hsn"]),
                    "uqc": bucket["uqc"],
                    "uqc_status": uqc_status,
                    "pack_as_printed": bucket["pack_seen"],
                    "hsn_status": hsn_status,
                    "rate": bucket["rate"],
                    "quantity": round(bucket["quantity"], 3),
                    "line_count": bucket["line_count"],
                    "taxable": Figure(bucket["taxable_paise"], drill),
                },
                drill=drill,
                flags=tuple(flags),
            ).to_dict()
        )

    return {
        "rows": rows,
        "row_count": len(rows),
        "totals": {
            "taxable": Figure(sum(b["taxable_paise"] for b in grouped.values())).to_dict(),
        },
        "rows_without_uqc": sum(1 for r in rows if r["cells"]["uqc_status"] != UQC_VALID),
        "rows_without_known_hsn": sum(1 for r in rows if r["cells"]["hsn_status"] != HSN_VALID),
        "note": (
            "Inward lines carry the supplier's pack column, not a unit quantity "
            "code. A UQC is derived where the pack makes that possible and left "
            "as missing where it does not - filing those as OTHERS would hide a "
            "gap rather than close it."
        ),
    }
