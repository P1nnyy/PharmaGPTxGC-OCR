"""Matching invoice names against the reference catalogue.

Every case here is drawn from the live catalogue and the real reference
export. The bias throughout is that refusing to answer is cheap and answering
wrongly is not: a wrong strength or pack multiplier written into master data
is silent, permanent, and corrupts every stock figure derived from it.
"""

import pytest

from enrichment.reference_match import (
    FORM_MAP,
    build_query,
    block_key,
    canon_strength,
    propose,
    score_row,
    split_name,
    strip_pack,
    unexplained_words,
)


def row(brand_name, **overrides) -> dict:
    base = {
        "brand_name": brand_name,
        "manufacturer": "Micro Labs Ltd",
        "dosage_form": "tablet",
        "pack_size": 10.0,
        "pack_unit": "strip",
        "primary_strength": "10mg",
        "ingredient_count": 1,
        "composition": None,
        "therapeutic_class": None,
        "price_inr": 100.0,
        "discontinued": 0,
    }
    base.update(overrides)
    return base


class TestNameSplitting:
    @pytest.mark.parametrize("name, expected_pack", [
        ("TRIOLMESAR 20 15'S", 15.0),
        ("ROSEDAY 5 15 'S", 15.0),
        ("THYROX 50 (120S)", 120.0),
        ("CARCA 3.125 20TAB", 20.0),
        ("PANTOP 40 1*15", 15.0),
    ])
    def test_pack_expressions_are_removed_from_the_name(self, name, expected_pack):
        # Left in, the pack count reads as a second variant number and the
        # product matches nothing: TRIOLMESAR 20 15'S would be looking for a
        # listing that names both 20 and 15.
        cleaned, pack = strip_pack(name)
        assert pack == expected_pack
        assert "15'S" not in cleaned and "120S" not in cleaned

    def test_a_dose_welded_to_a_unit_is_not_a_brand_word(self):
        parts = split_name("GLYCOMET 1GM")
        assert parts.words == ["GLYCOMET"]
        assert parts.strengths == ["1GM"]

    def test_bare_numbers_stay_as_variant_discriminators(self):
        parts = split_name("ROSEDAY 5")
        assert parts.words == ["ROSEDAY"]
        assert parts.numbers == ["5"]

    def test_form_words_are_not_part_of_the_brand(self):
        assert split_name("ZERODOL P TABLET").words == ["ZERODOL", "P"]

    def test_block_key_is_the_first_brand_word(self):
        assert block_key("TRIOLMESAR 20 15'S") == "TRIOLMESAR"
        assert block_key("1*10") is None


class TestStrengthCanonicalisation:
    def test_grams_and_milligrams_compare_equal(self):
        assert canon_strength("1GM") == canon_strength("1000mg")

    def test_micrograms_are_converted(self):
        assert canon_strength("500mcg") == canon_strength("0.5mg")

    def test_different_doses_stay_different(self):
        assert canon_strength("5mg") != canon_strength("10mg")


