"""Each GSTR-1 table, asserted to the paise.

Every figure here is an integer sum of integer paise, so these assertions are
exact by construction - there is no tolerance anywhere in this file, and a
test that needed one would be pointing at a bug.

The cases are chosen for what actually goes wrong in a pharmacy's return:
returns that outrun sales in a bucket, a place of supply nobody recorded, an
over-the-counter sale to a customer from another state, and a day total that
can answer some tables and not others.
"""

from decimal import Decimal

from services.gstr1.model import (
    DocumentStatus,
    DocumentType,
    OutwardDocument,
    OutwardLine,
    RateBlock,
    SupplyClass,
    SupplyType,
)
from services.gstr1.tables import (
    B2CL_THRESHOLD_PAISE,
    aggregate_b2b,
    aggregate_b2cl,
    aggregate_b2cs,
    aggregate_documents_issued,
    aggregate_hsn,
    aggregate_nil_exempt,
    qualifies_for_b2cl,
)

OWN_STATE = "27"      # Maharashtra - where the shop is.
OTHER_STATE = "29"    # Karnataka.


def taxable_line(taxable, rate_bp=1200, *, hsn="300490", uqc="TBS", qty="1", inter=False):
    """A taxable line with the tax split the supply type implies."""
    tax = taxable * rate_bp // 10_000
    if inter:
        return OutwardLine(
            hsn=hsn, uqc=uqc, quantity=Decimal(qty), rate_bp=rate_bp,
            supply_class=SupplyClass.TAXABLE, taxable_paise=taxable, igst_paise=tax,
        )
    half = tax // 2
    return OutwardLine(
        hsn=hsn, uqc=uqc, quantity=Decimal(qty), rate_bp=rate_bp,
        supply_class=SupplyClass.TAXABLE, taxable_paise=taxable,
        cgst_paise=half, sgst_paise=tax - half,
    )


def bill(document_id, *lines, **kwargs):
    """A counter bill, intra-state and to an unregistered customer by default."""
    fields = {
        "sale_date": "2026-09-05",
        "tax_period": "092026",
        "supplier_state_code": OWN_STATE,
        "place_of_supply_state_code": OWN_STATE,
    }
    fields.update(kwargs)
    lines = tuple(lines)
    if "taxable_paise" not in fields and lines:
        fields["taxable_paise"] = sum(l.taxable_paise for l in lines)
        fields["cgst_paise"] = sum(l.cgst_paise for l in lines)
        fields["sgst_paise"] = sum(l.sgst_paise for l in lines)
        fields["igst_paise"] = sum(l.igst_paise for l in lines)
    return OutwardDocument(document_id=document_id, lines=lines, **fields)


