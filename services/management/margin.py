"""Gross margin, by product, by vendor and by month.

Margin is sale taxable value less what the stock actually cost, taken from the
purchase movements that delivered the batch. That is the part no spreadsheet
the shop keeps can do: it needs the sale, the batch it came out of, and the
invoice that delivered that batch, joined.

Two honesty rules run through this:

**A margin computed against the wrong cost is worse than none.** Where a sale
names a batch no purchase recorded - common on imported and photographed bills -
the product's overall weighted average is used instead, and the row is marked
`PRODUCT` rather than `BATCH`. Where nothing is known, the row is marked `NONE`
and its margin is not reported at all rather than shown as equal to revenue,
which is what subtracting a zero cost would produce.

**Day totals are excluded, loudly.** A `DAY_TOTAL` declares a slab total and
names no product, so it cannot carry a margin. A shop that bills mostly that
way would otherwise see a margin report covering a fraction of its sales and
have no way to know. The empty state says so with the count.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from services.management.costing import quantity

# Cost bases, in descending order of how much they can be trusted.
BASIS_BATCH = "BATCH"
BASIS_PRODUCT = "PRODUCT"
BASIS_NONE = "NONE"


@dataclass
class MarginRow:
    key: str
    label: str
    revenue_paise: int = 0
    cost_paise: int = 0
    quantity: Decimal = Decimal("0")
    line_count: int = 0
    # Rows costed against a product average rather than the batch sold, and
    # rows with no cost at all. Carried per group so a total can say how much
    # of itself is measured.
    estimated_line_count: int = 0
    uncosted_line_count: int = 0
    uncosted_revenue_paise: int = 0
    vendor_id: Optional[str] = None

    @property
    def costed_revenue_paise(self) -> int:
        """Revenue that has a cost to set against it."""
        return self.revenue_paise - self.uncosted_revenue_paise

    @property
    def margin_paise(self) -> int:
        return self.costed_revenue_paise - self.cost_paise

    @property
    def margin_percent(self) -> Optional[float]:
        if self.costed_revenue_paise <= 0:
            return None
        return round(self.margin_paise * 100 / self.costed_revenue_paise, 2)

    @property
    def is_below_cost(self) -> bool:
        """Selling for less than it cost. The row somebody has to look at."""
        return self.costed_revenue_paise > 0 and self.margin_paise < 0

    @property
    def confidence(self) -> str:
        if self.uncosted_line_count == self.line_count and self.line_count:
            return BASIS_NONE
        if self.estimated_line_count or self.uncosted_line_count:
            return BASIS_PRODUCT
        return BASIS_BATCH

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "vendor_id": self.vendor_id,
            "quantity": float(self.quantity),
            "line_count": self.line_count,
            "revenue": round(self.revenue_paise / 100, 2),
            "cost": round(self.cost_paise / 100, 2),
            "margin": round(self.margin_paise / 100, 2),
            "margin_percent": self.margin_percent,
            "is_below_cost": self.is_below_cost,
            "confidence": self.confidence,
            "estimated_line_count": self.estimated_line_count,
            "uncosted_line_count": self.uncosted_line_count,
            "uncosted_revenue": round(self.uncosted_revenue_paise / 100, 2),
        }


def _accumulate(rows: dict, key: str, label: str, vendor_id: Optional[str]) -> MarginRow:
    row = rows.get(key)
    if row is None:
        row = rows[key] = MarginRow(key=key, label=label, vendor_id=vendor_id)
    return row


def build(lines: list, costing, day_total_count: int = 0,
          vendor_names: Optional[dict] = None) -> dict:
    """Margin grouped three ways from one pass over the sold lines."""
    vendor_names = vendor_names or {}
    by_product: dict = {}
    by_vendor: dict = {}
    by_month: dict = {}

    for line in lines:
        # A credit note returns stock; it reduces both revenue and cost, so it
        # nets out of margin rather than being dropped.
        sign = -1 if line.get("document_type") == "CREDIT_NOTE" else 1
        product_id = line.get("product_id")
        if not product_id:
            continue

        units = quantity(line.get("quantity"))
        revenue = sign * int(line.get("taxable_paise") or 0)
        cost, basis = costing.cost_for_sale(
            product_id, line.get("batch_number") or "", units
        )
        cost = sign * cost

        position = (
            costing.position(product_id, line.get("batch_number") or "")
            or costing.fallback(product_id)
        )
        vendor_id = position.vendor_id if position else None
        month = (line.get("sale_date") or "")[:7]

        targets = (
            _accumulate(by_product, product_id, line.get("product_name") or product_id, vendor_id),
            _accumulate(
                by_vendor, vendor_id or "unknown",
                vendor_names.get(vendor_id) or "Supplier not identified", vendor_id,
            ),
            _accumulate(by_month, month, month, None),
        )
        for target in targets:
            target.revenue_paise += revenue
            target.quantity += sign * units
            target.line_count += 1
            if basis == BASIS_NONE:
                target.uncosted_line_count += 1
                target.uncosted_revenue_paise += revenue
            else:
                target.cost_paise += cost
                if basis == BASIS_PRODUCT:
                    target.estimated_line_count += 1

    def ranked(rows: dict, by_margin: bool = True) -> list:
        return [
            row.to_dict()
            for row in sorted(
                rows.values(),
                key=(lambda r: r.margin_paise) if by_margin else (lambda r: r.key),
                reverse=by_margin,
            )
        ]

    every = list(by_product.values())
    below_cost = [r for r in every if r.is_below_cost]
    uncosted = sum(r.uncosted_line_count for r in every)

    return {
        "by_product": ranked(by_product),
        "by_vendor": ranked(by_vendor),
        "by_month": ranked(by_month, by_margin=False),
        "below_cost": [r.to_dict() for r in sorted(below_cost, key=lambda r: r.margin_paise)],
        "totals": {
            "revenue": round(sum(r.revenue_paise for r in every) / 100, 2),
            "cost": round(sum(r.cost_paise for r in every) / 100, 2),
            "margin": round(sum(r.margin_paise for r in every) / 100, 2),
            "product_count": len(every),
            "below_cost_count": len(below_cost),
            "uncosted_line_count": uncosted,
        },
        "excluded": {
            "day_total_count": day_total_count,
            # Shown when there is nothing to report, and also when there is -
            # a margin over half a shop's sales is not a margin.
            "note": (
                f"{day_total_count} declared day total"
                f"{'' if day_total_count == 1 else 's'} in this period "
                "carry no product lines, so they cannot appear here. Margin is "
                "computed from bills with item detail only."
            ) if day_total_count else None,
        },
        "empty_reason": _empty_reason(bool(lines), day_total_count, uncosted),
    }


def _empty_reason(has_lines: bool, day_total_count: int, uncosted: int) -> Optional[str]:
    """Why the report is empty, when it is. Never just "no data".

    A shopkeeper seeing an empty margin report needs to know which of three
    things happened, because two of them are fixable this afternoon and one is
    not a problem at all.
    """
    if has_lines:
        if uncosted:
            return None
        return None
    if day_total_count:
        return (
            f"There were {day_total_count} day total"
            f"{'' if day_total_count == 1 else 's'} in this period and no itemised "
            "bills. A day total records what the till took at each tax rate, not "
            "which products were sold, so there is nothing to compute a margin "
            "against. Billing through the counter screen, or photographing the "
            "bills, gives you this report."
        )
    return (
        "No sales with item detail in this period. Margin needs to know which "
        "product was sold and which batch it came out of."
    )