class TestDisqualification:
    """The rules that keep near-identical products apart."""

    def test_a_word_we_state_that_the_reference_lacks_disqualifies(self):
        # The case that made TELPLUS and TELPLUS TRIO resolve to one product.
        query = build_query("TELPLUS TRIO 15S")
        assert score_row(query, row("Telplus Tablet")) is None

    def test_a_release_suffix_only_the_reference_states_is_forgiven(self):
        # Invoices omit PR/SR; the row is still the same medicine at the same
        # strength, form and maker - which is all this module proposes.
        query = build_query("GLYCOMET GP 1 15 `S")
        assert score_row(query, row("Glycomet-GP 1 Tablet PR", ingredient_count=2)) is not None

    def test_an_unknown_word_only_the_reference_states_still_disqualifies(self):
        query = build_query("ZERODOL P")
        assert score_row(query, row("Zerodol MR Tablet")) is None

    def test_variant_numbers_must_match_as_a_set_not_merely_overlap(self):
        # GP 2/850 and GP 3/850 share the 850. An intersection test passes
        # them; they are different medicines.
        query = build_query("GLYCOMET GP 2/850")
        assert score_row(query, row("Glycomet-GP 3/850 Tablet SR")) is None
        assert score_row(query, row("Glycomet-GP 2/850 Tablet SR")) is not None

    def test_a_dose_stated_in_our_name_must_agree(self):
        query = build_query("GLYCOMET 1GM")
        assert score_row(query, row("Glycomet Tablet", primary_strength="500mg")) is None
        assert score_row(query, row("Glycomet Tablet", primary_strength="1000mg")) is not None

    def test_a_dose_the_catalogue_already_holds_must_agree(self):
        query = build_query("ROSEDAY", strength="10MG")
        assert score_row(query, row("Roseday Tablet", primary_strength="5mg")) is None
        assert score_row(query, row("Roseday Tablet", primary_strength="10mg")) is not None

    def test_a_bare_variant_number_pins_the_listing_not_the_dose(self):
        # "ROSEDAY 5" names the variant the way the reference names it, so the
        # number has to match the listing's number. It is deliberately not
        # read as a dose: for combinations the number in the name refers to
        # one component (GLYCOMET GP 2 is glimepiride 2mg), so treating it as
        # the product's strength would be wrong far more often than not.
        query = build_query("ROSEDAY 5")
        assert score_row(query, row("Roseday 5 Tablet")) is not None
        assert score_row(query, row("Roseday 10 Tablet")) is None

    def test_a_known_form_that_contradicts_disqualifies(self):
        query = build_query("MONTICOPE", form="Suspension")
        assert score_row(query, row("Monticope Tablet")) is None

    def test_an_unrelated_name_never_matches(self):
        assert score_row(build_query("ZOLFRESH"), row("Zerodol P Tablet")) is None


class TestUnexplainedWords:
    def test_a_moved_separator_is_not_an_extra_word(self):
        assert unexplained_words(split_name("LIVO LUK"), split_name("LIVOLUK")) == []

    def test_an_ocr_misread_is_not_an_extra_word(self):
        assert unexplained_words(split_name("MONTICOPE"), split_name("MONTIC0PE")) == []

    def test_a_genuine_extra_word_is_reported(self):
        assert unexplained_words(split_name("TELPLUS TRIO"), split_name("TELPLUS")) == ["TRIO"]


class TestConsensus:
    """Fields are filled by agreement among survivors, never by the winner."""

    def test_unanimous_fields_are_proposed(self):
        query = build_query("ROSEDAY 5")
        rows = [row("Roseday 5 Tablet", pack_size=10.0), row("Roseday 5 Tablet PR", pack_size=10.0)]
        result = propose(query, [{**r, "primary_strength": "5mg"} for r in rows])
        assert result["fields"]["strength"] == "5MG"
        assert result["fields"]["form"] == "Tablet"
        assert result["fields"]["base_unit"] == "TABLET"

    def test_a_contested_strength_is_never_proposed(self):
        query = build_query("THYROX")
        rows = [
            row("Thyrox Tablet", primary_strength="50mcg"),
            row("Thyrox Tablet SR", primary_strength="75mcg"),
        ]
        result = propose(query, rows)
        assert "strength" not in result["fields"]
        assert any(c["field"] == "strength" for c in result["contested"])

    def test_a_combination_product_never_gets_a_single_strength(self):
        # Telplus reports primary_strength 10mg and is Cilnidipine 10mg with
        # Telmisartan 40mg. "TELPLUS 10MG" would read as a 10mg telmisartan.
        query = build_query("TELPLUS")
        result = propose(query, [row(
            "Telplus Tablet",
            ingredient_count=2,
            primary_strength="10mg",
            composition="Cilnidipine 10mg + Telmisartan 40mg",
        )])
        assert "strength" not in result["fields"]
        assert result["composition"] == "Cilnidipine 10mg + Telmisartan 40mg"
        assert any("combination product" in c["reason"] for c in result["contested"])

    def test_the_invoices_own_pack_is_never_overwritten(self):
        # The reference knows which packs exist; the invoice knows which one
        # was bought, and it is a record of a real transaction.
        query = build_query("TELPLUS 15S", pack_multiplier=15)
        result = propose(query, [row("Telplus Tablet", pack_size=10.0, ingredient_count=2)])
        assert "pack_multiplier" not in result["fields"]
        assert any(
            c["field"] == "pack_multiplier" and "pack of 15" in c["reason"]
            for c in result["contested"]
        )

    def test_a_pack_we_do_not_know_is_offered(self):
        query = build_query("ZERODOL P")
        result = propose(query, [row("Zerodol-P Tablet", pack_size=10.0)])
        assert result["fields"]["pack_multiplier"] == 10.0

    def test_no_survivors_reports_no_match_rather_than_a_guess(self):
        result = propose(build_query("SOMETHINGELSE"), [row("Telplus Tablet")])
        assert result["status"] == "no_match"
        assert result["fields"] == {}

    def test_the_form_vocabulary_maps_onto_the_catalogue(self):
        # A form the catalogue cannot express must not be proposed at all -
        # "other" names nothing, and would overwrite a blank with a non-answer.
        assert "other" not in FORM_MAP
        for canonical, unit in FORM_MAP.values():
            assert canonical and unit

    def test_candidates_travel_with_the_proposal(self):
        # The reviewer's real question is which listing this is, so the
        # alternatives are returned alongside the fields.
        query = build_query("THYROX")
        result = propose(query, [
            row("Thyrox Tablet", primary_strength="50mcg"),
            row("Thyrox Tablet SR", primary_strength="75mcg"),
        ])
        assert len(result["candidates"]) == 2
        assert {c["primary_strength"] for c in result["candidates"]} == {"50mcg", "75mcg"}