class TestB2csTable7:
    def test_groups_by_place_of_supply_rate_and_supply_type(self):
        result = aggregate_b2cs([
            bill("A", taxable_line(100_00, 1200)),
            bill("B", taxable_line(200_00, 1200)),
            bill("C", taxable_line(100_00, 500)),
        ])
        assert len(result.buckets) == 2
        twelve = next(b for b in result.buckets if b.rate_bp == 1200)
        assert twelve.taxable_paise == 300_00
        # 12% of ₹300.00 is ₹36.00, half each way.
        assert twelve.cgst_paise == 18_00 and twelve.sgst_paise == 18_00
        five = next(b for b in result.buckets if b.rate_bp == 500)
        # 5% of ₹100.00 is ₹5.00.
        assert five.taxable_paise == 100_00
        assert five.cgst_paise == 2_50 and five.sgst_paise == 2_50

    def test_an_interstate_bucket_is_separate_from_an_intrastate_one(self):
        result = aggregate_b2cs([
            bill("A", taxable_line(100_00)),
            bill("B", taxable_line(100_00, inter=True),
                 place_of_supply_state_code=OTHER_STATE),
        ])
        assert len(result.buckets) == 2
        intra = next(b for b in result.buckets if b.supply_type == SupplyType.INTRA)
        inter = next(b for b in result.buckets if b.supply_type == SupplyType.INTER)
        assert intra.cgst_paise == 600 and intra.sgst_paise == 600 and intra.igst_paise == 0
        assert inter.igst_paise == 1200 and inter.cgst_paise == 0

    def test_a_sale_return_nets_into_the_same_bucket(self):
        sale = bill("A", taxable_line(1000_00))
        credit = bill("B", taxable_line(300_00), document_type=DocumentType.CREDIT_NOTE)
        result = aggregate_b2cs([sale, credit])
        bucket = result.buckets[0]
        assert bucket.taxable_paise == 700_00
        # 12% of 700.00 is 84.00, half each way.
        assert bucket.cgst_paise == 4200 and bucket.sgst_paise == 4200

    def test_a_bucket_that_would_go_negative_is_withheld_for_review(self):
        # A customer returning in September what they bought in August.
        result = aggregate_b2cs([
            bill("A", taxable_line(100_00)),
            bill("B", taxable_line(400_00), document_type=DocumentType.CREDIT_NOTE),
        ])
        assert result.buckets == []
        assert len(result.negative_buckets) == 1
        assert result.negative_buckets[0].taxable_paise == -300_00

    def test_a_negative_bucket_does_not_suppress_a_healthy_one(self):
        result = aggregate_b2cs([
            bill("A", taxable_line(100_00, 1200)),
            bill("B", taxable_line(400_00, 1200), document_type=DocumentType.CREDIT_NOTE),
            bill("C", taxable_line(500_00, 500)),
        ])
        assert [b.rate_bp for b in result.buckets] == [500]
        assert [b.rate_bp for b in result.negative_buckets] == [1200]

    def test_drafts_and_cancellations_contribute_nothing(self):
        result = aggregate_b2cs([
            bill("A", taxable_line(100_00)),
            bill("B", taxable_line(999_00), status=DocumentStatus.DRAFT),
            bill("C", taxable_line(999_00), status=DocumentStatus.CANCELLED),
        ])
        assert result.buckets[0].taxable_paise == 100_00

    def test_a_document_with_no_place_of_supply_is_left_out(self):
        # Left out rather than assumed intra-state: guessing here is exactly
        # how an interstate supply gets filed as CGST plus SGST.
        result = aggregate_b2cs([bill("A", taxable_line(100_00),
                                      place_of_supply_state_code=None)])
        assert result.buckets == []

    def test_b2b_supplies_are_not_in_b2cs(self):
        result = aggregate_b2cs([bill("A", taxable_line(100_00),
                                      customer_gstin="29AAAAA0000A1Z5")])
        assert result.buckets == []

    def test_a_day_total_is_aggregated_from_its_rate_blocks(self):
        day = OutwardDocument(
            document_id="DT", sale_date="2026-09-05", tax_period="092026",
            supplier_state_code=OWN_STATE, place_of_supply_state_code=OWN_STATE,
            is_aggregate=True,
            rate_blocks=(RateBlock(rate_bp=1200, taxable_paise=1000_00,
                                   cgst_paise=6000, sgst_paise=6000),),
        )
        bucket = aggregate_b2cs([day]).buckets[0]
        assert bucket.taxable_paise == 1000_00 and bucket.cgst_paise == 6000

    def test_lines_win_over_stored_rate_blocks(self):
        # A stored block that disagrees with the lines it came from must not be
        # able to contradict them.
        document = bill("A", taxable_line(100_00),
                        rate_blocks=(RateBlock(rate_bp=1200, taxable_paise=999_00),))
        assert aggregate_b2cs([document]).buckets[0].taxable_paise == 100_00

    def test_a_zero_rate_slab_is_not_reported_as_taxable(self):
        # A 0% taxable supply is a nil-rated supply and belongs in Table 8.
        document = bill("A", OutwardLine(hsn="300490", uqc="TBS", rate_bp=0,
                                         supply_class=SupplyClass.TAXABLE,
                                         taxable_paise=100_00))
        assert aggregate_b2cs([document]).buckets == []

    def test_a_bucket_remembers_the_bills_behind_it(self):
        result = aggregate_b2cs([bill("A", taxable_line(100_00)),
                                 bill("B", taxable_line(100_00))])
        assert result.buckets[0].document_ids == ["A", "B"]


