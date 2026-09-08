"""The triage rules, tested without a graph.

What matters here is not that the bands are computed but that they are
computed conservatively: `ready` is a claim that a pharmacist can approve an
item without looking at it, so anything that could make that claim wrong -
a guessed field, a price spread, a new spelling - has to pull the item back
out of the batch.
"""

import pytest

from db.product_review import (
    BLOCKED,
    LIKELY_DUPLICATE_SCORE,
    READY,
    REVIEW,
    assess_catalogue,
    assess_product,
    find_duplicate_candidates,
    score_duplicate_pair,
)
from db.product_repository import compute_flags
from extraction.normalizers.product_parser import build_identity_key, parse_product_name


def product(**overrides) -> dict:
    """A product with every required field filled and read confidently."""
    base = {
        "id": "p1",
        "canonical_name": "MONTICOPE SUSPENSION 60 ML",
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
        "acknowledged_fields": [],
        "suggested_fields": [],
        "observed_mrps": [120.0],
        "observed_hsns": ["30049099"],
        "aliases": [],
        "completeness": 1.0,
        "brand_confidence": 0.95,
        "strength_confidence": 0.95,
        "form_confidence": 0.95,
        "pack_size_confidence": 0.95,
        "pack_multiplier_confidence": 0.95,
        "base_unit_confidence": 0.95,
    }
    base.update(overrides)
    # Flags are derived, never hand-written, so the bands are tested against
    # the same analysis the API actually serves.
    base["flags"] = compute_flags(base)
    return base


class TestBands:
    def test_fully_read_product_is_ready(self):
        assert assess_product(product())["band"] == READY

    def test_missing_required_field_blocks(self):
        result = assess_product(product(pack_multiplier=None))
        assert result["band"] == BLOCKED
        assert result["weakest_field"] == "pack_multiplier"
        assert any("units per pack" in r for r in result["reasons"])

    def test_low_confidence_field_needs_review_not_batch_approval(self):
        # The dangerous case: everything is filled in, so completeness reads
        # 100%, but the strength was guessed off the end of a brand name.
        result = assess_product(product(strength_confidence=0.4))
        assert result["band"] == REVIEW
        assert result["weakest_field"] == "strength"
        assert any("40% confident" in r for r in result["reasons"])

    def test_confidence_at_the_threshold_is_ready(self):
        assert assess_product(product(strength_confidence=0.8))["band"] == READY

    def test_a_confirmed_field_is_never_second_guessed(self):
        # A person typed it. Its parse confidence stops being relevant.
        result = assess_product(
            product(strength_confidence=0.2, confirmed_fields=["strength"])
        )
        assert result["band"] == READY

    def test_price_spread_blocks_even_when_every_field_is_filled(self):
        result = assess_product(product(observed_mrps=[45.0, 90.0]))
        assert result["band"] == BLOCKED
        assert any("45.00" in r for r in result["reasons"])

    def test_acknowledged_blank_does_not_block_forever(self):
        # Someone looked, and the invoice genuinely never states it. The item
        # must be able to leave the queue, or answering the question is
        # indistinguishable from ignoring it.
        result = assess_product(
            product(pack_size=None, acknowledged_fields=["pack_size"])
        )
        assert result["band"] == READY

    def test_a_blank_is_not_answered_merely_by_having_been_saved(self):
        # confirmed_fields used to be set from the keys of the save payload,
        # and the drawer sends every field on every save - so pressing Save
        # marked each empty field as approved and emptied the queue of
        # products nobody had actually answered.
        result = assess_product(
            product(pack_size=None, confirmed_fields=["pack_size"])
        )
        assert result["band"] == BLOCKED

    def test_new_spelling_reopens_a_confirmed_product(self):
        result = assess_product(
            product(
                review_status="confirmed",
                confirmed_fields=["brand", "strength", "form", "pack_size",
                                  "pack_multiplier", "base_unit"],
                aliases=[{"id": "a1", "raw_name": "MONTICOPE SUSP 60ML", "status": "new"}],
            )
        )
        assert result["band"] == REVIEW
        assert any("New spelling" in r for r in result["reasons"])

    def test_missing_hsn_is_a_caveat_not_a_blocker(self):
        # Worth telling the reviewer about; not worth holding up a batch for.
        result = assess_product(product(hsn=None, observed_hsns=[]))
        assert result["band"] == READY
        assert any("HSN" in c for c in result["caveats"])


