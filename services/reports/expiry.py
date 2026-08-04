"""Near-expiry exposure, valued at what the stock cost.

The report that pays for itself. Distributors commonly accept saleable returns
for some months before expiry, so a batch spotted at 90 days out is usually
recoverable and the same batch spotted at 10 days out usually is not. Valuing
at purchase rate rather than MRP is deliberate: expired stock costs what was
paid for it, not what it might have sold for.

Scope is all stock ever purchased, not a reporting period. Stock bought in
March can expire in September, and a period filter would hide precisely the
batches this exists to surface.

One limitation has to travel with the numbers: this system sees purchases, not
sales, so a batch is counted at the quantity bought. Whatever has already been
dispensed is still in the figure. That makes the value at risk an upper bound,
and the payload says so — a pharmacist reading it as stock on hand would
over-estimate the exposure, and silently rounding it down would be worse.
"""

from datetime import date
from typing import Optional

from db.repositories import reports_repository
from services.reports import calculations as calc

# Buckets inside this are "act now" — the horizon a purchasing decision can
# still do something about.
ACTIONABLE_BUCKETS = ("expired", "0_30", "31_60", "61_90")


def build(
    statuses: Optional[list[str]],
    as_of: Optional[date] = None,
    horizon_days: int = 180,
) -> dict:
    """Batches bucketed by time to expiry, with value at risk per bucket."""
    as_of = as_of or date.today()
    rows = reports_repository.expiring_batches(statuses)

    buckets: dict[str, dict] = {
        key: {
            "bucket": key,
            "label": calc.EXPIRY_BUCKET_LABELS[key],
            "batch_count": 0,
            "value_at_risk": 0.0,
            "units": 0.0,
        }
        for key, _ in calc.EXPIRY_BUCKETS
    }

    entries = []
    total_at_risk = 0.0
    unreadable_expiry = 0

    for row in rows:
        days = calc.days_until_expiry(row.get("expiry_date"), as_of)
        bucket = calc.expiry_bucket(days)
        if bucket is None:
            # The batch carries an expiry the date parser could not read —
            # typically a row written before expiry normalisation. Counted, not
            # dropped, so the total is never quietly short.
            unreadable_expiry += 1
            continue

        # Cost basis is the line amount actually paid. Falling back to
        # rate x quantity keeps a batch in the report when the amount column
        # was not captured, rather than valuing it at zero and hiding it.
        value = row.get("amount")
        if value is None:
            value = calc.list_value(row.get("quantity"), 0, row.get("rate"))
        value = float(value or 0.0)

        units = calc.units_received(row.get("quantity"), row.get("free_quantity")) or 0.0

        buckets[bucket]["batch_count"] += 1
        buckets[bucket]["value_at_risk"] += value
        buckets[bucket]["units"] += units

        if days is not None and days <= horizon_days:
            total_at_risk += value
            entries.append(
                {
                    "expiry_date": row.get("expiry_date"),
                    "days_remaining": days,
                    "bucket": bucket,
                    "batch_number": row.get("batch_number"),
                    "product_name": row.get("product_name"),
                    "pack": row.get("pack"),
                    "quantity": row.get("quantity"),
                    "units": units,
                    "rate": row.get("rate"),
                    "mrp": row.get("mrp"),
                    "value_at_risk": round(value, 2),
                    "vendor_name": row.get("vendor_name"),
                    "invoice_id": row.get("invoice_id"),
                    "invoice_number": row.get("invoice_number"),
                    "invoice_date": row.get("invoice_date"),
                }
            )

    entries.sort(key=lambda e: e["days_remaining"])

    ordered = [
        {**buckets[key], "value_at_risk": round(buckets[key]["value_at_risk"], 2)}
        for key, _ in calc.EXPIRY_BUCKETS
    ]

    return {
        "as_of": as_of.isoformat(),
        "horizon_days": horizon_days,
        "buckets": ordered,
        "rows": entries,
        "total_value_at_risk": round(total_at_risk, 2),
        "actionable_value": round(
            sum(b["value_at_risk"] for b in ordered if b["bucket"] in ACTIONABLE_BUCKETS), 2
        ),
        "batches_with_unreadable_expiry": unreadable_expiry,
        # Consumed by the UI to label the figure honestly. Without a sales feed
        # these values are quantity purchased, not quantity still on the shelf.
        "basis": "quantity_purchased",
        "basis_note": (
            "Valued at purchase cost for the full quantity bought. Stock already "
            "dispensed cannot be netted off without sales data, so treat this as "
            "an upper bound."
        ),
    }