class TestB2clTable5:
    def test_an_over_the_counter_sale_never_qualifies_however_large(self):
        # The whole point: an OTC sale is supplied where the counter stands, so
        # it is intra-state no matter where the customer lives or how big it is.
        document = bill("A", taxable_line(9_00_000_00))
        assert not qualifies_for_b2cl(document)
        assert aggregate_b2cl([document]) == []

    def test_a_large_interstate_consumer_bill_qualifies(self):
        document = bill("A", taxable_line(3_00_000_00, inter=True),
                        place_of_supply_state_code=OTHER_STATE,
                        grand_total_paise=3_36_000_00)
        assert qualifies_for_b2cl(document)
        entries = aggregate_b2cl([document])
        assert len(entries) == 1
        assert entries[0].invoice_value_paise == 3_36_000_00
        assert entries[0].place_of_supply == OTHER_STATE

    def test_the_threshold_is_strictly_above_two_and_a_half_lakh(self):
        at = bill("A", taxable_line(1_00_00, inter=True),
                  place_of_supply_state_code=OTHER_STATE,
                  grand_total_paise=B2CL_THRESHOLD_PAISE)
        above = bill("B", taxable_line(1_00_00, inter=True),
                     place_of_supply_state_code=OTHER_STATE,
                     grand_total_paise=B2CL_THRESHOLD_PAISE + 1)
        assert not qualifies_for_b2cl(at)
        assert qualifies_for_b2cl(above)

    def test_a_registered_customer_goes_to_b2b_not_b2cl(self):
        document = bill("A", taxable_line(3_00_000_00, inter=True),
                        place_of_supply_state_code=OTHER_STATE,
                        customer_gstin="29AAAAA0000A1Z5",
                        grand_total_paise=3_36_000_00)
        assert not qualifies_for_b2cl(document)

    def test_a_qualifying_bill_is_excluded_from_the_b2cs_aggregate(self):
        # Otherwise the supply is reported twice.
        document = bill("A", taxable_line(3_00_000_00, inter=True),
                        place_of_supply_state_code=OTHER_STATE,
                        grand_total_paise=3_36_000_00)
        b2cl_ids = {e.document_id for e in aggregate_b2cl([document])}
        assert aggregate_b2cs([document], b2cl_document_ids=b2cl_ids).buckets == []


class TestB2bTable4a:
    def test_reports_a_supply_to_a_registered_person_invoice_wise(self):
        # Returning expired stock to a distributor, on the pharmacy's own
        # outward tax invoice.
        document = bill("A", taxable_line(5_000_00),
                        customer_gstin="27AAAAA0000A1Z5",
                        customer_name="Distributor Ltd",
                        document_class="TAX_INVOICE",
                        bill_number="EXP-0001",
                        grand_total_paise=5_600_00)
        entries = aggregate_b2b([document])
        assert len(entries) == 1
        entry = entries[0]
        assert entry.customer_gstin == "27AAAAA0000A1Z5"
        assert entry.invoice_value_paise == 5_600_00
        assert entry.supply_type == SupplyType.INTRA
        assert entry.rate_blocks == [
            {"rate_bp": 1200, "taxable_paise": 5_000_00, "cgst_paise": 30_000,
             "sgst_paise": 30_000, "igst_paise": 0, "cess_paise": 0}
        ]

    def test_unregistered_customers_are_not_in_b2b(self):
        assert aggregate_b2b([bill("A", taxable_line(100_00))]) == []


