"""Deterministic dedupe keys.

The house rules call duplicate ingestion the highest-severity class of bug in
this codebase. On the purchase side a duplicate double-claims input tax credit;
on the sales side it double-declares output tax. Either way the return is
wrong, so the key that prevents it is worth pinning by test.
"""

import pytest

from core.idempotency import content_hash, dedupe_key


class TestContentHash:
    def test_is_stable_for_the_same_bytes(self):
        assert content_hash(b"same") == content_hash(b"same")

    def test_differs_for_different_bytes(self):
        assert content_hash(b"a") != content_hash(b"b")

    def test_a_single_flipped_byte_changes_it(self):
        # A re-photographed bill is a different image; the same file uploaded
        # twice is not.
        assert content_hash(b"invoice-page-1") != content_hash(b"invoice-page-2")

    def test_is_hex_and_fixed_length(self):
        digest = content_hash(b"anything")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_refuses_anything_that_is_not_bytes(self):
        with pytest.raises(TypeError):
            content_hash("a string")


class TestDedupeKey:
    def test_is_stable_across_calls(self):
        assert dedupe_key("ph1", "DAY_TOTAL", "2026-09-10") == dedupe_key("ph1", "DAY_TOTAL", "2026-09-10")

    def test_separates_tenants(self):
        # The single most important property here: two shops declaring the
        # same day must never collide onto one record.
        assert dedupe_key("ph1", "DAY_TOTAL", "2026-09-10") != dedupe_key("ph2", "DAY_TOTAL", "2026-09-10")

    def test_separates_capture_modes(self):
        assert dedupe_key("ph1", "DAY_TOTAL", "x") != dedupe_key("ph1", "IMPORT", "x")

    def test_is_not_confusable_by_shifting_a_separator(self):
        # Naive joining lets ("a", "bc") and ("ab", "c") produce one key, which
        # would silently merge two different documents.
        assert dedupe_key("a", "bc") != dedupe_key("ab", "c")

    def test_normalises_incidental_differences(self):
        # A bill number retyped with different spacing or case is the same
        # bill, and treating it as new would let it be filed twice.
        assert dedupe_key("ph1", "IMPORT", " inv-001 ") == dedupe_key("ph1", "IMPORT", "INV-001")

    def test_a_missing_part_is_distinct_from_an_empty_one(self):
        assert dedupe_key("ph1", None) != dedupe_key("ph1", "")

    def test_refuses_an_empty_key(self):
        with pytest.raises(ValueError):
            dedupe_key()
