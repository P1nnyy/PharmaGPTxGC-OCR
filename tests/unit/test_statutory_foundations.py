"""The pieces the statutory report pack is built on.

Three things are pinned here, each because getting it wrong puts a wrong figure
on a filed return: the boundary that reads legacy float money into paise, the
catalogue that decides which GSTR-3B row a reversal lands in, and the rule that
a figure carries its own provenance.
"""

import pytest

from core.itc_rules import (
    TABLE_PERMANENT,
    TABLE_RECLAIM,
    TABLE_TEMPORARY,
    ItcRuleError,
    ReversalTrigger,
    describe,
    gstr3b_table,
    is_permanent,
    is_reclaimable,
    reason,
    statutory_reference,
)
from core.money import paise_from_legacy_rupees, parse_rupees_to_paise
from services.statutory.itc_sources import (
    EXCLUSION_NO_GSTIN,
    EXCLUSION_NO_TAX,
    SOURCE_PURCHASE_REGISTER,
    Gstr2bSource,
    PurchaseRegisterSource,
    default_source,
)
from services.statutory.model import CrossCheck, Drill, DrillKind, Figure, figure, total


class TestLegacyMoneyBoundary:
    def test_reads_an_ordinary_stored_amount(self):
        assert paise_from_legacy_rupees(1234.56) == 123456

    def test_absorbs_the_residue_a_float_leaves(self):
        # The purchase side stores rupees as floats. 1234.56 comes back out of
        # arithmetic as 1234.5600000000001, and refusing that would refuse a
        # real invoice.
        assert paise_from_legacy_rupees(1234.5600000000001) == 123456
        assert paise_from_legacy_rupees(0.1 + 0.2) == 30

    def test_the_strict_parser_still_refuses_what_this_one_accepts(self):
        # They read different things: one reads what a person typed, where a
        # third decimal is a typo; this one reads what is already stored.
        assert parse_rupees_to_paise(1234.5600000000001) is None
        assert paise_from_legacy_rupees(1234.5600000000001) == 123456

    def test_rounds_half_away_from_zero_on_both_signs(self):
        assert paise_from_legacy_rupees(1.005) == 101
        assert paise_from_legacy_rupees(-1.005) == -101

    def test_an_integer_is_whole_rupees(self):
        assert paise_from_legacy_rupees(100) == 10000

    def test_nothing_stays_nothing(self):
        assert paise_from_legacy_rupees(None) is None
        assert paise_from_legacy_rupees(True) is None
        assert paise_from_legacy_rupees("not money") is None


class TestReversalRules:
    def test_expired_stock_is_a_permanent_reversal(self):
        # The pharmacy's usual case, and it is not reclaimable - the goods are
        # destroyed and the credit on them was never earned.
        assert gstr3b_table(ReversalTrigger.EXPIRED_STOCK) == TABLE_PERMANENT
        assert statutory_reference(ReversalTrigger.EXPIRED_STOCK) == "Section 17(5)(h)"
        assert is_permanent(ReversalTrigger.EXPIRED_STOCK)
        assert not is_reclaimable(ReversalTrigger.EXPIRED_STOCK)

    def test_non_payment_is_temporary_and_reclaimable(self):
        assert gstr3b_table(ReversalTrigger.NON_PAYMENT_180_DAYS) == TABLE_TEMPORARY
        assert is_reclaimable(ReversalTrigger.NON_PAYMENT_180_DAYS)
        assert not is_permanent(ReversalTrigger.NON_PAYMENT_180_DAYS)

    def test_a_reclaim_lands_in_its_own_table(self):
        assert gstr3b_table(ReversalTrigger.RECLAIM) == TABLE_RECLAIM

    def test_the_exempt_proportion_rule_is_permanent(self):
        # Rule 42 matters for a pharmacy now that life-saving drugs are nil
        # rated: a shop selling both cannot claim the whole of its credit.
        assert statutory_reference(ReversalTrigger.EXEMPT_SUPPLY_PROPORTION) == "Rule 42"
        assert is_permanent(ReversalTrigger.EXEMPT_SUPPLY_PROPORTION)

    def test_every_trigger_has_a_rule_a_reference_and_a_reason(self):
        for trigger in ReversalTrigger.ALL:
            described = describe(trigger)
            assert described["statutory_reference"]
            assert described["gstr3b_table"] in {TABLE_PERMANENT, TABLE_TEMPORARY, TABLE_RECLAIM}
            assert len(reason(trigger)) > 20, f"{trigger} needs an explainable reason"

    def test_an_unclassified_trigger_is_refused(self):
        # There is no rule to cite and no table to report it in, so it cannot
        # be recorded at all.
        with pytest.raises(ItcRuleError):
            gstr3b_table("SOMETHING_ELSE")
        with pytest.raises(ItcRuleError):
            describe(None)


