"""Free-quantity shortfall detection.

Figures are from S.G. Pharma invoice CHEQ001391, where 2.75 + 0.2 = 2.95
packs - a quantity no distributor ships - while the line above it reads
5.50 + 0.50 = 6.00 correctly.

The refusals matter more than the catch. This proposes a change to a stock
quantity, so firing when nothing is wrong is worse than staying quiet: it
trains people to click past it.
"""

import pytest

from extraction.normalizers.quantity_check import (
    MAX_CORRECTION,
    check_free_quantity,
    check_line_items,
)

# The real invoice.
BETADINE = {"quantity": 2.0, "free_quantity": None, "rate": 189.0, "amount": 378.0}
AUGMENTIN = {"quantity": 5.5, "free_quantity": 0.5, "rate": 148.87, "amount": 818.79}
DIAPRIDE = {"quantity": 2.75, "free_quantity": 0.2, "rate": 120.0, "amount": 330.0}


class TestTheRealInvoice:
    def test_flags_the_short_row(self):
        s = check_free_quantity(DIAPRIDE)
        assert s is not None
        assert s.current == 0.2
        assert s.suggested == 0.25
        assert s.total_before == 2.95
        assert s.total_after == 3.0

    def test_reason_states_the_arithmetic(self):
        # The reviewer should be able to check the claim, not just trust it.
        s = check_free_quantity(DIAPRIDE)
        assert "2.95" in s.reason and "3" in s.reason

    def test_notes_that_the_billed_figure_is_money_confirmed(self):
        # 330 / 120 = 2.75 exactly, which is what rules the billed quantity
        # out as the source of the shortfall.
        s = check_free_quantity(DIAPRIDE)
        assert s.billed_verified

    def test_leaves_the_correct_row_alone(self):
        assert check_free_quantity(AUGMENTIN) is None

    def test_leaves_a_row_with_no_free_goods_alone(self):
        assert check_free_quantity(BETADINE) is None

    def test_across_the_invoice_only_one_row_is_flagged(self):
        found = check_line_items([BETADINE, AUGMENTIN, DIAPRIDE])
        assert list(found) == [2]


class TestRefusals:
    def test_silent_when_the_total_is_already_whole(self):
        assert check_free_quantity({"quantity": 9.0, "free_quantity": 1.0}) is None

    def test_silent_when_no_free_quantity_is_stated(self):
        # A blank free column is the normal case, not a defect.
        assert check_free_quantity({"quantity": 2.95, "free_quantity": None}) is None
        assert check_free_quantity({"quantity": 2.95, "free_quantity": 0}) is None

    def test_silent_when_the_correction_would_be_too_large(self):
        # 0.1 -> 0.9 is a different number, not a misread digit. Proposing it
        # would be inventing stock.
        assert check_free_quantity({"quantity": 2.1, "free_quantity": 0.1}) is None

    def test_correction_is_capped(self):
        # Just inside the cap fires, just outside does not.
        inside = check_free_quantity({"quantity": 3.0, "free_quantity": 0.95})
        outside = check_free_quantity({"quantity": 3.0, "free_quantity": 0.85})
        assert inside is not None and inside.suggested == 1.0
        assert outside is None
        assert MAX_CORRECTION == pytest.approx(0.1)

    def test_silent_when_the_money_disagrees_with_the_billed_quantity(self):
        # Something bigger is wrong with this row than a dropped digit;
        # adjusting the free column would paper over it.
        row = {"quantity": 2.75, "free_quantity": 0.2, "rate": 120.0, "amount": 999.0}
        assert check_free_quantity(row) is None

    def test_never_reduces_a_free_quantity(self):
        # Rounding DOWN would discard goods the invoice says arrived.
        row = {"quantity": 2.0, "free_quantity": 0.99}
        s = check_free_quantity(row)
        assert s is None or s.suggested > s.current


class TestWithoutMoney:
    def test_still_works_when_rate_and_amount_are_missing(self):
        # Plenty of rows have no readable amount; the check should still
        # help, just without the money corroboration.
        s = check_free_quantity({"quantity": 2.75, "free_quantity": 0.2})
        assert s is not None and s.suggested == 0.25
        assert not s.billed_verified

    def test_zero_rate_does_not_divide_by_zero(self):
        check_free_quantity({"quantity": 2.75, "free_quantity": 0.2, "rate": 0, "amount": 330.0})


class TestBadInput:
    @pytest.mark.parametrize("row", [
        {},
        {"quantity": None, "free_quantity": 0.2},
        {"quantity": "abc", "free_quantity": 0.2},
        {"quantity": 2.75, "free_quantity": "x"},
    ])
    def test_unusable_rows_are_skipped_not_raised(self, row):
        assert check_free_quantity(row) is None

    def test_float_noise_does_not_trigger_a_suggestion(self):
        # 2.75 + 0.25 lands on 3.0000000000000004 in binary floating point.
        assert check_free_quantity({"quantity": 2.75, "free_quantity": 0.25}) is None