class TestProposalBuckets:
    """How a proposal is split into what can be applied and what must be asked.

    The distinction matters because the batch action applies one bucket
    without a person reading each row. Anything that could be a real
    disagreement has to fall outside it.
    """

    def connection_free_product(self, **overrides) -> dict:
        base = {
            "id": "p1",
            "canonical_name": "TELPLUS 15S",
            "brand": "TELPLUS",
            "aliases": [{"id": "a1", "raw_name": "TELPLUS 15S"}],
            "strength": None, "form": None, "pack_size": None,
            "pack_multiplier": None, "base_unit": None, "manufacturer": None,
        }
        base.update(overrides)
        return base

    def test_a_truncated_manufacturer_is_an_expansion_not_a_conflict(self):
        from enrichment.reference_service import _is_expansion
        assert _is_expansion("MICR", "Micro Labs Ltd")
        assert _is_expansion("MACLEODS PHARM", "Macleods Pharmaceuticals Pvt Ltd")

    def test_a_bare_strength_gaining_its_unit_is_an_expansion(self):
        from enrichment.reference_service import _is_expansion
        assert _is_expansion("5", "5MG")
        assert _is_expansion("1.5", "1.5MG")

    def test_a_different_company_is_a_real_conflict(self):
        from enrichment.reference_service import _is_expansion
        # Billed as Cipla, made by Sanofi - a person should look at that.
        assert not _is_expansion("CIPL", "Sanofi India Ltd")

    def test_a_two_character_code_is_too_short_to_trust_as_a_prefix(self):
        from enrichment.reference_service import _is_expansion
        assert not _is_expansion("SU", "Sun Pharmaceutical Industries Ltd")

    def test_a_different_dose_is_a_real_conflict(self):
        from enrichment.reference_service import _is_expansion
        assert not _is_expansion("5MG", "10MG")


