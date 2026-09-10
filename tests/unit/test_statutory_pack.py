"""The seven reports, over the synthetic September the GSTR-1 tests pin.

Reusing that month is deliberate: its figures are already asserted to the paise
in `test_gstr1_synthetic_month.py`, so anything here that disagrees with them
is this pack's bug and not a new fixture's.

The last class is the one that matters most. "Every figure must be traceable"
is the headline requirement, and a requirement that is only ever checked by
eye stops being true the first time somebody adds a column. So it is asserted
structurally: walk the whole pack, find every figure, and fail if one of them
cannot say where it came from.
"""

import pytest

from core.itc_rules import TABLE_PERMANENT, TABLE_RECLAIM, TABLE_TEMPORARY
from services.gstr1.periods import resolve_filing_period
from services.statutory import pack
from services.statutory.gstr3b import AUTO_POPULATED_WARNING
from services.statutory.hsn import UQC_MISSING, UQC_VALID
from tests.unit.test_gstr1_synthetic_month import IDENTITY, PERIOD

# Rebuilt here rather than imported as a fixture, because the pack needs the
# documents as a plain list several times over.
from tests.unit.test_gstr1_synthetic_month import september as _september_fixture


@pytest.fixture
def documents():
    return _september_fixture.__wrapped__()


@pytest.fixture
def purchases():
    return [
        {"invoice_id": "P1", "invoice_number": "SUP-001", "invoice_date": "2026-09-03",
         "seller_name": "Distributor A", "seller_gstin": "27CCCCC0000C1Z5",
         "status": "verified", "taxable_paise": 1000000, "discount_paise": 0,
         "cgst_paise": 60000, "sgst_paise": 60000, "igst_paise": 0,
         "roundoff_paise": 0, "grand_total_paise": 1120000},
        # No supplier GSTIN: no credit, however clean the rest of it is.
        {"invoice_id": "P2", "invoice_number": "SUP-002", "invoice_date": "2026-09-10",
         "seller_name": "Cash Vendor", "seller_gstin": None, "status": "verified",
         "taxable_paise": 50000, "discount_paise": 0, "cgst_paise": 3000,
         "sgst_paise": 3000, "igst_paise": 0, "roundoff_paise": 0,
         "grand_total_paise": 56000},
    ]


@pytest.fixture
def reversals():
    return [
        {"id": "R1", "tax_period": "092026", "trigger": "EXPIRED_STOCK",
         "statutory_reference": "Section 17(5)(h)", "gstr3b_table": TABLE_PERMANENT,
         "reason": "Credit on goods written off.", "is_permanent": True,
         "cgst_paise": 1200, "sgst_paise": 1200, "igst_paise": 0, "cess_paise": 0,
         "total_paise": 2400, "source_type": "INVOICE", "source_id": "P1",
         "source_invoice_number": "SUP-001", "recorded_at": "2026-09-30T00:00:00Z"},
        {"id": "R2", "tax_period": "092026", "trigger": "NON_PAYMENT_180_DAYS",
         "statutory_reference": "Rule 37", "gstr3b_table": TABLE_TEMPORARY,
         "reason": "Supplier not paid within 180 days.", "is_permanent": False,
         "cgst_paise": 500, "sgst_paise": 500, "igst_paise": 0, "cess_paise": 0,
         "total_paise": 1000, "source_type": "INVOICE", "source_id": "P1",
         "source_invoice_number": "SUP-001", "recorded_at": "2026-09-30T00:00:00Z"},
    ]


@pytest.fixture
def reversal_totals():
    return {
        TABLE_PERMANENT: {"cgst_paise": 1200, "sgst_paise": 1200, "igst_paise": 0,
                          "cess_paise": 0, "total_paise": 2400, "reversal_ids": ["R1"]},
        TABLE_TEMPORARY: {"cgst_paise": 500, "sgst_paise": 500, "igst_paise": 0,
                          "cess_paise": 0, "total_paise": 1000, "reversal_ids": ["R2"]},
    }


@pytest.fixture
def payments():
    # D1's bill total is ₹1,320.00. Only bills with a split are compared.
    return [{"sale_id": "D1", "method": "cash", "amount_paise": 132000,
             "status": "CONFIRMED", "document_type": "INVOICE", "reference": None}]


@pytest.fixture
def hsn_lines():
    return [
        {"hsn": "3004", "gst_percent": 12.0, "pack": "10x10", "line_count": 3,
         "taxable_paise": 1000000, "quantity": 30.0, "invoice_ids": ["P1"]},
        {"hsn": "", "gst_percent": 5.0, "pack": "", "line_count": 1,
         "taxable_paise": 50000, "quantity": 2.0, "invoice_ids": ["P2"]},
    ]


