"""Count suffixes on packs that are measured, not counted.

Indian distributors print "N" (for "numbers") on every pack regardless of what
is in it. On a tablet strip that is true; on a 100ml solution it is
boilerplate, and reading it as a count both labels the pack "1x100N" beside a
dispensing unit of ML and multiplies the stock figure by a hundred.
"""

import pytest

from extraction.normalizers.form_indicators import PACK_CODES, read_pack_code
from extraction.normalizers.product_parser import (
    _measure_pack_display, _parse_pack_token, parse_product_name,
)


class TestTheMissingCode:
    def test_bare_n_is_recognised(self):
        # Unrecognised, the whole token matched no numeric pattern and was
        # stored as opaque text with no units per pack derived.
        code, _ = read_pack_code("1X100N")
        assert code is not None
        assert PACK_CODES["N"].counts_units is True

    def test_an_n_pack_now_parses_instead_of_falling_through(self):
        display, multiplier, _, _ = _parse_pack_token("1X100N")
        assert display == "1*100"
        assert multiplier == 100

    def test_the_multiplication_sign_variant_parses_too(self):
        # OCR returns × for the same glyph.
        assert _parse_pack_token("1×100N")[0] == "1*100"


class TestMeasuredForms:
    @pytest.mark.parametrize("name,pack,expected_pack,expected_units", [
        ("BETADINE SOL 10", "1X100N", "1x100ML", 1),
        ("MONTICOPE SUSPENSION", "1X60N", "1x60ML", 1),
        ("LULIFIN CREAM", "1X30N", "1x30GM", 1),
    ])
    def test_a_count_suffix_yields_to_the_form(self, name, pack, expected_pack, expected_units):
        parsed = parse_product_name(name, pack)
        assert parsed.pack_size.value == expected_pack
        # One bottle, not a hundred of something.
        assert parsed.pack_multiplier.value == expected_units

    def test_the_evidence_explains_the_override(self):
        parsed = parse_product_name("BETADINE SOL 10", "1X100N")
        assert "size, not a count" in (parsed.pack_multiplier.evidence or "")


class TestCountedFormsAreUntouched:
    def test_tablets_keep_their_count(self):
        # A strip really does hold a countable number; assuming 1 here would
        # understate stock by the size of the strip.
        parsed = parse_product_name("CALPOL 650 TABLET", "10X10N")
        assert parsed.pack_size.value == "10*10"
        assert parsed.pack_multiplier.value == 100

    def test_capsules_keep_their_count(self):
        parsed = parse_product_name("ALLEGRA 120MG", "1X10TA")
        assert parsed.pack_multiplier.value == 10


class TestTheRewriteItself:
    @pytest.mark.parametrize("display,unit,expected", [
        ("1*100", "ML", ("1x100ML", 1)),
        ("1*30", "GM", ("1x30GM", 1)),
        ("100'S", "ML", ("100ML", 1)),
    ])
    def test_rewrites_count_shapes(self, display, unit, expected):
        assert _measure_pack_display(display, unit) == expected

    def test_leaves_a_pack_that_already_states_its_unit(self):
        # "60x5ML" is sixty vials of 5ml - the outer number is a real count.
        assert _measure_pack_display("60x5ML", "ML") is None

    def test_leaves_counted_units_alone(self):
        assert _measure_pack_display("10*10", "TABLET") is None

    def test_needs_a_unit_to_rewrite_to(self):
        assert _measure_pack_display("1*100", None) is None
        assert _measure_pack_display("1*100", "") is None

    def test_leaves_shapes_it_does_not_recognise(self):
        # An unregistered suffix is left as printed rather than guessed at.
        assert _measure_pack_display("1X5DO", "ML") is None
