"""What a batch cost, and what is left of it.

The foundation the margin, expiry and movers reports all stand on, and the part
that is only possible because purchase cost, batch lineage and sales are in one
graph. Nothing else in the system can answer "what did the twelve packs still
on this shelf cost me", because that needs the invoice that delivered them, the
batch they were delivered as, and the sales that took some of them away.

**Weighted average, taken over sums.** A batch bought twice at different prices
has one cost per unit: total spent divided by total received. Averaging the two
unit prices instead would weight a delivery of two packs the same as one of
two hundred. The average is therefore never stored - it is derived from the
sums each time, so it cannot drift from the movements behind it.

**Quantities are decimal, money is integer paise.** A pack count can be
fractional (half a strip), so quantities go through `Decimal` rather than
float; costs stay integer paise and are apportioned with one rounding at the
end. `cost_of(units)` is the only place a per-unit figure is ever materialised,
and it rounds once.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


def quantity(value) -> Decimal:
    """A pack count as an exact decimal. Via `str` so 0.1 is one tenth."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _apportion(total_paise: int, part: Decimal, whole: Decimal) -> int:
    """`total * part / whole`, rounded half-up, once."""
    if whole == 0:
        return 0
    value = (Decimal(total_paise) * part) / whole
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class BatchPosition:
    """One batch: what came in, what went out, what it cost, when it expires."""

    product_id: str
    batch_number: str
    product_name: Optional[str] = None
    quantity_in: Decimal = Decimal("0")
    quantity_out: Decimal = Decimal("0")
    cost_paise: int = 0
    input_tax_paise: int = 0
    mrp_paise: int = 0
    gst_rate_bp: int = 0
    expiry: Optional[str] = None
    vendor_id: Optional[str] = None
    first_received_on: Optional[str] = None
    last_received_on: Optional[str] = None

    @property
    def on_hand(self) -> Decimal:
        """What is left. Never negative.

        A batch can read negative when a sale names a batch no purchase
        recorded - an imported bill, or stock that predates the ledger. That is
        a data gap, not negative stock sitting on a shelf, so it is clamped
        here and surfaced as `is_oversold` rather than propagated into a
        valuation that would come out below zero.
        """
        remaining = self.quantity_in - self.quantity_out
        return remaining if remaining > 0 else Decimal("0")

    @property
    def is_oversold(self) -> bool:
        return (self.quantity_in - self.quantity_out) < 0

    @property
    def has_cost_basis(self) -> bool:
        """Whether anything is known about what this batch cost."""
        return self.quantity_in > 0 and self.cost_paise > 0

    def cost_of(self, units) -> int:
        """What `units` of this batch cost, at the weighted average."""
        return _apportion(self.cost_paise, quantity(units), self.quantity_in)

    def input_tax_of(self, units) -> int:
        """The input credit taken on `units` of this batch.

        This is the figure that has to be reversed permanently under Section
        17(5)(h) if the stock is written off rather than returned.
        """
        return _apportion(self.input_tax_paise, quantity(units), self.quantity_in)

    def mrp_value_of(self, units) -> int:
        return int(
            (Decimal(self.mrp_paise) * quantity(units)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    @property
    def unit_cost_paise(self) -> Optional[int]:
        """Display only. The reports apportion from sums, not from this."""
        if self.quantity_in == 0:
            return None
        return _apportion(self.cost_paise, Decimal("1"), self.quantity_in)


@dataclass
class Costing:
    """Every batch position, indexed the two ways the reports ask for them."""

    by_batch: dict = field(default_factory=dict)
    by_product: dict = field(default_factory=dict)

    def position(self, product_id: str, batch_number: str) -> Optional[BatchPosition]:
        return self.by_batch.get((product_id, batch_number or ""))

    def fallback(self, product_id: str) -> Optional[BatchPosition]:
        """A product-level position, for a sale whose batch we never received.

        Imported and photographed bills often name a batch no purchase in this
        system delivered. Costing those at the product's overall weighted
        average is better than reporting no margin at all, but it is a
        different claim - so callers mark the row as estimated rather than
        letting it pass as measured.
        """
        return self.by_product.get(product_id)

    def cost_for_sale(self, product_id: str, batch_number: str, units) -> tuple:
        """`(cost_paise, basis)` for units sold out of a batch.

        `basis` is `BATCH`, `PRODUCT` or `NONE`, and it travels with the figure
        because a margin computed against a product-level average is a
        different quality of number from one computed against the batch that
        was actually sold.
        """
        exact = self.position(product_id, batch_number)
        if exact and exact.has_cost_basis:
            return exact.cost_of(units), "BATCH"
        loose = self.fallback(product_id)
        if loose and loose.has_cost_basis:
            return loose.cost_of(units), "PRODUCT"
        return 0, "NONE"


def build(costs: list, sales: list, names: Optional[dict] = None) -> Costing:
    """Assembles positions from purchase and sale movement aggregates."""
    names = names or {}
    by_batch: dict = {}

    for row in costs:
        key = (row["product_id"], row.get("batch_number") or "")
        by_batch[key] = BatchPosition(
            product_id=row["product_id"],
            batch_number=row.get("batch_number") or "",
            product_name=names.get(row["product_id"]),
            quantity_in=quantity(row.get("quantity_in")),
            cost_paise=int(row.get("cost_paise") or 0),
            input_tax_paise=int(row.get("input_tax_paise") or 0),
            mrp_paise=int(row.get("mrp_paise") or 0),
            gst_rate_bp=int(row.get("gst_rate_bp") or 0),
            expiry=row.get("expiry"),
            vendor_id=row.get("vendor_id"),
            first_received_on=row.get("first_received_on"),
            last_received_on=row.get("last_received_on"),
        )

    for row in sales:
        key = (row["product_id"], row.get("batch_number") or "")
        position = by_batch.get(key)
        if position is None:
            # Sold out of a batch no purchase recorded. Kept, with nothing
            # bought against it, so `is_oversold` can say so.
            position = by_batch[key] = BatchPosition(
                product_id=row["product_id"],
                batch_number=row.get("batch_number") or "",
                product_name=names.get(row["product_id"]),
            )
        # Sale movements are stored negative; quantity out is a magnitude.
        position.quantity_out += abs(quantity(row.get("quantity_out")))

    # The product-level rollup, for sales whose batch we never received.
    by_product: dict = {}
    for position in by_batch.values():
        rolled = by_product.get(position.product_id)
        if rolled is None:
            rolled = by_product[position.product_id] = BatchPosition(
                product_id=position.product_id,
                batch_number="",
                product_name=position.product_name,
            )
        rolled.quantity_in += position.quantity_in
        rolled.quantity_out += position.quantity_out
        rolled.cost_paise += position.cost_paise
        rolled.input_tax_paise += position.input_tax_paise
        rolled.mrp_paise = max(rolled.mrp_paise, position.mrp_paise)
        rolled.gst_rate_bp = rolled.gst_rate_bp or position.gst_rate_bp

    return Costing(by_batch=by_batch, by_product=by_product)
