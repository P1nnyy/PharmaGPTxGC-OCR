"""Deriving line amounts from the invoice's printed total.

Figures are from RAMA ENTERPRISES REV000732, whose Amount column carries
values under no column heading - so nothing anchors the column, every row
extracts blank, and row-level inference has no evidence to work from.

The cases where this must REFUSE matter more than the ones where it fires: a
wrong formula applied to every line of an invoice is worse than a blank the
review screen already knows how to flag.
"""

import pytest

from extraction.normalizers.amount_inference import (
    fill_missing_amounts,
    infer_amount_formula_from_total,
)
from extraction.normalizers.canonical_invoice import CanonicalLineItem

# The real invoice: 13 rows, printed subtotal 3747.24.
REAL_ROWS = [
    (2.75, 200.02), (2, 149.30), (3, 100.00), (2, 142.87), (2, 192.16),
    (1, 155.01), (1, 51.27), (3, 192.78), (4, 109.89), (2, 150.72),
    (1, 134.30), (1, 134.30), (1, 134.30),
]
REAL_SUBTOTAL = 3747.24


def rows(specs, **kwargs):
    return [
        CanonicalLineItem(name=f"item{i}", quantity=q, rate=r, **kwargs)
        for i, (q, r) in enumerate(specs)
    ]


class TestRealInvoice:
    def test_fills_every_row_from_the_printed_total(self):
        items = rows(REAL_ROWS, gst_percent=5.0)
        result = fill_missing_amounts(items, printed_total=REAL_SUBTOTAL)

        assert result["filled"] == 13
        assert result["formula"] == "qty x rate"
        assert result["evidence"] == "printed invoice total"

    def test_derived_amounts_reproduce_the_printed_total(self):
        items = rows(REAL_ROWS, gst_percent=5.0)
        fill_missing_amounts(items, printed_total=REAL_SUBTOTAL)
        assert round(sum(i.amount for i in items), 2) == pytest.approx(REAL_SUBTOTAL, abs=0.01)

    def test_derived_rows_are_labelled_as_derived(self):
        # Never passed off as something read off the page.
        items = rows(REAL_ROWS, gst_percent=5.0)
        fill_missing_amounts(items, printed_total=REAL_SUBTOTAL)
        assert all(i.is_estimated_amount for i in items)

    def test_billed_quantity_is_used_not_billed_plus_free(self):
        # Row 1 is 2.75 billed + 0.25 free. Only the billed part is charged,
        # which is precisely what makes the total reconcile.
        items = rows(REAL_ROWS, gst_percent=5.0)
        fill_missing_amounts(items, printed_total=REAL_SUBTOTAL)
        assert items[0].amount == pytest.approx(550.06, abs=0.01)


class TestRefusals:
    def test_no_total_means_no_derivation(self):
        items = rows(REAL_ROWS)
        assert fill_missing_amounts(items, printed_total=None)["filled"] == 0

    def test_total_matching_nothing_derives_nothing(self):
        # A blank the review screen flags beats a confidently wrong number.
        items = rows(REAL_ROWS, gst_percent=5.0)
        assert fill_missing_amounts(items, printed_total=9999.99)["filled"] == 0

    def test_one_unusable_row_blocks_the_whole_invoice(self):
        # The sum cannot be compared against a total that includes a row the
        # sum omits - it would reject a correct formula, or match a wrong one
        # whose error happens to fill the gap.
        items = rows(REAL_ROWS, gst_percent=5.0)
        items[3].rate = None
        assert fill_missing_amounts(items, printed_total=REAL_SUBTOTAL)["filled"] == 0

    def test_zero_and_negative_totals_are_ignored(self):
        items = rows(REAL_ROWS)
        assert infer_amount_formula_from_total(items, 0) is None
        assert infer_amount_formula_from_total(items, -100) is None

    def test_no_rows_at_all(self):
        assert infer_amount_formula_from_total([], 100.0) is None


class TestEvidencePreference:
    def test_row_evidence_wins_over_the_total(self):
        # Several rows agreeing independently is stronger than one equation
        # over the whole invoice.
        items = rows([(2, 100.0), (3, 100.0), (4, 100.0)], gst_percent=10.0)
        items[0].amount = 220.0   # qty x rate + gst
        items[1].amount = 330.0
        result = fill_missing_amounts(items, printed_total=900.0)

        assert result["evidence"] == "printed row amounts"
        assert items[2].amount == pytest.approx(440.0, abs=0.01)

    def test_total_used_only_when_no_row_has_an_amount(self):
        items = rows(REAL_ROWS, gst_percent=5.0)
        assert fill_missing_amounts(items, printed_total=REAL_SUBTOTAL)["evidence"] == (
            "printed invoice total"
        )

    def test_amounts_read_off_the_page_are_never_overwritten(self):
        items = rows(REAL_ROWS, gst_percent=5.0)
        items[0].amount = 1.11
        fill_missing_amounts(items, printed_total=REAL_SUBTOTAL)
        assert items[0].amount == 1.11


class TestFormulaSelection:
    def test_picks_a_tax_inclusive_formula_when_that_is_what_reconciles(self):
        # 2x100 + 3x100 = 500 pre-tax; a printed total of 550 says the line
        # amounts include 10% GST.
        items = rows([(2, 100.0), (3, 100.0)], gst_percent=10.0)
        formula = infer_amount_formula_from_total(items, 550.0)
        assert formula is not None and "gst" in formula.name

    def test_picks_a_discount_formula_when_that_is_what_reconciles(self):
        items = rows([(2, 100.0), (3, 100.0)], discount_percent=10.0)
        formula = infer_amount_formula_from_total(items, 450.0)
        assert formula is not None and "discount" in formula.name

    def test_prefers_the_simplest_among_equal_matches(self):
        # With zero discount and zero tax several formulas give the same sum;
        # the plainest one must win so no adjustment is invented.
        items = rows([(2, 100.0), (3, 100.0)])
        assert infer_amount_formula_from_total(items, 500.0).name == "qty x rate"

    def test_tolerance_absorbs_per_row_rounding(self):
        # Thirteen rows each rounded to paise contribute a few paise of drift.
        items = rows(REAL_ROWS, gst_percent=5.0)
        assert infer_amount_formula_from_total(items, REAL_SUBTOTAL + 0.30) is not None

    def test_tolerance_does_not_stretch_to_a_different_formula(self):
        items = rows(REAL_ROWS, gst_percent=5.0)
        assert infer_amount_formula_from_total(items, REAL_SUBTOTAL + 50) is None

    def test_a_tax_inclusive_total_selects_the_tax_inclusive_formula(self):
        # 5% GST on this invoice is ~187 rupees, far outside tolerance, so the
        # plain formula cannot claim it and the GST one must.
        items = rows(REAL_ROWS, gst_percent=5.0)
        formula = infer_amount_formula_from_total(items, round(REAL_SUBTOTAL * 1.05, 2))
        assert formula is not None and "gst" in formula.name