class TestCatalogueRollup:
    def test_counts_each_band(self):
        result = assess_catalogue([
            product(id="a"),
            product(id="b", strength_confidence=0.3),
            product(id="c", pack_multiplier=None),
        ])
        assert result["counts"] == {READY: 1, REVIEW: 1, BLOCKED: 1}
        assert [a["product_id"] for a in result["assessments"]] == ["a", "b", "c"]


class TestDuplicateDetection:
    def test_same_brand_one_silent_about_strength(self):
        # The case identity_key cannot merge on its own: DONEP|?|?|? and
        # DONEP|10MG|Tablet|1*10 are different keys, possibly one product.
        pair = score_duplicate_pair(
            product(id="a", brand="DONEP", strength=None, form=None,
                    pack_size=None, pack_multiplier=None, completeness=0.2),
            product(id="b", brand="DONEP", strength="10MG", form="Tablet",
                    pack_size="1*10", pack_multiplier=10, completeness=1.0),
        )
        assert pair is not None
        assert pair["score"] >= LIKELY_DUPLICATE_SCORE
        assert any("silent" in r for r in pair["reasons"])
        # Merge into the record that actually knows what the product is.
        assert pair["suggested_target"] == "b"

    def test_conflicting_strengths_are_disqualified_not_penalised(self):
        assert score_duplicate_pair(
            product(id="a", brand="DONEP", strength="5MG"),
            product(id="b", brand="DONEP", strength="10MG"),
        ) is None

    def test_conflicting_pack_multipliers_are_disqualified(self):
        # A strip of 10 and a strip of 15 are different SKUs however well the
        # names match, and merging them corrupts stock silently.
        assert score_duplicate_pair(
            product(id="a", brand="ZOLFRESH", pack_multiplier=10, pack_size=None),
            product(id="b", brand="ZOLFRESH", pack_multiplier=15, pack_size=None),
        ) is None

    def test_conflicting_forms_are_disqualified(self):
        assert score_duplicate_pair(
            product(id="a", brand="MONTICOPE", form="Tablet", strength=None),
            product(id="b", brand="MONTICOPE", form="Syrup", strength=None),
        ) is None

    def test_an_extra_token_is_treated_as_a_different_product_line(self):
        # MAHAFLOX and MAHAFLOX-LP fuzzy-match at ~90 and are different
        # medicines. The suggestion must not reach "likely".
        pair = score_duplicate_pair(
            product(id="a", brand="MAHAFLOX", strength=None, manufacturer=None,
                    pack_size=None, hsn=None, pack_multiplier=None),
            product(id="b", brand="MAHAFLOX LP", strength=None, manufacturer=None,
                    pack_size=None, hsn=None, pack_multiplier=None),
        )
        assert pair is None or pair["verdict"] == "possible"

    def test_unrelated_products_are_not_suggested(self):
        assert score_duplicate_pair(
            product(id="a", brand="MONTICOPE"),
            product(id="b", brand="ZOLFRESH"),
        ) is None

    def test_candidates_come_back_best_evidence_first(self):
        catalogue = [
            product(id="a", brand="DONEP", strength=None, pack_multiplier=None),
            product(id="b", brand="DONEP", strength="10MG"),
            product(id="c", brand="ZOLFRESH"),
        ]
        candidates = find_duplicate_candidates(catalogue)
        assert len(candidates) == 1
        assert set(candidates[0]["product_ids"]) == {"a", "b"}

    def test_a_product_with_no_name_is_never_matched(self):
        assert score_duplicate_pair(
            product(id="a", brand=None, canonical_name=None),
            product(id="b", brand=None, canonical_name=None),
        ) is None


def from_invoice_name(pid: str, raw: str, **overrides) -> dict:
    """Builds a product the way the catalogue actually does - by parsing an
    invoice's rendering of the name - so the calibration below is measured
    against real parser output rather than against fields chosen to prove a
    point."""
    parsed = parse_product_name(raw)
    field = lambda f: (getattr(parsed, f).value if getattr(parsed, f, None) else None)
    item = {
        "id": pid,
        "canonical_name": raw,
        "completeness": 0.5,
        "manufacturer": None,
        "hsn": None,
        **{f: field(f) for f in ("brand", "strength", "form", "pack_size",
                                 "pack_multiplier", "base_unit")},
    }
    item.update(overrides)
    item["identity_key"] = build_identity_key(
        item["brand"], item["strength"], item["form"], item["pack_size"]
    )
    return item