class TestCombinationStrength:
    """A combination's strength, when the invoice's own name settles it.

    The source's `primary_strength` is whichever ingredient was listed first,
    so it can never be used directly. But the figure the distributor printed
    usually names a component, and reading it off is not a guess - it is what
    the line says. Refusing every combination outright left strengths blank
    that the invoice had stated plainly.
    """

    def combo(self, strengths, **overrides):
        return row(
            overrides.pop("brand_name", "Triolmesar 20 Tablet"),
            ingredient_count=len(strengths.split("|")),
            ingredient_strengths=strengths,
            primary_strength=strengths.split("|")[0],
            **overrides,
        )

    def test_one_figure_in_the_name_selects_one_ingredient(self):
        result = propose(
            build_query("TRIOLMESAR 20 15'S"),
            [self.combo("20mg|5mg", composition="Olmesartan Medoxomil 20mg + Amlodipine 5mg")],
        )
        assert result["fields"]["strength"] == "20MG"

    def test_both_figures_in_the_name_select_both_ingredients(self):
        result = propose(
            build_query("GLYCOMET GP 2/850"),
            [self.combo("2mg|850mg", brand_name="Glycomet-GP 2/850 Tablet SR")],
        )
        assert result["fields"]["strength"] == "2MG+850MG"

    def test_a_figure_welded_into_a_word_still_counts(self):
        # DIAPRIDE M4 - the 4 is inside the token, not a standalone number.
        result = propose(
            build_query("DIAPRIDE M4 FORTE"),
            [self.combo("4mg|1000mg", brand_name="Diapride M4 Forte Tablet PR")],
        )
        assert result["fields"]["strength"] == "4MG"

    def test_a_name_that_pins_nothing_still_refuses(self):
        # The case the whole rule exists to protect: primary_strength says
        # 10mg, and a pharmacist reading "TELPLUS 10MG" would understand a
        # 10mg telmisartan. Nothing in the name settles it, so nothing is said.
        result = propose(
            build_query("TELPLUS 15S"),
            [self.combo("10mg|40mg", brand_name="Telplus Tablet",
                        composition="Cilnidipine 10mg + Telmisartan 40mg")],
        )
        assert "strength" not in result["fields"]
        assert any("states no figure" in c["reason"] for c in result["contested"])

    def test_a_pack_count_is_never_mistaken_for_a_dose(self):
        # "15'S" is stripped before any number is read, so the 15 cannot
        # select a 15mg ingredient that has nothing to do with the pack.
        result = propose(
            build_query("SOMEBRAND 15'S"),
            [self.combo("15mg|500mg", brand_name="Somebrand Tablet")],
        )
        assert "strength" not in result["fields"]

    def test_survivors_must_agree_on_the_pinned_strength(self):
        result = propose(
            build_query("GLYCOMET GP 2"),
            [
                self.combo("2mg|500mg", brand_name="Glycomet-GP 2 Tablet"),
                self.combo("2mg|850mg", brand_name="Glycomet-GP 2 Tablet SR"),
            ],
        )
        # One row pins 2mg, the other 2mg as well - the 500/850 are not named
        # by the invoice, so both resolve to the same answer.
        assert result["fields"]["strength"] == "2MG"


class TestPackagingProse:
    """The reference spells its packaging out in the brand name.

    "Hyperneb 3% Respules (4ml Each)" is a Cipla nebuliser that the index
    plainly contained, and the single word EACH was enough to reject it -
    the extra-word rule could not tell packaging prose from a product line.
    """

    def test_prose_in_the_reference_name_does_not_block_a_match(self):
        query = build_query("HYPERNEB 3%")
        assert score_row(query, row("Hyperneb 3% Respules (4ml Each)",
                                    dosage_form="respules", primary_strength=None)) is not None

    def test_a_kit_is_still_a_different_product(self):
        # SET and COMBIPACK say the item is a kit, not a single unit, so they
        # are deliberately not treated as prose.
        query = build_query("ZERODOL")
        assert score_row(query, row("Zerodol Combipack")) is None


class TestStrengthStatedInTheReferenceName:
    """Some rows carry their strength only in the name, with an empty column."""

    def test_a_percentage_in_the_name_separates_two_products(self):
        # Both Hyperneb rows have no primary_strength at all, so comparing
        # against the column alone let 3% and 7% both survive - and the answer
        # was then decided by whatever the two happened to share.
        query = build_query("HYPERNEB 3%")
        assert score_row(query, row("Hyperneb 7% Respules (4ml Each)",
                                    dosage_form="respules", primary_strength=None)) is None
        assert score_row(query, row("Hyperneb 3% Respules (4ml Each)",
                                    dosage_form="respules", primary_strength=None)) is not None

    def test_a_volume_in_the_name_is_not_weighed_against_a_percentage(self):
        # "(4ml Each)" states a volume. It says nothing about whether the
        # percentages agree, so it must not be compared against one.
        query = build_query("HYPERNEB 3%")
        assert score_row(query, row("Hyperneb 3% Respules (4ml Each)",
                                    dosage_form="respules", primary_strength=None)) is not None