class TestNilExemptTable8:
    def test_always_emits_all_four_rows(self):
        rows = aggregate_nil_exempt([])
        assert [r.code for r in rows] == ["8A", "8B", "8C", "8D"]
        assert all(r.total_paise == 0 for r in rows)

    def test_splits_intra_from_inter_and_registered_from_unregistered(self):
        nil = OutwardLine(hsn="300490", uqc="TBS", rate_bp=0,
                          supply_class=SupplyClass.NIL_RATED, taxable_paise=100_00)
        exempt = OutwardLine(hsn="300220", uqc="NOS", rate_bp=0,
                             supply_class=SupplyClass.EXEMPT, taxable_paise=50_00)
        rows = {r.code: r for r in aggregate_nil_exempt([
            bill("A", nil),                                                  # 8D
            bill("B", exempt, place_of_supply_state_code=OTHER_STATE),       # 8C
            bill("C", nil, customer_gstin="27AAAAA0000A1Z5"),                # 8B
            bill("D", exempt, place_of_supply_state_code=OTHER_STATE,
                 customer_gstin="29AAAAA0000A1Z5"),                          # 8A
        ])}
        assert rows["8D"].nil_rated_paise == 100_00
        assert rows["8C"].exempted_paise == 50_00
        assert rows["8B"].nil_rated_paise == 100_00
        assert rows["8A"].exempted_paise == 50_00

    def test_keeps_nil_rated_exempt_and_non_gst_apart(self):
        document = bill(
            "A",
            OutwardLine(supply_class=SupplyClass.NIL_RATED, taxable_paise=10_00),
            OutwardLine(supply_class=SupplyClass.EXEMPT, taxable_paise=20_00),
            OutwardLine(supply_class=SupplyClass.NON_GST, taxable_paise=30_00),
        )
        row = {r.code: r for r in aggregate_nil_exempt([document])}["8D"]
        assert row.nil_rated_paise == 10_00
        assert row.exempted_paise == 20_00
        assert row.non_gst_paise == 30_00
        assert row.total_paise == 60_00

    def test_a_day_total_declares_the_three_on_its_header(self):
        day = OutwardDocument(
            document_id="DT", sale_date="2026-09-05", tax_period="092026",
            supplier_state_code=OWN_STATE, place_of_supply_state_code=OWN_STATE,
            is_aggregate=True, nil_rated_paise=10_00, exempt_paise=20_00,
            non_gst_paise=30_00,
        )
        row = {r.code: r for r in aggregate_nil_exempt([day])}["8D"]
        assert (row.nil_rated_paise, row.exempted_paise, row.non_gst_paise) == (10_00, 20_00, 30_00)

    def test_a_credit_note_reduces_the_row(self):
        nil = OutwardLine(supply_class=SupplyClass.NIL_RATED, taxable_paise=100_00)
        back = OutwardLine(supply_class=SupplyClass.NIL_RATED, taxable_paise=40_00)
        rows = {r.code: r for r in aggregate_nil_exempt([
            bill("A", nil),
            bill("B", back, document_type=DocumentType.CREDIT_NOTE),
        ])}
        assert rows["8D"].nil_rated_paise == 60_00


class TestHsnTable12:
    def test_separates_b2b_from_b2c(self):
        summary = aggregate_hsn([
            bill("A", taxable_line(100_00)),
            bill("B", taxable_line(200_00), customer_gstin="27AAAAA0000A1Z5"),
        ])
        assert [r.taxable_paise for r in summary.b2c] == [100_00]
        assert [r.taxable_paise for r in summary.b2b] == [200_00]

    def test_keys_a_row_on_hsn_uqc_and_rate_together(self):
        summary = aggregate_hsn([
            bill("A", taxable_line(100_00, 1200, hsn="300490", uqc="TBS")),
            bill("B", taxable_line(100_00, 500, hsn="300490", uqc="TBS")),
            bill("C", taxable_line(100_00, 1200, hsn="300490", uqc="BTL")),
            bill("D", taxable_line(100_00, 1200, hsn="300510", uqc="TBS")),
        ])
        assert len(summary.b2c) == 4

    def test_sums_quantity_exactly_across_a_month(self):
        # Decimal, not float: a tenth added thirty times has to be three.
        document = bill("A", *[taxable_line(10_00, qty="0.1") for _ in range(30)])
        assert aggregate_hsn([document]).b2c[0].quantity == Decimal("3.0")

    def test_a_credit_note_reduces_quantity_and_value(self):
        summary = aggregate_hsn([
            bill("A", taxable_line(100_00, qty="10")),
            bill("B", taxable_line(30_00, qty="3"), document_type=DocumentType.CREDIT_NOTE),
        ])
        row = summary.b2c[0]
        assert row.quantity == Decimal("7")
        assert row.taxable_paise == 70_00

    def test_total_value_is_taxable_plus_every_tax(self):
        row = aggregate_hsn([bill("A", taxable_line(100_00))]).b2c[0]
        assert row.total_value_paise == 100_00 + 600 + 600

    def test_collects_lines_with_no_hsn_instead_of_dropping_them(self):
        summary = aggregate_hsn([bill("A", taxable_line(100_00, hsn=None))])
        assert summary.b2c == []
        assert len(summary.lines_without_hsn) == 1
        assert summary.lines_without_hsn[0]["document_id"] == "A"

    def test_collects_lines_with_no_uqc(self):
        summary = aggregate_hsn([bill("A", taxable_line(100_00, uqc=None))])
        assert len(summary.lines_without_uqc) == 1

    def test_records_documents_that_cannot_contribute_at_all(self):
        # A day total has no lines, so it cannot answer Table 12. Saying so is
        # the point - a partial summary presented as whole is worse.
        day = OutwardDocument(
            document_id="DT", sale_date="2026-09-05", tax_period="092026",
            supplier_state_code=OWN_STATE, place_of_supply_state_code=OWN_STATE,
            is_aggregate=True, taxable_paise=1000_00,
        )
        summary = aggregate_hsn([day])
        assert summary.documents_without_lines == ["DT"]

    def test_normalises_a_punctuated_code(self):
        assert aggregate_hsn([bill("A", taxable_line(100_00, hsn="3004.90"))]).b2c[0].hsn == "300490"


