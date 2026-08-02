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
# Tighter than the per-row figure: matching a whole-invoice total is a single
# equation rather than several independent agreements, so it has to clear a
# higher bar before a formula is trusted on that evidence alone.
_TOTAL_RELATIVE_TOLERANCE = 0.0005

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


def infer_amount_formula_from_total(
    items: List[CanonicalLineItem], printed_total: Optional[float]
) -> Optional[AmountFormula]:
    """Picks the formula whose row sum reproduces the invoice's printed total.

    Row-level inference needs at least one Amount to have been read, and some
    invoices supply none at all - a distributor whose Amount column has values
    but no column heading gives the extractor nothing to anchor on, so every
    row comes back blank and there is no evidence to learn from.

    The footer is the remaining witness. Summing a candidate over every row and
    comparing against the printed subtotal is a single equation over the whole
    invoice, and a formula that reproduces it to the paisa is not a guess: the
    document has confirmed it. On the invoice that prompted this, qty x rate
    summed to 3747.24 against a printed 3747.24.

    It is deliberately all-or-nothing. Every row must supply a usable quantity
    and rate, because a sum with rows missing cannot be compared against a
    total that includes them - it would either reject a correct formula or, far
    worse, quietly match a wrong one whose error happens to fill the gap.
    """
    if printed_total is None or printed_total <= 0:
        return None

    inputs = [_inputs(item) for item in items]
    if not inputs or any(i is None for i in inputs):
        return None

    # Tolerance grows with row count, since each rounded row contributes its
    # own error to the sum.
    tolerance = max(_MATCH_ABSOLUTE_TOLERANCE * len(inputs), abs(printed_total) * _TOTAL_RELATIVE_TOLERANCE)

    winners = []
    for candidate in _CANDIDATES:
        total = sum(
            candidate.compute(i["base"], i["d"], i["p"], i["g"]) for i in inputs  # type: ignore[index]
        )
        if abs(total - printed_total) <= tolerance:
            winners.append(candidate)

    if not winners:
        return None

    # Several formulas can reproduce the same total when the adjustments they
    # differ by are all zero. Prefer the simplest, as with row-level matching.
    return min(winners, key=lambda c: c.complexity)


def fill_missing_amounts(
    items: List[CanonicalLineItem], printed_total: Optional[float] = None
) -> Dict[str, Any]:
    """Derives Amount for rows that lack one, using the invoice's own formula.

    Only ever fills a blank - an Amount actually read off the invoice is never
    overwritten. Rows filled here are marked is_estimated_amount so the review
    screen can label them rather than pass them off as extracted.

    Two sources of truth, strongest first: the Amounts this invoice printed on
    other rows, and failing that its printed total. Row-level evidence is
    preferred because it is corroborated independently several times over,
    whereas the total is a single equation that a wrong formula could in
    principle satisfy by coincidence.
    """
    missing = [item for item in items if _as_float(item.amount) is None]
    if not missing:
        return {"formula": None, "filled": 0}

    formula = infer_amount_formula(items)
    evidence = "printed row amounts"

    if formula is None:
        formula = infer_amount_formula_from_total(items, printed_total)
        evidence = "printed invoice total"

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

    return {
        "formula": formula.name if filled else None,
        "filled": filled,
        "evidence": evidence if filled else None,
    }
