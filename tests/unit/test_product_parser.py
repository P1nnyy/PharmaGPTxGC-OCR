"""Parser cases are taken from names this system has actually extracted, not
invented ones - the whole point of the module is surviving the shapes real
distributors emit."""

import pytest

from extraction.normalizers.product_parser import (
    build_identity_key,
    infer_schedule,
    normalize_name,
    parse_product_name,
)


class TestNormalizeName:
    def test_collapses_case_and_whitespace(self):
        assert normalize_name("  monticope   Suspension ") == "MONTICOPE SUSPENSION"

    def test_hyphen_becomes_space_not_nothing(self):
        # MAHAFLOX and MAHAFLOX-LP are different products, so the separator
        # has to survive as a token break rather than being deleted outright.
        assert normalize_name("MAHAFLOX-LP") == "MAHAFLOX LP"
        assert normalize_name("DYNAPAR-QPS") == normalize_name("DYNAPAR QPS")

    def test_empty_input(self):
        assert normalize_name("") == ""
        assert normalize_name(None) == ""


class TestFormAndUnit:
    @pytest.mark.parametrize(
        "name,form,unit",
        [
            ("LUBIMOIST EYE DROPS", "Eye Drops", "ML"),
            ("MAHAFLOX-LP EYE DROPS", "Eye Drops", "ML"),
            ("MONTICOPE SUSPENSION 60 ML", "Suspension", "ML"),
            ("RANIDOM-MPS SUSP", "Suspension", "ML"),
            ("NUROKIND LC TAB", "Tablet", "TABLET"),
            ("LIVO-LUK SOLUTION 200ML", "Solution", "ML"),
            ("BECOSULES CAPSULES", "Capsule", "CAPSULE"),
            ("MONOCEF 1GM INJ", "Injection", "VIAL"),
        ],
    )
    def test_reads_form_and_base_unit(self, name, form, unit):
        parsed = parse_product_name(name)
        assert parsed.form.value == form
        assert parsed.base_unit.value == unit

    def test_specific_route_beats_generic_drops(self):
        # "Drops" alone would lose the route, and an eye drop is not
        # interchangeable with an oral drop.
        assert parse_product_name("XYZ EAR DROPS").form.value == "Ear Drops"
        assert parse_product_name("XYZ NASAL SPRAY").form.value == "Nasal Spray"

    def test_no_form_word_leaves_form_unknown(self):
        parsed = parse_product_name("DONEP")
        assert parsed.form.value is None
        assert "form" in parsed.unresolved


class TestStrength:
    def test_spaced_and_unspaced_strength_agree(self):
        assert parse_product_name("LIPIGO 10 MG").strength.value == "10MG"
        assert parse_product_name("LIPIGO 10MG").strength.value == "10MG"

    def test_combination_strength_preserved(self):
        assert parse_product_name("AUGMENTIN 500+125MG").strength.value == "500+125MG"

    def test_microgram_and_percent(self):
        assert parse_product_name("THYRONORM 25MCG").strength.value == "25MCG"
        assert parse_product_name("MOMETASONE 0.1%").strength.value == "0.1%"

    @pytest.mark.parametrize(
        "name,strength",
        [
            ("ALPRAX 0.5MG", "0.5MG"),
            ("THYRONORM 12.5MCG", "12.5MCG"),
            ("TELMA 5/10MG", "5/10MG"),
        ],
    )
    def test_decimal_and_ratio_strengths_survive_normalization(self, name, strength):
        # Flattening the separator here would write a tenfold dosing error
        # into the catalogue.
        assert parse_product_name(name).strength.value == strength

    def test_hyphen_number_is_low_confidence_strength(self):
        parsed = parse_product_name("NITROLONG-2.6 MANKINDS PLACIDA")
        assert parsed.strength.value == "2.6"
        assert parsed.strength.confidence < 0.5
        # and it is removed from the brand rather than counted twice
        assert "2.6" not in parsed.brand.value

    def test_millilitres_are_not_read_as_strength(self):
        # 200ML on LIVO-LUK is the bottle, not the dose.
        parsed = parse_product_name("LIVO-LUK SOLUTION 200ML")
        assert parsed.strength.value is None
        assert parsed.pack_size.value == "200ML"


