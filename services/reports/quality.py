"""Data-quality report: what is wrong with the ledger, and what it costs.

Ordinary validation tells you a field is empty. This report says what the empty
field means in rupees — a missing supplier GSTIN is not a cosmetic gap, it is
input tax credit that cannot be claimed.

Runs across every status rather than verified-only, because an invoice with a
problem is exactly the one that should be caught before somebody marks it
verified.
"""

from typing import Optional

from db.repositories import reports_repository
from services.reports import calculations as calc
from services.reports.periods import Period

# Severity drives ordering in the UI. `blocking` means money is at stake right
# now; `warning` means a figure is untrustworthy; `info` is worth knowing.
SEVERITY_ORDER = {"blocking": 0, "warning": 1, "info": 2}


def build(period: Period, arithmetic_tolerance: float = 1.0) -> dict:
    """Issues found across invoices in the period, most costly first."""
    rows = reports_repository.data_quality_rows(period.start, period.end)

    issues = []
    tax_at_risk = 0.0

    for row in rows:
        invoice_ref = {
            "invoice_id": row.get("invoice_id"),
            "invoice_number": row.get("invoice_number"),
            "invoice_date": row.get("invoice_date"),
            "seller_name": row.get("seller_name"),
            "grand_total": row.get("grand_total"),
            "status": row.get("status"),
        }

        tax = calc.tax_total(row.get("cgst"), row.get("sgst"), row.get("igst"))

        if not row.get("seller_gstin"):
            at_risk = tax or 0.0
            tax_at_risk += at_risk
            issues.append(
                {
                    **invoice_ref,
                    "code": "missing_seller_gstin",
                    "severity": "blocking",
                    "title": "Supplier GSTIN missing",
                    "detail": "Input tax credit cannot be claimed against this invoice.",
                    "value_at_stake": round(at_risk, 2),
                }
            )

        if tax is None:
            issues.append(
                {
                    **invoice_ref,
                    "code": "no_tax_captured",
                    "severity": "warning",
                    "title": "No tax captured",
                    "detail": "No CGST, SGST or IGST was read from this invoice.",
                    "value_at_stake": None,
                }
            )

        check = calc.check_invoice_arithmetic(
            row.get("line_total"),
            row.get("discount"),
            row.get("cgst"),
            row.get("sgst"),
            row.get("igst"),
            row.get("roundoff"),
            row.get("grand_total"),
            tolerance=arithmetic_tolerance,
        )
        if check.is_consistent is False:
            issues.append(
                {
                    **invoice_ref,
                    "code": "arithmetic_mismatch",
                    "severity": "warning",
                    "title": "Invoice does not add up",
                    "detail": (
                        f"Line items and taxes come to {check.expected_total}, "
                        f"but the invoice states {check.stated_total}."
                    ),
                    "value_at_stake": abs(check.delta) if check.delta is not None else None,
                    "arithmetic": check.to_dict(),
                }
            )

        estimated = row.get("estimated_lines") or 0
        if estimated:
            issues.append(
                {
                    **invoice_ref,
                    "code": "estimated_amounts",
                    "severity": "info",
                    "title": f"{estimated} line amount(s) inferred",
                    "detail": "These amounts were derived from other columns, not read from the invoice.",
                    "value_at_stake": None,
                }
            )

    for row in reports_repository.undated_invoices():
        issues.append(
            {
                "invoice_id": row.get("invoice_id"),
                "invoice_number": row.get("invoice_number"),
                "invoice_date": None,
                "seller_name": row.get("seller_name"),
                "grand_total": row.get("grand_total"),
                "status": row.get("status"),
                "code": "unreadable_date",
                "severity": "blocking",
                "title": "Invoice date could not be read",
                "detail": "This invoice is missing from every period report until the date is corrected.",
                "value_at_stake": None,
            }
        )

    duplicates = [
        {
            "code": "possible_duplicate",
            "severity": "blocking",
            "title": "Same invoice number from the same supplier",
            "detail": f"{group['occurrence_count']} invoices share this number.",
            "seller_gstin": group["gstin"],
            "invoice_number": group["invoice_number"],
            "occurrences": group["invoices"],
            "value_at_stake": _duplicate_exposure(group["invoices"]),
        }
        for group in reports_repository.duplicate_candidates()
    ]
    issues.extend(duplicates)

    issues.sort(
        key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), -(i.get("value_at_stake") or 0))
    )

    return {
        "period": period.to_dict(),
        "issues": issues,
        "issue_count": len(issues),
        "blocking_count": sum(1 for i in issues if i["severity"] == "blocking"),
        "itc_at_risk": round(tax_at_risk, 2),
        "duplicate_group_count": len(duplicates),
        "invoices_checked": len(rows),
    }


def _duplicate_exposure(occurrences: list[dict]) -> Optional[float]:
    """What a duplicate group could cost if paid twice.

    The first copy is the real invoice; every copy beyond it is the exposure.
    """
    totals = [float(o["grand_total"]) for o in occurrences if o.get("grand_total") is not None]
    if len(totals) < 2:
        return None
    return round(sum(sorted(totals, reverse=True)[1:]), 2)
