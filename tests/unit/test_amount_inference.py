"""Tests for deriving a line's Amount when the invoice didn't state one.

The figures are taken from the real invoices this system has processed,
because the whole point of the module is that no single formula fits them all:

    ARORA BROS / ENN PEE / GURKIRAT   amount = qty x rate
    EMM VEE TRADERS                   amount = (qty x rate - disc) x (1 + gst%)

A hard-coded "qty x rate - discount" is wrong on all four - and on the ones
where the discount column is a percentage it subtracts 5% as five rupees.
"""

import pytest

from extraction.normalizers.amount_inference import (
    fill_missing_amounts,
    infer_amount_formula,
)
from extraction.normalizers.canonical_invoice import CanonicalLineItem


def item(qty=None, rate=None, amount=None, discount=None, discount_percent=None, gst=None, name="X"):
    return CanonicalLineItem(
        name=name,
        quantity=qty,
        rate=rate,
        amount=amount,
        discount=discount,
        discount_percent=discount_percent,
        gst_percent=gst,
    )


# --------------------------------------------------------------------------
# Learning the formula from the invoice's own rows
# --------------------------------------------------------------------------

def test_infers_plain_qty_times_rate():
    """ENN PEE: amount is qty x rate; the discount is applied invoice-wide,
    not per line, even though a Dis column exists."""
    items = [
        item(qty=2.75, rate=154.45, amount=424.74, discount=5.0, gst=5.0),
        item(qty=1, rate=156.19, amount=156.19, discount=5.0, gst=5.0),
        item(qty=1, rate=101.23, amount=101.23, discount=5.0, gst=5.0),
    ]
    assert infer_amount_formula(items).name == "qty x rate"


def test_infers_tax_inclusive_formula():
    """EMM VEE TRADERS: the Amount column already includes tax and has the
    line discount taken off."""
    items = [
        item(qty=1, rate=73.98, discount=1.48, gst=18.0, amount=85.56),
        item(qty=1, rate=73.98, discount=1.48, gst=18.0, amount=85.55),
        item(qty=6, rate=22.42, discount=1.39, gst=18.0, amount=157.09),
    ]
    formula = infer_amount_formula(items)
    assert "gst" in formula.name
    assert "discount" in formula.name


def test_percentage_discount_is_not_subtracted_as_currency():
    """The bug this module exists for: a Dis column of 5.00 meaning 5% must
    not be deducted as five rupees."""
    items = [
        item(qty=2, rate=100.0, discount_percent=5.0, amount=190.0),
        item(qty=1, rate=200.0, discount_percent=5.0, amount=190.0),
        item(qty=3, rate=100.0, discount_percent=5.0, amount=285.0),
    ]
    assert infer_amount_formula(items).name == "qty x rate - discount%"


def test_prefers_the_simplest_formula_when_tied():
    """With a zero discount, "qty x rate" and "qty x rate - discount" are
    indistinguishable. The simpler one must win, so no adjustment is applied
    on the strength of rows that never evidenced it."""
    items = [
        item(qty=2, rate=50.0, discount=0.0, amount=100.0),
        item(qty=3, rate=10.0, discount=0.0, amount=30.0),
    ]
    assert infer_amount_formula(items).name == "qty x rate"


# --------------------------------------------------------------------------
# Refusing to guess
# --------------------------------------------------------------------------

def test_no_formula_when_evidence_is_too_thin():
    """One row proves nothing - many formulas fit a single data point."""
    assert infer_amount_formula([item(qty=1, rate=100.0, amount=100.0)]) is None


def test_no_formula_when_rows_disagree():
    """Contradictory rows mean the relationship wasn't read reliably; better
    to leave amounts blank than to apply a formula that fits a minority."""
    items = [
        item(qty=1, rate=100.0, amount=100.0),
        item(qty=1, rate=100.0, amount=250.0),
        item(qty=1, rate=100.0, amount=17.0),
        item(qty=1, rate=100.0, amount=903.0),
    ]
    assert infer_amount_formula(items) is None


