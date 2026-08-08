"""Pure calculations behind the purchase reports.

Everything here is a function of its arguments — no database, no clock, no
config. That is deliberate: these are the numbers a pharmacy owner will make
buying decisions on, so they need to be exhaustively testable in isolation.

Two conventions run through the module:

  * Missing inputs produce `None`, never `0`. A margin we cannot compute is not
    a margin of zero, and the reports must be able to say "not enough data on
    this line" rather than quietly averaging a fabricated zero into a total.
  * Free goods are part of the price. A 10+1 scheme is a discount expressed as
    quantity, and any cost figure that ignores it overstates what was paid per
    usable unit.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

# Buckets for time-to-expiry, in days. Ordered, and the first bucket whose
# threshold the value falls under wins. 90 and 180 matter because distributors
# commonly accept saleable returns some months ahead of expiry — stock inside
# those windows is still recoverable, stock past them usually is not.
EXPIRY_BUCKETS: tuple[tuple[str, Optional[int]], ...] = (
    ("expired", 0),
    ("0_30", 30),
    ("31_60", 60),
    ("61_90", 90),
    ("91_180", 180),
    ("beyond_180", None),
)

EXPIRY_BUCKET_LABELS = {
    "expired": "Already expired",
    "0_30": "Within 30 days",
    "31_60": "31–60 days",
    "61_90": "61–90 days",
    "91_180": "91–180 days",
    "beyond_180": "More than 180 days",
}


def _num(value) -> Optional[float]:
    """Coerces to float, treating unparseable and missing values alike as None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # filters NaN


def units_received(quantity, free_quantity) -> Optional[float]:
    """Billed units plus scheme units — what actually arrived on the shelf."""
    billed = _num(quantity)
    if billed is None:
        return None
    return billed + (_num(free_quantity) or 0.0)


def effective_unit_cost(amount, quantity, free_quantity) -> Optional[float]:
    """What one usable unit really cost, after discounts and free goods.

    This is the number that says which distributor is cheapest. The printed
    rate does not, because two suppliers quoting the same rate can differ by a
    scheme that makes one of them 9% cheaper per unit.
    """
    paid = _num(amount)
    received = units_received(quantity, free_quantity)
    if paid is None or received is None or received <= 0:
        return None
    return paid / received


def list_value(quantity, free_quantity, rate) -> Optional[float]:
    """What every unit received would have cost at the printed rate."""
    unit_rate = _num(rate)
    received = units_received(quantity, free_quantity)
    if unit_rate is None or received is None:
        return None
    return unit_rate * received


def effective_discount_rate(amount, quantity, free_quantity, rate) -> Optional[float]:
    """Total benefit as a fraction of list value, folding rupee discounts and
    free goods into one comparable number.

    Returns a fraction (0.136), not a percentage, so callers decide formatting.
    """
    gross = list_value(quantity, free_quantity, rate)
    paid = _num(amount)
    if gross is None or paid is None or gross <= 0:
        return None
    return 1.0 - (paid / gross)


def net_of_gst(mrp, gst_percent) -> Optional[float]:
    """Strips GST out of an MRP.

    MRP is a tax-inclusive shelf price; the purchase rate is pre-tax and the
    GST paid on it comes back as input credit. Comparing the two directly
    overstates margin by roughly the tax rate — 12 points on most pharma lines
    — so any margin figure has to net the tax out of MRP first.
    """
    price = _num(mrp)
    rate = _num(gst_percent)
    if price is None:
        return None
    if rate is None:
        return None
    if rate < 0:
        return None
    return price / (1.0 + rate / 100.0)


def margin_at_purchase(mrp, unit_cost, gst_percent) -> Optional[float]:
    """Potential retail margin on a line, as a fraction of the net sale price.

    "Potential" because this system sees no sales: it is the margin available
    if the stock sells at full MRP. Requires `gst_percent` — without it the
    result would be an inflated figure that looks like a margin, and a wrong
    margin is worse than a missing one.
    """
    net_price = net_of_gst(mrp, gst_percent)
    cost = _num(unit_cost)
    if net_price is None or cost is None or net_price <= 0:
        return None
    return (net_price - cost) / net_price


