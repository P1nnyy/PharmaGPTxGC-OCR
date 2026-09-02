"""Deciding what a person actually has to look at.

The catalogue already knows how to read an invoice name into fields, how sure
it is about each one, and what is missing. What it did not do was act on any
of that: every product, however unambiguous, arrived as one more row to open,
read, and click through. A pharmacy that scans a week of invoices meets two
hundred rows that each cost six interactions, and the ones that genuinely
needed a human are buried among the ones that did not.

This module is the triage layer. It is pure - dicts in, dicts out, no Cypher -
so the rules that decide what gets a pharmacist's attention can be tested
directly, which is the same reason compute_flags lives outside the graph.

Two questions are answered here.

*What does this product still need?* - `assess_product` sorts each item into
one of three bands. The point is not the label but the split: `ready` items
can be approved as a batch without opening any of them, so the review screen
stops charging a full visit for a product that has nothing left to ask.

*Which of these are the same thing twice?* - `find_duplicate_candidates`
proposes merges. Products whose identity_key already matches merged on the
way in; what is left over is the harder case, where one invoice stated a
strength and another didn't, or two distributors spelled a brand differently
enough to survive normalisation. Finding those by eye across four hundred
rows is exactly the work nobody does, so the catalogue quietly grows two
records for one medicine.

Nothing here writes, and nothing here decides. Both functions return a verdict
WITH the evidence for it, because the reviewer's real question is never "what
is the score" but "why do you think so, and are you wrong". The same reason
the enrichment matcher reports its reasons rather than just its number.
"""

from typing import Any, Optional

from rapidfuzz import fuzz

from db.product_repository import REQUIRED_FIELDS
from enrichment.matcher import strengths_conflict
from extraction.normalizers.form_indicators import forms_conflict
from extraction.normalizers.product_parser import normalize_name

# The confidence at or above which a parsed value is treated as read from the
# invoice rather than guessed at. Deliberately the same 0.8 the review drawer
# already uses to label a field "read from invoice" vs "guessed" - if the gate
# and the label disagreed, the screen would offer to bulk-approve fields it
# was simultaneously marking as guesses.
AUTO_CONFIDENCE = 0.8

# Bands. A product is only ever in one.
READY = "ready"        # nothing left to ask - approvable in a batch
REVIEW = "review"      # complete, but resting on a guess nobody has approved
BLOCKED = "blocked"    # missing something a human has to supply or decide

# Which required fields carry a per-field parse confidence. manufacturer, hsn
# and schedule are absent by design: they are never parsed with a confidence,
# so there is nothing to gate on.
_CONFIDENCE_FIELDS = {
    "brand": "brand_confidence",
    "strength": "strength_confidence",
    "form": "form_confidence",
    "pack_size": "pack_size_confidence",
    "pack_multiplier": "pack_multiplier_confidence",
    "base_unit": "base_unit_confidence",
}

# Fields that are not read from the invoice but implied by another field, and
# the field they follow from. The parser derives base_unit from whichever form
# it matched - same evidence, same match, recorded at a lower confidence - so
# judging it separately asks about the form twice and answers with a number
# that was never an independent reading.
#
# This is not a detail. Every correctly parsed tablet carries form 0.85 and
# base_unit 0.70; gating on the latter put essentially the whole catalogue in
# "resting on a guess" over a unit nobody was actually guessing at, which is
# the exact pile-up this triage exists to prevent.
_DERIVED_FROM = {"base_unit": "form"}

_FIELD_LABELS = {
    "brand": "brand",
    "strength": "strength",
    "form": "dosage form",
    "pack_size": "pack size",
    "pack_multiplier": "units per pack",
    "base_unit": "dispensing unit",
}


def _missing(product: dict, field: str) -> bool:
    return product.get(field) in (None, "", [])


