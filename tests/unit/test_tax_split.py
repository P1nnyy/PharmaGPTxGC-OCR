"""Splitting a combined tax figure into CGST/SGST/IGST.

Azure reports one TotalTax and never splits it. The reports show the halves
as separate columns, so an unsplit figure does not merely look odd - it reads
as a real breakdown that is wrong. Invoice A002245 came out as CGST 178.16
against a blank SGST, beside rows where the two matched.

The split is derived from GST law rather than guessed: equal halves for an
intra-state supply, all IGST for an inter-state one.
"""

import pytest

from extraction.normalizers.azure_invoice_normalizer import split_combined_tax

PUNJAB_SELLER = "03AADFM6639C1ZM"
PUNJAB_BUYER = "03AAJFR4013KIZE"
MAHARASHTRA = "27AAPFU0939F1ZV"


class TestIntraState:
    def test_splits_into_equal_halves(self):
        # The real A002245 figures: the invoice itself printed 89.08 / 89.08.
        assert split_combined_tax(178.16, PUNJAB_SELLER, PUNJAB_BUYER) == (89.08, 89.08, None)

    def test_the_halves_add_back_to_the_printed_total(self):
        for combined in (178.16, 101.01, 0.03, 5.55, 1234.57):
            cgst, sgst, igst = split_combined_tax(combined, PUNJAB_SELLER, PUNJAB_BUYER)
            assert igst is None
            # Dropping the odd paisa would make the breakdown disagree with
            # the total it came from.
            assert round(cgst + sgst, 2) == round(combined, 2)

    def test_an_odd_paisa_goes_to_one_side_rather_than_vanishing(self):
        cgst, sgst, _ = split_combined_tax(101.01, PUNJAB_SELLER, PUNJAB_BUYER)
        assert {cgst, sgst} == {50.51, 50.50}

    def test_zero_tax_stays_zero_on_both_halves(self):
        assert split_combined_tax(0.0, PUNJAB_SELLER, PUNJAB_BUYER) == (0.0, 0.0, None)


class TestInterState:
    def test_the_whole_amount_is_igst(self):
        # The case the old code got backwards: it booked inter-state tax as
        # cgst, which is wrong twice over - wrong field, and implying a split
        # that does not exist.
        assert split_combined_tax(100.0, PUNJAB_SELLER, MAHARASHTRA) == (None, None, 100.0)

    def test_nothing_lands_on_the_intra_state_fields(self):
        cgst, sgst, igst = split_combined_tax(250.0, MAHARASHTRA, PUNJAB_BUYER)
        assert cgst is None and sgst is None and igst == 250.0


class TestUnknownSupplyType:
    @pytest.mark.parametrize("seller,buyer", [
        (None, PUNJAB_BUYER),
        (PUNJAB_SELLER, None),
        (None, None),
        ("", ""),
        ("garbage", PUNJAB_BUYER),
    ])
    def test_an_unreadable_gstin_leaves_the_figure_unsplit(self, seller, buyer):
        # Inventing a split here would be worse than admitting we cannot tell:
        # the total stays right and nothing is fabricated.
        cgst, sgst, igst = split_combined_tax(90.0, seller, buyer)
        assert (cgst, sgst, igst) == (90.0, None, None)


class TestNoTax:
    def test_no_combined_figure_yields_nothing(self):
        assert split_combined_tax(None, PUNJAB_SELLER, PUNJAB_BUYER) == (None, None, None)
