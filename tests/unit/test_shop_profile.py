"""The shop's business details.

These fields exist to be used, not filed: the GSTIN decides which party on a
scanned invoice is us, and its state code decides whether a purchase is
CGST+SGST or IGST. So the tests are mostly about refusing a number that would
be wrong in a way nobody would notice until the invoices were already wrong.
"""

from unittest.mock import patch

import pytest

from core.gstin import GstinError, checksum_char, parse, same_state, validate
from db.repositories import pharmacy_repository
from db.repositories.pharmacy_repository import ProfileError, missing_fields

VALID = "27AAPFU0939F1Z" + checksum_char("27AAPFU0939F1Z")


class TestGstin:
    def test_accepts_a_well_formed_number_and_derives_what_it_contains(self):
        parsed = parse(VALID)
        assert parsed["state_code"] == "27"
        assert parsed["state"] == "Maharashtra"
        # The PAN is embedded, so it is never asked for separately.
        assert parsed["pan"] == "AAPFU0939F"

    def test_rejects_a_wrong_check_character(self):
        wrong = VALID[:14] + ("A" if VALID[14] != "A" else "B")
        with pytest.raises(GstinError, match="check character"):
            validate(wrong)

    def test_rejects_an_unknown_state_code(self):
        with pytest.raises(GstinError, match="state code"):
            validate("99AAPFU0939F1ZV")

    def test_rejects_the_wrong_length(self):
        with pytest.raises(GstinError, match="15 characters"):
            validate(VALID[:-1])

    def test_normalises_spacing_and_case(self):
        assert validate(f"  {VALID.lower()}  ") == VALID

    def test_same_state_says_unknown_rather_than_guessing(self):
        # "We could not tell" and "different states" lead to different tax
        # treatment, so they must not collapse into one answer.
        assert same_state(VALID, None) is None
        assert same_state(VALID, "27XXXXX0000X1Z0") is True
        assert same_state(VALID, "29XXXXX0000X1Z0") is False


class TestProfile:
    def test_a_bad_gstin_is_refused_before_it_can_misassign_anything(self):
        with pytest.raises(ProfileError):
            pharmacy_repository.update_profile({"gstin": "not-a-gstin"}, "ph1")

    def test_pincode_must_be_six_digits(self):
        with pytest.raises(ProfileError, match="six digits"):
            pharmacy_repository.update_profile({"pincode": "12345"}, "ph1")

    def test_unknown_keys_cannot_write_arbitrary_properties(self):
        captured = {}

        class FakeSession:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute_write(self, fn):
                return fn(type("Tx", (), {
                    "run": lambda _s, q, **k: type("R", (), {
                        "single": lambda _x: captured.update(query=q, params=k) or {"ph": {}}
                    })()
                })())

        with patch.object(pharmacy_repository, "get_driver",
                          return_value=type("D", (), {"session": lambda _s: FakeSession()})()):
            pharmacy_repository.update_profile(
                {"legal_name": "Real Pharmacy", "is_admin": True, "role": "super_admin"}, "ph1"
            )
        assert "legal_name" in captured["params"]
        assert "is_admin" not in captured["params"]
        assert "role" not in captured["params"]

    def test_missing_fields_lists_what_still_blocks_setup(self):
        assert set(missing_fields(None)) == set(pharmacy_repository.REQUIRED_FIELDS)
        partial = {"legal_name": "X", "gstin": VALID}
        assert "city" in missing_fields(partial)
        assert "legal_name" not in missing_fields(partial)

    def test_a_complete_profile_has_nothing_missing(self):
        full = {f: "x" for f in pharmacy_repository.REQUIRED_FIELDS}
        assert missing_fields(full) == []
