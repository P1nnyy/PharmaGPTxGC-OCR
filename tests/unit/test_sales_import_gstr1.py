"""The GSTR-1 JSON importer.

The universal fallback: almost every Indian billing package can emit a GSTR-1
JSON, so a shop whose day-book format we have never seen can still get its
outward supplies in. It is also the least ambiguous source we accept — the
schema states taxable value and tax separately, so nothing has to be inferred
about whether a figure includes tax.

Which is exactly why the reconciliation is strict here. If the file's own
declared tax does not match its declared rate and taxable value, the file is
internally inconsistent and importing it would carry that inconsistency into a
return.
"""

import json

import pytest

from services.sales.importers.base import ImportRejected
from services.sales.importers.gstr1_json import Gstr1JsonAdapter


def a_file(**overrides) -> bytes:
    payload = {
        "gstin": "27AAAAA0000A1Z5",
        "fp": "092026",
        "b2cs": [
            {"sply_ty": "INTRA", "typ": "OE", "pos": "27", "rt": 12.0,
             "txval": 100000.00, "camt": 6000.00, "samt": 6000.00, "csamt": 0}
        ],
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class TestSniff:
    def test_recognises_a_gstr1_payload(self):
        assert Gstr1JsonAdapter().sniff(a_file()) is True

    def test_rejects_a_csv(self):
        assert Gstr1JsonAdapter().sniff(b"Invoice No,Date,Amount\n1,2026-09-10,100") is False

    def test_rejects_json_that_is_not_a_return(self):
        assert Gstr1JsonAdapter().sniff(b'{"hello": "world"}') is False

    def test_rejects_bytes_that_are_not_text(self):
        assert Gstr1JsonAdapter().sniff(b"\x89PNG\r\n\x1a\n") is False


class TestParse:
    def test_reads_a_b2cs_row_into_a_rate_block(self):
        drafts = Gstr1JsonAdapter().parse(a_file())
        assert len(drafts) == 1
        draft = drafts[0]
        assert draft["tax_period"] == "092026"
        block = draft["rate_blocks"][0]
        assert block["rate_bp"] == 1200
        assert block["taxable_paise"] == 10_000_000
        assert block["cgst_paise"] == 600_000
        assert block["sgst_paise"] == 600_000

    def test_the_header_sums_the_blocks(self):
        drafts = Gstr1JsonAdapter().parse(
            a_file(b2cs=[
                {"sply_ty": "INTRA", "typ": "OE", "pos": "27", "rt": 12.0,
                 "txval": 1000.00, "camt": 60.00, "samt": 60.00},
                {"sply_ty": "INTRA", "typ": "OE", "pos": "27", "rt": 5.0,
                 "txval": 2000.00, "camt": 50.00, "samt": 50.00},
            ])
        )
        draft = drafts[0]
        assert draft["taxable_paise"] == 300000
        assert draft["cgst_paise"] == 11000
        assert draft["sgst_paise"] == 11000

    def test_one_sale_per_place_of_supply(self):
        # B2CS is reported per place of supply, and two states are two
        # different figures in the return, not one.
        drafts = Gstr1JsonAdapter().parse(
            a_file(b2cs=[
                {"sply_ty": "INTRA", "typ": "OE", "pos": "27", "rt": 12.0,
                 "txval": 1000.00, "camt": 60.00, "samt": 60.00},
                {"sply_ty": "INTER", "typ": "OE", "pos": "29", "rt": 12.0,
                 "txval": 2000.00, "camt": 0, "samt": 0, "iamt": 240.00},
            ])
        )
        assert len(drafts) == 2
        assert {d["place_of_supply"] for d in drafts} == {"27", "29"}

    def test_reads_the_nil_section_into_its_three_buckets(self):
        drafts = Gstr1JsonAdapter().parse(
            a_file(nil={"inv": [
                {"sply_ty": "INTRB2C", "expt_amt": 500.00, "nil_amt": 300.00, "ngsup_amt": 200.00}
            ]})
        )
        draft = drafts[0]
        assert draft["exempt_paise"] == 50000
        assert draft["nil_rated_paise"] == 30000
        assert draft["non_gst_paise"] == 20000

    def test_marks_the_record_as_an_aggregate(self):
        draft = Gstr1JsonAdapter().parse(a_file())[0]
        assert draft["is_aggregate"] is True
        assert draft["rate_source"] == "gstr1"


class TestReconciliation:
    def test_refuses_a_file_whose_tax_contradicts_its_own_rate(self):
        # 12% of 1000 is 120, not 200. The file is internally inconsistent and
        # importing it would carry that into a return.
        with pytest.raises(ImportRejected, match="12"):
            Gstr1JsonAdapter().parse(
                a_file(b2cs=[
                    {"sply_ty": "INTRA", "typ": "OE", "pos": "27", "rt": 12.0,
                     "txval": 1000.00, "camt": 100.00, "samt": 100.00}
                ])
            )

    def test_accepts_a_single_paisa_of_rounding_in_the_halves(self):
        # 5% of 1234.57 is 61.7285 -> 61.73, which cannot halve evenly.
        drafts = Gstr1JsonAdapter().parse(
            a_file(b2cs=[
                {"sply_ty": "INTRA", "typ": "OE", "pos": "27", "rt": 5.0,
                 "txval": 1234.57, "camt": 30.86, "samt": 30.87}
            ])
        )
        assert drafts[0]["cgst_paise"] + drafts[0]["sgst_paise"] == 6173


class TestUnusableFiles:
    def test_refuses_a_file_with_no_period(self):
        with pytest.raises(ImportRejected, match="period"):
            Gstr1JsonAdapter().parse(a_file(fp=None))

    def test_refuses_a_malformed_period(self):
        with pytest.raises(ImportRejected):
            Gstr1JsonAdapter().parse(a_file(fp="2026-09"))

    def test_refuses_a_file_with_nothing_to_import(self):
        with pytest.raises(ImportRejected, match="nothing"):
            Gstr1JsonAdapter().parse(a_file(b2cs=[]))

    def test_refuses_broken_json(self):
        with pytest.raises(ImportRejected):
            Gstr1JsonAdapter().parse(b"{not json")
