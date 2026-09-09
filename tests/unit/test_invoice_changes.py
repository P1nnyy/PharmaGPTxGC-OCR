"""The per-field change log.

What makes this trail worth keeping is that it survives being asked a
specific question months later - "who changed the tax, and from what?" - so
the tests are about the before value being right, and about not burying real
edits under saves that changed nothing.
"""

from services.invoices.changes import (
    as_details, header_changes, line_item_change, summarise,
)


class TestNoise:
    def test_resending_an_unchanged_field_is_not_a_change(self):
        # The review screen sends every field on every save. Without this,
        # one edit would be logged as fifteen.
        before = {"discount": 227.4, "seller_name": "Mahajan"}
        after = {"discount": 227.4, "seller_name": "Mahajan"}
        assert header_changes(before, after) == []

    def test_a_number_retyped_in_another_form_is_not_a_change(self):
        # "227.40" typed over a stored 227.4 is the same figure.
        assert header_changes({"discount": 227.4}, {"discount": "227.40"}) == []

    def test_float_noise_is_not_a_change(self):
        assert header_changes({"cgst": 89.08}, {"cgst": 89.0800001}) == []

    def test_blank_over_absent_is_not_a_change(self):
        assert header_changes({"igst": None}, {"igst": "  "}) == []

    def test_a_field_the_request_omitted_is_not_reported(self):
        # The update will not touch it, so the log must not claim it did.
        assert header_changes({"discount": 10.0, "cgst": 5.0}, {"cgst": 5.0}) == []


class TestRealEdits:
    def test_records_both_sides_of_the_change(self):
        [change] = header_changes({"cgst": 178.16}, {"cgst": "89.08"})
        assert change["label"] == "CGST"
        assert change["from"] == "178.16"
        assert change["to"] == "89.08"

    def test_filling_an_empty_field_names_the_absence(self):
        # "from empty" is the case this whole feature exists for: extraction
        # missed the tax and a reviewer typed it in.
        [change] = header_changes({"sgst": None}, {"sgst": "89.08"})
        assert change["from"] == "empty"
        assert change["to"] == "89.08"

    def test_clearing_a_field_is_recorded_too(self):
        [change] = header_changes({"sgst": 89.08}, {"sgst": ""})
        assert change["to"] == "empty"

    def test_text_changes_are_recorded_verbatim(self):
        [change] = header_changes({"seller_name": "Mahajan"}, {"seller_name": "Mahajan Medical"})
        assert (change["from"], change["to"]) == ("Mahajan", "Mahajan Medical")

    def test_untracked_fields_are_ignored(self):
        assert header_changes({"status": "needs_review"}, {"status": "verified"}) == []


class TestLineItems:
    def test_a_row_count_change_is_summarised(self):
        assert line_item_change(16, 17)["to"] == "17"

    def test_an_unchanged_count_reports_nothing(self):
        # Rows are resent wholesale, so equal counts are the common case.
        assert line_item_change(16, 16) is None

    def test_untouched_rows_report_nothing(self):
        assert line_item_change(16, None) is None

    def test_emptying_the_table_is_recorded(self):
        assert line_item_change(16, 0)["from"] == "16"


class TestReadability:
    def test_a_single_change_reads_as_a_sentence(self):
        changes = header_changes({"cgst": 178.16}, {"cgst": "89.08"})
        assert summarise("Pranav", changes) == "Pranav changed CGST from 178.16 to 89.08"

    def test_several_changes_are_listed(self):
        changes = header_changes(
            {"cgst": 1.0, "sgst": 1.0}, {"cgst": "2.0", "sgst": "2.0"})
        assert summarise("Pranav", changes) == "Pranav changed CGST and SGST"

    def test_many_changes_are_counted_rather_than_listed(self):
        before = {k: 1.0 for k in ("cgst", "sgst", "igst", "discount", "roundoff")}
        after = {k: "2.0" for k in before}
        assert "5 fields" in summarise("Pranav", header_changes(before, after))

    def test_a_save_with_no_changes_says_so(self):
        assert summarise("Pranav", []) == "Pranav saved the invoice with no changes"

    def test_details_flatten_for_storage(self):
        # Neo4j cannot hold a list of maps on a node.
        details = as_details(header_changes({"cgst": 178.16}, {"cgst": "89.08"}))
        assert details == ["CGST: 178.16 -> 89.08"]
        assert all(isinstance(d, str) for d in details)