def _confidence(product: dict, field: str) -> Optional[float]:
    key = _CONFIDENCE_FIELDS.get(field)
    if not key:
        return None
    value = product.get(key)
    try:
        confidence = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    # Zero is "no reading was recorded", not "read with no confidence" - the
    # parser never emits it for a value it actually found. The review drawer
    # already reads it that way (it shows a confidence chip only above zero),
    # and when the two disagreed a field filled from the reference catalogue
    # was announced as "guessed from the item name (0% confident)".
    return confidence or None


def assess_product(product: dict) -> dict:
    """Sorts one product into a band, and says why in words.

    The bands are ordered by what they cost a human, not by how complete the
    record looks:

      blocked  - a required field is empty, or the evidence contradicts itself
                 (an MRP spread that says two pack sizes were merged). Someone
                 has to supply a fact or make a call; no amount of looking at
                 it settles anything.
      review   - every field is filled, but at least one is a low-confidence
                 guess that no human has approved. Cheap to check, and the
                 whole point of checking is that the guess might be wrong.
      ready    - every required field is filled and each is either confirmed by
                 a person or was read from the invoice at high confidence.
                 There is no question left to put to a reviewer.

    `caveats` carries what is imperfect but not disqualifying - a missing HSN,
    a manufacturer nobody recorded. Those travel separately from `reasons` so
    a batch approval can show them without them blocking the batch: a blank
    HSN is worth knowing about and is not worth stopping for.
    """
    flags = product.get("flags") or []
    confirmed = set(product.get("confirmed_fields") or [])
    acknowledged = set(product.get("acknowledged_fields") or [])

    reasons: list[str] = []
    caveats: list[str] = []

    missing_fields = [f for f in REQUIRED_FIELDS if _missing(product, f)]
    # A field a person looked at and deliberately left blank is not an open
    # question - the invoice may genuinely never state it. compute_flags
    # already downgrades those to "(acknowledged)"; the band has to agree,
    # otherwise an item stays blocked forever precisely because someone
    # answered it.
    #
    # Read from acknowledged_fields rather than confirmed_fields. Confirmation
    # is about a value someone approved, and a blank has no value to approve -
    # conflating the two let a product with no strength on any invoice claim
    # it needed nothing further.
    unanswered = [f for f in missing_fields if f not in acknowledged]

    for field in unanswered:
        reasons.append(f"No {_FIELD_LABELS[field]} recorded.")

    # No need to exclude acknowledged fields here: compute_flags has already
    # demoted a missing-but-confirmed field to "low", so anything still high is
    # a genuine contradiction. An MRP spread stays high even when the pack size
    # was confirmed, which is right - confirming the pack does not explain why
    # the same item was billed at twice the price.
    high_flags = [f for f in flags if f.get("severity") == "high"]
    for flag in high_flags:
        # The missing_* flags restate what `unanswered` already said above.
        if not flag.get("code", "").startswith("missing_"):
            reasons.append(flag.get("message", flag.get("code", "")))

    # Fields resting on a guess: present, not confirmed, and parsed below the
    # bar. Reported with the number so the reviewer knows how much doubt they
    # are being asked to resolve.
    weak: list[tuple[str, float]] = []
    for field in REQUIRED_FIELDS:
        if _missing(product, field) or field in confirmed:
            continue
        # A derived field is only its own question when the field it derives
        # from is absent - a dispensing unit read off a pack code with no form
        # to imply it. Otherwise the source field is what is uncertain, and it
        # is already being judged on its own line.
        source = _DERIVED_FROM.get(field)
        if source and not _missing(product, source):
            continue
        confidence = _confidence(product, field)
        if confidence is not None and confidence < AUTO_CONFIDENCE:
            weak.append((field, confidence))

    for field, confidence in weak:
        reasons.append(
            f"The {_FIELD_LABELS[field]} was guessed from the item name "
            f"({round(confidence * 100)}% confident)."
        )

    # A value PharmaGPT filled from the reference catalogue is complete but
    # unowned: no invoice stated it and no person has approved it. It must
    # therefore never let an item into the "nothing left to ask" band, which
    # is a claim that a batch approval is safe without opening the product.
    # A glance is exactly what these need, and naming the fields makes that
    # glance quick.
    suggested = [
        f for f in REQUIRED_FIELDS
        if f in set(product.get("suggested_fields") or []) and f not in confirmed
    ]
    if suggested:
        reasons.append(
            "Filled in from the reference catalogue, not from this invoice: "
            + ", ".join(_FIELD_LABELS[f] for f in suggested)
            + "."
        )

    # A spelling seen since the last confirmation reopens the item: the new
    # name may be the same product, or may be a different one that landed here
    # because both were silent about strength.
    new_aliases = [a for a in (product.get("aliases") or []) if a.get("status") == "new"]
    if product.get("review_status") == "confirmed" and new_aliases:
        names = ", ".join(a.get("raw_name", "") for a in new_aliases[:3])
        reasons.append(f"New spelling since it was confirmed: {names}.")

    for flag in flags:
        if flag.get("severity") in ("medium", "low") and flag.get("code") != "new_alias":
            caveats.append(flag.get("message", flag.get("code", "")))

    if unanswered or high_flags:
        band = BLOCKED
    elif weak or suggested or (new_aliases and product.get("review_status") == "confirmed"):
        band = REVIEW
    else:
        band = READY

    return {
        "product_id": product.get("id"),
        "band": band,
        "reasons": reasons,
        "caveats": caveats,
        # The field a reviewer should look at first: the least certain thing
        # standing between this product and being settled.
        "weakest_field": (
            unanswered[0] if unanswered
            else min(weak, key=lambda w: w[1])[0] if weak
            else suggested[0] if suggested
            else None
        ),
    }


