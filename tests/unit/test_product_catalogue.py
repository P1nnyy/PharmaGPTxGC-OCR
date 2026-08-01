"""Ambiguity analysis is kept pure precisely so it can be tested without a
graph database - the rules that decide what a pharmacist gets nagged about
are the part most worth pinning down."""

import pytest

from db.product_repository import (
    REQUIRED_FIELDS,
    compute_completeness,
    compute_flags,
)


def product(**overrides) -> dict:
    """A fully-specified product; tests knock out the field under examination."""
    base = {
        "brand": "MONTICOPE",
        "strength": "5MG",
        "form": "Suspension",
        "pack_size": "60ML",
        "pack_multiplier": 1,
        "base_unit": "ML",
        "manufacturer": "Mankind",
        "hsn": "30049099",
        "schedule": "Schedule H",
        "review_status": "needs_review",
        "confirmed_fields": [],
        "observed_mrps": [120.0],
        "observed_hsns": ["30049099"],
        "aliases": [],
    }
    base.update(overrides)
    return base


def codes(prod: dict) -> set:
    return {f["code"] for f in compute_flags(prod)}


def severity_of(prod: dict, code: str) -> str:
    return next(f["severity"] for f in compute_flags(prod) if f["code"] == code)


class TestCompleteProduct:
    def test_nothing_flagged_when_everything_known(self):
        assert compute_flags(product()) == []

    def test_completeness_is_one(self):
        assert compute_completeness(product()) == 1.0


class TestMissingFields:
    @pytest.mark.parametrize(
        "field,code",
        [
            ("pack_multiplier", "missing_pack_multiplier"),
            ("strength", "missing_strength"),
            ("form", "missing_form"),
            ("base_unit", "missing_base_unit"),
            ("pack_size", "missing_pack_size"),
            ("hsn", "missing_hsn"),
            ("schedule", "missing_schedule"),
            ("manufacturer", "missing_manufacturer"),
        ],
    )
    def test_each_gap_raises_its_flag(self, field, code):
        assert code in codes(product(**{field: None}))

    def test_empty_string_counts_as_missing(self):
        assert "missing_hsn" in codes(product(hsn=""))

    def test_stock_breaking_gaps_outrank_paperwork_gaps(self):
        # Severity has to track downstream damage: without a multiplier every
        # derived stock number is wrong, while a blank schedule is a form
        # field somebody fills in later.
        assert severity_of(product(pack_multiplier=None), "missing_pack_multiplier") == "high"
        assert severity_of(product(schedule=None), "missing_schedule") == "low"

    def test_completeness_drops_with_each_gap(self):
        assert compute_completeness(product(strength=None)) == round(
            (len(REQUIRED_FIELDS) - 1) / len(REQUIRED_FIELDS), 2
        )

    def test_completeness_ignores_optional_fields(self):
        # manufacturer/hsn/schedule are worth flagging but do not make the
        # product unusable, so they stay out of the completeness score.
        assert compute_completeness(product(manufacturer=None, schedule=None)) == 1.0


class TestPriceSpread:
    def test_wide_spread_reads_as_two_products_merged(self):
        # A 5mg and a 10mg DONEP fused into one record announce themselves
        # through price long before anyone notices the strengths.
        flags = compute_flags(product(strength=None, observed_mrps=[45.0, 90.0]))
        conflict = next(f for f in flags if f["code"] == "mrp_conflict")
        assert conflict["severity"] == "high"
        assert "45.00" in conflict["message"] and "90.00" in conflict["message"]

    def test_modest_spread_reads_as_a_price_revision(self):
        flags = compute_flags(product(observed_mrps=[100.0, 120.0]))
        assert "mrp_drift" in {f["code"] for f in flags}
        assert "mrp_conflict" not in {f["code"] for f in flags}

    def test_single_price_is_silent(self):
        assert "mrp_conflict" not in codes(product(observed_mrps=[120.0]))
        assert "mrp_drift" not in codes(product(observed_mrps=[120.0]))

    def test_no_prices_observed_is_silent(self):
        assert "mrp_conflict" not in codes(product(observed_mrps=[]))

    def test_zero_price_does_not_divide_by_zero(self):
        compute_flags(product(observed_mrps=[0.0, 90.0]))

    def test_non_numeric_prices_are_ignored(self):
        compute_flags(product(observed_mrps=[None, "n/a", 90.0]))


class TestHsnConflict:
    def test_disagreeing_invoices_are_flagged(self):
        flags = compute_flags(product(observed_hsns=["30049099", "30041000"]))
        assert "hsn_conflict" in {f["code"] for f in flags}

    def test_agreement_is_silent(self):
        assert "hsn_conflict" not in codes(product(observed_hsns=["30049099", "30049099"]))


class TestNewSpelling:
    def test_new_alias_reopens_a_confirmed_product(self):
        prod = product(
            review_status="confirmed",
            aliases=[
                {"raw_name": "MONTICOPE SUSP", "status": "confirmed"},
                {"raw_name": "MONTICOPE SUSPENSION 60ML", "status": "new"},
            ],
        )
        flag = next(f for f in compute_flags(prod) if f["code"] == "new_alias")
        assert "MONTICOPE SUSPENSION 60ML" in flag["message"]

    def test_unconfirmed_product_does_not_raise_it(self):
        # It is already in the queue; saying "new spelling" adds nothing.
        prod = product(aliases=[{"raw_name": "X", "status": "new"}])
        assert "new_alias" not in codes(prod)


class TestAcknowledgement:
    def test_confirming_a_blank_field_downgrades_the_nag(self):
        # The pharmacist may know the invoice genuinely never states it.
        prod = product(pack_multiplier=None, confirmed_fields=["pack_multiplier"])
        flag = next(f for f in compute_flags(prod) if f["code"] == "missing_pack_multiplier")
        assert flag["severity"] == "low"
        assert "acknowledged" in flag["message"]

    def test_unacknowledged_stays_high(self):
        prod = product(pack_multiplier=None)
        assert severity_of(prod, "missing_pack_multiplier") == "high"