class TestDoseAgainstEveryIngredient:
    """A stated dose is checked against ALL of a row's strengths.

    `primary_strength` is whichever ingredient the source listed first, which
    on a combination is arbitrary. Comparing against it alone is the same trap
    that made TELPLUS report 10mg - only here it caused the opposite failure,
    throwing away a perfect name match because the invoice named the second
    ingredient rather than the first.
    """

    def test_a_dose_matching_the_second_ingredient_is_accepted(self):
        # JALRA DP 100MG against Jalra-DP Tablet SR: Dapagliflozin 10mg +
        # Vildagliptin 100mg. Zero unexplained words on either side, and the
        # 100 is a real component.
        query = build_query("JALRA DP 100MG SR", strength="100MG")
        candidate = row("Jalra-DP Tablet SR", ingredient_count=2,
                        primary_strength="10mg", ingredient_strengths="10mg|100mg")
        assert score_row(query, candidate) is not None

    def test_a_dose_matching_no_ingredient_is_still_a_conflict(self):
        query = build_query("JALRA DP 250MG SR", strength="250MG")
        candidate = row("Jalra-DP Tablet SR", ingredient_count=2,
                        primary_strength="10mg", ingredient_strengths="10mg|100mg")
        assert score_row(query, candidate) is None

    def test_single_ingredient_rows_are_unaffected(self):
        query = build_query("ZOLFRESH", strength="10MG")
        assert score_row(query, row("Zolfresh Tablet", primary_strength="5mg",
                                    ingredient_strengths="5mg")) is None
        assert score_row(query, row("Zolfresh Tablet", primary_strength="10mg",
                                    ingredient_strengths="10mg")) is not None

    def test_a_row_with_no_breakdown_falls_back_to_its_column(self):
        query = build_query("SOMEBRAND", strength="10MG")
        assert score_row(query, row("Somebrand Tablet", primary_strength="10mg",
                                    ingredient_strengths=None)) is not None


class TestNamesAsDistributorsPrintThem:
    """Shapes the invoices actually use that the reference does not.

    Each of these was a whole class of silent misses - the product sat in the
    index and the name simply could not reach it.
    """

    def test_a_number_welded_to_a_word_is_separated(self):
        # ECOSPRIN GOLD20 against Ecosprin Gold 20 Tablet.
        parts = split_name("ECOSPRIN GOLD20")
        assert parts.words == ["ECOSPRIN", "GOLD"]
        assert parts.numbers == ["20"]

    def test_an_ocr_digit_inside_a_word_is_left_alone(self):
        # The counterpart rule. Splitting on every digit shattered MONTIC0PE
        # into MONTIC, 0, PE - the exact spelling the matcher must forgive.
        assert split_name("MONTIC0PE").words == ["MONTIC0PE"]

    def test_a_dose_is_never_split_from_its_unit(self):
        assert split_name("AUGMENTIN 625MG").strengths == ["625MG"]

    def test_a_pack_welded_to_the_brand_is_stripped(self):
        # "1X20GMBETADINE OINT" - the pack ran into the name and the block key
        # became a string no reference row could share.
        query = build_query("1X20GMBETADINE OINT")
        assert query.parts.words == ["BETADINE"]
        assert query.pack_multiplier == 20.0

    def test_an_eye_drop_abbreviation_never_becomes_a_product_marker(self):
        # "E\\D" is eye drops. Flattened into the tokens E and D it could match
        # "Moxi D Eye Drop" - a different medicine - so this one risked a wrong
        # answer, not merely a miss.
        assert split_name(r"MOXI-P E\D").words == ["MOXI", "P"]
        assert split_name("MOXI-P EYEDROPS").words == ["MOXI", "P"]

    def test_a_flavour_only_the_reference_names_is_forgiven(self):
        # "Emeset Syrup Juicy Lemon" is what EMESET SYRUP means. Flavour
        # changes neither the form, the maker, nor the composition.
        query = build_query("EMESET SYRUP")
        assert score_row(query, row("Emeset Syrup Juicy Lemon", dosage_form="syrup",
                                    primary_strength=None)) is not None

    def test_a_flavour_WE_name_still_has_to_match(self):
        # Forgiven on the reference side only: an invoice that names a flavour
        # is saying something.
        query = build_query("EMESET SYRUP MANGO")
        assert score_row(query, row("Emeset Syrup Juicy Lemon", dosage_form="syrup",
                                    primary_strength=None)) is None


