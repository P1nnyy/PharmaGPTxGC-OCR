"""The document role: is this a bill we received, or one we issued?

The same parser reads both. What differs is who "we" are on the page — the
buyer on a purchase invoice, the seller on our own counter bill — and that
decides whether the tax on it is input tax or output tax. Getting it backwards
would put a sale into the purchase register and claim credit on our own
output, so the resolution is pinned by test.

Layout heuristics settle the ordinary case. When the shop's own GSTIN is known
the answer stops being a heuristic altogether, and that is what the role is
for.
"""

import pytest

from extraction.normalizers.canonical_invoice import DocumentRole
from extraction.normalizers.azure_invoice_normalizer import assign_parties_by_role

OURS = "27AAAAA0000A1Z5"
THEIRS = "29BBBBB1111B1Z4"


class TestPurchase:
    def test_our_gstin_belongs_in_the_buyer_slot(self):
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.PURCHASE, seller_gstin=THEIRS, buyer_gstin=OURS, own_gstin=OURS
        )
        assert (seller, buyer, swapped) == (THEIRS, OURS, False)

    def test_swaps_when_the_reader_put_us_in_the_seller_slot(self):
        # Azure mislabels VendorTaxId and CustomerTaxId on invoices that print
        # both parties side by side. Knowing our own number settles it.
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.PURCHASE, seller_gstin=OURS, buyer_gstin=THEIRS, own_gstin=OURS
        )
        assert (seller, buyer, swapped) == (THEIRS, OURS, True)


class TestSale:
    def test_our_gstin_belongs_in_the_seller_slot(self):
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.SALE, seller_gstin=OURS, buyer_gstin=THEIRS, own_gstin=OURS
        )
        assert (seller, buyer, swapped) == (OURS, THEIRS, False)

    def test_swaps_when_the_reader_put_us_in_the_buyer_slot(self):
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.SALE, seller_gstin=THEIRS, buyer_gstin=OURS, own_gstin=OURS
        )
        assert (seller, buyer, swapped) == (OURS, THEIRS, True)

    def test_a_counter_bill_to_an_unregistered_customer_has_no_buyer(self):
        # The overwhelmingly common case: a walk-in customer has no GSTIN.
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.SALE, seller_gstin=OURS, buyer_gstin=None, own_gstin=OURS
        )
        assert (seller, buyer, swapped) == (OURS, None, False)

    def test_puts_us_in_the_seller_slot_even_if_the_reader_found_nothing_there(self):
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.SALE, seller_gstin=None, buyer_gstin=OURS, own_gstin=OURS
        )
        assert (seller, buyer) == (OURS, None)
        assert swapped is True


class TestWithoutOurGstin:
    def test_leaves_the_layout_heuristic_alone(self):
        # No own GSTIN means nothing to match against, so whatever the
        # page-position heuristic decided stands. Inventing a swap here would
        # trade a rare error for a common one.
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.SALE, seller_gstin=THEIRS, buyer_gstin=None, own_gstin=None
        )
        assert (seller, buyer, swapped) == (THEIRS, None, False)


class TestGstinComparison:
    def test_ignores_spacing_and_case(self):
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.SALE, seller_gstin=" 27aaaaa0000a1z5 ", buyer_gstin=None, own_gstin=OURS
        )
        assert swapped is False
        # The value read off the page is kept as read, not overwritten with
        # our stored spelling: what the document says is evidence.
        assert seller == " 27aaaaa0000a1z5 "

    def test_a_different_number_is_not_us(self):
        seller, buyer, swapped = assign_parties_by_role(
            DocumentRole.SALE, seller_gstin=THEIRS, buyer_gstin=THEIRS, own_gstin=OURS
        )
        assert swapped is False


class TestRoles:
    def test_only_two_roles_exist(self):
        assert DocumentRole.ALL == {DocumentRole.PURCHASE, DocumentRole.SALE}

    def test_purchase_is_the_default_everywhere(self):
        # Every existing caller reads purchase invoices, so the parameter has
        # to be additive or it changes behaviour it was not meant to touch.
        from extraction.normalizers.azure_invoice_normalizer import normalize_azure_invoice
        import inspect

        signature = inspect.signature(normalize_azure_invoice)
        assert signature.parameters["document_role"].default == DocumentRole.PURCHASE
        assert signature.parameters["own_gstin"].default is None
