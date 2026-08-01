"""Tests for multi-page invoice merging.

Figures are taken from a real two-page invoice (Arora Bros Medi Linkers, bill
GST-15168, 28/07/2026) so the totals behaviour is pinned to something that
actually exists rather than to invented numbers.
"""

import pytest

from extraction.normalizers.canonical_invoice import CanonicalInvoice, CanonicalLineItem
from extraction.normalizers.invoice_merger import (
    check_pages_consistent,
    merge_invoice_pages,
)

# Page 1: eleven items, no totals block (the sheet continues overleaf).
PAGE1_AMOUNTS = [152.00, 260.00, 123.00, 160.00, 173.00, 81.00, 135.00, 72.00, 222.00, 75.00, 300.00]
# Page 2: five items, plus the totals block covering the WHOLE order.
PAGE2_AMOUNTS = [159.00, 153.00, 43.50, 79.00, 90.00]

PAGE1_SUM = 1753.00
PAGE2_SUM = 524.50
PRINTED_TOTAL = 2277.50           # equals PAGE1_SUM + PAGE2_SUM
PRINTED_NET = 2278.00


def _items(amounts, prefix):
    return [
        CanonicalLineItem(name=f"{prefix}-{i}", amount=a, quantity=1)
        for i, a in enumerate(amounts, start=1)
    ]


def page_one(**overrides) -> CanonicalInvoice:
    data = dict(
        invoice_number="GST-15168",
        invoice_date="2026-07-28",
        seller_name="ARORA BROS MEDI LINKERS",
        seller_gstin="03AACPA7667E1ZN",
        buyer_name="RAM CHAND & SONS",
        buyer_gstin="03AAJFR4013K1ZE",
        line_items=_items(PAGE1_AMOUNTS, "P1"),
        confidence=0.85,
        extraction_engine="azure_document_intelligence",
    )
    data.update(overrides)
    return CanonicalInvoice(**data)


def page_two(**overrides) -> CanonicalInvoice:
    data = dict(
        invoice_number="GST-15168",
        invoice_date="2026-07-28",
        seller_name="ARORA BROS MEDI LINKERS",
        seller_gstin="03AACPA7667E1ZN",
        line_items=_items(PAGE2_AMOUNTS, "P2"),
        subtotal=PRINTED_TOTAL,
        discount=151.42,
        cgst=75.86,
        sgst=75.86,
        roundoff=0.20,
        grand_total=PRINTED_NET,
        confidence=0.65,
        extraction_engine="azure_document_intelligence",
    )
    data.update(overrides)
    return CanonicalInvoice(**data)


# --------------------------------------------------------------------------
# Line items
# --------------------------------------------------------------------------

def test_line_items_concatenate_in_page_order():
    merged = merge_invoice_pages([page_one(), page_two()])
    assert len(merged.line_items) == 16
    assert merged.line_items[0].name == "P1-1"
    assert merged.line_items[10].name == "P1-11"
    assert merged.line_items[11].name == "P2-1"
    assert merged.line_items[15].name == "P2-5"


def test_page_order_is_respected_when_reversed():
    """The user chooses page order; the merger must not re-sort."""
    merged = merge_invoice_pages([page_two(), page_one()])
    assert merged.line_items[0].name == "P2-1"
    assert merged.line_items[5].name == "P1-1"


# --------------------------------------------------------------------------
# Totals - the part that would silently corrupt the books if wrong
# --------------------------------------------------------------------------

def test_totals_are_not_summed_across_pages():
    merged = merge_invoice_pages([page_one(), page_two()])
    assert merged.subtotal == PRINTED_TOTAL
    assert merged.grand_total == PRINTED_NET


def test_carried_forward_subtotal_does_not_double_count():
    """Some distributors print a running subtotal on every page. Taking the
    last page's complete block must ignore the earlier carry-forward rather
    than adding to it."""
    carried = page_one(subtotal=PAGE1_SUM)
    merged = merge_invoice_pages([carried, page_two()])
    assert merged.subtotal == PRINTED_TOTAL
    assert merged.subtotal != PAGE1_SUM + PRINTED_TOTAL


def test_totals_block_is_taken_whole_not_field_by_field():
    """Mixing an early page's subtotal with the last page's grand total would
    produce an internally inconsistent set that fails the review math check."""
    merged = merge_invoice_pages([page_one(subtotal=999.99, discount=5.0), page_two()])
    assert merged.subtotal == PRINTED_TOTAL
    assert merged.discount == 151.42
    assert merged.cgst == 75.86
    assert merged.roundoff == 0.20


