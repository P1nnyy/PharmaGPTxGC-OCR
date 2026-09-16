"""HSN and UQC validation against the stored GSTN master.

These are pinned by test because each one decides whether a filed return is
accepted. The portal's Table 12 takes codes from its own list and units from
its own list, and neither failure is visible until filing — by which time the
month is closed.
"""

import pytest

from core.hsn import (
    AATO_SIX_DIGIT_THRESHOLD_PAISE,
    EXACT,
    PARENT_MATCHED,
    HsnError,
    describe,
    is_known,
    is_valid_uqc,
    normalize_hsn,
    normalize_uqc,
    policy_digits,
    policy_for_aato,
    resolve_hsn,
    validate_hsn,
    validate_uqc,
    valid_uqcs,
)


class TestNormalizeHsn:
    def test_strips_the_punctuation_people_type(self):
        assert normalize_hsn("3004.90") == "300490"
        assert normalize_hsn("30 04") == "3004"
        assert normalize_hsn(" 3004 ") == "3004"

    def test_an_absent_code_normalises_to_empty(self):
        assert normalize_hsn(None) == ""
        assert normalize_hsn("") == ""


class TestMaster:
    def test_knows_the_code_most_of_a_pharmacy_sells_under(self):
        # 3004 is medicaments in measured doses - the retail pharmacy code.
        assert is_known("3004")
        assert is_known("300490")
        assert is_known("30049099")

    def test_does_not_know_an_invented_code(self):
        assert not is_known("9999")
        # 3009 looks like a chapter-30 code and is not one.
        assert not is_known("3009")

    def test_describes_a_code_it_knows(self):
        # GSTN publishes the tariff text in capitals; the assertion is about
        # the description being the right one, not about its case.
        assert "measured doses" in (describe("3004") or "").lower()

    def test_holds_codes_at_four_six_and_eight_digits(self):
        # A shop reporting at six digits cannot file a four-digit code, so the
        # master has to carry the longer forms of what a pharmacy sells.
        assert is_known("3004") and is_known("300420") and is_known("30042099")


class TestDigitPolicy:
    def test_five_crore_exactly_still_reports_four_digits(self):
        # The rule is four digits *up to* five crore and six *above* it, so the
        # boundary itself stays on four.
        assert policy_for_aato(AATO_SIX_DIGIT_THRESHOLD_PAISE) == "FOUR_DIGIT"

    def test_a_rupee_above_the_threshold_moves_to_six(self):
        assert policy_for_aato(AATO_SIX_DIGIT_THRESHOLD_PAISE + 100) == "SIX_DIGIT"

    def test_well_under_the_threshold_is_four(self):
        assert policy_for_aato(4_00_00_000_00) == "FOUR_DIGIT"

    def test_unknown_turnover_defaults_to_the_stricter_policy(self):
        # Reporting more digits than owed is accepted; reporting fewer is not.
        # So not knowing must cost precision, never a rejected return.
        assert policy_for_aato(None) == "SIX_DIGIT"

    def test_policy_names_resolve_to_digit_counts(self):
        assert policy_digits("FOUR_DIGIT") == 4
        assert policy_digits("SIX_DIGIT") == 6

    def test_an_unset_policy_resolves_to_six(self):
        assert policy_digits(None) == 6
        assert policy_digits("") == 6


class TestValidateHsn:
    def test_accepts_a_known_code_at_the_required_length(self):
        assert validate_hsn("3004", 4) == "3004"
        assert validate_hsn("300490", 6) == "300490"

    def test_accepts_more_digits_than_required(self):
        # Eight digits satisfies a six-digit obligation - it is accepted, not
        # refused. What comes back is the six-digit code it will be filed
        # under, because that is the shop's reporting length; see TestRollUp.
        assert validate_hsn("30049099", 6) == "300490"

    def test_refuses_too_few_digits_for_the_policy(self):
        with pytest.raises(HsnError) as excinfo:
            validate_hsn("3004", 6)
        # The message has to point at the digits, not at the code: 3004 is a
        # real code, and being told it is unknown would send someone hunting
        # for a classification error that is not there.
        assert "digits" in str(excinfo.value)

    def test_refuses_a_code_the_portal_does_not_list(self):
        with pytest.raises(HsnError) as excinfo:
            validate_hsn("3009", 4)
        assert "master" in str(excinfo.value)

    def test_refuses_an_impossible_length(self):
        with pytest.raises(HsnError):
            validate_hsn("300", 4)
        with pytest.raises(HsnError):
            validate_hsn("30049", 4)

    def test_refuses_a_missing_code(self):
        with pytest.raises(HsnError):
            validate_hsn(None, 4)
        with pytest.raises(HsnError):
            validate_hsn("", 4)


