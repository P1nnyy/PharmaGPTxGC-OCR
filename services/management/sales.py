"""The daily sales summary, and the working-capital trend.

Two reports a shopkeeper opens rather than files.

**Daily summary** — by hour, by payment method, bill count, average bill value,
cash against everything else, and the same month a year's worth of habit ago.
The month-on-month comparison is the part that earns the daily open: a number
on its own is trivia, and the same number against last month is a fact.

**Purchase versus sales trend** — the working capital picture. Money goes out to
distributors in lumps and comes back over the following weeks, and a pharmacy
that cannot see the two curves together finds out it is short only when it is.
"""

from datetime import date, timedelta
from typing import Optional

# What the UI calls the non-cash methods when splitting the till. Cash is the
# one that matters on its own - it is the one that has to be counted, banked
# and reconciled, and the one a scrutiny officer asks about.
_CASH = {"cash", "CASH"}


def _percent(part: int, whole: int) -> Optional[float]:
    if not whole:
        return None
    return round(part * 100 / whole, 1)


def _change(current: int, previous: int) -> Optional[float]:
    """Percent change, or None when there is nothing to compare against.

    None rather than 100%: a first month with sales has not grown infinitely,
    it simply has no predecessor, and rendering that as a number invites it to
    be read as one.
    """
    if not previous:
        return None
    return round((current - previous) * 100 / previous, 1)


def daily_summary(
    by_hour: list,
    by_day: list,
    payments: list,
    previous_by_day: Optional[list] = None,
    previous_payments: Optional[list] = None,
) -> dict:
    """Hourly shape, payment split, and the month before for comparison."""
    previous_by_day = previous_by_day or []

    value = sum(int(d.get("value_paise") or 0) for d in by_day)
    bills = sum(int(d.get("bill_count") or 0) for d in by_day)
    previous_value = sum(int(d.get("value_paise") or 0) for d in previous_by_day)
    previous_bills = sum(int(d.get("bill_count") or 0) for d in previous_by_day)

    average = int(value / bills) if bills else 0
    previous_average = int(previous_value / previous_bills) if previous_bills else 0

    total_paid = sum(int(p.get("amount_paise") or 0) for p in payments)
    cash = sum(
        int(p.get("amount_paise") or 0) for p in payments if (p.get("method") or "") in _CASH
    )

    # Every hour of the trading day, including the empty ones. A chart drawn
    # only from hours that had a sale hides the quiet ones, which is the shape
    # somebody is looking for.
    hours = {int(h["hour"]): h for h in by_hour if h.get("hour") is not None}
    unknown_hour = next((h for h in by_hour if h.get("hour") is None), None)

    return {
        "totals": {
            "value": round(value / 100, 2),
            "bill_count": bills,
            "average_bill_value": round(average / 100, 2),
        },
        "comparison": {
            "previous_value": round(previous_value / 100, 2),
            "previous_bill_count": previous_bills,
            "previous_average_bill_value": round(previous_average / 100, 2),
            "value_change_percent": _change(value, previous_value),
            "bill_count_change_percent": _change(bills, previous_bills),
            "average_bill_change_percent": _change(average, previous_average),
        },
        "by_hour": [
            {
                "hour": hour,
                "label": f"{hour:02d}:00",
                "bill_count": int(hours.get(hour, {}).get("bill_count") or 0),
                "value": round(int(hours.get(hour, {}).get("value_paise") or 0) / 100, 2),
            }
            for hour in range(24)
        ],
        "bills_without_a_time": int(unknown_hour.get("bill_count") or 0) if unknown_hour else 0,
        "by_day": [
            {
                "day": d.get("day"),
                "bill_count": int(d.get("bill_count") or 0),
                "value": round(int(d.get("value_paise") or 0) / 100, 2),
            }
            for d in by_day
        ],
        "payment_split": [
            {
                "method": p.get("method"),
                "amount": round(int(p.get("amount_paise") or 0) / 100, 2),
                "payment_count": int(p.get("payment_count") or 0),
                "share_percent": _percent(int(p.get("amount_paise") or 0), total_paid),
            }
            for p in payments
        ],
        "cash_vs_digital": {
            "cash": round(cash / 100, 2),
            "digital": round((total_paid - cash) / 100, 2),
            "cash_share_percent": _percent(cash, total_paid),
            "recorded_total": round(total_paid / 100, 2),
            # The gap between what the bills say and what was recorded as
            # taken. The statutory pack's cross-check tests the same thing;
            # here it is shown so a shopkeeper notices before an officer does.
            "unrecorded": round((value - total_paid) / 100, 2),
        },
    }


def trend(purchases_by_day: list, sales_by_day: list) -> dict:
    """Purchases against sales, day by day, with the running gap.

    The running cumulative difference is the point. A single day where
    purchases exceed sales is an ordinary delivery; six weeks of it is working
    capital draining, and only the cumulative line shows the difference.
    """
    purchases = {p["day"]: int(p.get("cost_paise") or 0) for p in purchases_by_day}
    sales = {s["day"]: int(s.get("taxable_paise") or 0) for s in sales_by_day}
    days = sorted(set(purchases) | set(sales))

    rows = []
    running = 0
    for day in days:
        bought = purchases.get(day, 0)
        sold = sales.get(day, 0)
        running += sold - bought
        rows.append({
            "day": day,
            "purchases": round(bought / 100, 2),
            "sales": round(sold / 100, 2),
            "net": round((sold - bought) / 100, 2),
            "cumulative_net": round(running / 100, 2),
        })

    bought_total = sum(purchases.values())
    sold_total = sum(sales.values())
    return {
        "rows": rows,
        "totals": {
            "purchases": round(bought_total / 100, 2),
            "sales": round(sold_total / 100, 2),
            "net": round((sold_total - bought_total) / 100, 2),
            "purchase_invoice_count": sum(
                int(p.get("invoice_count") or 0) for p in purchases_by_day
            ),
        },
        "note": (
            "Sales are taxable value and purchases are cost, so the gap is gross "
            "margin before overheads — not profit, and not cash in hand."
        ),
    }


def month_bounds(period_start: date) -> tuple:
    """First and last day of the month `period_start` falls in."""
    first = period_start.replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (next_month - timedelta(days=1)).isoformat()


def previous_month_bounds(period_start: date) -> tuple:
    first = period_start.replace(day=1)
    previous_last = first - timedelta(days=1)
    return month_bounds(previous_last)