@pytest.fixture
def built(documents, purchases, payments, hsn_lines, reversals, reversal_totals):
    return pack.build(
        IDENTITY,
        resolve_filing_period(PERIOD, "MONTHLY"),
        documents,
        payments,
        purchases,
        [{"invoice_id": "P1", "gst_percent": 12.0, "taxable_paise": 1000000, "line_count": 3}],
        hsn_lines,
        reversals,
        reversal_totals,
        own_sales_paise=31100000,
    )


class TestGstr3bWorksheet:
    def rows(self, built):
        return {r["code"]: r for r in built.to_dict()["reports"]["gstr3b"]["outward"]}

    def test_outward_taxable_matches_the_return(self, built):
        # ₹3,10,400 - the same figure test_gstr1_synthetic_month pins.
        row = self.rows(built)["3.1(a)"]
        assert row["taxable"]["value"] == 310400.00
        assert row["cgst"]["value"] == 558.50
        assert row["igst"]["value"] == 36096.00

    def test_nil_and_exempt_combine_into_3_1_c(self, built):
        # Table 8 keeps them apart; 3.1(c) asks for them together.
        assert self.rows(built)["3.1(c)"]["taxable"]["value"] == 600.00

    def test_non_gst_gets_its_own_row_rather_than_inflating_exempt(self, built):
        assert self.rows(built)["3.1(e)"]["taxable"]["value"] == 0.00

    def test_every_outward_row_warns_that_it_cannot_be_edited(self, built):
        # The instinct on seeing a wrong number is to fix it where you found
        # it, and at the portal that is impossible for these rows.
        for row in self.rows(built).values():
            assert row["auto_populated"] is True
            assert any("GSTR-1A" in c for c in row["caveats"])
        assert "GSTR-1A" in AUTO_POPULATED_WARNING

    def test_itc_available_comes_from_the_purchase_register(self, built):
        itc = {r["code"]: r for r in built.to_dict()["reports"]["gstr3b"]["itc"]}
        # Only P1 is eligible: ₹600 CGST. P2 has no supplier GSTIN.
        assert itc["4(A)(5)"]["cgst"]["value"] == 600.00

    def test_itc_available_is_marked_provisional(self, built):
        source = built.to_dict()["reports"]["gstr3b"]["itc_source"]
        assert source["is_authoritative"] is False
        assert any("GSTR-2B" in c for c in source["caveats"])
        assert source["counted_invoices"] == 1
        assert source["excluded"][0]["invoice_number"] == "SUP-002"

    def test_reversals_land_in_the_right_rows(self, built):
        itc = {r["code"]: r for r in built.to_dict()["reports"]["gstr3b"]["itc"]}
        assert itc[TABLE_PERMANENT]["cgst"]["value"] == 12.00
        assert itc[TABLE_TEMPORARY]["cgst"]["value"] == 5.00
        assert itc[TABLE_RECLAIM]["cgst"]["value"] == 0.00

    def test_net_itc_subtracts_both_reversal_rows(self, built):
        # 600 - 12 - 5.
        net = built.to_dict()["reports"]["gstr3b"]["net_itc"]
        assert net["cgst"]["value"] == 583.00

    def test_net_itc_does_not_add_the_reclaim_back(self, built):
        # A reclaim is a disclosure; the credit already sits inside 4(A)(5)
        # for the period it was reclaimed in. Adding it would claim it twice.
        net = built.to_dict()["reports"]["gstr3b"]["net_itc"]
        assert "not added in" in net["note"]


class TestPurchaseRegister:
    def report(self, built):
        return built.to_dict()["reports"]["purchase_register"]

    def test_is_invoice_wise_and_never_collapsed(self, built):
        assert self.report(built)["row_count"] == 2

    def test_marks_an_invoice_with_no_supplier_gstin_as_blocked(self, built):
        rows = {r["cells"]["invoice_number"]: r for r in self.report(built)["rows"]}
        blocked = rows["SUP-002"]
        assert blocked["cells"]["itc_eligible"] is False
        assert blocked["cells"]["itc_blocked_reason"] == "Supplier GSTIN missing"
        assert "ITC_BLOCKED" in blocked["flags"]

    def test_separates_claimable_from_blocked_tax(self, built):
        totals = self.report(built)["totals"]
        assert totals["itc_eligible_tax"]["value"] == 1200.00
        assert totals["itc_blocked_tax"]["value"] == 60.00

    def test_carries_rate_blocks_per_invoice(self, built):
        rows = {r["cells"]["invoice_number"]: r for r in self.report(built)["rows"]}
        blocks = rows["SUP-001"]["cells"]["rate_blocks"]
        assert blocks[0]["gst_percent"] == 12.0
        assert blocks[0]["taxable"]["value"] == 10000.00


