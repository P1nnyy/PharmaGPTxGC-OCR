"""Derives a line's Amount when the invoice didn't print one we could read.

Why this isn't a single formula
-------------------------------
There is no universal relationship between a line's quantity, rate, discount
and its Amount - it depends on the distributor's format. Measured across the
real invoices this system has processed:

    ARORA BROS      amount = qty x rate          (discount applied invoice-wide)
    ENN PEE         amount = qty x rate
    GURKIRAT        amount = qty x rate
    EMM VEE TRADERS amount = qty x rate x (1 - disc%) x (1 + gst%)

and the discount column itself is sometimes a percentage and sometimes rupees,
which is not always stated in the header. Hard-coding "qty x rate - discount"
gets three of those four wrong, and on the fourth it subtracts a percentage as
though it were currency.

So instead of assuming, the formula is *learned from the invoice itself*: every
candidate is tested against the rows where Amount WAS read successfully, and
the one that reproduces them is applied to the rows where it is missing. The
invoice is its own ground truth, which is what makes this hold up on formats
nobody has seen yet.

If no candidate reproduces the known rows, nothing is filled in - a blank
Amount carries an amber "missing" flag the reviewer will act on, whereas a
confidently wrong number is the kind of error that reaches the books.
"""

from typing import Any, Callable, Dict, List, NamedTuple, Optional

from extraction.normalizers.canonical_invoice import CanonicalLineItem

# A candidate must reproduce a known Amount to within this much to count as a
# match. Invoices round to paise, and qty x rate can legitimately differ in the
# last decimal place, so a small absolute floor plus a tiny relative term.
_MATCH_ABSOLUTE_TOLERANCE = 0.05
_MATCH_RELATIVE_TOLERANCE = 0.001

# A formula must be corroborated by at least this many rows, and by this
# share of the rows it could have explained. Two independent rows agreeing is
# weak evidence on its own; the share requirement stops a formula that happens
# to fit a couple of rows from being applied to the whole invoice.
_MIN_SUPPORTING_ROWS = 2
_MIN_SUPPORT_RATIO = 0.6


class AmountFormula(NamedTuple):
    name: str
    # Fewer adjustments = simpler. Used to break ties, so an adjustment is
    # never applied on rows that provide no evidence for it (a zero discount
    # makes "qty x rate" and "qty x rate - discount" indistinguishable).
    complexity: int
    # (base, discount_amount, discount_percent, gst_percent) -> amount
    compute: Callable[[float, float, float, float], float]


# base = qty x rate, d = rupee discount, p = discount percent, g = gst percent
_CANDIDATES: List[AmountFormula] = [
    AmountFormula("qty x rate", 0, lambda base, d, p, g: base),
    AmountFormula("qty x rate - discount", 1, lambda base, d, p, g: base - d),
    AmountFormula("qty x rate - discount%", 1, lambda base, d, p, g: base * (1 - p / 100.0)),
    AmountFormula("qty x rate + gst", 1, lambda base, d, p, g: base * (1 + g / 100.0)),
    AmountFormula(
        "(qty x rate - discount) + gst", 2,
        lambda base, d, p, g: (base - d) * (1 + g / 100.0),
    ),
    AmountFormula(
        "(qty x rate - discount%) + gst", 2,
        lambda base, d, p, g: base * (1 - p / 100.0) * (1 + g / 100.0),
    ),
]


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _inputs(item: CanonicalLineItem) -> Optional[Dict[str, float]]:
    """The figures a formula needs, or None if quantity/rate are unusable."""
    qty = _as_float(item.quantity)
    rate = _as_float(item.rate)
    if qty is None or rate is None or qty == 0:
        return None
    return {
        "base": qty * rate,
        "d": _as_float(item.discount) or 0.0,
        "p": _as_float(getattr(item, "discount_percent", None)) or 0.0,
        "g": _as_float(item.gst_percent) or 0.0,
    }


def _matches(predicted: float, actual: float) -> bool:
    tolerance = max(_MATCH_ABSOLUTE_TOLERANCE, abs(actual) * _MATCH_RELATIVE_TOLERANCE)
    return abs(predicted - actual) <= tolerance


def infer_amount_formula(items: List[CanonicalLineItem]) -> Optional[AmountFormula]:
    """Picks the formula that best reproduces the Amounts this invoice printed.

    Returns None when the evidence is too thin or too contradictory to trust,
    in which case no amounts should be derived at all.
    """
    evidence = [
        (inputs, actual)
        for item in items
        for inputs in [_inputs(item)]
        for actual in [_as_float(item.amount)]
        if inputs is not None and actual is not None
    ]
    if len(evidence) < _MIN_SUPPORTING_ROWS:
        return None

    scored = []
    for candidate in _CANDIDATES:
        hits = sum(
            1 for inputs, actual in evidence
            if _matches(candidate.compute(inputs["base"], inputs["d"], inputs["p"], inputs["g"]), actual)
        )
        scored.append((hits, candidate))

    best_hits = max(hits for hits, _ in scored)
    if best_hits < _MIN_SUPPORTING_ROWS or best_hits / len(evidence) < _MIN_SUPPORT_RATIO:
        return None

    # Among equally-supported formulas prefer the simplest, so a discount or
    # tax adjustment is only applied where the rows actually evidence it.
    winners = [candidate for hits, candidate in scored if hits == best_hits]
    return min(winners, key=lambda c: c.complexity)


def fill_missing_amounts(items: List[CanonicalLineItem]) -> Dict[str, Any]:
    """Derives Amount for rows that lack one, using the invoice's own formula.

    Only ever fills a blank - an Amount actually read off the invoice is never
    overwritten. Rows filled here are marked is_estimated_amount so the review
    screen can label them rather than pass them off as extracted.
    """
    missing = [item for item in items if _as_float(item.amount) is None]
    if not missing:
        return {"formula": None, "filled": 0}

    formula = infer_amount_formula(items)
    if formula is None:
        return {"formula": None, "filled": 0}

    filled = 0
    for item in missing:
        inputs = _inputs(item)
        if inputs is None:
            continue
        item.amount = round(
            formula.compute(inputs["base"], inputs["d"], inputs["p"], inputs["g"]), 2
        )
        item.is_estimated_amount = True
        filled += 1

    return {"formula": formula.name if filled else None, "filled": filled}
