"""One synthetic month, end to end, asserted to the paise.

A pharmacy's September: counter bills at two rates, nil-rated and exempt lines
alongside taxable ones, a day total with no lines at all, a customer return, a
cancelled bill, a hole in the bill series, an inter-state delivery, a B2B
invoice raised on a distributor for expired stock, and one bill still in draft.

Every expected figure below is worked out by hand in the comments rather than
computed by the test, because a test that recomputes the thing it is testing
proves only that the code is consistent with itself.

The month deliberately contains two inter-state supplies of different sizes:
one small enough to belong in the Table 7 aggregate and one large enough to be
reported invoice-wise in Table 5. Getting those two the same way round is the
distinction the whole B2CL guard exists to make.
"""

from decimal import Decimal

import pytest

from services.gstr1.engine import compute
from services.gstr1.model import (
    DocumentStatus,
    DocumentType,
    OutwardDocument,
    OutwardLine,
    RateBlock,
    SupplyClass,
    SupplyType,
)
from services.gstr1.periods import resolve_filing_period

OWN_STATE = "27"      # Maharashtra: where the shop is.
OTHER_STATE = "29"    # Karnataka.
PERIOD = "092026"

IDENTITY = {
    "gstin": "27AAAAA0000A1Z5",
    "pan": "AAAAA0000A",
    "state_code": OWN_STATE,
    "state": "Maharashtra",
    "legal_name": "Test Pharmacy",
    "filing_frequency": "MONTHLY",
    "effective_filing_frequency": "MONTHLY",
    # ₹2 crore, so HSN is reported at four digits.
    "aato_paise": 2_00_00_000_00,
    "aato_financial_year": 2025,
    "hsn_digit_policy": "FOUR_DIGIT",
    "hsn_digits": 4,
    "hsn_policy_is_declared": True,
}


def line(hsn, uqc, qty, rate_bp, taxable, *, cgst=0, sgst=0, igst=0,
         supply_class=SupplyClass.TAXABLE, line_id=None):
    return OutwardLine(
        line_id=line_id, product_id=f"P-{hsn}", product_name=f"Product {hsn}",
        hsn=hsn, uqc=uqc, quantity=Decimal(qty), rate_bp=rate_bp,
        supply_class=supply_class, taxable_paise=taxable,
        cgst_paise=cgst, sgst_paise=sgst, igst_paise=igst,
    )


def document(document_id, date, **kwargs):
    fields = {
        "sale_date": date,
        "tax_period": PERIOD,
        "supplier_state_code": OWN_STATE,
        "place_of_supply_state_code": OWN_STATE,
        "document_class": "INVOICE_CUM_BILL_OF_SUPPLY",
    }
    fields.update(kwargs)
    return OutwardDocument(document_id=document_id, **fields)