class TestDuplicateCalibration:
    """The line between a duplicate and a different medicine, measured on the
    name shapes these invoices actually print.

    Pairs that already share an identity_key are excluded from each case: those
    merged on the way in and can never reach this code. What is left is the
    residue - and getting the residue wrong in the permissive direction merges
    two medicines, so each case states which side of the line it belongs on.
    """

    @pytest.mark.parametrize("left, right", [
        # One invoice stated the dose and the other didn't. Different
        # identity_keys, almost certainly one product.
        ("DONEP", "DONEP 10MG TAB"),
        # A separator moved. Set-difference tokenising calls this two extra
        # tokens; it is one product.
        ("LIVO-LUK SOLUTION 200ML", "LIVOLUK SOLUTION 200ML"),
        # A zero read for an O.
        ("MONTICOPE TAB", "MONTIC0PE TAB"),
    ])
    def test_real_duplicates_are_offered(self, left, right):
        pair = score_duplicate_pair(
            from_invoice_name("a", left), from_invoice_name("b", right)
        )
        assert pair is not None, f"{left!r} vs {right!r} should have been offered"

    def test_manufacturer_inlined_in_one_name_is_not_an_extra_word(self):
        pair = score_duplicate_pair(
            from_invoice_name("a", "NITROLONG-2.6", manufacturer="Mankind"),
            from_invoice_name("b", "NITROLONG-2.6 MANKIND", manufacturer="Mankind"),
        )
        assert pair is not None
        assert pair["verdict"] == "likely"

    @pytest.mark.parametrize("left, right", [
        # One token apart, and a different medicine. These fuzzy-match ~100,
        # which is exactly why the extra-token rule has to survive.
        ("MAHAFLOX TAB", "MAHAFLOX-LP TAB"),
        ("DYNAPAR QPS", "DYNAPAR QPS PLUS"),
        ("NUROKIND LC TAB", "NUROKIND PLUS TAB"),
        # Same brand, different dose - the merge that must never be proposed.
        ("ZOLFRESH 10MG", "ZOLFRESH 5MG"),
        ("MONTICOPE TAB", "ZOLFRESH TAB"),
    ])
    def test_different_medicines_are_never_offered(self, left, right):
        pair = score_duplicate_pair(
            from_invoice_name("a", left), from_invoice_name("b", right)
        )
        assert pair is None, f"{left!r} vs {right!r} should not have been offered"

    def test_two_spellings_of_one_sku_never_reach_this_code(self):
        # Stated for the record: these merge on identity_key at write time, so
        # the duplicate finder is only ever asked about what survived that.
        left = from_invoice_name("a", "MONTICOPE SUSPENSION 60 ML")
        right = from_invoice_name("b", "MONTICOPE SUSP 60ML")
        assert left["identity_key"] == right["identity_key"]


class TestDerivedFields:
    """The dispensing unit follows from the dosage form - the parser reads one
    form match and records both, giving the unit a lower confidence. Treating
    that lower number as an independent doubt put every correctly-parsed
    tablet into the review band over a unit nobody guessed at."""

    def test_a_unit_implied_by_a_known_form_is_not_a_separate_question(self):
        # What the parser actually produces for "PANTOP 40MG TAB" + pack 1*15.
        result = assess_product(product(form_confidence=0.85, base_unit_confidence=0.7))
        assert result["band"] == READY
        assert not any("dispensing unit" in r for r in result["reasons"])

    def test_a_weak_form_is_reported_once_not_twice(self):
        result = assess_product(product(form_confidence=0.55, base_unit_confidence=0.7))
        assert result["band"] == REVIEW
        assert [r for r in result["reasons"] if "dosage form" in r]
        assert not any("dispensing unit" in r for r in result["reasons"])

    def test_a_unit_with_no_form_behind_it_is_still_gated(self):
        # Read off a pack code with no form in the name: nothing else is
        # carrying that uncertainty, so it has to be asked about.
        result = assess_product(
            product(form=None, form_confidence=None, base_unit_confidence=0.5,
                    acknowledged_fields=["form"])
        )
        assert result["band"] == REVIEW
        assert any("dispensing unit" in r for r in result["reasons"])