class TestPackAndMultiplier:
    def test_grid_pack_multiplies_both_numbers(self):
        # 10 strips of 10 is 100 tablets. Taking only the inner number would
        # under-count the box by 10x.
        parsed = parse_product_name("SOMEDRUG", pack_column="10*10")
        assert parsed.pack_size.value == "10*10"
        assert parsed.pack_multiplier.value == 100

    def test_single_strip(self):
        parsed = parse_product_name("SOMEDRUG", pack_column="1*10")
        assert parsed.pack_multiplier.value == 10

    @pytest.mark.parametrize("token", ["10'S", "10S", "10 'S", "10"])
    def test_count_forms_agree(self, token):
        assert parse_product_name("SOMEDRUG", pack_column=token).pack_multiplier.value == 10

    def test_volume_pack_is_one_dispensable_unit(self):
        parsed = parse_product_name("MONTICOPE SUSPENSION 60 ML")
        assert parsed.pack_size.value == "60ML"
        assert parsed.pack_multiplier.value == 1

    def test_pack_column_outranks_name(self):
        # A dedicated column is a statement; a token inside a name is a guess.
        parsed = parse_product_name("SOMEDRUG 15'S", pack_column="1*10")
        assert parsed.pack_multiplier.value == 10
        assert parsed.pack_size.confidence > 0.8

    def test_missing_pack_is_reported_unresolved(self):
        parsed = parse_product_name("NUROKIND LC TAB")
        assert parsed.pack_multiplier.value is None
        assert "pack_multiplier" in parsed.unresolved


class TestBrand:
    @pytest.mark.parametrize(
        "name,brand",
        [
            ("LIPIGO 10 MG", "LIPIGO"),
            ("NUROKIND LC TAB", "NUROKIND LC"),
            ("MONTICOPE SUSPENSION 60 ML", "MONTICOPE"),
            ("DYNAPAR QPS 30 ML", "DYNAPAR QPS"),
            ("LIVO-LUK SOLUTION 200ML", "LIVO LUK"),
        ],
    )
    def test_brand_is_what_remains(self, name, brand):
        assert parse_product_name(name).brand.value == brand

    def test_plus_variant_stays_distinct(self):
        # DYNAPAR QPS and DYNAPAR QPS PLUS appear on the same bill and are
        # different products.
        a = parse_product_name("DYNAPAR QPS 30 ML")
        b = parse_product_name("DYNAPAR QPS PLUS 30 ML")
        assert a.brand.value != b.brand.value
        assert a.identity_key != b.identity_key


class TestIdentityKey:
    def test_same_sku_spelled_differently_converges(self):
        # This is the merge the catalogue needs: one SKU, two renderings.
        a = parse_product_name("MONTICOPE SUSPENSION 60 ML")
        b = parse_product_name("MONTICOPE SUSP 60ML")
        assert a.identity_key == b.identity_key

    def test_different_strength_stays_apart(self):
        a = parse_product_name("DONEP 5MG")
        b = parse_product_name("DONEP 10MG")
        assert a.identity_key != b.identity_key

    def test_unknown_components_collapse_together(self):
        # Two bare DONEPs merge by default and carry the missing_strength
        # flag; the price spread across observations is what exposes it if
        # they were really 5mg and 10mg.
        a = parse_product_name("DONEP")
        b = parse_product_name("donep")
        assert a.identity_key == b.identity_key
        assert "strength" in a.unresolved

    def test_key_is_deterministic(self):
        assert build_identity_key("DONEP", None, None, None) == "DONEP|?|?|?"


class TestEdgeCases:
    def test_empty_name_reports_everything_unresolved(self):
        parsed = parse_product_name("")
        assert parsed.brand.value is None
        assert "brand" in parsed.unresolved

    def test_none_name(self):
        assert parse_product_name(None).identity_key == "?|?|?|?"

    def test_every_field_carries_evidence_when_known(self):
        parsed = parse_product_name("MONTICOPE SUSPENSION 60 ML")
        for field in ("brand", "form", "pack_size"):
            guess = getattr(parsed, field)
            assert guess.evidence, f"{field} claimed a value with no evidence"


class TestSchedule:
    def test_reads_printed_schedule(self):
        assert infer_schedule("ALPRAX 0.5MG SCHEDULE H1").value == "Schedule H1"

    def test_does_not_guess_from_brand(self):
        # A compliance claim nobody checked is worse than a blank field.
        assert infer_schedule("ALPRAX 0.5MG").value is None