@pytest.fixture
def september():
    """The month itself."""
    return [
        # CTR-000001: ₹1,000 at 12% plus ₹200 of nil-rated life-saving drugs.
        document(
            "D1", "2026-09-02", bill_number="CTR-000001", series_prefix="CTR-",
            serial_sequence=1,
            lines=(
                line("3004", "TBS", "2", 1200, 100000, cgst=6000, sgst=6000, line_id="D1L1"),
                line("3002", "NOS", "1", 0, 20000, supply_class=SupplyClass.NIL_RATED,
                     line_id="D1L2"),
            ),
            taxable_paise=100000, cgst_paise=6000, sgst_paise=6000,
            nil_rated_paise=20000, grand_total_paise=132000,
        ),
        # CTR-000002: ₹500 at 5%.
        document(
            "D2", "2026-09-05", bill_number="CTR-000002", series_prefix="CTR-",
            serial_sequence=2,
            lines=(line("3004", "TBS", "1", 500, 50000, cgst=1250, sgst=1250),),
            taxable_paise=50000, cgst_paise=1250, sgst_paise=1250,
            grand_total_paise=52500,
        ),
        # CTR-000003: cancelled. Consumed a number, supplied nothing.
        document(
            "D3", "2026-09-08", bill_number="CTR-000003", series_prefix="CTR-",
            serial_sequence=3, status=DocumentStatus.CANCELLED,
            lines=(line("3004", "TBS", "1", 1200, 99900, cgst=5994, sgst=5994),),
            taxable_paise=99900, cgst_paise=5994, sgst_paise=5994,
            grand_total_paise=111888,
        ),
        # CTR-000004 was never synced. That hole is the series gap.
        # CTR-000005: ₹2,000 at 12% plus ₹300 exempt.
        document(
            "D5", "2026-09-12", bill_number="CTR-000005", series_prefix="CTR-",
            serial_sequence=5,
            lines=(
                line("3004", "TBS", "4", 1200, 200000, cgst=12000, sgst=12000),
                line("3006", "NOS", "1", 0, 30000, supply_class=SupplyClass.EXEMPT),
            ),
            taxable_paise=200000, cgst_paise=12000, sgst_paise=12000,
            exempt_paise=30000, grand_total_paise=254000,
        ),
        # A declared day total: no lines, so it can answer Tables 7 and 8 and
        # not Table 12.
        document(
            "DT", "2026-09-15", is_aggregate=True,
            rate_blocks=(RateBlock(rate_bp=1200, taxable_paise=150000,
                                   cgst_paise=9000, sgst_paise=9000),),
            taxable_paise=150000, cgst_paise=9000, sgst_paise=9000,
            nil_rated_paise=10000, grand_total_paise=178000,
        ),
        # Still a draft on filing day. None of its figures may appear.
        document(
            "D11", "2026-09-18", status=DocumentStatus.DRAFT,
            lines=(line("3004", "TBS", "1", 1200, 999900, cgst=59994, sgst=59994),),
            taxable_paise=999900, cgst_paise=59994, sgst_paise=59994,
        ),
        # A customer returning ₹400 of what they bought.
        document(
            "D8", "2026-09-20", bill_number="CN-0001", series_prefix="CN-",
            serial_sequence=1, document_type=DocumentType.CREDIT_NOTE,
            lines=(line("3004", "TBS", "1", 1200, 40000, cgst=2400, sgst=2400),),
            taxable_paise=40000, cgst_paise=2400, sgst_paise=2400,
            grand_total_paise=44800,
        ),
        # Expired stock returned to the distributor on the shop's own tax
        # invoice - an outward B2B supply.
        document(
            "D9", "2026-09-25", bill_number="EXP-0001", series_prefix="EXP-",
            serial_sequence=1, customer_gstin="27BBBBB0000B1Z5",
            customer_name="Distributor Ltd", document_class="TAX_INVOICE",
            lines=(line("3004", "TBS", "20", 1200, 500000, cgst=30000, sgst=30000),),
            taxable_paise=500000, cgst_paise=30000, sgst_paise=30000,
            grand_total_paise=560000,
        ),
        # A small inter-state delivery: goes in the Table 7 aggregate.
        document(
            "D6", "2026-09-28", bill_number="CTR-000006", series_prefix="CTR-",
            serial_sequence=6, place_of_supply_state_code=OTHER_STATE,
            lines=(line("3004", "TBS", "2", 1200, 80000, igst=9600),),
            taxable_paise=80000, igst_paise=9600, grand_total_paise=89600,
        ),
        # A large one: over ₹2,50,000, so Table 5 and a review item.
        document(
            "D7", "2026-09-29", bill_number="CTR-000007", series_prefix="CTR-",
            serial_sequence=7, place_of_supply_state_code=OTHER_STATE,
            lines=(line("3004", "TBS", "10", 1200, 30000000, igst=3600000),),
            taxable_paise=30000000, igst_paise=3600000, grand_total_paise=33600000,
        ),
    ]