def test_nothing_filled_when_no_formula_can_be_inferred():
    items = [
        item(qty=1, rate=100.0, amount=100.0),
        item(qty=1, rate=100.0, amount=250.0),
        item(qty=1, rate=100.0, amount=17.0),
        item(qty=2, rate=50.0),  # missing amount
    ]
    result = fill_missing_amounts(items)
    assert result["filled"] == 0
    assert items[-1].amount is None
    assert items[-1].is_estimated_amount is False


# --------------------------------------------------------------------------
# Filling in
# --------------------------------------------------------------------------

def test_fills_missing_amount_using_the_learned_formula():
    """The real case: ENN PEE item 31 had no readable Amount. qty x rate gives
    124.14, which is what the invoice actually prints. The old hard-coded
    "qty x rate - discount" gave 119.14 by treating 5% as five rupees."""
    items = [
        item(qty=2.75, rate=154.45, amount=424.74, discount=5.0, gst=5.0),
        item(qty=1, rate=156.19, amount=156.19, discount=5.0, gst=5.0),
        item(qty=1, rate=101.23, amount=101.23, discount=5.0, gst=5.0),
        item(qty=1, rate=124.14, amount=None, discount=5.0, gst=5.0, name="VONEFI 20 MG"),
    ]
    result = fill_missing_amounts(items)

    assert result["filled"] == 1
    assert result["formula"] == "qty x rate"
    assert items[-1].amount == 124.14
    assert items[-1].is_estimated_amount is True


def test_extracted_amounts_are_never_overwritten():
    items = [
        item(qty=2, rate=50.0, amount=100.0),
        item(qty=3, rate=10.0, amount=30.0),
        item(qty=1, rate=999.0, amount=1.0),  # odd, but it is what was printed
    ]
    fill_missing_amounts(items)
    assert items[-1].amount == 1.0
    assert items[-1].is_estimated_amount is False


def test_rows_without_qty_or_rate_are_left_alone():
    """Nothing to compute from - the row keeps its blank and its flag."""
    items = [
        item(qty=2, rate=50.0, amount=100.0),
        item(qty=3, rate=10.0, amount=30.0),
        item(name="NO NUMBERS"),
    ]
    result = fill_missing_amounts(items)
    assert result["filled"] == 0
    assert items[-1].amount is None


def test_zero_quantity_row_is_not_derived():
    items = [
        item(qty=2, rate=50.0, amount=100.0),
        item(qty=3, rate=10.0, amount=30.0),
        item(qty=0, rate=10.0),
    ]
    assert fill_missing_amounts(items)["filled"] == 0


def test_no_op_when_every_amount_is_present():
    items = [item(qty=2, rate=50.0, amount=100.0), item(qty=3, rate=10.0, amount=30.0)]
    result = fill_missing_amounts(items)
    assert result["filled"] == 0
    assert all(not i.is_estimated_amount for i in items)


def test_fill_is_idempotent():
    """Runs once per page and again after a multi-page merge; the second pass
    must not re-derive or double-adjust anything."""
    items = [
        item(qty=2, rate=50.0, amount=100.0),
        item(qty=3, rate=10.0, amount=30.0),
        item(qty=4, rate=25.0),
    ]
    first = fill_missing_amounts(items)
    derived = items[-1].amount
    second = fill_missing_amounts(items)
    assert first["filled"] == 1
    assert second["filled"] == 0
    assert items[-1].amount == derived


def test_continuation_page_item_derived_from_earlier_page_evidence():
    """A continuation page alone has too few rows to infer anything; merged
    with page 1 it inherits the pattern."""
    page2_only = [item(qty=1, rate=124.14)]
    assert fill_missing_amounts(page2_only)["filled"] == 0

    merged = [
        item(qty=2.75, rate=154.45, amount=424.74),
        item(qty=1, rate=156.19, amount=156.19),
        item(qty=1, rate=101.23, amount=101.23),
        item(qty=1, rate=124.14),
    ]
    assert fill_missing_amounts(merged)["filled"] == 1
    assert merged[-1].amount == 124.14