def assess_catalogue(products: list[dict]) -> dict:
    """Bands every product and counts the outcome.

    The counts are what makes the screen honest about the size of the job: not
    "212 products need review" but "180 of them need nothing but your word".
    """
    assessments = [assess_product(p) for p in products]
    by_band = {READY: 0, REVIEW: 0, BLOCKED: 0}
    for assessment in assessments:
        by_band[assessment["band"]] += 1
    return {"assessments": assessments, "counts": by_band}


# --------------------------------------------------------------------------
# Duplicate detection
# --------------------------------------------------------------------------

# Below this a pair is not worth showing. Set high on purpose: a merge
# suggestion that turns out to be two different medicines costs far more than
# a duplicate nobody was offered, so this errs toward saying nothing.
MIN_DUPLICATE_SCORE = 82.0
# At or above this, every stated field agrees and only silence separates them.
LIKELY_DUPLICATE_SCORE = 90.0

# Tokens that differ between two distributors' rendering of one product
# without indicating a different product. Same list the enrichment matcher
# works from, for the same reason.
_NOISE_TOKENS = {
    "TAB", "TABS", "TABLET", "TABLETS", "CAP", "CAPS", "CAPSULE", "CAPSULES",
    "INJ", "INJECTION", "SUSP", "SUSPENSION", "SYP", "SYR", "SYRUP",
}

# An unexplained token is the strongest evidence of a different product line
# that a name comparison has: MAHAFLOX vs MAHAFLOX-LP scores ~90 on any fuzzy
# ratio and is a different medicine. Penalised the same asymmetric way the
# enrichment matcher penalises it, and for the same reason.
_FIRST_EXTRA_PENALTY = 20.0
_FURTHER_EXTRA_PENALTY = 5.0
_MAX_EXTRA_PENALTY = 35.0

# How close a token has to be to something on the other side before it counts
# as that thing written differently rather than as an extra word. MONTICOPE
# and MONTIC0PE - one OCR'd zero - sit at 89.
_TOKEN_MATCH_RATIO = 85.0

# Corroboration. Small on purpose - these are supporting evidence, never the
# reason for a merge. HSN is the weakest of them: distributors enter it
# inconsistently and a shared code covers most of a pharmacy's stock, so a
# match on it means very little.
_MANUFACTURER_BONUS = 6.0
_PACK_BONUS = 5.0
_HSN_BONUS = 3.0


