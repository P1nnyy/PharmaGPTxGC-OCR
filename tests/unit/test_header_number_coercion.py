"""Money typed on the review screen is stored as a number.

The review screen holds whatever the reviewer typed, so an edited field
arrives as text. Stored as text it breaks every consumer that adds it up -
reports sum cgst+sgst+igst, the review screen calls toFixed on them - and it
does so far from the edit that caused it.
"""

import pytest

from db.repositories.invoice_repository import (
    _NUMERIC_HEADER_FIELDS, _EDITABLE_HEADER_FIELDS, _to_stored_number,
)


class TestCoercion:
    @pytest.mark.parametrize("typed,expected", [
        ("89.08", 89.08),
        ("  89.08  ", 89.08),
        ("1,234.56", 1234.56),
        ("0", 0.0),
        ("-12.5", -12.5),
        (89.08, 89.08),
        (5, 5.0),
    ])
    def test_reads_what_a_person_would_type(self, typed, expected):
        assert _to_stored_number(typed) == expected

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_an_empty_box_clears_the_field_rather_than_storing_zero(self, blank):
        # A zero tax is a claim about the invoice; absence is not the same
        # claim, and storing 0.0 would assert something nobody typed.
        assert _to_stored_number(blank) is None

    @pytest.mark.parametrize("junk", ["abc", "--", "1.2.3", "₹"])
    def test_unparseable_text_becomes_none_rather_than_being_kept(self, junk):
        assert _to_stored_number(junk) is None

    def test_returns_a_float_even_for_integers(self):
        # Mixed int/float in the graph makes later comparisons inconsistent.
        assert isinstance(_to_stored_number("5"), float)


class TestFieldLists:
    def test_every_numeric_field_is_also_editable(self):
        # A field that is coerced but not writable would be dead code; one
        # that is writable but not coerced is the bug this module exists for.
        assert _NUMERIC_HEADER_FIELDS <= _EDITABLE_HEADER_FIELDS

    def test_the_tax_components_are_editable(self):
        # The point of the change: a failed scan leaves these empty and the
        # reviewer must be able to put the figure back.
        for field in ("cgst", "sgst", "igst"):
            assert field in _EDITABLE_HEADER_FIELDS
            assert field in _NUMERIC_HEADER_FIELDS
