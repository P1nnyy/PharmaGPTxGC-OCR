"""Cases are the pack codes and name suffixes this system's own invoices
carry. The rules that must NOT fire get as much coverage as the ones that
must: most short suffixes on Indian brand names are salt abbreviations, and
reading those as dosage forms would attach a confident wrong form to a large
share of the catalogue."""

import pytest

from extraction.normalizers.form_indicators import (
    forms_conflict,
    read_name_modifier,
    read_pack_code,
    strip_pack_code,
)
from extraction.normalizers.product_parser import parse_product_name


class TestPackCodes:
    @pytest.mark.parametrize(
        "token,form,unit,counts",
        [
            ("1×10TA", "Tablet", "TABLET", True),
            ("1X10TA", "Tablet", "TABLET", True),
            ("1×10 T", "Tablet", "TABLET", True),
            ("1X10CA", "Capsule", "CAPSULE", True),
            ("1X200M", None, "ML", False),
            ("1x5ML", None, "ML", False),
            ("1×20GM", None, "GM", False),
        ],
    )
    def test_reads_codes_seen_on_real_invoices(self, token, form, unit, counts):
        code, _ = read_pack_code(token)
        assert code is not None
        assert code.form == form
        assert code.base_unit == unit
        assert code.counts_units is counts

    def test_longest_code_wins(self):
        # "TAB" must not be shortened to "TA", nor "SUSP" to "SU".
        assert read_pack_code("1x10TAB")[1].upper() == "TAB"
        assert read_pack_code("1x60SUSP")[1].upper() == "SUSP"

    def test_unknown_code_is_not_guessed(self):
        assert read_pack_code("1x10ZZ")[0] is None

    def test_no_code_at_all(self):
        assert read_pack_code("1*10")[0] is None
        assert read_pack_code(None)[0] is None

    def test_strip_leaves_the_numbers(self):
        assert strip_pack_code("1×10TA") == "1×10"
        assert strip_pack_code("1×10 T") == "1×10"
        assert strip_pack_code("1*10") == "1*10"


class TestCountVersusMeasure:
    def test_count_code_multiplies_through(self):
        # 1 strip of 10 tablets is 10 dispensable units.
        parsed = parse_product_name("CALCIDEF", "1×10TA")
        assert parsed.pack_multiplier.value == 10
        assert parsed.form.value == "Tablet"

    def test_measure_code_does_not_multiply(self):
        # "1X200M" is ONE 200ml bottle. Multiplying through would claim two
        # hundred bottles and inflate every figure derived from it.
        parsed = parse_product_name("RACIRAFT SYRUP", "1X200M")
        assert parsed.pack_multiplier.value == 1
        assert parsed.pack_size.value == "1x200ML"

    def test_bare_number_after_a_measure_code_is_a_volume(self):
        # "60 ML" strips to "60"; reading that as a count turns one syrup
        # bottle into sixty of them.
        parsed = parse_product_name("MONTICOPE SUSPENSION 60 ML")
        assert parsed.pack_size.value == "60ML"
        assert parsed.pack_multiplier.value == 1

    def test_grams_pack_is_one_tube(self):
        parsed = parse_product_name("SOMECREAM", "1×20GM")
        assert parsed.pack_multiplier.value == 1
        assert parsed.base_unit.value == "GM"


class TestNameModifiers:
    @pytest.mark.parametrize("name,note", [
        ("PRAMIPEX ER 1.5", "extended"),
        ("JALRA DP 100MG SR", "sustained"),
        ("SOMEDRUG XR 10", "extended"),
    ])
    def test_release_markers_imply_a_solid_oral_dose(self, name, note):
        hint = read_name_modifier(name)
        assert hint is not None and hint.form == "Tablet"
        assert note in hint.note
        # Under-determined - could be a capsule - so it must not read as
        # confident.
        assert hint.confidence < 0.6

    @pytest.mark.parametrize("name", ["SIZODON MD 0.5", "SOMEDRUG DT", "SOMEDRUG ODT 10"])
    def test_tablet_markers_are_more_confident(self, name):
        hint = read_name_modifier(name)
        assert hint.form == "Tablet"
        assert hint.confidence >= 0.7

    @pytest.mark.parametrize("name", [
        "DICLOMOL SP",      # serratiopeptidase
        "MONTAIR LC",       # levocetirizine
        "SILODAL D 8",      # dutasteride
        "RANIDOM MPS",      # magaldrate + polysilane
        "CLAVOSAF CV",      # clavulanic acid
        "NUROKIND LC",
    ])
    def test_salt_abbreviations_are_never_read_as_a_form(self, name):
        # The allowlist exists for exactly this: these outnumber the real
        # form hints, and guessing from them would be confidently wrong at
        # catalogue scale.
        assert read_name_modifier(name) is None

    def test_marker_must_be_a_whole_token(self):
        # "AMLOD" ends in OD but is a brand, not a once-daily marker.
        assert read_name_modifier("AMLOD 5") is None
        assert read_name_modifier("ODOMOS") is None

    def test_pack_column_beats_a_release_marker(self):
        # A capsule that is also sustained-release must come out a capsule.
        parsed = parse_product_name("SOMEDRUG SR", "1X10CA")
        assert parsed.form.value == "Capsule"

    def test_modifier_used_only_when_nothing_better_exists(self):
        parsed = parse_product_name("PRAMIPEX ER 1.5", "1*10")
        assert parsed.form.value == "Tablet"
        assert parsed.form.confidence < 0.6


