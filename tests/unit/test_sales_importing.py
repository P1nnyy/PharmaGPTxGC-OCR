"""Previewing and committing an import, with the graph stubbed.

Two behaviours matter most here and neither is about parsing. First, a preview
writes nothing — a mis-mapped column has to be visible before it is stored, not
after. Second, importing the same file twice does not import it twice, and
importing a file that has grown by a day imports only the new day.
"""

import json
from unittest.mock import patch

import pytest

from core.tenancy import tenant_scope
from services.sales.importers.base import ImportRejected
from services.sales.importers.registry import detect, describe
from services.sales.importing import commit_import, preview_import

CSV = (
    "Invoice No,Date,GST%,Taxable Value,CGST Amt,SGST Amt,Net Amount\n"
    "S-1001,10/09/2026,12,1000.00,60.00,60.00,1120.00\n"
    "S-1002,10/09/2026,5,2000.00,50.00,50.00,2100.00\n"
).encode("utf-8")

GSTR1 = json.dumps({
    "gstin": "27AAAAA0000A1Z5",
    "fp": "092026",
    "b2cs": [{"sply_ty": "INTRA", "typ": "OE", "pos": "27", "rt": 12.0,
              "txval": 1000.00, "camt": 60.00, "samt": 60.00}],
}).encode("utf-8")


@pytest.fixture(autouse=True)
def workspace():
    with tenant_scope("ph-1"):
        yield


@pytest.fixture(autouse=True)
def no_stored_mapping():
    with patch("db.repositories.sales_repository.get_import_mapping", return_value=None), \
         patch("db.repositories.sales_repository.find_by_source_file_hash", return_value=[]):
        yield


class TestDetection:
    def test_picks_the_gstr1_adapter_for_a_return(self):
        assert detect(GSTR1, "returns.json").name == "gstr1_json"

    def test_picks_the_tabular_adapter_for_a_day_book(self):
        assert detect(CSV, "daybook.csv").name == "tabular"

    def test_refuses_a_file_it_does_not_recognise(self):
        with pytest.raises(ImportRejected, match="Could not tell"):
            detect(b"\x89PNG\r\n\x1a\n", "photo.png")

    def test_lists_what_it_supports(self):
        assert {f["name"] for f in describe()} == {"gstr1_json", "tabular"}


class TestPreview:
    def test_writes_nothing(self):
        with patch("db.repositories.sales_repository.upsert_sale") as write:
            preview_import(CSV, "daybook.csv")
        write.assert_not_called()

    def test_reports_the_per_rate_totals_the_file_would_produce(self):
        result = preview_import(CSV, "daybook.csv")
        assert result["rejected"] is False
        rates = [b["rate_bp"] for b in result["summary"]["rate_blocks"]]
        assert rates == [500, 1200]
        assert result["summary"]["taxable_paise"] == 300000
        assert result["summary"]["document_count"] == 2

    def test_offers_a_mapping_and_the_headers_behind_it(self):
        result = preview_import(CSV, "daybook.csv")
        assert result["mapping"]["taxable"] == "Taxable Value"
        assert "Net Amount" in result["headers"]

    def test_a_rejected_file_still_comes_back_with_its_headers(self):
        # The user has to be able to fix the mapping, which means seeing the
        # columns even though the parse failed.
        broken = dict(preview_import(CSV, "d.csv")["mapping"], taxable="Net Amount", total="Taxable Value")
        result = preview_import(CSV, "d.csv", mapping=broken)
        assert result["rejected"] is True
        assert result["reason"]
        assert result["headers"]
        assert result["drafts"] == []

    def test_prefers_a_remembered_mapping_over_a_fresh_proposal(self):
        remembered = {"bill_number": "Invoice No", "sale_date": "Date", "rate": "GST%",
                      "taxable": "Taxable Value", "cgst": "CGST Amt", "sgst": "SGST Amt",
                      "total": "Net Amount"}
        with patch("db.repositories.sales_repository.get_import_mapping", return_value=remembered):
            result = preview_import(CSV, "daybook.csv")
        assert result["mapping"] == remembered

    def test_says_when_this_file_has_been_seen_before(self):
        with patch("db.repositories.sales_repository.find_by_source_file_hash", return_value=[{"id": "s1"}]):
            result = preview_import(CSV, "daybook.csv")
        assert result["already_imported"] == 1