class TestSalesRegister:
    def test_is_bill_wise_including_what_does_not_reach_the_return(self, documents, built):
        report = built.to_dict()["reports"]["sales_register"]
        # Every document, drafts and cancellations included - a register that
        # omits them disagrees with the bill book it is reconciled against.
        assert report["row_count"] == len(documents)
        flags = {f for r in report["rows"] for f in r["flags"]}
        assert "CANCELLED" in flags and "DRAFT" in flags and "CREDIT_NOTE" in flags

    def test_totals_count_only_what_reaches_the_return(self, built):
        # Same ₹3,10,400 as the return, which is what the cross-check compares.
        assert built.to_dict()["reports"]["sales_register"]["totals"]["taxable"]["value"] == 310400.00

    def test_filters_by_rate(self, documents, payments, purchases, hsn_lines,
                             reversals, reversal_totals):
        built = pack.build(
            IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"), documents, payments,
            purchases, [], hsn_lines, reversals, reversal_totals,
            sales_filters={"rate_bp": 500},
        )
        report = built.to_dict()["reports"]["sales_register"]
        assert report["row_count"] == 1
        assert report["rows"][0]["cells"]["bill_number"] == "CTR-000002"

    def test_filters_by_capture_mode(self, documents, payments, purchases, hsn_lines,
                                     reversals, reversal_totals):
        built = pack.build(
            IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"), documents, payments,
            purchases, [], hsn_lines, reversals, reversal_totals,
            sales_filters={"capture_mode": "COUNTER"},
        )
        assert built.to_dict()["reports"]["sales_register"]["row_count"] == len(documents)

    def test_filters_by_payment_method(self, documents, payments, purchases, hsn_lines,
                                       reversals, reversal_totals):
        built = pack.build(
            IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"), documents, payments,
            purchases, [], hsn_lines, reversals, reversal_totals,
            sales_filters={"payment_method": "cash"},
        )
        report = built.to_dict()["reports"]["sales_register"]
        assert report["row_count"] == 1
        assert report["rows"][0]["cells"]["document_id"] == "D1"

    def test_offers_the_filters_that_actually_apply(self, built):
        available = built.to_dict()["reports"]["sales_register"]["available_filters"]
        assert 12.0 in available["rates"] and 5.0 in available["rates"]
        assert available["payment_methods"] == ["cash"]


class TestHsnSummary:
    def test_outward_carries_uqc_status_per_row(self, built):
        outward = built.to_dict()["reports"]["hsn_summary"]["outward"]
        assert all(r["cells"]["uqc_status"] == UQC_VALID for r in outward["b2c"])
        assert outward["unfilable_row_count"] == 0

    def test_inward_says_when_it_has_no_unit_rather_than_inventing_one(self, built):
        # `LineItem` has a pack column and no unit field. Filing those as OTH
        # would hide the gap rather than close it.
        inward = built.to_dict()["reports"]["hsn_summary"]["inward"]
        assert inward["rows_without_uqc"] == 2
        assert all(r["cells"]["uqc_status"] != UQC_VALID for r in inward["rows"])
        assert inward["rows"][0]["cells"]["uqc"] is None

    def test_inward_flags_a_line_with_no_hsn(self, built):
        inward = built.to_dict()["reports"]["hsn_summary"]["inward"]
        assert inward["rows_without_known_hsn"] >= 1
        assert any("HSN_MISSING" in r["flags"] for r in inward["rows"])

    def test_inward_keeps_the_pack_string_it_could_not_map(self, built):
        rows = built.to_dict()["reports"]["hsn_summary"]["inward"]["rows"]
        packed = [r for r in rows if r["cells"]["pack_as_printed"]]
        assert packed and packed[0]["cells"]["pack_as_printed"] == "10x10"


class TestDocumentSeries:
    def test_flags_the_series_with_a_hole_in_it(self, built):
        report = built.to_dict()["reports"]["document_series"]
        assert report["has_gaps"] is True
        counter = next(r for r in report["rows"] if r["cells"]["series_prefix"] == "CTR-")
        assert counter["cells"]["gaps"] == [4]
        assert "GAP" in counter["flags"]

    def test_a_clean_series_is_not_flagged(self, built):
        report = built.to_dict()["reports"]["document_series"]
        credit = next(r for r in report["rows"] if r["cells"]["series_prefix"] == "CN-")
        assert credit["flags"] == []


class TestItcReversalRegister:
    def report(self, built):
        return built.to_dict()["reports"]["itc_reversals"]

    def test_every_row_can_defend_itself(self, built):
        # Trigger, provision, 3B row, and the document it came from. Those
        # four together are what turn a number into an answer.
        for row in self.report(built)["rows"]:
            assert row["cells"]["trigger"]
            assert row["cells"]["statutory_reference"]
            assert row["cells"]["gstr3b_table"]
            assert row["cells"]["source_id"]
            assert row["cells"]["reason"]

    def test_links_back_to_the_source_invoice(self, built):
        row = self.report(built)["rows"][0]
        assert row["cells"]["source_invoice_number"] == "SUP-001"
        assert row["drill"]["kind"] == "PURCHASES"
        assert row["drill"]["filters"]["ids"] == ["P1"]

    def test_totals_split_permanent_from_temporary(self, built):
        totals = self.report(built)["totals"]
        assert totals["permanent"]["value"] == 24.00
        assert totals["temporary"]["value"] == 10.00
        assert totals["reclaimed"]["value"] == 0.00