class TestFigureClassification:
    """The same figure written two different ways.

    An invoice says BETADINE SOL 10 and the reference says "Betadine 10%
    Solution". One classifies the 10 as a bare variant number, the other as a
    strength - and comparing the token lists rejected a row naming the
    identical product.
    """

    def test_a_bare_number_matches_the_same_figure_written_as_a_strength(self):
        query = build_query("BETADINE SOL 10", form="Solution")
        assert score_row(query, row("Betadine 10% Solution", dosage_form="solution",
                                    primary_strength=None)) is not None

    def test_a_different_figure_is_still_rejected(self):
        query = build_query("BETADINE SOL 10", form="Solution")
        assert score_row(query, row("Betadine 2% Gargle", dosage_form="solution",
                                    primary_strength=None)) is None

    def test_equality_not_membership(self):
        # GLYCOMET GP 2 must not reach Glycomet-GP 2/850: same glimepiride,
        # different metformin, different medicine. Requiring every figure to be
        # accounted for on BOTH sides is what keeps them apart - a subset test
        # would let the 2 alone carry it.
        query = build_query("GLYCOMET GP 2")
        assert score_row(query, row("Glycomet-GP 2/850 Tablet SR")) is None


class TestNamesThatFoundNothing:
    """Spellings that returned "no product matches" about a product the index held.

    Each of these was a total failure rather than a near miss: the whole block
    was rejected, so the screen reported an absence and the reviewer had no
    signal that the answer was sitting in the reference. They are grouped here
    because they share a shape - a descriptive fragment of the name was read as
    if it identified the product.
    """

    def test_a_strength_printed_with_a_space_is_still_a_strength(self):
        """OMNACORTIL 10 MG TAB. — the reported case.

        Split on whitespace, MG stood alone and was classified as a brand word;
        no listing can account for a brand called MG, so all thirteen Omnacortil
        rows were rejected.
        """
        parts = split_name("OMNACORTIL 10 MG TAB.")
        assert parts.words == ["OMNACORTIL"]
        assert parts.strengths == ["10MG"]
        assert parts.numbers == []

    def test_the_reported_name_now_finds_its_listing(self):
        query = build_query(
            "OMNACORTIL 10 MG TAB.", pack_multiplier=10, strength="10MG", form="Tablet"
        )
        result = propose(query, [
            row("Omnacortil 10 Tablet DT", primary_strength="10mg",
                composition="Prednisolone 10mg",
                manufacturer="Macleods Pharmaceuticals Pvt Ltd"),
            row("Omnacortil 5 Tablet DT", primary_strength="5mg",
                manufacturer="Macleods Pharmaceuticals Pvt Ltd"),
            row("Omnacortil 20 Tablet DT", primary_strength="20mg",
                manufacturer="Macleods Pharmaceuticals Pvt Ltd"),
        ])
        assert result["status"] == "ok"
        assert result["candidates"][0]["brand_name"] == "Omnacortil 10 Tablet DT"
        assert result["fields"]["strength"] == "10MG"

    def test_a_spaced_gram_dose_is_read_as_one_dose(self):
        parts = split_name("LEVIPIL 1 GM")
        assert parts.words == ["LEVIPIL"]
        assert parts.strengths == ["1GM"]

    def test_a_unit_is_only_absorbed_when_a_figure_precedes_it(self):
        """MG after a word is still a word - only a bare figure claims it."""
        assert "GM" in split_name("SOME BRAND GM").words

    @pytest.mark.parametrize(
        "name, expected_numbers",
        [
            ("CTD 6.25 TAB", ["6.25"]),
            ("METOLAR XR 12.5 CAPS", ["12.5"]),
        ],
    )
    def test_a_decimal_dose_survives_the_pack_reader(self, name, expected_numbers):
        """The digits after the decimal point opened a word boundary of their own.

        "CTD 6.25 TAB" matched the pack pattern at "25 TAB": the pack became 25
        and the dose was truncated to 6, so the row that named the product
        ("CTD 6.25 Tablet") was rejected for stating 6.25 against our 6.
        """
        cleaned, pack = strip_pack(name)
        assert pack is None
        assert split_name(cleaned).numbers == expected_numbers

    def test_a_spaced_form_word_does_not_eat_the_strength(self):
        """LASILACTON 50 TAB is Lasilactone 50, not a pack of fifty."""
        cleaned, pack = strip_pack("LASILACTON 50 TAB")
        assert pack is None
        assert split_name(cleaned).numbers == ["50"]

    def test_a_welded_count_is_still_read_as_a_pack(self):
        assert strip_pack("TRIOLMESAR 20 20TAB")[1] == 20.0

    def test_a_misspelled_presentation_word_is_not_a_brand_word(self):
        """DUONASE NASEL SPRAY — NASEL survived as a brand word and rejected
        "Duonase Nasal Spray", the only row in the block."""
        assert split_name("DUONASE NASEL SPRAY").words == ["DUONASE"]

    def test_a_short_product_marker_keeps_its_power_to_distinguish(self):
        """The forgiveness must not reach the markers that name a real variant."""
        assert "P" in split_name("MOXI-P").words
        assert "M" in split_name("DIAPRIDE M4").words

    @pytest.mark.parametrize(
        "reference_name",
        ["Freego Granules", "Rabivax-S Vaccine", "Neosporin Dusting Powder"],
    )
    def test_presentation_words_the_reference_adds_are_not_extra_words(self, reference_name):
        theirs = split_name(reference_name)
        ours = split_name(reference_name.split()[0])
        assert unexplained_words(theirs, ours, forgive_modifiers=True) == []

    def test_a_sugar_free_variant_is_the_same_medicine(self):
        """Neither word can be forgiven alone - Betafree and Itch Free are real
        brands - but as a phrase they only ever mark a variant."""
        assert split_name("Raciraft Oral Suspension Sugar Free").words == ["RACIRAFT"]