class TestNameAbbreviations:
    """Forms abbreviated in the product name rather than the pack column."""

    @pytest.mark.parametrize("name,form,unit", [
        ("SUNSHADE ULTRA BLOCK LT-50", "Lotion", "ML"),
        ("XYZ LOT 100ML", "Lotion", "ML"),
        ("BETADINE SOL", "Solution", "ML"),
        ("ABC SPR", "Spray", "ML"),
        ("DEF DRP", "Drops", "ML"),
        ("GHI POW", "Powder", "GM"),
        ("JKL INJ", "Injection", "VIAL"),
        ("MNO CAP", "Capsule", "CAPSULE"),
        ("PQR TAB", "Tablet", "TABLET"),
    ])
    def test_reads_the_abbreviation(self, name, form, unit):
        parsed = parse_product_name(name)
        assert parsed.form.value == form
        assert parsed.base_unit.value == unit

    @pytest.mark.parametrize("name,brand", [
        # The form code must be removed as a WHOLE TOKEN. Stripping "LT" as a
        # substring gutted ULTRA and produced a brand of "SUNSHADE U RA BLOCK".
        ("SUNSHADE ULTRA BLOCK LT-50", "SUNSHADE ULTRA BLOCK"),
        ("ULTRACET TAB", "ULTRACET"),
        ("CAPSTAR CAP", "CAPSTAR"),
        ("INJECTAMOL INJ", "INJECTAMOL"),
        ("SALT LOT", "SALT"),
    ])
    def test_abbreviation_is_not_stripped_from_inside_a_word(self, name, brand):
        assert parse_product_name(name).brand.value == brand

    def test_cr_in_a_name_is_release_not_cream(self):
        # The pack column and the product name use CR for different things;
        # reading the name's CR as cream would relabel controlled-release
        # tablets as topicals.
        assert parse_product_name("PANTOCID CR 40").form.value == "Tablet"


class TestSingleContainerForms:
    @pytest.mark.parametrize("name", [
        "SUNSHADE ULTRA BLOCK LT-50", "XYZ CREAM", "BETADINE SOL",
        "RACIRAFT SYRUP", "MOXITOB E/DROPS",
    ])
    def test_container_forms_are_one_unit_per_pack(self, name):
        # A 100ml lotion is one bottle; the number says how much is inside,
        # not how many there are. Left unset these sit in the catalogue
        # permanently flagged for a question with one possible answer.
        assert parse_product_name(name).pack_multiplier.value == 1

    @pytest.mark.parametrize("name,pack", [
        ("CALCIDEF", "1x10TA"),
        ("SILODAL D 8", "1X10CA"),
    ])
    def test_counted_forms_keep_their_real_pack(self, name, pack):
        assert parse_product_name(name, pack).pack_multiplier.value == 10

    def test_a_tablet_with_no_pack_is_not_assumed_to_be_one(self):
        # A strip holds a genuinely countable number. Defaulting to 1 would
        # understate stock by the size of the strip.
        assert parse_product_name("NUROKIND LC TAB").pack_multiplier.value is None


class TestPrecedenceAndConflict:
    def test_spelled_out_form_beats_the_pack_code(self):
        parsed = parse_product_name("RACIRAFT SYRUP", "1X200M")
        assert parsed.form.value == "Syrup"

    def test_disagreement_lowers_confidence_rather_than_picking(self):
        # A name saying SYRUP against a pack column saying tablets is a real
        # contradiction; neither should win silently.
        parsed = parse_product_name("SOMEDRUG SYRUP", "1×10TA")
        assert parsed.form.confidence <= 0.3
        assert "disagree" in parsed.form.evidence

    def test_liquid_wordings_are_not_a_conflict(self):
        # Syrup vs Suspension is a difference in wording, not in what the
        # pharmacist is holding.
        assert not forms_conflict("Syrup", "Suspension")
        assert not forms_conflict("Tablet", "Capsule")
        assert forms_conflict("Tablet", "Syrup")
        assert not forms_conflict("Tablet", None)
        assert not forms_conflict("Tablet", "Tablet")


class TestRealCatalogueRows:
    @pytest.mark.parametrize(
        "name,pack,form,multiplier",
        [
            ("CALCIDEF", "1×10TA", "Tablet", 10),
            ("DICLOMOL SP", "1×10TA", "Tablet", 10),
            ("MONTAIR LC", "1×15TA", "Tablet", 15),
            ("SILODAL D 8", "1X10CA", "Capsule", 10),
            ("MOXITOB E/DROPS", "1x5ML", "Drops", 1),
            ("SIZODON MD 0.5", "1*10", "Tablet", 10),
        ],
    )
    def test_rows_that_previously_resolved_to_nothing(self, name, pack, form, multiplier):
        # Every one of these sat in the catalogue with no form and no units
        # per pack, because the letters defeated the numeric patterns.
        parsed = parse_product_name(name, pack)
        assert parsed.form.value == form
        assert parsed.pack_multiplier.value == multiplier
