"""Day-total entry: the aggregate a shop declares instead of billing through us.

Written before `services/sales/day_total.py`. Every figure here reaches GSTR-1
B2CS, so the arithmetic is pinned rather than trusted.

The shop enters what the till collected at each slab — a tax-inclusive figure —
and the taxable value is derived from it. That direction was settled
deliberately: it is what a day book and a POS Z-report actually show, and it
means the per-rate figures add up against the payment split without the staff
doing any arithmetic themselves.
"""

import pytest

from services.sales.day_total import DayTotalError, compute_day_total


def _blocks(*pairs):
    return [{"rate_bp": rate, "gross_paise": gross} for rate, gross in pairs]


def _pay(**kwargs):
    return [{"method": m, "amount_paise": a, "reference": None} for m, a in kwargs.items()]


class TestSingleSlab:
    def test_backs_taxable_and_tax_out_of_the_collected_figure(self):
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=_blocks((1200, 112000)),
            exempt_paise=0,
            nil_rated_paise=0,
            non_gst_paise=0,
            payments=_pay(cash=112000),
        )
        block = result["rate_blocks"][0]
        assert block["taxable_paise"] == 100000
        assert block["cgst_paise"] == 6000
        assert block["sgst_paise"] == 6000
        assert result["taxable_paise"] == 100000
        assert result["grand_total_paise"] == 112000
        assert result["round_off_paise"] == 0

    def test_the_customer_never_pays_more_than_was_collected(self):
        # The defining property of an inclusive figure.
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=_blocks((1200, 99999)),
            exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
            payments=_pay(cash=100000),
        )
        block = result["rate_blocks"][0]
        assert block["taxable_paise"] + block["cgst_paise"] + block["sgst_paise"] == 99999


class TestSeveralSlabs:
    def test_sums_each_slab_into_the_header(self):
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=_blocks((500, 105000), (1200, 112000)),
            exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
            payments=_pay(cash=217000),
        )
        assert result["taxable_paise"] == 100000 + 100000
        assert result["cgst_paise"] == 2500 + 6000
        assert result["sgst_paise"] == 2500 + 6000
        assert result["grand_total_paise"] == 217000

    def test_refuses_the_same_slab_twice(self):
        # Two rows at 12% is a data-entry mistake, and silently adding them
        # would hide it. The shop states each slab once.
        with pytest.raises(DayTotalError, match="12"):
            compute_day_total(
                sale_date="2026-09-10",
                rate_blocks=_blocks((1200, 10000), (1200, 20000)),
                exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
                payments=_pay(cash=30000),
            )

    def test_reconciles_the_blocks_to_the_header(self):
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=_blocks((500, 133337), (1200, 74321), (1800, 999)),
            exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
            payments=_pay(cash=208700),
        )
        from_blocks = sum(
            b["taxable_paise"] + b["cgst_paise"] + b["sgst_paise"]
            for b in result["rate_blocks"]
        )
        assert from_blocks == sum(b["gross_paise"] for b in result["rate_blocks"])
        assert result["taxable_paise"] == sum(b["taxable_paise"] for b in result["rate_blocks"])


class TestUntaxedBuckets:
    def test_exempt_nil_and_non_gst_carry_no_tax(self):
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=[],
            exempt_paise=50000, nil_rated_paise=25000, non_gst_paise=10000,
            payments=_pay(cash=85000),
        )
        assert result["taxable_paise"] == 0
        assert result["cgst_paise"] == 0
        assert result["sgst_paise"] == 0
        assert result["exempt_paise"] == 50000
        assert result["nil_rated_paise"] == 25000
        assert result["non_gst_paise"] == 10000
        assert result["grand_total_paise"] == 85000

    def test_they_stay_separate_from_each_other(self):
        # GSTR-1 Table 8 reports these in three different columns; collapsing
        # them into one figure would mis-state the table.
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=_blocks((500, 10500)),
            exempt_paise=1, nil_rated_paise=2, non_gst_paise=3,
            # 10500 + 6 rounds back down to 10500, so that is what was taken.
            payments=_pay(cash=10500),
        )
        assert (result["exempt_paise"], result["nil_rated_paise"], result["non_gst_paise"]) == (1, 2, 3)
        assert result["round_off_paise"] == -6


