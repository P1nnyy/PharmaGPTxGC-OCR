"""The stock ledger, and what is moving.

Two reports over the same movements.

**The ledger** is movement history per batch with a running balance. It only
became possible when purchases started being recorded: before that the ledger
held sales alone and a running balance could only count down from zero.

**Fast and slow movers** ranks by units and value, and answers the question a
shopkeeper actually asks about slow stock - not "how little did this sell" but
**"how long will what I am holding last?"** Days of cover turns a rate into a
date, and a date is something you can act on.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from services.management.costing import quantity

# Below this, stock is effectively dead: a year of cover on a pharmacy shelf
# means it will expire before it sells.
DEAD_STOCK_DAYS = 365


def ledger(movements: list) -> dict:
    """Movement history with a running balance, oldest first.

    The balance is carried per (product, batch) rather than globally, because
    a ledger that mixes batches answers no question anyone has: stock is
    tracked by batch because expiry, cost and recall all are.
    """
    balances: dict = {}
    rows = []

    for movement in movements:
        key = (movement.get("product_id"), movement.get("batch_number") or "")
        delta = quantity(movement.get("quantity_delta"))
        balances[key] = balances.get(key, Decimal("0")) + delta

        rows.append({
            "id": movement.get("id"),
            "occurred_on": movement.get("occurred_on"),
            "recorded_at": movement.get("recorded_at"),
            "product_id": movement.get("product_id"),
            "product_name": movement.get("product_name"),
            "batch_number": movement.get("batch_number"),
            "expiry": movement.get("expiry"),
            "reason": movement.get("reason"),
            "quantity_delta": float(delta),
            "balance": float(balances[key]),
            "value": round(int(movement.get("taxable_paise") or 0) / 100, 2),
            "input_tax": round(int(movement.get("input_tax_paise") or 0) / 100, 2),
            "source_type": movement.get("source_type"),
            "source_id": movement.get("source_id"),
            # A balance that has gone below zero means stock left the shelf
            # that no purchase in this system put there - an imported bill, or
            # stock predating the ledger. Flagged rather than hidden.
            "flags": ["NEGATIVE_BALANCE"] if balances[key] < 0 else [],
        })

    return {
        "rows": rows,
        "row_count": len(rows),
        "closing_balances": [
            {"product_id": product_id, "batch_number": batch, "balance": float(balance)}
            for (product_id, batch), balance in sorted(balances.items(), key=lambda kv: kv[0])
        ],
        "negative_balance_count": sum(1 for r in rows if r["flags"]),
    }


@dataclass
class Mover:
    product_id: str
    product_name: Optional[str]
    units_sold: Decimal = Decimal("0")
    revenue_paise: int = 0
    on_hand: Decimal = Decimal("0")
    stock_value_paise: int = 0

    def days_of_cover(self, days_observed: int) -> Optional[float]:
        """How long current stock lasts at the rate it has been selling.

        None when nothing sold in the window - which is not "infinite cover",
        it is "we have no rate to project from", and the two look very
        different to somebody deciding whether to reorder.
        """
        if days_observed <= 0 or self.units_sold <= 0:
            return None
        per_day = self.units_sold / Decimal(days_observed)
        return round(float(self.on_hand / per_day), 1)

    def to_dict(self, days_observed: int) -> dict:
        cover = self.days_of_cover(days_observed)
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "units_sold": float(self.units_sold),
            "revenue": round(self.revenue_paise / 100, 2),
            "on_hand": float(self.on_hand),
            "stock_value": round(self.stock_value_paise / 100, 2),
            "days_of_cover": cover,
            "never_sold": self.units_sold <= 0 and self.on_hand > 0,
            "dead_stock": cover is not None and cover > DEAD_STOCK_DAYS,
        }


def movers(lines: list, costing, days_observed: int, limit: int = 25) -> dict:
    """Fast and slow movers, with days of cover against what is held."""
    tracked: dict = {}

    for line in lines:
        product_id = line.get("product_id")
        if not product_id:
            continue
        sign = -1 if line.get("document_type") == "CREDIT_NOTE" else 1
        mover = tracked.get(product_id)
        if mover is None:
            mover = tracked[product_id] = Mover(
                product_id=product_id, product_name=line.get("product_name")
            )
        mover.units_sold += sign * quantity(line.get("quantity"))
        mover.revenue_paise += sign * int(line.get("taxable_paise") or 0)

    # Everything held, including products that sold nothing - those are the
    # slow movers the report exists to surface, and a report built only from
    # sales would omit exactly them.
    for position in costing.by_batch.values():
        on_hand = position.on_hand
        if on_hand <= 0:
            continue
        mover = tracked.get(position.product_id)
        if mover is None:
            mover = tracked[position.product_id] = Mover(
                product_id=position.product_id, product_name=position.product_name
            )
        if mover.product_name is None:
            mover.product_name = position.product_name
        mover.on_hand += on_hand
        mover.stock_value_paise += position.cost_of(on_hand)

    rows = [m.to_dict(days_observed) for m in tracked.values()]
    by_units = sorted(rows, key=lambda r: r["units_sold"], reverse=True)
    by_value = sorted(rows, key=lambda r: r["revenue"], reverse=True)
    slow = sorted(
        [r for r in rows if r["on_hand"] > 0],
        # Never-sold stock first, then the longest cover: both are money
        # sitting still, and the first kind is worse.
        key=lambda r: (not r["never_sold"], -(r["days_of_cover"] or 0)),
    )

    return {
        "days_observed": days_observed,
        "fast_by_units": by_units[:limit],
        "fast_by_value": by_value[:limit],
        "slow": slow[:limit],
        "totals": {
            "product_count": len(rows),
            "never_sold_count": sum(1 for r in rows if r["never_sold"]),
            "dead_stock_count": sum(1 for r in rows if r["dead_stock"]),
            "stock_value": round(sum(r["stock_value"] for r in rows), 2),
        },
    }


def stock_value(costing) -> dict:
    """What is on the shelf, at cost. The dashboard's fourth card."""
    total = 0
    batches = 0
    for position in costing.by_batch.values():
        on_hand = position.on_hand
        if on_hand <= 0:
            continue
        total += position.cost_of(on_hand)
        batches += 1
    return {
        "value_at_cost": round(total / 100, 2),
        "value_at_cost_paise": total,
        "batch_count": batches,
    }
