"""Money as integer paise.

The house rule this module exists to enforce: monetary values are stored and
computed as integer paise, never as floats. `0.1 + 0.2` is not `0.3`, and a
hundredth of a rupee lost per line becomes a reconciliation failure at the
document header — which is an error to surface, not something to absorb.

Rupees appear in exactly one place: `paise_to_rupees`, called at the API
boundary on the way out, and `parse_rupees_to_paise` on the way in. Nothing
between those two functions should hold a rupee value.

The arithmetic here deliberately mirrors `frontend/src/features/sell/money.ts`.
A day-total entered for a date and a counter bill issued on the same date have
to agree about what 12% of a figure is, and the only way to guarantee that is
for both sides to round in the same direction at the same step.
"""

from decimal import Decimal, InvalidOperation
from typing import Optional, Union

# Rates are held in integer basis points: 1200 bp is 12.00%. A float
# percentage cannot represent 12.5% exactly, and a rate multiplied into a
# taxable value has to be exact.
BP_DENOMINATOR = 10_000

Money = Union[int, float, str, Decimal, None]


def apply_ratio(amount: int, numerator: int, denominator: int) -> int:
    """`amount * numerator / denominator`, rounded half-up on the magnitude.

    Every proportional step in the tax engine goes through this one function,
    so rounding is a single auditable decision rather than a `round()` spread
    across call sites. Rounding half-up on the absolute value (rather than
    Python's banker's rounding, or truncation toward zero) is what makes a
    credit note the exact mirror of the bill it reverses.
    """
    if denominator == 0:
        raise ValueError("apply_ratio: denominator must not be zero")
    sign = -1 if amount < 0 else 1
    scaled = (abs(amount) * numerator * 2 + denominator) // (denominator * 2)
    return sign * scaled


def split_inclusive(gross_paise: int, rate_bp: int) -> "tuple[int, int]":
    """Splits a tax-inclusive figure into (taxable value, tax).

    Used wherever a shop states what it collected rather than what it charged
    before tax — the day-total screen, and MRP-inclusive counter pricing.

    The tax is derived by subtraction rather than computed independently, and
    that is the whole point: it guarantees `taxable + tax == gross` exactly, so
    the figure the customer paid is never contradicted by a stray paisa of
    rounding.
    """
    if rate_bp < 0:
        raise ValueError("split_inclusive: rate must not be negative")
    taxable = apply_ratio(gross_paise, BP_DENOMINATOR, BP_DENOMINATOR + rate_bp)
    return taxable, gross_paise - taxable


def tax_on_exclusive(taxable_paise: int, rate_bp: int) -> int:
    """Tax added on top of a figure that does not already contain it."""
    if rate_bp < 0:
        raise ValueError("tax_on_exclusive: rate must not be negative")
    return apply_ratio(taxable_paise, rate_bp, BP_DENOMINATOR)


def halve_tax(tax_paise: int) -> "tuple[int, int]":
    """Splits intra-state tax into (CGST, SGST).

    An intra-state supply is exactly half each. The odd paisa goes to SGST
    rather than being dropped, matching `frontend/src/pages/taxSplit.ts`, so
    that a purchase reviewed by hand and a sale computed here round the same
    way instead of disagreeing for no reason anyone can see.
    """
    cgst = tax_paise // 2
    return cgst, tax_paise - cgst


def round_to_rupee(paise: int) -> "tuple[int, int]":
    """Returns (rounded total, the adjustment that got there).

    The caller stores the adjustment in `round_off_paise`. Rounding happens
    once, at the document level, and never into a taxable value — a rounded
    taxable value is a wrong taxable value in the return.
    """
    sign = -1 if paise < 0 else 1
    rounded = sign * ((abs(paise) + 50) // 100) * 100
    return rounded, rounded - paise


def parse_rupees_to_paise(value: Money) -> Optional[int]:
    """Reads a rupee figure into integer paise, or None if it cannot be read.

    None rather than a coerced number, deliberately. `float("12abc")` at least
    raises, but a silent truncation of `12.999` to 12.99 would put a figure on
    a return that nobody typed. More than two decimal places is refused for the
    same reason: a pharmacy cannot charge a fraction of a paisa, so a third
    decimal is a typo, and rounding it here would hide the typo.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value * 100
    if isinstance(value, float):
        value = repr(value)

    text = str(value).strip().replace("₹", "").replace(",", "").replace(" ", "")
    if not text or text in {".", "-", "-."}:
        return None

    negative = text.startswith("-")
    if negative:
        text = text[1:]
    if not text or not all(c.isdigit() or c == "." for c in text) or text.count(".") > 1:
        return None

    whole, _, fraction = text.partition(".")
    if len(fraction) > 2:
        return None
    if whole == "" and fraction == "":
        return None

    try:
        paise = int(Decimal(whole or "0") * 100 + Decimal(fraction.ljust(2, "0") or "0"))
    except (InvalidOperation, ValueError):
        return None
    return -paise if negative else paise


def paise_to_rupees(paise: Optional[int]) -> Optional[float]:
    """Paise to rupees, for the API boundary and nowhere else.

    None passes through as None: a figure that was never computed must not
    leave here as 0.00, which downstream would read as a fact.
    """
    if paise is None:
        return None
    return round(paise / 100, 2)