def _name_of(product: dict) -> str:
    return product.get("brand") or product.get("canonical_name") or ""


def _tokens(text: str) -> set:
    return {t for t in normalize_name(text).split() if t and t not in _NOISE_TOKENS}


def _unexplained_tokens(
    tokens: set,
    other_tokens: set,
    other_compact: str,
    manufacturers: set,
) -> set:
    """Tokens on one side that the other side has nothing to account for.

    The distinction this draws is the whole difference between finding
    duplicates and inventing them. LIVO-LUK and LIVOLUK are one product whose
    space moved; MAHAFLOX and MAHAFLOX-LP are two products separated by one
    token. A plain set difference calls both of them "an extra token" and gets
    one of the two answers badly wrong.

    So a token counts as extra only when all three of these fail:

      * it appears inside the other name with its spaces removed - which is
        what a lost or gained separator looks like;
      * something on the other side is nearly the same word, which is what an
        OCR misread looks like (MONTIC0PE for MONTICOPE);
      * it is the manufacturer's name, which distributors inline into the item
        name on some invoices and omit on others.
    """
    extra = set()
    for token in tokens:
        if token in other_compact:
            continue
        if any(fuzz.ratio(token, other) >= _TOKEN_MATCH_RATIO for other in other_tokens):
            continue
        if token in manufacturers:
            continue
        extra.add(token)
    return extra


def _multipliers_conflict(a: Any, b: Any) -> bool:
    """True only when both products state a units-per-pack and they differ.

    This is the most discriminative field in the whole comparison. A strip of
    10 and a strip of 15 are different SKUs whatever else agrees, and merging
    them corrupts every stock figure derived from the result - silently, and
    in a way nothing downstream can detect. So a disagreement here disqualifies
    the pair outright rather than costing it points.
    """
    if a in (None, "") or b in (None, ""):
        return False
    try:
        return float(a) != float(b)
    except (TypeError, ValueError):
        return False