def test_merged_totals_reconcile_with_line_items():
    """subtotal - discount + tax + roundoff == grand_total, and the line items
    sum to the subtotal."""
    merged = merge_invoice_pages([page_one(), page_two()])
    assert round(sum(i.amount for i in merged.line_items), 2) == PRINTED_TOTAL
    derived = merged.subtotal - merged.discount + merged.cgst + merged.sgst + merged.roundoff
    assert round(derived, 2) == PRINTED_NET


def test_subtotal_falls_back_to_line_items_when_no_page_has_totals():
    merged = merge_invoice_pages([page_one(), page_two(subtotal=None, grand_total=None)])
    assert merged.subtotal == round(PAGE1_SUM + PAGE2_SUM, 2)


def test_last_page_with_grand_total_wins():
    a = page_one(subtotal=100.0, grand_total=100.0)
    b = page_two()
    assert merge_invoice_pages([a, b]).grand_total == PRINTED_NET


# --------------------------------------------------------------------------
# Header identity
# --------------------------------------------------------------------------

def test_header_taken_from_first_page_supplying_it():
    merged = merge_invoice_pages([page_one(), page_two()])
    assert merged.invoice_number == "GST-15168"
    assert merged.seller_name == "ARORA BROS MEDI LINKERS"
    assert merged.buyer_gstin == "03AAJFR4013K1ZE"


def test_continuation_page_supplies_missing_header_fields():
    """A page 1 that omitted a field should be filled from a later page."""
    merged = merge_invoice_pages([page_one(buyer_name=None), page_two(buyer_name="RAM CHAND & SONS")])
    assert merged.buyer_name == "RAM CHAND & SONS"


def test_confidence_is_bounded_by_weakest_page():
    merged = merge_invoice_pages([page_one(), page_two()])
    assert merged.confidence == 0.65


def test_metadata_records_page_provenance():
    merged = merge_invoice_pages([page_one(), page_two()])
    meta = merged.raw_engine_metadata
    assert meta["multipage"] is True
    assert meta["page_count"] == 2
    assert meta["totals_source_page"] == 2
    assert meta["line_items_per_page"] == [11, 5]


# --------------------------------------------------------------------------
# Degenerate inputs
# --------------------------------------------------------------------------

def test_single_page_passes_through_unchanged():
    only = page_one()
    assert merge_invoice_pages([only]) is only


def test_empty_input_rejected():
    with pytest.raises(ValueError):
        merge_invoice_pages([])


# --------------------------------------------------------------------------
# Consistency checking
# --------------------------------------------------------------------------

def test_matching_pages_are_consistent():
    report = check_pages_consistent([page_one(), page_two()])
    assert report.is_consistent
    assert not [c for c in report.conflicts if c.severity == "hard"]


def test_different_invoice_numbers_flagged_hard():
    report = check_pages_consistent([page_one(), page_two(invoice_number="GST-99999")])
    assert not report.is_consistent
    assert any(c.field == "invoice_number" and c.severity == "hard" for c in report.conflicts)


def test_different_seller_gstin_flagged_hard():
    report = check_pages_consistent([page_one(), page_two(seller_gstin="03ZZZZZ9999Z1ZZ")])
    assert not report.is_consistent


def test_different_date_is_soft_only():
    """A misread date should warn but not block - OCR gets dates wrong more
    often than it invents a whole different invoice number."""
    report = check_pages_consistent([page_one(), page_two(invoice_date="2026-07-29")])
    assert report.is_consistent
    assert any(c.field == "invoice_date" and c.severity == "soft" for c in report.conflicts)


def test_absent_field_on_continuation_page_is_not_a_conflict():
    """Continuation pages legitimately omit header fields; absence must not
    read as disagreement."""
    report = check_pages_consistent([page_one(), page_two(invoice_number=None, seller_gstin=None)])
    assert report.is_consistent
    assert not report.conflicts


def test_case_and_spacing_differences_are_not_conflicts():
    report = check_pages_consistent([page_one(), page_two(seller_name="arora  bros   medi linkers")])
    assert report.is_consistent


def test_missing_invoice_number_everywhere_warns():
    report = check_pages_consistent(
        [page_one(invoice_number=None), page_two(invoice_number=None)]
    )
    assert any("could not be automatically confirmed" in w for w in report.warnings)


