"""Mapping a photographed counter bill into the Sale schema.

The bill is a source document: we read what it says rather than recomputing it
from assumptions. The one thing a retail bill does not state outright is
whether its line amounts already contain the tax, and that single question
moves every figure — so it is *derived from the document itself* by testing
both readings against the totals the bill printed, rather than assumed.

When neither reading reconciles, the mapping says so and the record stays a
draft. Nothing reaches a return without a person confirming it.
"""

import pytest

from services.sales.from_image import PricingBasis, map_sale_from_extraction


def bill(**overrides) -> dict:
    base = {
        "invoice_number": "S-1001",
        "invoice_date": "2026-09-10",
        "line_items": [],
        "subtotal": None,
        "cgst": None,
        "sgst": None,
        "grand_total": None,
        "roundoff": None,
    }
    base.update(overrides)
    return base


def line(amount, gst_percent, name="ITEM"):
    return {"name": name, "amount": amount, "gst_percent": gst_percent}


class TestInclusiveBill:
    def test_reads_amounts_as_tax_inclusive_when_that_is_what_reconciles(self):
        # 112.00 at 12% inclusive is 100.00 taxable + 12.00 tax, and the
        # footer agrees. Nothing is assumed: the footer picked the reading.
        result = map_sale_from_extraction(
            bill(
                line_items=[line(112.00, 12.0)],
                subtotal=100.00, cgst=6.00, sgst=6.00, grand_total=112.00,
            )
        )
        assert result["pricing_basis"] == PricingBasis.INCLUSIVE
        assert result["taxable_paise"] == 10000
        assert result["cgst_paise"] == 600
        assert result["sgst_paise"] == 600
        assert result["grand_total_paise"] == 11200
        assert result["reconciliation"]["reconciles"] is True


class TestExclusiveBill:
    def test_reads_amounts_as_tax_exclusive_when_that_is_what_reconciles(self):
        # The same rate, but here the line amount is the taxable value and the
        # footer adds tax on top.
        result = map_sale_from_extraction(
            bill(
                line_items=[line(100.00, 12.0)],
                subtotal=100.00, cgst=6.00, sgst=6.00, grand_total=112.00,
            )
        )
        assert result["pricing_basis"] == PricingBasis.EXCLUSIVE
        assert result["taxable_paise"] == 10000
        assert result["grand_total_paise"] == 11200
        assert result["reconciliation"]["reconciles"] is True


class TestSeveralRates:
    def test_groups_lines_into_one_block_per_rate(self):
        result = map_sale_from_extraction(
            bill(
                line_items=[line(105.00, 5.0), line(112.00, 12.0), line(210.00, 5.0)],
                subtotal=400.00, cgst=13.50, sgst=13.50, grand_total=427.00,
            )
        )
        rates = [b["rate_bp"] for b in result["rate_blocks"]]
        assert rates == [500, 1200]
        five = next(b for b in result["rate_blocks"] if b["rate_bp"] == 500)
        assert five["gross_paise"] == 31500

    def test_the_blocks_add_back_to_the_header(self):
        result = map_sale_from_extraction(
            bill(
                line_items=[line(105.00, 5.0), line(112.00, 12.0)],
                subtotal=200.00, cgst=8.50, sgst=8.50, grand_total=217.00,
            )
        )
        assert result["taxable_paise"] == sum(b["taxable_paise"] for b in result["rate_blocks"])
        assert result["cgst_paise"] == sum(b["cgst_paise"] for b in result["rate_blocks"])


class TestDisagreement:
    def test_flags_a_footer_that_does_not_match_the_lines(self):
        # The reviewer has to see this. Absorbing it would put a figure on a
        # return that neither the lines nor the footer support.
        result = map_sale_from_extraction(
            bill(
                line_items=[line(112.00, 12.0)],
                subtotal=100.00, cgst=6.00, sgst=6.00, grand_total=999.00,
            )
        )
        assert result["reconciliation"]["reconciles"] is False
        assert result["reconciliation"]["differences"]

    def test_says_the_basis_is_unresolved_when_neither_reading_fits(self):
        result = map_sale_from_extraction(
            bill(
                line_items=[line(112.00, 12.0)],
                subtotal=57.00, cgst=1.00, sgst=1.00, grand_total=59.00,
            )
        )
        assert result["pricing_basis"] == PricingBasis.UNRESOLVED
        assert result["reconciliation"]["reconciles"] is False


class TestNoFooter:
    def test_a_bill_with_no_printed_totals_cannot_pick_a_basis(self):
        # Without a footer there is nothing to test a reading against, so the
        # mapping refuses to choose rather than defaulting to one.
        result = map_sale_from_extraction(bill(line_items=[line(112.00, 12.0)]))
        assert result["pricing_basis"] == PricingBasis.UNRESOLVED
        assert result["reconciliation"]["reconciles"] is False
        assert any("total" in d.lower() for d in result["reconciliation"]["differences"])


class TestZeroRatedLines:
    def test_a_zero_percent_line_is_its_own_block_not_an_exempt_total(self):
        # A bill cannot tell exempt from nil-rated from non-GST — they all
        # print as no tax. Guessing would mis-state GSTR-1 Table 8, so the
        # split is left for the reviewer.
        result = map_sale_from_extraction(
            bill(
                line_items=[line(50.00, 0.0), line(112.00, 12.0)],
                subtotal=150.00, cgst=6.00, sgst=6.00, grand_total=162.00,
            )
        )
        assert 0 in [b["rate_bp"] for b in result["rate_blocks"]]
        assert result["exempt_paise"] == 0
        assert result["nil_rated_paise"] == 0
        assert any("exempt" in n.lower() for n in result["review_notes"])


class TestProvenance:
    def test_records_where_the_figures_came_from(self):
        result = map_sale_from_extraction(
            bill(line_items=[line(112.00, 12.0)], subtotal=100.00, cgst=6.00, sgst=6.00, grand_total=112.00)
        )
        assert result["rate_source"] == "extracted"
        assert result["bill_number"] == "S-1001"
        assert result["tax_period"] == "092026"


class TestUnusableInput:
    def test_refuses_a_bill_with_no_readable_date(self):
        from services.sales.from_image import SaleMappingError

        with pytest.raises(SaleMappingError, match="date"):
            map_sale_from_extraction(bill(invoice_date=None, line_items=[line(112.00, 12.0)]))

    def test_refuses_a_bill_with_no_lines_and_no_totals(self):
        from services.sales.from_image import SaleMappingError

        with pytest.raises(SaleMappingError):
            map_sale_from_extraction(bill(line_items=[]))