class TestReasonAccuracy:
    """A reason the reviewer can see is false costs more than it explains."""

    def test_identical_names_are_described_as_identical(self):
        pair = score_duplicate_pair(
            from_invoice_name("a", "DONEP"), from_invoice_name("b", "DONEP 10MG TAB")
        )
        assert any("Both names reduce to" in r for r in pair["reasons"])

    def test_differently_written_names_are_not_claimed_to_be_the_same_string(self):
        pair = score_duplicate_pair(
            from_invoice_name("a", "LIVO-LUK SOLUTION 200ML"),
            from_invoice_name("b", "LIVOLUK SOLUTION 200ML"),
        )
        assert not any("Both names reduce to" in r for r in pair["reasons"])
        assert any("differ only in how they are written" in r for r in pair["reasons"])


class TestBrandVariantsFromRealData:
    """Pairs the live catalogue actually produced.

    Each is one token apart, and each is a different medicine: PLUS, FORTE,
    TRIO and SP name a different formulation of the same brand. They are also,
    necessarily, from the same manufacturer in the same pack under the same
    HSN code - so corroboration on those fields carries no information here,
    and letting it score was cancelling the extra-token penalty and promoting
    them to "likely the same".
    """

    @pytest.mark.parametrize("left, right", [
        ("DYTOR", "DYTOR PLUS"),
        ("DIAPRIDE M4", "DIAPRIDE M4 FORTE"),
        ("TELPLUS 15S", "TELPLUS TRIO 15S"),
        ("ZERODOL P", "ZERODOL SP"),
    ])
    def test_a_variant_is_not_offered_as_a_duplicate(self, left, right):
        shared = dict(manufacturer="CIPL", hsn="3004", pack_size="1*15")
        pair = score_duplicate_pair(
            from_invoice_name("a", left, **shared),
            from_invoice_name("b", right, **shared),
        )
        assert pair is None, f"{left!r} vs {right!r} must not be offered"

    def test_corroboration_still_counts_when_nothing_is_unexplained(self):
        # The same shared fields on a pair with no extra token are genuine
        # supporting evidence, and must keep working.
        shared = dict(manufacturer="WIN", hsn="3004", pack_size="1*15")
        pair = score_duplicate_pair(
            from_invoice_name("a", "BETADINE", **shared),
            from_invoice_name("b", "BETADINE 10", **shared),
        )
        assert pair is not None
        assert any("made by WIN" in r for r in pair["reasons"])


class TestMachineFilledValues:
    """A value written by the reference matcher is not a parser reading.

    The per-field confidences describe what the PARSER got out of the invoice
    name. Once something else writes over one of those fields, the old number
    describes a value that is gone - and the queue reads it, so a dosage form
    supplied by the reference catalogue was being reported to the user as
    "guessed from the item name (0% confident)".
    """

    def test_a_filled_field_with_no_confidence_is_not_treated_as_a_guess(self):
        result = assess_product(product(form="Capsule", form_confidence=None))
        assert result["band"] == READY
        assert not any("dosage form" in r for r in result["reasons"])

    def test_a_stale_zero_confidence_would_have_reported_a_false_guess(self):
        # Pinned deliberately: this is the shape the bug had, so that a
        # regression shows up as this test rather than as a puzzling string
        # in the review queue.
        result = assess_product(product(form="Capsule", form_confidence=0.0))
        assert result["band"] == READY


class TestSuggestedValues:
    """A value PharmaGPT filled from the reference catalogue.

    No invoice stated it and no person approved it, so it sits between the two
    - complete enough to leave the blocked band, not owned enough to be
    rubber-stamped in a batch without anyone looking.
    """

    def test_a_suggestion_keeps_an_item_out_of_the_batch(self):
        result = assess_product(product(suggested_fields=["form", "base_unit"]))
        assert result["band"] == REVIEW
        assert any("reference catalogue" in r for r in result["reasons"])

    def test_the_reason_names_which_fields_came_from_the_reference(self):
        result = assess_product(product(suggested_fields=["strength"]))
        assert any("Strength" in r or "strength" in r for r in result["reasons"])
        assert result["weakest_field"] == "strength"

    def test_confirming_a_suggestion_settles_it(self):
        # Once a person approves the value it stops being a suggestion.
        result = assess_product(
            product(suggested_fields=["form"], confirmed_fields=["form"])
        )
        assert result["band"] == READY

    def test_a_suggestion_on_a_field_the_queue_does_not_require_is_ignored(self):
        # manufacturer is not one of the fields completeness is measured on.
        result = assess_product(product(suggested_fields=["manufacturer"]))
        assert result["band"] == READY
