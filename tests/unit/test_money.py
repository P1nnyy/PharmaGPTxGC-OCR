"""Integer-paise arithmetic.

Written before `core/money.py`, per the house rule on anything computing a tax
figure. These figures end up in a GST return, so every rounding decision here
is pinned by a test rather than left to whatever `round()` happened to do.

The expectations deliberately mirror `frontend/src/features/sell/money.ts` and
`totals.ts`: a day-total entered for a date and a counter bill issued on the
same date must not disagree about what 12% of a figure is.
"""

import pytest

from core.money import (
    BP_DENOMINATOR,
    apply_ratio,
    halve_tax,
    parse_rupees_to_paise,
    paise_to_rupees,
    round_to_rupee,
    split_inclusive,
    tax_on_exclusive,
)


class TestApplyRatio:
    def test_scales_exactly_when_it_divides(self):
        assert apply_ratio(20000, 1200, BP_DENOMINATOR) == 2400

    def test_rounds_half_up_on_the_magnitude(self):
        # 12345 * 5% = 617.25 -> 617
        assert apply_ratio(12345, 500, BP_DENOMINATOR) == 617
        # A clean .5 goes up, not to even.
        assert apply_ratio(1000, 5000, BP_DENOMINATOR) == 500
        assert apply_ratio(50, 5000, BP_DENOMINATOR) == 25
        assert apply_ratio(30, 5000, BP_DENOMINATOR) == 15

    def test_rounds_a_negative_away_from_zero_symmetrically(self):
        # A credit note must be the exact mirror of the bill it reverses.
        assert apply_ratio(-12345, 500, BP_DENOMINATOR) == -617

    def test_refuses_a_zero_denominator(self):
        with pytest.raises(ValueError):
            apply_ratio(100, 1, 0)


class TestSplitInclusive:
    def test_backs_the_taxable_value_out_of_a_tax_inclusive_figure(self):
        taxable, tax = split_inclusive(11200, 1200)
        assert (taxable, tax) == (10000, 1200)

    def test_the_parts_always_add_back_to_the_gross(self):
        # The property that matters: the customer paid the gross, so no
        # rounding may create or destroy a paisa.
        for gross in (1, 99, 100, 4999, 29997, 123456, 999999):
            for rate_bp in (0, 500, 1200, 1800, 2800):
                taxable, tax = split_inclusive(gross, rate_bp)
                assert taxable + tax == gross

    def test_a_gross_that_does_not_divide_cleanly(self):
        # 29997 at 12%: 29997 * 10000/11200 = 26783.03...
        assert split_inclusive(29997, 1200) == (26783, 3214)

    def test_a_zero_rate_is_all_taxable_and_no_tax(self):
        assert split_inclusive(50000, 0) == (50000, 0)

    def test_zero_gross_is_zero_both_ways(self):
        assert split_inclusive(0, 1200) == (0, 0)

    def test_refuses_a_negative_rate(self):
        with pytest.raises(ValueError):
            split_inclusive(1000, -1)


class TestTaxOnExclusive:
    def test_adds_tax_on_top(self):
        assert tax_on_exclusive(20000, 1200) == 2400

    def test_rounds_half_up(self):
        assert tax_on_exclusive(12345, 500) == 617


class TestHalveTax:
    def test_splits_an_even_figure_evenly(self):
        assert halve_tax(2400) == (1200, 1200)

    def test_gives_the_odd_paisa_to_sgst(self):
        # Matches frontend taxSplit.ts and totals.ts, so a sale reviewed by
        # hand and one computed here break the same way.
        assert halve_tax(617) == (308, 309)

    def test_the_halves_always_add_back(self):
        for tax in range(0, 500):
            cgst, sgst = halve_tax(tax)
            assert cgst + sgst == tax
            assert sgst - cgst in (0, 1)


class TestRoundToRupee:
    def test_rounds_up_past_the_half(self):
        assert round_to_rupee(12962) == (13000, 38)

    def test_rounds_down_below_the_half(self):
        assert round_to_rupee(12930) == (12900, -30)

    def test_a_clean_rupee_needs_no_adjustment(self):
        assert round_to_rupee(43600) == (43600, 0)

    def test_the_adjustment_always_closes_the_gap(self):
        for value in range(0, 1000):
            rounded, adjustment = round_to_rupee(value)
            assert rounded == value + adjustment
            assert rounded % 100 == 0
            assert abs(adjustment) <= 50


class TestParseRupeesToPaise:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("100", 10000),
            ("100.5", 10050),
            ("100.50", 10050),
            ("1,234.56", 123456),
            ("₹ 1,234.56", 123456),
            ("0", 0),
            ("0.01", 1),
            ("-12.34", -1234),
        ],
    )
    def test_reads_money(self, text, expected):
        assert parse_rupees_to_paise(text) == expected

    @pytest.mark.parametrize("text", ["12abc", "", "  ", "1.234", ".", "-", "abc", None])
    def test_refuses_anything_it_cannot_read_exactly(self, text):
        # Never coerce: float("12abc") raising is the good case, but
        # int(float("12.999")) silently losing a paisa is the dangerous one.
        assert parse_rupees_to_paise(text) is None

    def test_accepts_an_integer_or_float_as_given(self):
        assert parse_rupees_to_paise(100) == 10000
        assert parse_rupees_to_paise(100.5) == 10050


class TestPaiseToRupees:
    def test_converts_only_at_the_boundary(self):
        assert paise_to_rupees(123456) == 1234.56
        assert paise_to_rupees(0) == 0.0
        assert paise_to_rupees(None) is None