def days_until_expiry(expiry_iso: Optional[str], as_of: date) -> Optional[int]:
    """Whole days from `as_of` to the expiry date. Negative once expired."""
    if not expiry_iso:
        return None
    try:
        expiry = date.fromisoformat(expiry_iso)
    except (ValueError, TypeError):
        return None
    return (expiry - as_of).days


def expiry_bucket(days: Optional[int]) -> Optional[str]:
    """Maps days-to-expiry onto a bucket key. None when the date is unknown."""
    if days is None:
        return None
    if days < 0:
        return "expired"
    for key, threshold in EXPIRY_BUCKETS:
        if key == "expired":
            continue
        if threshold is None or days <= threshold:
            return key
    return "beyond_180"


@dataclass(frozen=True)
class ArithmeticCheck:
    """Result of re-adding an invoice from its parts."""

    expected_total: Optional[float]
    stated_total: Optional[float]
    delta: Optional[float]
    is_consistent: Optional[bool]

    def to_dict(self) -> dict:
        return {
            "expected_total": self.expected_total,
            "stated_total": self.stated_total,
            "delta": self.delta,
            "is_consistent": self.is_consistent,
        }


def check_invoice_arithmetic(
    line_total,
    discount,
    cgst,
    sgst,
    igst,
    roundoff,
    grand_total,
    tolerance: float = 1.0,
) -> ArithmeticCheck:
    """Does the invoice add up from its own line items and taxes?

    Failures split into two useful piles — extraction errors to fix, and
    genuine supplier billing errors to dispute — and both are worth surfacing.
    The default one-rupee tolerance absorbs per-line rounding that suppliers
    apply differently without flagging every invoice as broken.

    `is_consistent` is None when the invoice does not carry enough figures to
    check, which is a different thing from failing the check.
    """
    lines = _num(line_total)
    stated = _num(grand_total)
    if lines is None or stated is None:
        return ArithmeticCheck(None, stated, None, None)

    expected = (
        lines
        - (_num(discount) or 0.0)
        + (_num(cgst) or 0.0)
        + (_num(sgst) or 0.0)
        + (_num(igst) or 0.0)
        + (_num(roundoff) or 0.0)
    )
    delta = round(stated - expected, 2)
    return ArithmeticCheck(
        expected_total=round(expected, 2),
        stated_total=stated,
        delta=delta,
        is_consistent=abs(delta) <= tolerance,
    )


def tax_total(cgst, sgst, igst) -> Optional[float]:
    """Sum of the tax actually stated on the invoice.

    Returns None when no tax component was captured at all. It deliberately
    does not infer a total from line-level GST percentages: an invoice whose
    tax we failed to read belongs in the data-quality report, not in the tax
    summary wearing a number we invented.
    """
    parts = [_num(cgst), _num(sgst), _num(igst)]
    if all(p is None for p in parts):
        return None
    return round(sum(p for p in parts if p is not None), 2)


def supply_type(cgst, sgst, igst) -> Optional[str]:
    """Whether the invoice is an intra-state or inter-state supply.

    Read from which tax heads carry a value rather than assumed: CGST+SGST is
    intra-state, IGST is inter-state. Never guess one from the other — splitting
    an unknown tax 50/50 into CGST and SGST invents two taxes that appear
    nowhere on the invoice, and is wrong outright for an inter-state purchase.
    """
    central, state, integrated = _num(cgst), _num(sgst), _num(igst)
    has_intra = bool(central or state)
    has_inter = bool(integrated)
    if has_intra and has_inter:
        return "mixed"
    if has_intra:
        return "intra_state"
    if has_inter:
        return "inter_state"
    return None


def share_of(value: Optional[float], total: Optional[float]) -> Optional[float]:
    """Fraction of a total, guarding the divide-by-zero an empty period gives."""
    numerator, denominator = _num(value), _num(total)
    if numerator is None or not denominator:
        return None
    return numerator / denominator
