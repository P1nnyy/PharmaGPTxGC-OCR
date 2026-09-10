"""Why input tax credit gets reversed, and where each reversal is reported.

A reversal without a reason is indefensible. When an officer asks why ₹4,000 of
credit came back in March, "the system reversed it" is not an answer - the
answer has to name the rule, the document, and the table it was reported in.
So a reversal is never just an amount: it carries a trigger, the statutory
provision behind it, and the GSTR-3B row it lands in.

The distinction that matters most is **permanent versus temporary**, because it
decides which 3B row is used and whether the credit can ever come back:

  4(B)(1)  permanent. The credit is gone. Expired stock written off is the
           pharmacy's usual case, and it is not reclaimable - the goods are
           destroyed and the credit on them was never earned.
  4(B)(2)  temporary. The credit is reversed now and may be reclaimed later.
           Rule 37's 180-day non-payment is the standard case: pay the
           supplier and the credit comes back.
  4(D)(1)  the reclaim itself, when a 4(B)(2) reversal is undone.

Reporting a permanent reversal in 4(B)(2) understates a liability that will
never be reclaimed, and reporting a temporary one in 4(B)(1) throws away credit
the shop is entitled to. Neither is recoverable by a later correction without
an amendment, which is why the mapping lives in one table here rather than
being decided at each call site.
"""

from typing import Optional

# The three GSTR-3B rows a reversal or reclaim can land in.
TABLE_PERMANENT = "4(B)(1)"
TABLE_TEMPORARY = "4(B)(2)"
TABLE_RECLAIM = "4(D)(1)"


class ReversalTrigger:
    """What caused the reversal. Stored on the ledger row verbatim."""

    # Section 17(5)(h): goods lost, stolen, destroyed or written off. For a
    # pharmacy this is the common one by a wide margin - every expired pack
    # written off carries credit that has to go back.
    EXPIRED_STOCK = "EXPIRED_STOCK"
    DAMAGED_STOCK = "DAMAGED_STOCK"
    STOCK_WRITTEN_OFF = "STOCK_WRITTEN_OFF"

    # Rule 42: inputs used partly for exempt supplies. Material for a pharmacy
    # now that the notified life-saving drugs are nil rated - a shop selling
    # both taxable and nil-rated stock cannot claim the whole of its credit.
    EXEMPT_SUPPLY_PROPORTION = "EXEMPT_SUPPLY_PROPORTION"

    # Rule 43: the same idea for capital goods, spread over sixty months.
    CAPITAL_GOODS_EXEMPT = "CAPITAL_GOODS_EXEMPT"

    # Rule 37: supplier not paid within 180 days. Temporary - the credit comes
    # back on payment, which is what makes 4(D)(1) exist.
    NON_PAYMENT_180_DAYS = "NON_PAYMENT_180_DAYS"

    # Section 17(5) generally: credits blocked by their nature.
    BLOCKED_CREDIT = "BLOCKED_CREDIT"

    # A supplier's credit note reduces the credit originally claimed.
    SUPPLIER_CREDIT_NOTE = "SUPPLIER_CREDIT_NOTE"

    # Undoing an earlier temporary reversal. Always points at the row it undoes.
    RECLAIM = "RECLAIM"

    ALL = {
        EXPIRED_STOCK, DAMAGED_STOCK, STOCK_WRITTEN_OFF,
        EXEMPT_SUPPLY_PROPORTION, CAPITAL_GOODS_EXEMPT,
        NON_PAYMENT_180_DAYS, BLOCKED_CREDIT, SUPPLIER_CREDIT_NOTE, RECLAIM,
    }


# Trigger -> (statutory reference, 3B table, plain-language reason).
# The reason is written for the person who has to explain the figure, not for
# the person who wrote the code.
RULES: dict = {
    ReversalTrigger.EXPIRED_STOCK: (
        "Section 17(5)(h)",
        TABLE_PERMANENT,
        "Credit on goods written off. Expired stock was never sold, so the credit "
        "taken on buying it has to go back.",
    ),
    ReversalTrigger.DAMAGED_STOCK: (
        "Section 17(5)(h)",
        TABLE_PERMANENT,
        "Credit on goods destroyed or damaged beyond sale.",
    ),
    ReversalTrigger.STOCK_WRITTEN_OFF: (
        "Section 17(5)(h)",
        TABLE_PERMANENT,
        "Credit on stock written off for any other reason.",
    ),
    ReversalTrigger.EXEMPT_SUPPLY_PROPORTION: (
        "Rule 42",
        TABLE_PERMANENT,
        "The share of common input credit attributable to exempt and nil-rated "
        "supplies, which cannot be claimed.",
    ),
    ReversalTrigger.CAPITAL_GOODS_EXEMPT: (
        "Rule 43",
        TABLE_PERMANENT,
        "The share of capital-goods credit attributable to exempt supplies, "
        "spread over sixty months.",
    ),
    ReversalTrigger.NON_PAYMENT_180_DAYS: (
        "Rule 37, second proviso to Section 16(2)",
        TABLE_TEMPORARY,
        "The supplier has not been paid within 180 days of the invoice. The "
        "credit is reversed now and can be reclaimed once payment is made.",
    ),
    ReversalTrigger.BLOCKED_CREDIT: (
        "Section 17(5)",
        TABLE_PERMANENT,
        "Credit blocked by the nature of the supply.",
    ),
    ReversalTrigger.SUPPLIER_CREDIT_NOTE: (
        "Section 16(2) with Rule 37A",
        TABLE_PERMANENT,
        "The supplier issued a credit note, reducing the credit originally taken.",
    ),
    ReversalTrigger.RECLAIM: (
        "Rule 37, second proviso to Section 16(2)",
        TABLE_RECLAIM,
        "Reclaim of credit reversed earlier for non-payment, now that the "
        "supplier has been paid.",
    ),
}


class ItcRuleError(ValueError):
    """Raised when a reversal cannot be classified."""


def statutory_reference(trigger: str) -> str:
    return _rule(trigger)[0]


def gstr3b_table(trigger: str) -> str:
    """Which GSTR-3B row this reversal is reported in."""
    return _rule(trigger)[1]


def reason(trigger: str) -> str:
    """Why, in words a person can repeat to an officer."""
    return _rule(trigger)[2]


def is_permanent(trigger: str) -> bool:
    return gstr3b_table(trigger) == TABLE_PERMANENT


def is_reclaimable(trigger: str) -> bool:
    """Whether a reversal on this trigger can ever be reclaimed.

    Only the temporary ones. Offering a reclaim against a permanent reversal
    would claim credit on stock that no longer exists.
    """
    return gstr3b_table(trigger) == TABLE_TEMPORARY


def describe(trigger: str) -> dict:
    """Everything the reversal register has to show for one row."""
    reference, table, why = _rule(trigger)
    return {
        "trigger": trigger,
        "statutory_reference": reference,
        "gstr3b_table": table,
        "reason": why,
        "is_permanent": table == TABLE_PERMANENT,
        "is_reclaimable": table == TABLE_TEMPORARY,
    }


def _rule(trigger: Optional[str]) -> tuple:
    try:
        return RULES[trigger]
    except KeyError:
        raise ItcRuleError(
            f"{trigger!r} is not a reversal trigger this system knows, so there is "
            "no rule to cite and no 3B table to report it in. Classify it before "
            "recording it."
        )