class TestFormsThatMeanTheSameThing:
    def test_an_ampoule_is_an_injection(self):
        assert score_row(
            build_query("AVIL AMPOULES", form="Ampoule"),
            row("Avil Injection", dosage_form="injection", primary_strength=None),
        )

    def test_an_eye_drop_is_a_drop(self):
        assert score_row(
            build_query("BETAFREE EYE DROPS", form="Eye Drops"),
            row("Betafree Eye Drop", dosage_form="drops", primary_strength=None),
        )

    def test_a_syrup_and_a_suspension_are_one_bottle(self):
        assert score_row(
            build_query("SILYBON SYRUP", form="Syrup"),
            row("Silybon Suspension", dosage_form="suspension", primary_strength=None),
        )

    def test_a_plural_is_not_a_disagreement(self):
        assert score_row(
            build_query("HYPERNEB RESPULES", form="Respule"),
            row("Hyperneb Respules", dosage_form="respules", primary_strength=None),
        )

    def test_a_tablet_is_still_not_a_capsule(self):
        assert score_row(
            build_query("TOLFEN CAP", form="Capsule"),
            row("Tolfen Tablet", dosage_form="tablet", primary_strength=None),
        ) is None

    def test_the_rows_own_name_can_rescue_a_miscoded_column(self):
        """"Arotear Gel" is filed under `solution` in the reference export."""
        assert score_row(
            build_query("AROTEAR GEL", form="Gel"),
            row("Arotear Gel", dosage_form="solution", primary_strength=None),
        )

    def test_the_column_can_rescue_a_name_that_describes_it_differently(self):
        """An eye drop the catalogue holds as a Solution — both are true."""
        assert score_row(
            build_query("WINOLAP MAX E/D", form="Solution"),
            row("Winolap Max Eye Drop", dosage_form="solution", primary_strength=None),
        )