class TestFigure:
    def test_carries_its_own_drill(self):
        f = figure(123456, DrillKind.SALES, count=4, period="092026")
        assert f.to_dict()["value"] == 1234.56
        assert f.to_dict()["drill"] == {
            "kind": "SALES", "filters": {"period": "092026"}, "count": 4
        }

    def test_a_figure_without_a_drill_says_so(self):
        assert Figure(100).to_dict()["drill"] is None

    def test_adding_keeps_the_caveat(self):
        # The sum of a certain figure and an uncertain one is uncertain, and
        # the doubt has to survive into the total somebody files.
        certain = Figure(100)
        doubtful = Figure(200, caveat="Provisional")
        assert (certain + doubtful).paise == 300
        assert (certain + doubtful).caveat == "Provisional"

    def test_adding_drops_the_drill_rather_than_guessing(self):
        # Two different drills do not compose into one, and a wrong drill is
        # worse than none.
        a = figure(100, DrillKind.SALES, period="092026")
        b = figure(200, DrillKind.PURCHASES, period="092026")
        assert (a + b).drill is None

    def test_a_repeated_caveat_is_not_repeated_in_the_total(self):
        a = Figure(100, caveat="Provisional")
        b = Figure(200, caveat="Provisional")
        assert (a + b).caveat == "Provisional"

    def test_an_empty_total_is_zero_not_nothing(self):
        assert total([]).paise == 0


class TestCrossCheck:
    def _check(self, left, right, tolerance=0):
        return CrossCheck(
            code="X", label="test", left_label="l", right_label="r",
            left=Figure(left), right=Figure(right), tolerance_paise=tolerance,
        )

    def test_agrees_when_identical(self):
        assert self._check(1000, 1000).agrees

    def test_reports_the_difference_and_its_direction(self):
        assert self._check(1000, 900).difference_paise == 100
        assert self._check(900, 1000).difference_paise == -100

    def test_a_difference_either_way_is_within_tolerance(self):
        assert self._check(1000, 900, tolerance=100).agrees
        assert self._check(900, 1000, tolerance=100).agrees
        assert not self._check(1000, 899, tolerance=100).agrees


class TestPurchaseRegisterItcSource:
    def invoice(self, **kwargs):
        # As `statutory_repository` hands it over: already integer paise.
        base = {
            "invoice_id": "I1", "invoice_number": "INV-1",
            "seller_gstin": "27BBBBB0000B1Z5",
            "cgst_paise": 30000, "sgst_paise": 30000, "igst_paise": 0,
        }
        base.update(kwargs)
        return base

    def test_sums_eligible_tax_into_paise(self):
        claim = PurchaseRegisterSource().claim_for(
            ["092026"], [self.invoice(), self.invoice(invoice_id="I2")]
        )
        assert claim.cgst.paise == 60000
        assert claim.sgst.paise == 60000
        assert claim.total_paise == 120000
        assert claim.counted_invoices == 2

    def test_an_invoice_without_a_supplier_gstin_earns_no_credit(self):
        claim = PurchaseRegisterSource().claim_for(
            ["092026"], [self.invoice(seller_gstin=None)]
        )
        assert claim.total_paise == 0
        assert claim.counted_invoices == 0
        assert claim.excluded[0]["reason"] == EXCLUSION_NO_GSTIN
        # The excluded tax is reported, because "we left ₹600 out" is the
        # number somebody acts on.
        assert claim.excluded[0]["tax_paise"] == 60000

    def test_an_invoice_with_no_tax_is_excluded_separately(self):
        claim = PurchaseRegisterSource().claim_for(
            ["092026"], [self.invoice(cgst_paise=0, sgst_paise=0, igst_paise=0)]
        )
        assert claim.excluded[0]["reason"] == EXCLUSION_NO_TAX

    def test_is_never_authoritative_and_says_why(self):
        # Since October 2022 the claimable figure is capped by GSTR-2B, so the
        # purchase register is an upper bound and usually wrong.
        claim = PurchaseRegisterSource().claim_for(["092026"], [self.invoice()])
        assert claim.is_authoritative is False
        assert claim.source_name == SOURCE_PURCHASE_REGISTER
        assert any("GSTR-2B" in c for c in claim.caveats)
        assert claim.cgst.caveat and "Provisional" in claim.cgst.caveat

    def test_every_figure_drills_back_to_the_purchases(self):
        claim = PurchaseRegisterSource().claim_for(["092026"], [self.invoice()])
        drill = claim.cgst.drill
        assert drill.kind == DrillKind.PURCHASES
        assert drill.filters["periods"] == ["092026"]
        assert drill.count == 1

    def test_an_empty_period_claims_nothing_without_erroring(self):
        claim = PurchaseRegisterSource().claim_for(["092026"], [])
        assert claim.total_paise == 0

    def test_the_default_source_is_the_purchase_register_for_now(self):
        assert default_source().name == SOURCE_PURCHASE_REGISTER


class TestGstr2bSource:
    def test_refuses_rather_than_claiming_nothing(self):
        # A source that silently answered "nil" would file a return claiming
        # no credit at all.
        with pytest.raises(NotImplementedError):
            Gstr2bSource().claim_for(["092026"])
