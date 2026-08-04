"""The matcher is the only place where this feature can do real harm, so its
rejection rules get the most coverage. Cases are drawn from listings actually
present in the 1mg index."""

import pytest

from enrichment.index import slug_to_fields
from enrichment.matcher import MIN_SCORE, score_candidate


def listing(brand_key, strength=None, form=None, slug="/drugs/x-1"):
    return {
        "slug": slug,
        "source": "1mg",
        "url": f"https://www.1mg.com{slug}",
        "display": brand_key.lower(),
        "brand_key": brand_key,
        "strength": strength,
        "form": form,
    }


class TestSlugParsing:
    @pytest.mark.parametrize(
        "slug,brand,strength,form",
        [
            ("/drugs/dulohox-20mg-tablet-732600", "DULOHOX", "20MG", "Tablet"),
            ("/drugs/eromed-gel-240352", "EROMED", None, "Gel"),
            ("/drugs/cinnarise-d-15mg-20mg-tablet-636478", "CINNARISE D", "15MG+20MG", "Tablet"),
        ],
    )
    def test_reads_slug_fields(self, slug, brand, strength, form):
        f = slug_to_fields(slug)
        assert f["brand_key"] == brand
        assert f["strength"] == strength
        assert f["form"] == form

    @pytest.mark.parametrize("slug,brand,strength", [
        ("/drugs/lipigo-10-tablet-123", "LIPIGO", "10"),
        ("/drugs/lipigo-20-tablet-124", "LIPIGO", "20"),
        ("/drugs/lipigo-f-5-tablet-9", "LIPIGO F", "5"),
    ])
    def test_bare_number_is_a_strength_not_part_of_the_brand(self, slug, brand, strength):
        # Reading "lipigo-10" as a brand makes the correct listing score
        # identically to lipigo-20 and lipigo-5, so the reviewer sees three
        # indistinguishable options with no signal which is right.
        f = slug_to_fields(slug)
        assert f["brand_key"] == brand
        assert f["strength"] == strength

    def test_otc_id_suffix_is_stripped(self):
        # OTC ids are fused to the last token with no separator.
        f = slug_to_fields("/otc/melaglow-day-otc372604")
        assert "372604" not in f["brand_key"]
        assert f["brand_key"] == "MELAGLOW DAY"


class TestStrengthGuard:
    def test_disagreeing_strength_is_rejected_outright(self):
        # The load-bearing rule. DONEP 5MG and DONEP 10MG score 100 on brand;
        # no name-based penalty can separate them.
        assert score_candidate("DONEP", "5MG", None, listing("DONEP", "10MG")) is None

    def test_agreeing_strength_is_verified(self):
        c = score_candidate("DONEP", "5MG", None, listing("DONEP", "5MG"))
        assert c is not None and c.strength_verified

    def test_missing_unit_still_matches_the_same_dose(self):
        # Listings write the dose bare ("lipigo-10-tablet"). Rejecting that
        # would discard the one right answer and keep its wrong-dose siblings.
        c = score_candidate("LIPIGO", "10MG", None, listing("LIPIGO", "10"))
        assert c is not None and c.strength_verified

    def test_missing_unit_different_number_still_rejected(self):
        assert score_candidate("LIPIGO", "10MG", None, listing("LIPIGO", "20")) is None

    def test_decimal_forms_agree(self):
        c = score_candidate("X", "20MG", None, listing("X", "20.0MG"))
        assert c is not None and c.strength_verified

    def test_silence_on_either_side_is_not_a_conflict(self):
        assert score_candidate("DONEP", None, None, listing("DONEP", "10MG")) is not None
        assert score_candidate("DONEP", "5MG", None, listing("DONEP", None)) is not None

    def test_unverified_when_nobody_stated_a_strength(self):
        c = score_candidate("DONEP", None, None, listing("DONEP", "10MG"))
        assert not c.strength_verified
        assert any("cannot verify" in r for r in c.reasons)


