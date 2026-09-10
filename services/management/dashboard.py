"""Four cards, each one a number somebody can act on.

The test every card here had to pass: **if this number moves, does the
shopkeeper do something differently today?** Lifetime scans, total invoices
processed and products in catalogue all fail it. They describe the software's
activity rather than the shop's, and a dashboard made of them is one people
stop opening.

  Today's sales          did the shop take money today, and how does that
                         compare with the same day last week
  ITC at risk            stock about to expire, and the credit that has to be
                         reversed permanently if it does. The reason to open
                         the app daily rather than monthly.
  Compliance actions     what is blocking this period's return, now, while
                         there is still time to fix it
  Stock value            what is sitting on the shelf, at cost

Each card carries where it links to. A number with no route to the report
behind it is a number somebody has to go looking for.
"""

from datetime import date, timedelta
from typing import Optional


def _change(current: int, previous: int) -> Optional[float]:
    if not previous:
        return None
    return round((current - previous) * 100 / previous, 1)


def build(
    today: date,
    todays_sales_paise: int,
    todays_bill_count: int,
    comparison_sales_paise: int,
    expiry_report: dict,
    stock: dict,
    validation: Optional[dict] = None,
    period_label: str = "",
) -> dict:
    """The four cards."""
    validation = validation or {"blocking": [], "warnings": []}
    blocking = len(validation.get("blocking") or [])
    warnings = len(validation.get("warnings") or [])

    expiry_totals = expiry_report.get("totals", {})
    tax_at_risk = expiry_totals.get("input_tax_at_risk", 0.0)
    soonest = expiry_report.get("buckets", [{}])[0] if expiry_report.get("buckets") else {}

    return {
        "as_of": today.isoformat(),
        "cards": [
            {
                "id": "todays_sales",
                "title": "Today's sales",
                "value": round(todays_sales_paise / 100, 2),
                "unit": "currency",
                "detail": (
                    f"{todays_bill_count} bill{'' if todays_bill_count == 1 else 's'}"
                    if todays_bill_count else "No bills yet today"
                ),
                # Against the same weekday, not yesterday: a Monday compared
                # with a Sunday says more about the calendar than the shop.
                "comparison_label": "vs same day last week",
                "comparison_percent": _change(todays_sales_paise, comparison_sales_paise),
                "comparison_value": round(comparison_sales_paise / 100, 2),
                "link": "/reports/daily-sales",
                "tone": "neutral",
            },
            {
                "id": "itc_at_risk",
                "title": "Input credit at risk",
                "value": tax_at_risk,
                "unit": "currency",
                "detail": (
                    f"{expiry_totals.get('batch_count', 0)} batch"
                    f"{'' if expiry_totals.get('batch_count') == 1 else 'es'} expiring within "
                    f"{expiry_report.get('horizon_days', 180)} days"
                    + (
                        f" · {soonest.get('batch_count', 0)} within 30"
                        if soonest.get("batch_count") else ""
                    )
                ),
                "secondary": {
                    "label": "Stock value at cost",
                    "value": expiry_totals.get("value_at_cost", 0.0),
                },
                "note": (
                    f"₹{expiry_totals.get('still_returnable_value_at_cost', 0):,.0f} of this "
                    "can still go back to the distributor."
                    if expiry_totals.get("still_returnable_value_at_cost") else None
                ),
                "link": "/reports/expiry-risk",
                "tone": "bad" if tax_at_risk else "good",
            },
            {
                "id": "compliance_actions",
                "title": "Open compliance actions",
                "value": blocking + warnings,
                "unit": "count",
                "detail": (
                    f"{blocking} blocking, {warnings} to review"
                    if (blocking or warnings) else "Nothing outstanding"
                ),
                "secondary": {"label": "Period", "value": period_label} if period_label else None,
                "link": "/statutory-reports",
                "tone": "bad" if blocking else ("warn" if warnings else "good"),
            },
            {
                "id": "stock_value",
                "title": "Stock on hand",
                "value": stock.get("value_at_cost", 0.0),
                "unit": "currency",
                "detail": (
                    f"{stock.get('batch_count', 0)} batch"
                    f"{'' if stock.get('batch_count') == 1 else 'es'} at cost"
                ),
                "link": "/reports/stock-ledger",
                "tone": "neutral",
            },
        ],
    }


def comparison_day(today: date) -> str:
    """The same weekday a week ago."""
    return (today - timedelta(days=7)).isoformat()
