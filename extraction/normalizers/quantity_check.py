"""Catches a free quantity that leaves the received total short of a pack.

The case this exists for
------------------------
S.G. Pharma invoice CHEQ001391, line 3:

    DIAPRIDE M4   qty 2.75   free 0.2   ->  total 2.95

2.95 packs is not a thing a distributor ships. The line above it on the same
invoice reads 5.50 + 0.50 = 6.00, and 2.75 + 0.25 would be 3.00 - the same
11:1 scheme ratio, and a whole number. The free figure was almost certainly
0.25 with the last digit lost.

Why the FREE figure and not the billed one
------------------------------------------
The billed quantity is corroborated by money: amount / rate came to exactly
2.7500, so the invoice charged for 2.75 and that reading is sound. Free goods
are by definition not charged for, so no arithmetic anywhere on the invoice
constrains them - which is precisely why a misread there survives every other
check in this system and lands in stock.

Why this proposes rather than rounds
------------------------------------
Rounding silently would be the wrong shape of fix twice over. Some invoices
genuinely do carry fractional totals, so a blanket round corrupts them; and
quantity feeds stock, where a number nobody agreed to is exactly what the
review screen exists to prevent. So this returns a suggestion carrying its
own arithmetic, and a human accepts it - the same contract as the catalogue
lookup and the amount inference.

Deliberately narrow. It fires only when every one of these holds:

  * a free quantity was actually stated (a blank free column is not an error)
  * the received total is not already whole
  * the billed quantity IS whole-ish or money-verified, so the shortfall is
    attributable to the free figure rather than to the billed one
  * the correction needed is small enough to be a misread digit rather than
    a different number entirely
"""

import math
from typing import Any, Optional

from pydantic import BaseModel

# How far the free figure may be moved. 0.2 -> 0.25 is a dropped trailing
# digit; 0.1 -> 0.25 is a different number, and proposing that would be
# inventing stock rather than repairing a misread.
MAX_CORRECTION = 0.1

# Tolerance for "already a whole number", absorbing float representation
# error (2.75 + 0.25 lands on 3.0000000000000004).
_WHOLE_EPSILON = 1e-6

# The billed quantity is trusted when the money agrees with it to within this
# much - the same relative tolerance the amount checks use.
_MONEY_EPSILON = 0.02


class QuantitySuggestion(BaseModel):
    field: str = "free_quantity"
    current: float
    suggested: float
    total_before: float
    total_after: float
    # Plain-language arithmetic, shown next to the row so the reviewer can
    # check the claim rather than trust the number.
    reason: str
    # True when amount / rate reproduced the billed quantity exactly, which is
    # what rules the billed figure out as the source of the shortfall.
    billed_verified: bool = False


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_whole(value: float) -> bool:
    return abs(value - round(value)) < _WHOLE_EPSILON


def check_free_quantity(item: dict) -> Optional[QuantitySuggestion]:
    """Returns a suggested free quantity, or None when nothing is wrong.

    `item` is a line-item-shaped dict: quantity, free_quantity, rate, amount.
    """
    billed = _as_float(item.get("quantity"))
    free = _as_float(item.get("free_quantity"))

    # No free goods stated: nothing to correct. A missing free column is the
    # normal case, not a defect.
    if billed is None or free is None or free <= 0:
        return None

    total = billed + free
    if _is_whole(total):
        return None

    # Confirm the billed figure against the money before blaming the free
    # one. Without this the same shortfall could equally be a misread billed
    # quantity, and moving the free figure would paper over it.
    rate = _as_float(item.get("rate"))
    amount = _as_float(item.get("amount"))
    billed_verified = False
    if rate and amount and rate != 0:
        implied = amount / rate
        billed_verified = abs(implied - billed) <= max(_MONEY_EPSILON, abs(billed) * 0.001)
        if not billed_verified:
            # The money disagrees with the billed quantity too. Something
            # larger is wrong with this row than a dropped digit, and
            # quietly adjusting the free column would hide it.
            return None

    target = math.ceil(total - _WHOLE_EPSILON)
    required_free = round(target - billed, 4)
    correction = required_free - free

    if correction <= 0 or correction > MAX_CORRECTION:
        return None

    return QuantitySuggestion(
        current=free,
        suggested=required_free,
        total_before=round(total, 4),
        total_after=float(target),
        billed_verified=billed_verified,
        reason=(
            f"{_fmt(billed)} billed + {_fmt(free)} free = {_fmt(total)}, "
            f"which is not a whole pack. {_fmt(billed)} + {_fmt(required_free)} "
            f"= {_fmt(float(target))}"
            + (
                " — and the billed quantity is confirmed by the line amount, "
                "so the free figure is the one in doubt."
                if billed_verified
                else "."
            )
        ),
    )


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def check_line_items(items: list[dict]) -> dict[int, QuantitySuggestion]:
    """Runs the check across an invoice, keyed by list position."""
    found = {}
    for index, item in enumerate(items):
        suggestion = check_free_quantity(item)
        if suggestion:
            found[index] = suggestion
    return found