class TestQualifierTokens:
    def test_extra_qualifier_is_pushed_below_the_exact_match(self):
        # MAHAFLOX and MAHAFLOX-LP are different medicines one token apart.
        exact = score_candidate("MAHAFLOX", None, None, listing("MAHAFLOX"))
        variant = score_candidate("MAHAFLOX", None, None, listing("MAHAFLOX LP"))
        assert exact.score > (variant.score if variant else 0)

    def test_extra_qualifier_is_called_out(self):
        c = score_candidate("DYNAPAR", None, None, listing("DYNAPAR PLUS"))
        if c:
            assert any("adds" in r.lower() for r in c.reasons)

    def test_missing_qualifier_is_called_out(self):
        # Invoice says DYNAPAR QPS, listing is plain DYNAPAR - a real product
        # difference the reviewer has to see.
        c = score_candidate("DYNAPAR QPS", None, None, listing("DYNAPAR"))
        assert c is None or any("does not" in r for r in c.reasons)

    def test_dosage_words_do_not_count_as_qualifiers(self):
        # "NUROKIND LC TAB" vs "NUROKIND LC" differ only by a form word.
        c = score_candidate("NUROKIND LC TAB", None, None, listing("NUROKIND LC"))
        assert c is not None
        assert not any("adds" in r.lower() for r in c.reasons)


class TestMarketingCopyVersusVariant:
    """Both "add tokens", and the penalty has to tell them apart.

    A single extra short code usually means a DIFFERENT medicine
    (MAHAFLOX vs MAHAFLOX-LP). A pile of extra words usually means the same
    product described at retail ("SUNSHADE ULTRA BLOCK" vs "SUNSHADE ULTRA
    BLOCK MINERAL GLOW SUNSCREEN SPF 50 PA"). A flat per-token charge treated
    the second as six times worse and threw the correct listing away while a
    weaker one survived.
    """

    def test_long_marketing_listing_still_matches(self):
        c = score_candidate(
            "SUNSHADE ULTRA BLOCK", None, None,
            listing("SUNSHADE ULTRA BLOCK MINERAL GLOW SUNSCREEN SPF 50 PA"),
        )
        assert c is not None
        assert c.score >= MIN_SCORE

    def test_single_extra_token_still_ranks_below_the_exact_match(self):
        exact = score_candidate("MAHAFLOX", None, None, listing("MAHAFLOX"))
        variant = score_candidate("MAHAFLOX", None, None, listing("MAHAFLOX LP"))
        assert exact.score == 100.0
        assert variant is not None
        assert variant.score < exact.score - 10

    def test_a_very_verbose_listing_is_not_penalised_out_of_existence(self):
        # The cap exists so that piling on descriptive words cannot drive a
        # genuine match below the threshold. Asserting the surviving score
        # rather than equality between two listings: their base brand
        # similarity differs with length, so the totals legitimately differ
        # even where the penalty component is identical.
        verbose = score_candidate(
            "BRAND", None, None,
            listing("BRAND ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT"),
        )
        assert verbose is not None
        assert verbose.score >= MIN_SCORE

    def test_penalty_stops_growing_once_capped(self):
        from enrichment.matcher import (
            _FIRST_EXTRA_PENALTY,
            _FURTHER_EXTRA_PENALTY,
            _MAX_EXTRA_PENALTY,
        )

        def penalty(n_extra: int) -> float:
            return min(
                _FIRST_EXTRA_PENALTY + _FURTHER_EXTRA_PENALTY * (n_extra - 1),
                _MAX_EXTRA_PENALTY,
            )

        assert penalty(1) == _FIRST_EXTRA_PENALTY
        assert penalty(2) > penalty(1)
        assert penalty(20) == _MAX_EXTRA_PENALTY
        assert penalty(50) == penalty(20)

    def test_the_exact_match_still_wins_over_the_verbose_one(self):
        exact = score_candidate("SUNSHADE", None, None, listing("SUNSHADE"))
        verbose = score_candidate(
            "SUNSHADE", None, None, listing("SUNSHADE ULTRA BLOCK MINERAL GLOW SUNSCREEN")
        )
        assert exact.score > verbose.score


class TestFormAndThreshold:
    def test_form_disagreement_penalised_and_explained(self):
        tablet = score_candidate("NUROKIND LC", None, "Tablet", listing("NUROKIND LC", None, "Tablet"))
        injection = score_candidate("NUROKIND LC", None, "Tablet", listing("NUROKIND LC", None, "Injection"))
        assert tablet.score > injection.score
        assert any("form differs" in r for r in injection.reasons)

    def test_unrelated_brand_falls_below_threshold(self):
        assert score_candidate("MONTICOPE", None, None, listing("ZYRTEC")) is None

    def test_surviving_candidates_meet_the_floor(self):
        c = score_candidate("PICOLEX", None, None, listing("PICOLEX"))
        assert c.score >= MIN_SCORE

    def test_empty_listing_brand_is_skipped(self):
        assert score_candidate("PICOLEX", None, None, listing("")) is None