class TestCommit:
    def test_writes_one_sale_per_bill(self):
        with patch("db.repositories.sales_repository.upsert_sale", side_effect=lambda **kw: ({"id": kw["dedupe_key"][:8]}, True)), \
             patch("db.repositories.sales_repository.save_import_mapping"):
            result = commit_import(CSV, "daybook.csv", created_by="u-1")
        assert result["created_count"] == 2
        assert result["skipped_count"] == 0

    def test_skips_documents_already_imported_from_this_file(self):
        # Re-uploading a day book that gained a row must import the row, not
        # the whole file again.
        calls = {"n": 0}

        def upsert(**kwargs):
            calls["n"] += 1
            return {"id": f"s{calls['n']}"}, calls["n"] > 1

        with patch("db.repositories.sales_repository.upsert_sale", side_effect=upsert), \
             patch("db.repositories.sales_repository.save_import_mapping"):
            result = commit_import(CSV, "daybook.csv")
        assert result["created_count"] == 1
        assert result["skipped_count"] == 1

    def test_two_places_of_supply_do_not_collide_on_one_key(self):
        # A GSTR-1 return has no bill numbers, so without a discriminator the
        # second place of supply would be swallowed as a duplicate.
        two_pos = json.dumps({
            "gstin": "27AAAAA0000A1Z5", "fp": "092026",
            "b2cs": [
                {"sply_ty": "INTRA", "typ": "OE", "pos": "27", "rt": 12.0,
                 "txval": 1000.00, "camt": 60.00, "samt": 60.00},
                {"sply_ty": "INTER", "typ": "OE", "pos": "29", "rt": 12.0,
                 "txval": 2000.00, "camt": 0, "samt": 0, "iamt": 240.00},
            ],
        }).encode("utf-8")

        keys = []

        def upsert(**kwargs):
            keys.append(kwargs["dedupe_key"])
            return {"id": kwargs["dedupe_key"][:8]}, True

        with patch("db.repositories.sales_repository.upsert_sale", side_effect=upsert), \
             patch("db.repositories.sales_repository.save_import_mapping"):
            commit_import(two_pos, "returns.json")
        assert len(keys) == 2
        assert len(set(keys)) == 2

    def test_remembers_the_mapping_that_worked(self):
        with patch("db.repositories.sales_repository.upsert_sale", return_value=({"id": "s1"}, True)), \
             patch("db.repositories.sales_repository.save_import_mapping") as remember:
            commit_import(CSV, "daybook.csv")
        remember.assert_called_once()
        assert remember.call_args[0][0] == "tabular"

    def test_can_be_told_not_to_remember(self):
        with patch("db.repositories.sales_repository.upsert_sale", return_value=({"id": "s1"}, True)), \
             patch("db.repositories.sales_repository.save_import_mapping") as remember:
            commit_import(CSV, "daybook.csv", remember_mapping=False)
        remember.assert_not_called()

    def test_a_file_that_does_not_reconcile_writes_nothing(self):
        bad = (
            "Invoice No,Date,GST%,Taxable Value,CGST Amt,SGST Amt,Net Amount\n"
            "S-9001,10/09/2026,12,1000.00,999.00,999.00,2998.00\n"
        ).encode("utf-8")
        with patch("db.repositories.sales_repository.upsert_sale") as write, \
             patch("db.repositories.sales_repository.save_import_mapping"):
            with pytest.raises(ImportRejected):
                commit_import(bad, "daybook.csv")
        write.assert_not_called()

    def test_everything_lands_as_a_draft(self):
        captured = []

        def upsert(**kwargs):
            captured.append(kwargs)
            return {"id": "s1"}, True

        with patch("db.repositories.sales_repository.upsert_sale", side_effect=upsert), \
             patch("db.repositories.sales_repository.save_import_mapping"):
            commit_import(CSV, "daybook.csv")
        assert {c["status"] for c in captured} == {"DRAFT"}
        assert {c["capture_mode"] for c in captured} == {"IMPORT"}