class TestCrossChecks:
    def checks(self, built):
        return {c["code"]: c for c in built.to_dict()["cross_checks"]}

    def test_all_four_run_on_every_load(self, built):
        assert set(self.checks(built)) == {
            "GSTR1_VS_SALES_REGISTER", "HSN_VS_TRANSACTIONS",
            "RATE_BLOCKS_VS_HEADERS", "TURNOVER_VS_PAYMENTS",
        }

    def test_a_consistent_month_passes_every_check(self, built):
        assert built.to_dict()["checks_pass"] is True
        assert built.to_dict()["failing_check_count"] == 0

    def test_both_sides_of_a_check_can_be_drilled(self, built):
        for check in self.checks(built).values():
            assert check["left"]["drill"] is not None
            assert check["right"]["drill"] is not None

    def test_a_header_that_disagrees_with_its_lines_is_caught(
        self, documents, payments, purchases, hsn_lines, reversals, reversal_totals
    ):
        # Break one document's header and confirm the check notices, rather
        # than trusting that it would.
        from dataclasses import replace
        broken = [replace(d, taxable_paise=d.taxable_paise + 5000)
                  if d.document_id == "D1" else d for d in documents]
        built = pack.build(
            IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"), broken, payments,
            purchases, [], hsn_lines, reversals, reversal_totals,
        )
        check = self.checks(built)["RATE_BLOCKS_VS_HEADERS"]
        assert check["agrees"] is False
        assert check["difference"] == -50.00
        assert check["right"]["drill"]["filters"]["ids"] == ["D1"]

    def test_unrecorded_cash_shows_as_a_shortfall(
        self, documents, purchases, hsn_lines, reversals, reversal_totals
    ):
        # A bill for ₹1,320 recorded as ₹1,000 taken: ₹320 either never rung
        # up or never entered. A scrutiny officer runs this same comparison.
        short = [{"sale_id": "D1", "method": "cash", "amount_paise": 100000,
                  "status": "CONFIRMED", "document_type": "INVOICE", "reference": None}]
        built = pack.build(
            IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"), documents, short,
            purchases, [], hsn_lines, reversals, reversal_totals,
        )
        check = self.checks(built)["TURNOVER_VS_PAYMENTS"]
        assert check["agrees"] is False
        assert check["difference"] == 320.00

    def test_bills_without_a_payment_split_are_excluded_and_counted(self, built):
        # Including them would make every period fail, which would train
        # people to ignore the check.
        check = self.checks(built)["TURNOVER_VS_PAYMENTS"]
        assert check["agrees"] is True
        assert "no payment split" in check["explanation"]


class TestEveryFigureIsTraceable:
    """The headline requirement, asserted structurally.

    A number a user cannot explain to an officer is worse than no number. This
    walks the entire serialised pack, finds everything shaped like a figure,
    and fails if one of them has no route back to the documents behind it.
    """

    def figures(self, node, path="") -> list:
        found = []
        if isinstance(node, dict):
            if "paise" in node and "value" in node and "drill" in node:
                found.append((path, node))
            for key, value in node.items():
                found += self.figures(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found += self.figures(value, f"{path}[{index}]")
        return found

    def test_the_pack_is_full_of_figures(self, built):
        # A guard on the guard: if the walker stopped finding figures the
        # test below would pass vacuously.
        assert len(self.figures(built.to_dict())) > 50

    def test_every_figure_in_every_report_can_be_drilled(self, built):
        undrillable = []
        for path, node in self.figures(built.to_dict()["reports"]):
            if node["drill"] is None:
                undrillable.append(path)
        # Subtotals computed from other figures are allowed no drill of their
        # own - each part drills separately - so they are named explicitly
        # rather than waved through by a blanket rule.
        allowed = ("gstr3b.net_itc", "purchase_register.totals",
                   "sales_register.totals", "hsn_summary.outward.totals",
                   "hsn_summary.inward.totals", "itc_reversals.totals",
                   "gstr1.totals")
        unexplained = [p for p in undrillable if not any(a in p for a in allowed)]
        assert unexplained == [], f"figures with no provenance: {unexplained}"

    def test_a_drill_names_a_kind_the_resolver_understands(self, built):
        from services.statutory.model import DrillKind
        for _path, node in self.figures(built.to_dict()):
            if node["drill"]:
                assert node["drill"]["kind"] in DrillKind.ALL
