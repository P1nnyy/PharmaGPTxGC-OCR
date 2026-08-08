"""Headline totals and the spend trend."""

from typing import Optional

from db.repositories import reports_repository
from services.reports import calculations as calc
from services.reports.periods import Period, month_sequence


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def build(period: Period, statuses: Optional[list[str]]) -> dict:
    """Totals for the period, alongside what the status filter excluded.

    The excluded block is part of the payload rather than an afterthought: the
    UI has to be able to say "12 invoices worth ₹84,000 are not in this total",
    and it can only do that if the number travels with the total.
    """
    summary = reports_repository.period_summary(period.start, period.end, statuses)
    included = summary["included"]
    excluded = summary["excluded"]

    cgst = _f(included.get("cgst_total"))
    sgst = _f(included.get("sgst_total"))
    igst = _f(included.get("igst_total"))
    gross = _f(included.get("gross_total"))
    taxable = _f(included.get("taxable_total"))
    list_value = _f(included.get("list_value_total"))
    line_total = _f(included.get("line_total"))

    return {
        "period": period.to_dict(),
        "invoice_count": included.get("invoice_count", 0) or 0,
        "vendor_count": included.get("vendor_count", 0) or 0,
        "gross_total": round(gross, 2),
        "taxable_total": round(taxable, 2),
        "discount_total": round(_f(included.get("discount_total")), 2),
        "cgst_total": round(cgst, 2),
        "sgst_total": round(sgst, 2),
        "igst_total": round(igst, 2),
        "tax_total": round(cgst + sgst + igst, 2),
        # Benefit captured against what the same goods would have cost at list
        # rate — this is the only place free goods show up in a headline figure.
        "effective_discount_rate": (
            round(1.0 - (line_total / list_value), 4) if list_value > 0 else None
        ),
        "estimated_line_count": included.get("estimated_line_count", 0) or 0,
        "excluded": {
            "invoice_count": excluded.get("invoice_count", 0) or 0,
            "gross_total": round(_f(excluded.get("gross_total")), 2),
            "reason": "Not yet verified" if statuses else None,
        },
    }


def spend_trend(period: Period, statuses: Optional[list[str]]) -> dict:
    """Monthly spend across the period, with empty months kept as zero.

    A month with no purchases is information — it should render as a gap in the
    bars, not disappear and let the neighbouring months close ranks.
    """
    rows = {r["month"]: r for r in reports_repository.monthly_spend(period.start, period.end, statuses)}
    months = month_sequence(period)

    series = [
        {
            "month": month,
            "gross_total": round(_f(rows.get(month, {}).get("gross_total")), 2),
            "taxable_total": round(_f(rows.get(month, {}).get("taxable_total")), 2),
            "invoice_count": rows.get(month, {}).get("invoice_count", 0) or 0,
        }
        for month in months
    ]

    active = [point for point in series if point["invoice_count"] > 0]
    total = sum(point["gross_total"] for point in series)

    return {
        "period": period.to_dict(),
        "series": series,
        "total": round(total, 2),
        # Averaged over months that actually had purchases. Dividing by the full
        # period would understate the run rate for a pharmacy that has only been
        # uploading invoices for part of the year.
        "average_active_month": round(total / len(active), 2) if active else None,
        "active_month_count": len(active),
        "peak_month": max(series, key=lambda p: p["gross_total"])["month"] if active else None,
    }