class TestDocumentsIssuedTable13:
    def series(self, *documents):
        return {s.series_prefix: s for s in aggregate_documents_issued(documents).series}

    def test_reports_opening_closing_and_counts_per_series(self):
        docs = [
            bill(f"D{n}", taxable_line(100_00), bill_number=f"CTR-{n:06d}",
                 series_prefix="CTR-", serial_sequence=n)
            for n in range(1, 6)
        ]
        summary = self.series(*docs)["CTR-"]
        assert summary.opening_number == "CTR-000001"
        assert summary.closing_number == "CTR-000005"
        assert summary.total_issued == 5
        assert summary.cancelled == 0
        assert summary.net_issued == 5
        assert summary.gaps == []

    def test_counts_a_cancelled_bill_as_issued_then_cancelled(self):
        # It consumed a number. Leaving it out would show a gap instead.
        docs = [
            bill("D1", taxable_line(100_00), bill_number="CTR-000001",
                 series_prefix="CTR-", serial_sequence=1),
            bill("D2", taxable_line(100_00), bill_number="CTR-000002",
                 series_prefix="CTR-", serial_sequence=2,
                 status=DocumentStatus.CANCELLED),
        ]
        summary = self.series(*docs)["CTR-"]
        assert summary.total_issued == 2
        assert summary.cancelled == 1
        assert summary.net_issued == 1
        assert summary.gaps == []

    def test_finds_a_hole_in_the_middle_of_a_series(self):
        docs = [
            bill(f"D{n}", taxable_line(100_00), bill_number=f"CTR-{n:06d}",
                 series_prefix="CTR-", serial_sequence=n)
            for n in (1, 2, 5)
        ]
        summary = self.series(*docs)["CTR-"]
        assert summary.gaps == [3, 4]
        assert aggregate_documents_issued(docs).has_gaps

    def test_keeps_separate_series_apart(self):
        docs = [
            bill("D1", taxable_line(100_00), bill_number="CTR-000001",
                 series_prefix="CTR-", serial_sequence=1),
            bill("D2", taxable_line(100_00), bill_number="EXP-0001",
                 series_prefix="EXP-", serial_sequence=1),
        ]
        summary = self.series(*docs)
        assert set(summary) == {"CTR-", "EXP-"}
        assert all(s.total_issued == 1 for s in summary.values())

    def test_a_draft_still_counts_as_a_number_issued(self):
        docs = [bill("D1", taxable_line(100_00), bill_number="CTR-000001",
                     series_prefix="CTR-", serial_sequence=1,
                     status=DocumentStatus.DRAFT)]
        assert self.series(*docs)["CTR-"].total_issued == 1

    def test_a_day_total_is_not_a_missing_serial(self):
        day = OutwardDocument(
            document_id="DT", sale_date="2026-09-05", tax_period="092026",
            supplier_state_code=OWN_STATE, is_aggregate=True,
        )
        assert aggregate_documents_issued([day]).documents_without_series == []

    def test_a_bill_with_no_serial_is_surfaced(self):
        document = bill("A", taxable_line(100_00))
        assert aggregate_documents_issued([document]).documents_without_series == ["A"]
