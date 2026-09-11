"""The generic day-book / sales-register importer.

Marg and Vyapar exports vary by version, and we have no samples of either, so
guessing their column names would produce an adapter that passes tests written
against the guess and mis-maps a real file. Instead this adapter maps columns
explicitly: it proposes a mapping from the headers it recognises, the user
corrects it, and the correction is remembered for that format.

The reconciliation is what makes a wrong mapping safe to make. A column mapped
to the wrong field almost never still satisfies "tax equals rate times taxable"
and "total equals taxable plus tax", so a mis-mapping is rejected rather than
imported.
"""

import pytest

from services.sales.importers.base import ImportRejected
from services.sales.importers.tabular import TabularAdapter, propose_mapping

CSV = (
    "Invoice No,Date,GST%,Taxable Value,CGST Amt,SGST Amt,Net Amount\n"
    "S-1001,10/09/2026,12,1000.00,60.00,60.00,1120.00\n"
    "S-1002,10/09/2026,5,2000.00,50.00,50.00,2100.00\n"
).encode("utf-8")

MAPPING = {
    "bill_number": "Invoice No",
    "sale_date": "Date",
    "rate": "GST%",
    "taxable": "Taxable Value",
    "cgst": "CGST Amt",
    "sgst": "SGST Amt",
    "total": "Net Amount",
}


class TestSniff:
    def test_recognises_a_csv(self):
        assert TabularAdapter().sniff(CSV, "daybook.csv") is True

    def test_does_not_claim_json(self):
        assert TabularAdapter().sniff(b'{"fp": "092026", "gstin": "x", "b2cs": []}', "r.json") is False

    def test_does_not_claim_an_image(self):
        assert TabularAdapter().sniff(b"\x89PNG\r\n\x1a\n", "bill.png") is False


class TestProposeMapping:
    def test_recognises_common_headers(self):
        proposal = propose_mapping(
            ["Invoice No", "Date", "GST%", "Taxable Value", "CGST Amt", "SGST Amt", "Net Amount"]
        )
        assert proposal["bill_number"] == "Invoice No"
        assert proposal["taxable"] == "Taxable Value"
        assert proposal["rate"] == "GST%"

    def test_leaves_a_header_it_does_not_know_unmapped(self):
        # Better an empty field the user fills in than a confident wrong guess.
        proposal = propose_mapping(["Bill Ref", "Txn Dt", "Slab", "Base", "C", "S", "Gross"])
        assert proposal.get("bill_number") is None

    def test_is_not_confused_by_case_or_spacing(self):
        proposal = propose_mapping(["  invoice no  ", "DATE", "gst %"])
        assert proposal["bill_number"] == "  invoice no  "
        assert proposal["sale_date"] == "DATE"


class TestParse:
    def test_reads_each_bill_into_its_own_sale(self):
        drafts = TabularAdapter().parse(CSV, "daybook.csv", mapping=MAPPING)
        assert [d["bill_number"] for d in drafts] == ["S-1001", "S-1002"]

    def test_reads_the_figures_as_paise(self):
        draft = TabularAdapter().parse(CSV, "daybook.csv", mapping=MAPPING)[0]
        assert draft["taxable_paise"] == 100000
        assert draft["cgst_paise"] == 6000
        assert draft["sgst_paise"] == 6000
        assert draft["grand_total_paise"] == 112000

    def test_reads_a_day_first_date(self):
        # 10/09/2026 is 10 September, the Indian convention these exports use.
        draft = TabularAdapter().parse(CSV, "daybook.csv", mapping=MAPPING)[0]
        assert draft["sale_date"] == "2026-09-10"
        assert draft["tax_period"] == "092026"

    def test_several_rates_on_one_bill_become_rate_blocks(self):
        two_rate = (
            "Invoice No,Date,GST%,Taxable Value,CGST Amt,SGST Amt,Net Amount\n"
            "S-2001,10/09/2026,12,1000.00,60.00,60.00,1120.00\n"
            "S-2001,10/09/2026,5,2000.00,50.00,50.00,2100.00\n"
        ).encode("utf-8")
        drafts = TabularAdapter().parse(two_rate, "d.csv", mapping=MAPPING)
        assert len(drafts) == 1
        assert [b["rate_bp"] for b in drafts[0]["rate_blocks"]] == [500, 1200]
        assert drafts[0]["taxable_paise"] == 300000

    def test_carries_line_detail_rather_than_claiming_to_be_an_aggregate(self):
        draft = TabularAdapter().parse(CSV, "daybook.csv", mapping=MAPPING)[0]
        assert draft["is_aggregate"] is False
        assert draft["rate_source"] == "imported"


class TestReconciliation:
    def test_refuses_a_row_whose_tax_contradicts_its_rate(self):
        bad = (
            "Invoice No,Date,GST%,Taxable Value,CGST Amt,SGST Amt,Net Amount\n"
            "S-3001,10/09/2026,12,1000.00,999.00,999.00,2998.00\n"
        ).encode("utf-8")
        with pytest.raises(ImportRejected, match="S-3001"):
            TabularAdapter().parse(bad, "d.csv", mapping=MAPPING)

    def test_refuses_a_row_whose_total_contradicts_its_parts(self):
        bad = (
            "Invoice No,Date,GST%,Taxable Value,CGST Amt,SGST Amt,Net Amount\n"
            "S-3002,10/09/2026,12,1000.00,60.00,60.00,9999.00\n"
        ).encode("utf-8")
        with pytest.raises(ImportRejected, match="total"):
            TabularAdapter().parse(bad, "d.csv", mapping=MAPPING)

    def test_a_wrong_mapping_is_caught_rather_than_imported(self):
        # This is the whole safety argument for a user-editable mapping: swap
        # taxable and total and the arithmetic stops working, so the file is
        # refused instead of silently importing inflated figures.
        swapped = dict(MAPPING, taxable="Net Amount", total="Taxable Value")
        with pytest.raises(ImportRejected):
            TabularAdapter().parse(CSV, "d.csv", mapping=swapped)


class TestUnusableFiles:
    def test_refuses_a_mapping_that_misses_a_required_field(self):
        with pytest.raises(ImportRejected, match="taxable"):
            TabularAdapter().parse(CSV, "d.csv", mapping={k: v for k, v in MAPPING.items() if k != "taxable"})

    def test_refuses_a_column_the_file_does_not_have(self):
        with pytest.raises(ImportRejected, match="Nonexistent"):
            TabularAdapter().parse(CSV, "d.csv", mapping=dict(MAPPING, taxable="Nonexistent"))

    def test_refuses_an_empty_file(self):
        with pytest.raises(ImportRejected):
            TabularAdapter().parse(b"", "d.csv", mapping=MAPPING)

    def test_refuses_a_row_with_an_unreadable_date(self):
        bad = (
            "Invoice No,Date,GST%,Taxable Value,CGST Amt,SGST Amt,Net Amount\n"
            "S-4001,not-a-date,12,1000.00,60.00,60.00,1120.00\n"
        ).encode("utf-8")
        with pytest.raises(ImportRejected, match="date"):
            TabularAdapter().parse(bad, "d.csv", mapping=MAPPING)