def test_multiple_totals_pages_warn():
    report = check_pages_consistent([page_one(grand_total=100.0), page_two()])
    assert any("more than one page carries a final total" in w.lower() for w in report.warnings)


def test_single_page_is_trivially_consistent():
    assert check_pages_consistent([page_one()]).is_consistent


# --------------------------------------------------------------------------
# Fuzzy name comparison
#
# Real case that motivated this: Azure read page 2 of the Gurkirat invoice as
# "GURKIE" - a partial catch of the diagonal watermark - against page 1's
# "GURKIRAT MEDICOS". Flagging that as a conflict on a perfectly valid invoice
# trains the user to dismiss the confirmation dialog without reading it.
# --------------------------------------------------------------------------

def test_partial_seller_name_is_not_a_conflict():
    """The observed case: page 2 of the Gurkirat invoice OCR'd as "GURKIE",
    a partial catch of the diagonal watermark."""
    report = check_pages_consistent(
        [page_one(seller_name="GURKIRAT MEDICOS"), page_two(seller_name="GURKIE")]
    )
    assert report.is_consistent
    assert not [c for c in report.conflicts if c.field == "seller_name"]


def test_truncated_seller_name_is_not_a_conflict():
    report = check_pages_consistent([page_one(), page_two(seller_name="ARORA BROS")])
    assert not [c for c in report.conflicts if c.field == "seller_name"]


def test_genuinely_different_seller_names_still_flagged():
    report = check_pages_consistent(
        [page_one(seller_name="GURKIRAT MEDICOS"), page_two(seller_name="MAHAJAN MEDICINE CO")]
    )
    assert any(c.field == "seller_name" for c in report.conflicts)


def test_different_pharmacies_sharing_a_suffix_still_flagged():
    """'MEDICOS' is a common suffix - two different distributors must not be
    treated as the same page set just because both end in it."""
    report = check_pages_consistent(
        [page_one(seller_name="GURKIRAT MEDICOS"), page_two(seller_name="JEEVAN MEDICOS")]
    )
    assert any(c.field == "seller_name" for c in report.conflicts)


def test_consecutive_invoice_numbers_are_never_fuzzy_matched():
    """The dangerous case: A002571 and A002572 are two different invoices from
    the same supplier that differ by one character. Identifiers must compare
    exactly or two real invoices get welded into one."""
    report = check_pages_consistent(
        [page_one(invoice_number="A002571"), page_two(invoice_number="A002572")]
    )
    assert not report.is_consistent
    assert any(c.field == "invoice_number" and c.severity == "hard" for c in report.conflicts)


def test_gstin_off_by_one_character_still_flagged():
    report = check_pages_consistent(
        [page_one(seller_gstin="03AACPA7667E1ZN"), page_two(seller_gstin="03AACPA7667E1ZM")]
    )
    assert not report.is_consistent


def test_same_gstin_read_differently_across_pages_is_not_a_conflict():
    """Observed on the Arora Bros invoice: the seller GSTIN came back as
    ...F1ZN on one page and ...FIZN on the other - one identifier, two
    readings of the same glyph. Blocking that would make the user override a
    correct upload."""
    report = check_pages_consistent([
        page_one(seller_gstin="03AACFA7667F1ZN"),
        page_two(seller_gstin="03AACFA7667FIZN"),
    ])
    assert report.is_consistent
    assert not report.conflicts


def test_buyer_gstin_look_alike_is_not_a_conflict():
    report = check_pages_consistent([
        page_one(buyer_gstin="03AAJFR4013K1ZE"),
        page_two(buyer_gstin="03AAJFR4013KIZE"),
    ])
    assert not [c for c in report.conflicts if c.field == "buyer_gstin"]


def test_digits_never_collapse_so_sequential_ids_stay_distinct():
    """The safety property the identifier comparison relies on: every
    look-alike group contains at most one digit, so two different digits can
    never be treated as equal."""
    from extraction.normalizers.azure_invoice_normalizer import _OCR_VISUAL_GROUPS
    for representative, chars in _OCR_VISUAL_GROUPS.items():
        digits = [c for c in chars if c.isdigit()]
        assert len(digits) <= 1, f"group {representative!r} merges digits {digits}"


def test_invoice_number_differing_by_a_real_digit_still_conflicts():
    report = check_pages_consistent([
        page_one(invoice_number="A002571"),
        page_two(invoice_number="A002572"),
    ])
    assert not report.is_consistent