@pytest.fixture
def result(september):
    return compute(september, IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"))


class TestTable7B2cs:
    def test_has_exactly_three_buckets(self, result):
        assert len(result.tables["b2cs"].buckets) == 3

    def test_the_five_percent_bucket(self, result):
        bucket = result.tables["b2cs"].buckets[0]
        assert (bucket.place_of_supply, bucket.rate_bp, bucket.supply_type) == \
            (OWN_STATE, 500, SupplyType.INTRA)
        # CTR-000002 alone: ₹500.00 at 5% is ₹25.00 of tax, ₹12.50 each way.
        assert bucket.taxable_paise == 50000
        assert bucket.cgst_paise == 1250
        assert bucket.sgst_paise == 1250
        assert bucket.igst_paise == 0

    def test_the_twelve_percent_intrastate_bucket_nets_the_return(self, result):
        bucket = result.tables["b2cs"].buckets[1]
        assert (bucket.place_of_supply, bucket.rate_bp, bucket.supply_type) == \
            (OWN_STATE, 1200, SupplyType.INTRA)
        # CTR-000001 1,00,000 + CTR-000005 2,00,000 + day total 1,50,000
        #   less the CN-0001 return of 40,000 = 4,10,000 paise.
        assert bucket.taxable_paise == 410000
        # 6,000 + 12,000 + 9,000 - 2,400 = 24,600 paise each way.
        assert bucket.cgst_paise == 24600
        assert bucket.sgst_paise == 24600
        # The cancelled bill and the draft are in neither figure.
        assert "D3" not in bucket.document_ids
        assert "D11" not in bucket.document_ids

    def test_the_interstate_bucket_holds_only_the_small_delivery(self, result):
        bucket = result.tables["b2cs"].buckets[2]
        assert (bucket.place_of_supply, bucket.rate_bp, bucket.supply_type) == \
            (OTHER_STATE, 1200, SupplyType.INTER)
        # CTR-000006 only. CTR-000007 is reported invoice-wise in Table 5 and
        # must not also be summed here.
        assert bucket.taxable_paise == 80000
        assert bucket.igst_paise == 9600
        assert bucket.cgst_paise == 0 and bucket.sgst_paise == 0
        assert bucket.document_ids == ["D6"]

    def test_no_bucket_went_negative(self, result):
        assert result.tables["b2cs"].negative_buckets == []


class TestTable5B2cl:
    def test_reports_the_large_interstate_bill_invoice_wise(self, result):
        entries = result.tables["b2cl"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry.bill_number == "CTR-000007"
        assert entry.place_of_supply == OTHER_STATE
        # ₹3,00,000 taxable plus ₹36,000 IGST.
        assert entry.invoice_value_paise == 33600000
        assert entry.rate_blocks == [
            {"rate_bp": 1200, "taxable_paise": 30000000, "cgst_paise": 0,
             "sgst_paise": 0, "igst_paise": 3600000, "cess_paise": 0}
        ]

    def test_the_small_interstate_delivery_is_not_here(self, result):
        assert all(e.bill_number != "CTR-000006" for e in result.tables["b2cl"])


class TestTable4aB2b:
    def test_reports_the_expired_stock_invoice(self, result):
        entries = result.tables["b2b"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry.customer_gstin == "27BBBBB0000B1Z5"
        assert entry.bill_number == "EXP-0001"
        assert entry.invoice_value_paise == 560000
        assert entry.supply_type == SupplyType.INTRA
        assert entry.rate_blocks == [
            {"rate_bp": 1200, "taxable_paise": 500000, "cgst_paise": 30000,
             "sgst_paise": 30000, "igst_paise": 0, "cess_paise": 0}
        ]


class TestTable8NilExempt:
    def test_all_four_rows_are_present(self, result):
        assert [r.code for r in result.tables["nil_exempt"]] == ["8A", "8B", "8C", "8D"]

    def test_the_untaxed_supplies_are_all_intrastate_to_consumers(self, result):
        rows = {r.code: r for r in result.tables["nil_exempt"]}
        # Nil-rated: ₹200 on CTR-000001 plus ₹100 declared on the day total.
        assert rows["8D"].nil_rated_paise == 30000
        # Exempt: ₹300 on CTR-000005.
        assert rows["8D"].exempted_paise == 30000
        assert rows["8D"].non_gst_paise == 0
        assert rows["8D"].total_paise == 60000

    def test_the_other_three_rows_are_zero(self, result):
        rows = {r.code: r for r in result.tables["nil_exempt"]}
        assert rows["8A"].total_paise == 0
        assert rows["8B"].total_paise == 0
        assert rows["8C"].total_paise == 0


class TestTable12Hsn:
    def test_b2c_rows_are_keyed_on_hsn_uqc_and_rate(self, result):
        rows = result.tables["hsn"].b2c
        assert [(r.hsn, r.uqc, r.rate_bp) for r in rows] == [
            ("3002", "NOS", 0),
            ("3004", "TBS", 500),
            ("3004", "TBS", 1200),
            ("3006", "NOS", 0),
        ]

    def test_the_twelve_percent_row_sums_every_contributing_line(self, result):
        row = result.tables["hsn"].b2c[2]
        # Quantities: 2 + 4 + 2 + 10 less the 1 returned = 17.
        assert row.quantity == Decimal("17")
        # 1,00,000 + 2,00,000 + 80,000 + 3,00,00,000 - 40,000.
        assert row.taxable_paise == 30340000
        # Intra-state tax only: 6,000 + 12,000 - 2,400.
        assert row.cgst_paise == 15600
        assert row.sgst_paise == 15600
        # Inter-state tax: 9,600 + 36,00,000.
        assert row.igst_paise == 3609600
        assert row.total_value_paise == 30340000 + 15600 + 15600 + 3609600

    def test_the_nil_and_exempt_rows_carry_no_tax(self, result):
        nil_row, exempt_row = result.tables["hsn"].b2c[0], result.tables["hsn"].b2c[3]
        assert (nil_row.taxable_paise, nil_row.quantity) == (20000, Decimal("1"))
        assert (exempt_row.taxable_paise, exempt_row.quantity) == (30000, Decimal("1"))
        assert nil_row.total_value_paise == 20000
        assert exempt_row.total_value_paise == 30000

    def test_the_five_percent_row(self, result):
        row = result.tables["hsn"].b2c[1]
        assert row.taxable_paise == 50000
        assert row.cgst_paise == 1250 and row.sgst_paise == 1250

    def test_b2b_is_summarised_separately(self, result):
        rows = result.tables["hsn"].b2b
        assert len(rows) == 1
        assert (rows[0].hsn, rows[0].uqc, rows[0].rate_bp) == ("3004", "TBS", 1200)
        assert rows[0].quantity == Decimal("20")
        assert rows[0].taxable_paise == 500000
        assert rows[0].cgst_paise == 30000 and rows[0].sgst_paise == 30000

    def test_the_day_total_cannot_contribute_and_says_so(self, result):
        assert result.tables["hsn"].documents_without_lines == ["DT"]

    def test_the_draft_and_the_cancelled_bill_are_absent(self, result):
        every_document = {
            document_id
            for row in result.tables["hsn"].b2c + result.tables["hsn"].b2b
            for document_id in row.document_ids
        }
        assert "D11" not in every_document
        assert "D3" not in every_document


class TestTable13DocumentsIssued:
    def series(self, result):
        return {s.series_prefix: s for s in result.tables["documents"].series}

    def test_the_counter_series_spans_one_to_seven(self, result):
        counter = self.series(result)["CTR-"]
        assert counter.opening_number == "CTR-000001"
        assert counter.closing_number == "CTR-000007"
        # Six numbers exist: 1, 2, 3, 5, 6, 7.
        assert counter.total_issued == 6
        assert counter.cancelled == 1
        assert counter.net_issued == 5

    def test_the_missing_bill_shows_as_a_gap(self, result):
        assert self.series(result)["CTR-"].gaps == [4]
        assert result.tables["documents"].has_gaps

    def test_the_credit_note_and_b2b_series_are_counted_apart(self, result):
        series = self.series(result)
        assert set(series) == {"CTR-", "CN-", "EXP-"}
        assert series["CN-"].total_issued == 1 and series["CN-"].gaps == []
        assert series["EXP-"].total_issued == 1 and series["EXP-"].gaps == []

    def test_the_draft_has_no_serial_and_is_surfaced(self, result):
        assert result.tables["documents"].documents_without_series == ["D11"]


class TestTotals:
    def test_the_headline_figures(self, result):
        totals = result.totals
        # B2CS 50,000 + 4,10,000 + 80,000, plus B2B 5,00,000, plus B2CL
        # 3,00,00,000.
        assert totals["taxable_paise"] == 31040000
        # B2CS 1,250 + 24,600 plus B2B 30,000.
        assert totals["cgst_paise"] == 55850
        assert totals["sgst_paise"] == 55850
        # B2CS 9,600 plus B2CL 36,00,000.
        assert totals["igst_paise"] == 3609600
        assert totals["untaxed_paise"] == 60000
        assert totals["supplies_paise"] == 31100000

    def test_a_month_with_sales_is_not_a_nil_return(self, result):
        assert not result.is_nil_return


class TestValidation:
    def codes(self, result):
        return {item.code for item in result.report.items}

    def test_the_series_gap_blocks_the_close(self, result):
        assert "SERIES_GAP" in {i.code for i in result.report.blocking}

    def test_the_large_interstate_bill_is_raised_for_review(self, result):
        item = next(i for i in result.report.items if i.code == "B2CL_NEEDS_REVIEW")
        assert item.severity == "BLOCKING"
        assert item.record_id == "D7"

    def test_the_draft_is_warned_about_not_blocked(self, result):
        item = next(i for i in result.report.items if i.code == "DRAFT_IN_PERIOD")
        assert item.severity == "WARNING"
        assert item.record_id == "D11"

    def test_the_day_total_leaves_the_hsn_summary_incomplete(self, result):
        item = next(i for i in result.report.items if i.code == "HSN_SUMMARY_INCOMPLETE")
        assert item.severity == "WARNING"

    def test_the_tax_invoice_carrying_no_exempt_lines_is_not_flagged(self, result):
        # EXP-0001 is a TAX_INVOICE and is entirely taxable, so it should not
        # trip the Rule 46A check.
        assert "EXEMPT_LINE_ON_TAX_INVOICE" not in self.codes(result)

    def test_nothing_fails_to_reconcile(self, result):
        assert "RATE_BLOCK_DOES_NOT_RECONCILE" not in self.codes(result)

    def test_the_period_cannot_close_while_blocking_items_stand(self, result):
        assert not result.can_close

    def test_acknowledging_every_blocking_item_allows_the_close(self, september):
        first = compute(september, IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"))
        acknowledged = {item.id for item in first.report.blocking}
        second = compute(september, IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"),
                         acknowledged=acknowledged)
        assert second.can_close

    def test_an_item_id_is_stable_across_runs(self, september):
        first = compute(september, IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"))
        second = compute(september, IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"))
        assert [i.id for i in first.report.items] == [i.id for i in second.report.items]


class TestPayload:
    def test_carries_the_shop_and_the_period(self, result):
        assert result.payload["gstin"] == "27AAAAA0000A1Z5"
        assert result.payload["fp"] == "092026"

    def test_b2cs_rows_are_in_rupees(self, result):
        rows = {(r["pos"], r["rt"]): r for r in result.payload["b2cs"]}
        twelve = rows[(OWN_STATE, 12)]
        assert twelve["txval"] == 4100.00
        assert twelve["camt"] == 246.00
        assert twelve["samt"] == 246.00
        assert twelve["sply_ty"] == "INTRA"
        assert twelve["typ"] == "OE"

    def test_b2b_is_grouped_by_customer_gstin(self, result):
        section = result.payload["b2b"]
        assert len(section) == 1
        assert section[0]["ctin"] == "27BBBBB0000B1Z5"
        invoice = section[0]["inv"][0]
        assert invoice["inum"] == "EXP-0001"
        assert invoice["idt"] == "25-09-2026"
        assert invoice["val"] == 5600.00
        assert invoice["itms"][0]["itm_det"]["txval"] == 5000.00
        assert invoice["itms"][0]["itm_det"]["camt"] == 300.00

    def test_b2cl_is_grouped_by_place_of_supply(self, result):
        section = result.payload["b2cl"]
        assert section[0]["pos"] == OTHER_STATE
        assert section[0]["inv"][0]["val"] == 336000.00

    def test_the_nil_section_uses_the_portals_vocabulary(self, result):
        rows = {r["sply_ty"]: r for r in result.payload["nil"]["inv"]}
        assert set(rows) == {"INTRB2B", "INTRAB2B", "INTRB2C", "INTRAB2C"}
        assert rows["INTRAB2C"]["nil_amt"] == 300.00
        assert rows["INTRAB2C"]["expt_amt"] == 300.00
        assert rows["INTRAB2C"]["ngsup_amt"] == 0.00

    def test_hsn_keeps_b2b_and_b2c_apart(self, result):
        hsn = result.payload["hsn"]
        assert len(hsn["hsn_b2c"]) == 4
        assert len(hsn["hsn_b2b"]) == 1
        twelve = hsn["hsn_b2c"][2]
        assert twelve["hsn_sc"] == "3004"
        assert twelve["uqc"] == "TBS"
        assert twelve["rt"] == 12
        assert twelve["qty"] == 17.0
        assert twelve["txval"] == 303400.00
        assert twelve["iamt"] == 36096.00

    def test_documents_issued_reports_the_series(self, result):
        docs = result.payload["doc_issue"]["doc_det"][0]["docs"]
        counter = next(d for d in docs if d["from"] == "CTR-000001")
        assert counter["to"] == "CTR-000007"
        assert counter["totnum"] == 6
        assert counter["cancel"] == 1
        assert counter["net_issue"] == 5

    def test_is_serialisable_as_json(self, result):
        import json
        assert json.loads(json.dumps(result.payload))["fp"] == "092026"


class TestQuarterlyFiler:
    def test_a_qrmp_shop_aggregates_the_whole_quarter(self, september):
        # The same September, asked for as a quarterly filer, covers Jul-Sep -
        # and the payload is identified by the month the quarter ends in.
        quarterly = resolve_filing_period(PERIOD, "QUARTERLY")
        assert quarterly.months == ("072026", "082026", "092026")
        result = compute(september, {**IDENTITY, "filing_frequency": "QUARTERLY"}, quarterly)
        assert result.payload["fp"] == "092026"
        assert result.payload["filing_frequency"] == "QUARTERLY"
        # The figures are the same because the fixture only holds September;
        # what changes is the window the repository would have read.
        assert result.totals["taxable_paise"] == 31040000


class TestNilPeriod:
    def test_a_month_with_no_sales_still_produces_a_return(self):
        # A nil GSTR-1 must still be filed. The engine has to produce a
        # payload for an empty month rather than nothing at all.
        result = compute([], IDENTITY, resolve_filing_period(PERIOD, "MONTHLY"))
        assert result.is_nil_return
        assert result.totals["supplies_paise"] == 0
        # The period statements still go, at zero.
        assert len(result.payload["nil"]["inv"]) == 4
        assert result.payload["hsn"] == {"hsn_b2b": [], "hsn_b2c": []}
        # Sections with nothing in them are dropped rather than sent empty.
        assert "b2b" not in result.payload
        assert "b2cs" not in result.payload
        assert result.can_close