class TestRounding:
    def test_rounds_once_at_the_document(self):
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=_blocks((1200, 112051)),
            exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
            payments=_pay(cash=112100),
        )
        assert result["round_off_paise"] == 49
        assert result["grand_total_paise"] == 112100
        # The rounding must not have been folded into a taxable value.
        assert (
            result["taxable_paise"] + result["cgst_paise"] + result["sgst_paise"]
            + result["exempt_paise"] + result["nil_rated_paise"] + result["non_gst_paise"]
            + result["round_off_paise"]
        ) == result["grand_total_paise"]

    def test_always_lands_on_a_whole_rupee(self):
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=_blocks((500, 33337), (1200, 74329)),
            exempt_paise=111, nil_rated_paise=0, non_gst_paise=0,
            payments=_pay(cash=107800),
        )
        assert result["grand_total_paise"] % 100 == 0


class TestPayments:
    def test_refuses_a_split_that_does_not_add_up(self):
        with pytest.raises(DayTotalError, match="payment"):
            compute_day_total(
                sale_date="2026-09-10",
                rate_blocks=_blocks((1200, 112000)),
                exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
                payments=_pay(cash=100000),
            )

    def test_accepts_a_split_across_methods(self):
        result = compute_day_total(
            sale_date="2026-09-10",
            rate_blocks=_blocks((1200, 112000)),
            exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
            payments=_pay(cash=50000, upi=62000),
        )
        assert result["grand_total_paise"] == 112000

    def test_refuses_an_unknown_method(self):
        with pytest.raises(DayTotalError, match="method"):
            compute_day_total(
                sale_date="2026-09-10",
                rate_blocks=_blocks((1200, 112000)),
                exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
                payments=[{"method": "barter", "amount_paise": 112000, "reference": None}],
            )


class TestValidation:
    def test_refuses_a_day_with_nothing_in_it(self):
        with pytest.raises(DayTotalError, match="nothing"):
            compute_day_total(
                sale_date="2026-09-10", rate_blocks=[],
                exempt_paise=0, nil_rated_paise=0, non_gst_paise=0, payments=[],
            )

    def test_refuses_a_negative_amount(self):
        with pytest.raises(DayTotalError):
            compute_day_total(
                sale_date="2026-09-10", rate_blocks=_blocks((1200, -100)),
                exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
                payments=_pay(cash=-100),
            )

    def test_refuses_an_impossible_rate(self):
        with pytest.raises(DayTotalError, match="rate"):
            compute_day_total(
                sale_date="2026-09-10", rate_blocks=_blocks((10001, 100)),
                exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
                payments=_pay(cash=100),
            )

    def test_refuses_an_unreadable_date(self):
        with pytest.raises(DayTotalError, match="date"):
            compute_day_total(
                sale_date="10/09/26xx", rate_blocks=_blocks((1200, 112000)),
                exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
                payments=_pay(cash=112000),
            )

    def test_refuses_a_future_date(self):
        # A day total for a day that has not finished cannot be a day total.
        with pytest.raises(DayTotalError, match="future"):
            compute_day_total(
                sale_date="2099-01-01", rate_blocks=_blocks((1200, 112000)),
                exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
                payments=_pay(cash=112000),
            )


class TestProvenance:
    def test_records_the_period_and_that_the_rates_were_declared(self):
        result = compute_day_total(
            sale_date="2026-09-10", rate_blocks=_blocks((1200, 112000)),
            exempt_paise=0, nil_rated_paise=0, non_gst_paise=0,
            payments=_pay(cash=112000),
        )
        assert result["tax_period"] == "092026"
        # The slab came from the operator, not from a rate table resolved
        # against the date. Reporting has to be able to say so.
        assert result["rate_source"] == "declared"
