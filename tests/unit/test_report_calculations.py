from datetime import date

import pytest

from services.reports import calculations as calc


class TestUnitsAndLandedCost:
    def test_free_goods_count_as_units_received(self):
        assert calc.units_received(10, 1) == 11

    def test_missing_free_quantity_is_treated_as_none_given(self):
        assert calc.units_received(10, None) == 10

    def test_missing_quantity_gives_none_not_zero(self):
        assert calc.units_received(None, 1) is None

    def test_effective_unit_cost_spreads_payment_over_free_goods(self):
        """A 10+1 scheme at rate 100 with a 50 discount: 950 paid for 11 units."""
        assert calc.effective_unit_cost(950, 10, 1) == pytest.approx(86.3636, abs=1e-4)

    def test_effective_unit_cost_without_scheme_is_just_the_net_rate(self):
        assert calc.effective_unit_cost(1000, 10, 0) == 100.0

    def test_effective_unit_cost_is_none_when_nothing_was_received(self):
        assert calc.effective_unit_cost(950, 0, 0) is None

    def test_effective_unit_cost_is_none_when_amount_missing(self):
        assert calc.effective_unit_cost(None, 10, 1) is None


class TestEffectiveDiscount:
    def test_folds_scheme_goods_and_rupee_discount_into_one_rate(self):
        """11 units at list 100 is 1100; paying 950 is a 13.6% effective benefit."""
        assert calc.effective_discount_rate(950, 10, 1, 100) == pytest.approx(0.1364, abs=1e-4)

    def test_a_pure_scheme_still_registers_as_a_discount(self):
        """Paying full rate for 10 and getting 1 free is ~9% off per unit."""
        assert calc.effective_discount_rate(1000, 10, 1, 100) == pytest.approx(0.0909, abs=1e-4)

    def test_no_benefit_is_zero_not_none(self):
        assert calc.effective_discount_rate(1000, 10, 0, 100) == pytest.approx(0.0)

    def test_missing_rate_gives_none(self):
        assert calc.effective_discount_rate(950, 10, 1, None) is None


class TestMargin:
    def test_gst_is_netted_out_of_mrp_before_comparing_to_cost(self):
        """MRP 112 at 12% GST is a net 100 sale price; cost 80 is a 20% margin.
        Comparing 112 to 80 directly would report 28.6% - a 9-point overstatement."""
        assert calc.margin_at_purchase(112, 80, 12) == pytest.approx(0.20, abs=1e-4)

    def test_naive_comparison_would_have_overstated_it(self):
        netted = calc.margin_at_purchase(112, 80, 12)
        naive = (112 - 80) / 112
        assert naive > netted

    def test_margin_is_none_without_a_gst_rate(self):
        """A confidently wrong margin drives worse decisions than a blank one."""
        assert calc.margin_at_purchase(112, 80, None) is None

    def test_margin_can_be_negative_when_bought_above_net_mrp(self):
        assert calc.margin_at_purchase(105, 100, 5) == pytest.approx(0.0)
        assert calc.margin_at_purchase(105, 110, 5) < 0

    def test_net_of_gst_at_zero_rate_is_the_mrp(self):
        assert calc.net_of_gst(100, 0) == 100.0


class TestExpiryBuckets:
    AS_OF = date(2026, 8, 5)

    @pytest.mark.parametrize(
        "expiry,expected_days",
        [("2026-08-05", 0), ("2026-09-04", 30), ("2026-08-04", -1)],
    )
    def test_days_until_expiry(self, expiry, expected_days):
        assert calc.days_until_expiry(expiry, self.AS_OF) == expected_days

    def test_unparseable_expiry_gives_none(self):
        assert calc.days_until_expiry("08/26", self.AS_OF) is None
        assert calc.days_until_expiry(None, self.AS_OF) is None

    @pytest.mark.parametrize(
        "days,bucket",
        [
            (-1, "expired"),
            (0, "0_30"),
            (30, "0_30"),
            (31, "31_60"),
            (60, "31_60"),
            (61, "61_90"),
            (90, "61_90"),
            (91, "91_180"),
            (180, "91_180"),
            (181, "beyond_180"),
            (5000, "beyond_180"),
        ],
    )
    def test_bucket_boundaries(self, days, bucket):
        assert calc.expiry_bucket(days) == bucket

    def test_expiring_today_is_not_yet_expired(self):
        """Stock is good through its expiry date, so day zero is still saleable."""
        assert calc.expiry_bucket(0) == "0_30"

    def test_unknown_days_gives_no_bucket(self):
        assert calc.expiry_bucket(None) is None


class TestTaxHandling:
    def test_tax_total_sums_stated_components(self):
        assert calc.tax_total(50, 50, None) == 100.0

    def test_tax_total_is_none_when_nothing_was_captured(self):
        """Distinct from a genuine zero-rated invoice: nothing was read at all."""
        assert calc.tax_total(None, None, None) is None

    def test_an_explicit_zero_is_not_missing(self):
        assert calc.tax_total(0, 0, 0) == 0.0

    @pytest.mark.parametrize(
        "cgst,sgst,igst,expected",
        [
            (50, 50, None, "intra_state"),
            (None, None, 100, "inter_state"),
            (50, 50, 10, "mixed"),
            (None, None, None, None),
        ],
    )
    def test_supply_type_is_read_not_inferred(self, cgst, sgst, igst, expected):
        assert calc.supply_type(cgst, sgst, igst) == expected

    def test_an_inter_state_invoice_is_never_reported_as_intra_state(self):
        """The bug this replaces split unknown tax 50/50 into CGST/SGST, which
        invents two taxes that appear nowhere on an IGST invoice."""
        assert calc.supply_type(None, None, 100) == "inter_state"


class TestArithmeticCheck:
    def test_a_consistent_invoice_passes(self):
        check = calc.check_invoice_arithmetic(
            line_total=1000, discount=50, cgst=57, sgst=57, igst=None,
            roundoff=-0.4, grand_total=1063.6,
        )
        assert check.is_consistent is True
        assert check.delta == pytest.approx(0.0)

    def test_a_mismatch_is_flagged_with_its_size(self):
        check = calc.check_invoice_arithmetic(
            line_total=1000, discount=0, cgst=0, sgst=0, igst=0,
            roundoff=0, grand_total=1500,
        )
        assert check.is_consistent is False
        assert check.delta == 500.0

    def test_small_rounding_differences_are_tolerated(self):
        check = calc.check_invoice_arithmetic(
            line_total=1000, discount=0, cgst=0, sgst=0, igst=0,
            roundoff=None, grand_total=1000.6,
        )
        assert check.is_consistent is True

    def test_unverifiable_invoice_reports_none_not_false(self):
        """No line total means the check could not run - not that it failed."""
        check = calc.check_invoice_arithmetic(
            line_total=None, discount=None, cgst=None, sgst=None, igst=None,
            roundoff=None, grand_total=1000,
        )
        assert check.is_consistent is None


class TestShareOf:
    def test_computes_a_fraction(self):
        assert calc.share_of(25, 100) == 0.25

    def test_empty_total_gives_none_rather_than_dividing_by_zero(self):
        assert calc.share_of(25, 0) is None
        assert calc.share_of(25, None) is None