class TestRollUp:
    """A longer code than the shop files at is reported under its parent.

    Distributors print eight-digit codes because that is what the customs
    tariff carries. A shop under ₹5 crore files four. Those are not in
    conflict: the eight-digit code *is* the four-digit one, more precisely
    stated, and Table 12 wants the four. Refusing the line would be refusing
    a correct code for being too specific.

    The limit is that the parent has to be real. Rolling `30999999` up to a
    `3099` that GSTN has never listed would invent a classification, which is
    the failure this module exists to prevent.
    """

    def test_an_eight_digit_code_reports_under_its_four_digit_parent(self):
        # Not a listed code; 3004 is. A four-digit filer reports 3004.
        assert not is_known("30049010")
        resolution = resolve_hsn("30049010", 4)
        assert resolution.reported == "3004"
        assert resolution.match == PARENT_MATCHED
        assert resolution.code == "30049010"

    def test_a_listed_eight_digit_code_still_rolls_up(self):
        # 30049079 is in the master. It rolls up anyway, because what decides
        # the reported code is the shop's obligation, not how specific the
        # distributor chose to be. Filing it as printed would be legal and
        # would also split Table 12 into one row per pack.
        assert is_known("30049079")
        resolution = resolve_hsn("30049079", 4)
        assert resolution.reported == "3004"
        assert resolution.match == PARENT_MATCHED

    def test_a_code_at_the_reporting_length_is_reported_as_itself(self):
        resolution = resolve_hsn("3004", 4)
        assert resolution.reported == "3004"
        assert resolution.match == EXACT

    def test_an_unknown_parent_still_fails(self):
        # 3009 is not a chapter-30 heading. Nothing to roll up to.
        assert not is_known("3009")
        with pytest.raises(HsnError) as excinfo:
            resolve_hsn("30099999", 4)
        assert "master" in str(excinfo.value)

    def test_a_six_digit_filer_reporting_four_digits_still_fails(self):
        # Roll-up goes down the digits, never up. A six-digit filer owes six,
        # and 3004 stays short however well known it is.
        with pytest.raises(HsnError) as excinfo:
            resolve_hsn("3004", 6)
        assert "digits" in str(excinfo.value)

    def test_a_six_digit_filer_rolls_an_eight_digit_code_to_six(self):
        assert not is_known("30049010")
        resolution = resolve_hsn("30049010", 6)
        assert resolution.reported == "300490"
        assert resolution.match == PARENT_MATCHED

    def test_validate_returns_the_code_that_will_be_filed(self):
        # validate_hsn hands back what goes on the return, which for a rolled
        # up line is the parent - not the code that was passed in.
        assert validate_hsn("30049010", 4) == "3004"
        assert validate_hsn("30049079", 4) == "3004"
        assert validate_hsn("30049079", 6) == "300490"

    def test_a_chapter_heading_is_never_filable(self):
        # Chapter 30 is in GSTN's list but is two digits, and Table 12 takes
        # 4, 6 or 8. Being in the master is necessary, not sufficient.
        assert is_known("30")
        with pytest.raises(HsnError):
            resolve_hsn("30", 4)


class TestUqc:
    def test_the_portals_own_codes_pass_through(self):
        assert normalize_uqc("NOS") == "NOS"
        assert normalize_uqc("tbs") == "TBS"

    def test_maps_what_a_pharmacy_actually_says(self):
        # The portal has never heard of a strip.
        assert normalize_uqc("strip") == "TBS"
        assert normalize_uqc("Vial") == "NOS"
        assert normalize_uqc("bottle") == "BTL"
        assert normalize_uqc("tube") == "TUB"

    def test_refuses_rather_than_falling_back_to_others(self):
        # OTH exists and would always "work". Using it for anything unmapped
        # turns a fixable data problem into a permanently vague return.
        assert normalize_uqc("banana") is None
        assert normalize_uqc("") is None
        assert normalize_uqc(None) is None

    def test_validate_explains_an_unmappable_unit(self):
        with pytest.raises(HsnError) as excinfo:
            validate_uqc("banana")
        assert "recognise" in str(excinfo.value)

    def test_validate_explains_a_missing_unit(self):
        with pytest.raises(HsnError) as excinfo:
            validate_uqc(None)
        assert "unit" in str(excinfo.value).lower()

    def test_is_valid_uqc_only_accepts_the_portals_list(self):
        assert is_valid_uqc("NOS")
        assert not is_valid_uqc("STRIP")

    def test_carries_the_full_gstn_list(self):
        codes = valid_uqcs()
        # Spot-check the ones a pharmacy files under most.
        for code in ("NOS", "TBS", "BTL", "TUB", "PAC", "KGS", "MLT", "OTH"):
            assert code in codes