class TestTheDefaultDoseTheReferenceLeavesOut:
    """The reference names the common dose by omitting it: the 40mg
    pantoprazole is just "Pantocid Tablet", beside "Pantocid 20 Tablet"."""

    def test_a_figure_we_state_may_be_pinned_by_the_rows_strength(self):
        assert score_row(
            build_query("PANTOCID 40", form="Tablet", strength="40"),
            row("Pantocid Tablet", primary_strength="40mg", ingredient_strengths="40mg"),
        )

    def test_a_sibling_with_a_different_dose_is_still_rejected(self):
        assert score_row(
            build_query("PANTOCID 40", form="Tablet", strength="40"),
            row("Pantocid 20 Tablet", primary_strength="20mg", ingredient_strengths="20mg"),
        ) is None

    def test_a_combination_is_not_pinned_by_one_of_its_ingredients(self):
        """Pantocid DSR is 30mg domperidone with 40mg pantoprazole. The 40
        appears in it, but the product is not Pantocid 40."""
        assert score_row(
            build_query("PANTOCID 40", form="Tablet", strength="40"),
            row("Pantocid DSR Capsule", dosage_form="capsule", primary_strength="30mg",
                ingredient_strengths="30mg|40mg", ingredient_count=2),
        ) is None

    def test_a_row_that_names_its_own_figures_is_judged_on_those_alone(self):
        """The fallback must never widen a name that already states a figure -
        GLYCOMET GP 2 must stay away from Glycomet-GP 2/850."""
        assert score_row(
            build_query("GLYCOMET GP 2"),
            row("Glycomet-GP 2/850 Tablet SR", primary_strength="2mg",
                ingredient_strengths="2mg|850mg", ingredient_count=2),
        ) is None


class TestAFigureTheRowNamesButDoesNotRecord:
    def test_a_dose_named_in_the_row_settles_a_differing_column(self):
        """Metapro-XL 25 is 23.75mg of the succinate, equivalent to 25mg of the
        tartrate. The name carries the figure the invoice uses."""
        assert score_row(
            build_query("METAPRO XL 25MG TABLETS", form="Tablet", strength="25MG"),
            row("Metapro -XL 25 Tablet", primary_strength="23.75mg",
                ingredient_strengths="23.75mg"),
        )

    def test_a_dose_neither_the_name_nor_the_column_supports_is_rejected(self):
        assert score_row(
            build_query("METAPRO XL 25MG TABLETS", form="Tablet", strength="25MG"),
            row("Metapro-XL 50 Tablet", primary_strength="47.5mg",
                ingredient_strengths="47.5mg"),
        ) is None


class TestWhichOfARowsTwoAnswersIsProposed:
    """A reference row states its form and its strength twice over, and the two
    statements can differ. Which one is proposed is the difference between
    filling a field correctly and filling it with something a pharmacist will
    have to undo."""

    def test_a_form_the_row_names_beats_the_column_it_is_filed_under(self):
        result = propose(build_query("AROTEAR GEL"), [
            row("Arotear Gel", dosage_form="solution", primary_strength=None),
        ])
        assert result["fields"]["form"] == "Gel"
        assert result["fields"]["base_unit"] == "GM"

    def test_the_column_still_answers_when_the_name_says_nothing(self):
        result = propose(build_query("SILYBON"), [
            row("Silybon", dosage_form="suspension", primary_strength=None),
        ])
        assert result["fields"]["form"] == "Suspension"

    def test_a_dose_the_row_names_beats_the_ingredient_it_records(self):
        """Metolar XR 12.5 contains 11.8mg of metoprolol succinate. The pack
        says 12.5, and so will next month's invoice."""
        result = propose(build_query("METOLAR XR 12.5", form="Capsule"), [
            row("Metolar XR 12.5 Capsule", dosage_form="capsule",
                primary_strength="11.8mg", ingredient_strengths="11.8mg"),
        ])
        assert result["fields"]["strength"] == "12.5MG"

    def test_a_dose_the_row_agrees_with_is_left_as_recorded(self):
        result = propose(build_query("OMNACORTIL 10", form="Tablet"), [
            row("Omnacortil 10 Tablet DT", primary_strength="10mg",
                ingredient_strengths="10mg"),
        ])
        assert result["fields"]["strength"] == "10MG"

    def test_a_name_stating_several_figures_is_left_to_the_combination_rule(self):
        result = propose(build_query("GLYCOMET GP 2/850"), [
            row("Glycomet-GP 2/850 Tablet SR", primary_strength="2mg",
                ingredient_strengths="2mg|850mg", ingredient_count=2,
                composition="Glimepiride 2mg + Metformin 850mg"),
        ])
        assert result["fields"]["strength"] == "2MG+850MG"