def score_duplicate_pair(left: dict, right: dict) -> Optional[dict]:
    """Scores one pair as candidates for being the same SKU.

    Returns None when the pair is disqualified, which is a different statement
    from a low score: disqualification means a stated field actively
    contradicts, and no amount of name similarity should override that.
    """
    left_name, right_name = _name_of(left), _name_of(right)
    if not left_name or not right_name:
        return None

    # Disqualifying contradictions, checked before anything is scored. Each is
    # a case where two products state a fact and the facts differ; silence on
    # either side is never a contradiction, because most invoice lines are
    # silent about most fields.
    if strengths_conflict(left.get("strength"), right.get("strength")):
        return None
    if forms_conflict(left.get("form"), right.get("form")):
        return None
    if _multipliers_conflict(left.get("pack_multiplier"), right.get("pack_multiplier")):
        return None

    left_norm, right_norm = normalize_name(left_name), normalize_name(right_name)
    base = float(fuzz.token_set_ratio(left_norm, right_norm))

    reasons: list[str] = []

    # token_set_ratio scores a subset as a perfect match, which is exactly the
    # blind spot that matters here: "MAHAFLOX" against "MAHAFLOX LP" is 100.
    # The penalty is what puts that difference back.
    left_tokens, right_tokens = _tokens(left_name), _tokens(right_name)
    manufacturers = {
        normalize_name(str(p.get("manufacturer")))
        for p in (left, right)
        if p.get("manufacturer")
    }
    left_compact = left_norm.replace(" ", "")
    right_compact = right_norm.replace(" ", "")
    extra = _unexplained_tokens(
        left_tokens, right_tokens, right_compact, manufacturers
    ) | _unexplained_tokens(
        right_tokens, left_tokens, left_compact, manufacturers
    )
    if extra:
        penalty = min(
            _FIRST_EXTRA_PENALTY + _FURTHER_EXTRA_PENALTY * (len(extra) - 1),
            _MAX_EXTRA_PENALTY,
        )
        base -= penalty
        reasons.append(
            f"One name carries {', '.join(sorted(extra))} and the other does not — "
            f"often a different product line rather than a spelling."
        )
    elif left_norm == right_norm:
        reasons.append(f"Both names reduce to “{left_norm}”.")
    else:
        # Not identical, but nothing in either name is unaccounted for in the
        # other - a moved separator, or a character read wrong. Saying they
        # "reduce to" one string here would be a claim the reviewer can see is
        # false, which costs more trust than the reason is worth.
        reasons.append(
            f"“{left_norm}” and “{right_norm}” differ only in how they are written — "
            f"neither carries a word the other cannot account for."
        )

    score = base

    def agrees(field: str) -> bool:
        a, b = left.get(field), right.get(field)
        return bool(a) and bool(b) and str(a).strip().upper() == str(b).strip().upper()

    # Corroboration is only allowed to help when nothing is unexplained.
    #
    # A brand's variants - DYTOR and DYTOR PLUS, ZERODOL P and ZERODOL SP,
    # DIAPRIDE M4 and DIAPRIDE M4 FORTE - share a manufacturer, a pack size
    # and an HSN code by construction, because they are the same product line
    # from the same maker. Letting those agreements add points therefore adds
    # nothing but noise, and it adds it in the worst possible place: it was
    # cancelling the extra-token penalty on the exact pairs the penalty exists
    # to catch, promoting them to "likely the same" underneath a reason that
    # read "often a different product line". Different medicines, offered for
    # merging, with the argument against printed next to the recommendation.
    if not extra:
        if agrees("manufacturer"):
            score += _MANUFACTURER_BONUS
            reasons.append(f"Both are made by {left['manufacturer']}.")
        if agrees("pack_size"):
            score += _PACK_BONUS
            reasons.append(f"Both are packed as {left['pack_size']}.")
        if agrees("hsn"):
            score += _HSN_BONUS
            reasons.append(f"Both carry HSN {left['hsn']} (weak evidence on its own).")

    # What separates them is silence, not disagreement - the case identity_key
    # cannot merge on its own, and the one most worth surfacing.
    for field in ("strength", "form", "pack_multiplier"):
        left_has, right_has = bool(left.get(field)), bool(right.get(field))
        if left_has != right_has:
            stated = left if left_has else right
            reasons.append(
                f"Only one of them states a {_FIELD_LABELS[field]} "
                f"({stated.get(field)}); the other is silent, so they could not merge automatically."
            )

    score = max(0.0, min(100.0, score))
    if score < MIN_DUPLICATE_SCORE:
        return None

    return {
        "product_ids": [left.get("id"), right.get("id")],
        "names": [left_name, right_name],
        "score": round(score, 1),
        "verdict": "likely" if score >= LIKELY_DUPLICATE_SCORE else "possible",
        "reasons": reasons,
        # Merging into the more complete record loses less: the other one's
        # spellings and history come across either way, but its blank fields
        # would overwrite nothing.
        "suggested_target": (
            left.get("id")
            if (left.get("completeness") or 0) >= (right.get("completeness") or 0)
            else right.get("id")
        ),
    }


def find_duplicate_candidates(products: list[dict], limit: int = 50) -> list[dict]:
    """Proposes merges across the catalogue, best evidence first.

    All-pairs, which is quadratic. That is affordable at the scale this runs
    at - a pharmacy's catalogue is hundreds of items, and rapidfuzz compares
    short strings in microseconds - and blocking on a name prefix, the usual
    fix, would defeat the purpose: the pairs most worth finding are the ones
    whose spellings diverge early.
    """
    candidates = []
    for i, left in enumerate(products):
        for right in products[i + 1:]:
            pair = score_duplicate_pair(left, right)
            if pair:
                candidates.append(pair)

    candidates.sort(key=lambda c: -c["score"])
    return candidates[:limit]
