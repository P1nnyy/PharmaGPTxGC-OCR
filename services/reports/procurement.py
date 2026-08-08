"""Vendor scorecard and product price variance.

These are the two reports that use data almost nobody else captures. Free
quantity is stored as its own field rather than folded into the discount, which
makes it possible to answer the question distributors compete on and pharmacies
cannot currently check: after the scheme, who is actually cheaper?
"""

from collections import defaultdict
from typing import Optional

from db.repositories import reports_repository
from services.reports import calculations as calc
from services.reports.periods import Period

# Below this many purchases of the same product, a rate change is an anecdote
# rather than a trend, and flagging it produces noise the buyer learns to ignore.
MIN_PURCHASES_FOR_VARIANCE = 2

# A rate move smaller than this is rounding or a minor scheme change, not a
# price rise worth surfacing.
MATERIAL_RATE_CHANGE = 0.02


def _f(value, default=0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def vendor_scorecard(period: Period, statuses: Optional[list[str]]) -> dict:
    """Per-vendor spend, share, scheme volume and effective discount."""
    rows = reports_repository.vendor_breakdown(period.start, period.end, statuses)
    total_spend = sum(_f(r.get("gross_total")) for r in rows)

    vendors = []
    for row in rows:
        line_total = _f(row.get("line_total"))
        list_value = _f(row.get("list_value_total"))
        billed = _f(row.get("billed_units"))
        free = _f(row.get("free_units"))

        vendors.append(
            {
                "vendor_name": row.get("vendor_name"),
                "gstin": row.get("gstin"),
                "invoice_count": row.get("invoice_count", 0) or 0,
                "gross_total": round(_f(row.get("gross_total")), 2),
                "taxable_total": round(_f(row.get("taxable_total")), 2),
                "share": calc.share_of(_f(row.get("gross_total")), total_spend),
                "billed_units": billed,
                "free_units": free,
                # How much of what arrived was free. A 10+1 scheme shows up here
                # as roughly 0.09, and it is directly comparable across vendors
                # in a way "10+1" versus "5% off" is not.
                "free_unit_share": (free / (billed + free)) if (billed + free) > 0 else None,
                "effective_discount_rate": (
                    round(1.0 - (line_total / list_value), 4) if list_value > 0 else None
                ),
                "last_purchase_date": row.get("last_purchase_date"),
                "identified": bool(row.get("gstin")),
            }
        )

    top_three = sum(v["gross_total"] for v in vendors[:3])
    return {
        "period": period.to_dict(),
        "vendors": vendors,
        "vendor_count": len(vendors),
        "total_spend": round(total_spend, 2),
        # Concentration is a supply risk: if three distributors cover nearly all
        # purchasing, one of them having a bad month is the pharmacy's problem.
        "top_three_share": calc.share_of(top_three, total_spend),
        "unidentified_vendor_count": sum(1 for v in vendors if not v["identified"]),
    }


def price_variance(period: Period, statuses: Optional[list[str]]) -> dict:
    """Rate movement per product, and the same product bought at two prices.

    Two signals come out of the same history: a rate that has moved since the
    last purchase, and a spread between what two suppliers charge for the
    identical item in the same period. The second is usually the more actionable
    of the two.
    """
    rows = reports_repository.product_purchase_history(period.start, period.end, statuses)

    by_product: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_product[row["product_id"]].append(row)

    products = []
    for product_id, purchases in by_product.items():
        # Repository returns these already ordered by date; sorting again keeps
        # the calculation correct if that ever changes.
        purchases.sort(key=lambda p: p.get("invoice_date") or "")

        unit_costs = []
        for purchase in purchases:
            cost = calc.effective_unit_cost(
                purchase.get("amount"), purchase.get("quantity"), purchase.get("free_quantity")
            )
            unit_costs.append(
                {
                    "invoice_date": purchase.get("invoice_date"),
                    "invoice_id": purchase.get("invoice_id"),
                    "invoice_number": purchase.get("invoice_number"),
                    "vendor_name": purchase.get("vendor_name"),
                    "rate": purchase.get("rate"),
                    "mrp": purchase.get("mrp"),
                    "gst_percent": purchase.get("gst_percent"),
                    "quantity": purchase.get("quantity"),
                    "free_quantity": purchase.get("free_quantity"),
                    "effective_unit_cost": round(cost, 4) if cost is not None else None,
                    "margin_at_purchase": _margin(purchase, cost),
                }
            )

        priced = [u for u in unit_costs if u["effective_unit_cost"] is not None]
        if not priced:
            continue

        first, last = priced[0], priced[-1]
        change = None
        if len(priced) >= MIN_PURCHASES_FOR_VARIANCE and first["effective_unit_cost"]:
            change = (last["effective_unit_cost"] - first["effective_unit_cost"]) / first[
                "effective_unit_cost"
            ]

        costs = [u["effective_unit_cost"] for u in priced]
        vendors = {u["vendor_name"] for u in priced}
        cheapest = min(priced, key=lambda u: u["effective_unit_cost"])
        dearest = max(priced, key=lambda u: u["effective_unit_cost"])

        products.append(
            {
                "product_id": product_id,
                "product_name": purchases[0].get("product_name"),
                "pack": purchases[0].get("pack"),
                "purchase_count": len(priced),
                "vendor_count": len(vendors),
                "first_unit_cost": first["effective_unit_cost"],
                "latest_unit_cost": last["effective_unit_cost"],
                "min_unit_cost": min(costs),
                "max_unit_cost": max(costs),
                "rate_change": round(change, 4) if change is not None else None,
                "rate_increased": bool(change is not None and change > MATERIAL_RATE_CHANGE),
                # A spread only means something when more than one supplier is
                # involved; the same vendor changing price over time is the
                # rate_change signal, not a sourcing opportunity.
                "cross_vendor_spread": (
                    round(dearest["effective_unit_cost"] - cheapest["effective_unit_cost"], 4)
                    if len(vendors) > 1
                    else None
                ),
                "cheapest_vendor": cheapest["vendor_name"] if len(vendors) > 1 else None,
                "latest_margin": last["margin_at_purchase"],
                "purchases": unit_costs,
            }
        )

    products.sort(key=lambda p: (p["rate_change"] or 0), reverse=True)

    return {
        "period": period.to_dict(),
        "products": products,
        "product_count": len(products),
        "increased_count": sum(1 for p in products if p["rate_increased"]),
        "multi_vendor_count": sum(1 for p in products if p["cross_vendor_spread"] is not None),
    }


def _margin(purchase: dict, unit_cost: Optional[float]) -> Optional[float]:
    """Potential margin on a purchase, netting GST out of MRP first.

    Returns None when the GST rate was not captured — comparing a tax-inclusive
    MRP against a pre-tax cost would overstate the margin by roughly the slab,
    and a confidently wrong margin drives worse decisions than a blank.
    """
    margin = calc.margin_at_purchase(
        purchase.get("mrp"), unit_cost, purchase.get("gst_percent")
    )
    return round(margin, 4) if margin is not None else None
