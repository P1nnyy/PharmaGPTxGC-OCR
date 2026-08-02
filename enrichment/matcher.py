"""Scores reference listings against an invoice's item name.

The whole risk of this feature lives in this file. Everything downstream just
displays what the matcher returns, so a confident wrong match here is a wrong
strength written into a medicine record.

Two rules do the load-bearing work:

1. A stated strength that DISAGREES is disqualifying, not merely a penalty.
   DONEP 5MG and DONEP 10MG have brand similarity of 100 - no amount of name
   scoring separates them, and a penalty large enough to would also suppress
   legitimate matches. So a candidate whose strength contradicts a known
   invoice strength is dropped outright, whatever it scores otherwise. When
   either side is silent about strength no rule can fire, and the result is
   reported as unverified rather than confident.

2. Extra brand tokens are penalised asymmetrically. MAHAFLOX vs MAHAFLOX-LP
   and DYNAPAR QPS vs DYNAPAR QPS PLUS are different medicines separated by
   one token, and plain fuzzy ratios score them ~90. A candidate carrying
   tokens the query never mentioned is far more likely to be a different
   product line than a spelling variant, so it is pushed down hard.

Scores are advisory and always shown to a human. Nothing here decides
anything; it only decides what to put in front of the reviewer first.
"""

import re
from typing import Optional

from pydantic import BaseModel
from rapidfuzz import fuzz

from extraction.normalizers.product_parser import normalize_name, parse_product_name

# Below this a candidate is not worth a reviewer's attention.
MIN_SCORE = 60.0
# At or above this the brand, strength and form all line up. Still shown for
# confirmation - it raises no field automatically.
STRONG_SCORE = 88.0

# Tokens that routinely differ between a distributor's rendering and a retail
# listing without indicating a different product.
_NOISE_TOKENS = {"TAB", "TABS", "TABLET", "CAP", "CAPS", "CAPSULE", "INJ", "INJECTION", "SUSP", "SYP"}


class MatchCandidate(BaseModel):
    slug: str
    source: str
    url: str
    display: str
    listing_brand: str
    listing_strength: Optional[str] = None
    listing_form: Optional[str] = None

    score: float
    brand_score: float
    # True when both sides stated a strength and they agree - the difference
    # between "we checked" and "nobody said".
    strength_verified: bool = False
    form_agrees: bool = False
    # Plain-language reasons, shown next to the suggestion so a reviewer can
    # judge the match rather than the number.
    reasons: list[str] = []


def _significant_tokens(text: str) -> set:
    return {t for t in normalize_name(text).split() if t and t not in _NOISE_TOKENS}


def _strengths_conflict(a: Optional[str], b: Optional[str]) -> bool:
    """True only when both sides stated a strength and they genuinely differ.

    Silence is never a conflict: most invoice lines omit strength entirely,
    and treating that as disagreement would reject every useful match.

    Neither is a missing UNIT. Listings routinely write the dose bare -
    "lipigo-10-tablet" for Lipigo 10mg - so when either side omits the unit
    the comparison falls back to the numbers. Demanding an exact string match
    there would disqualify the one correct listing while leaving its wrong-dose
    siblings in the results, which is the worst possible outcome: the reviewer
    is shown only wrong answers and no sign that the right one was discarded.
    """
    if not a or not b:
        return False

    ca, cb = _canon_strength(a), _canon_strength(b)
    if ca == cb:
        return False

    na, nb = _strength_numbers(ca), _strength_numbers(cb)
    if not _has_unit(ca) or not _has_unit(cb):
        return na != nb

    return True


def _canon_strength(value: str) -> str:
    text = re.sub(r"\s+", "", str(value).upper())
    # 20MG and 20.0MG are the same dose.
    return re.sub(r"(\d+)\.0+(?=[A-Z%]|$)", r"\1", text)


def _strength_numbers(value: str) -> tuple:
    return tuple(float(n) for n in re.findall(r"\d+(?:\.\d+)?", value))


def _has_unit(value: str) -> bool:
    return bool(re.search(r"(MCG|MG|IU|ML|GM|%)", value))


def score_candidate(
    query_brand: str,
    query_strength: Optional[str],
    query_form: Optional[str],
    candidate: dict,
) -> Optional[MatchCandidate]:
    """Scores one listing, or returns None if it is disqualified."""
    listing_brand = candidate.get("brand_key") or ""
    if not listing_brand:
        return None

    if _strengths_conflict(query_strength, candidate.get("strength")):
        # Rule 1. Not a penalty - a rejection.
        return None

    brand_score = max(
        fuzz.token_sort_ratio(query_brand, listing_brand),
        fuzz.partial_ratio(query_brand, listing_brand),
    )

    query_tokens = _significant_tokens(query_brand)
    listing_tokens = _significant_tokens(listing_brand)
    extra = listing_tokens - query_tokens
    missing = query_tokens - listing_tokens

    score = float(brand_score)
    reasons: list[str] = []

    # Rule 2. A qualifier the invoice never mentioned usually means a
    # different product in the same family.
    if extra:
        score -= 18.0 * len(extra)
        reasons.append(f"listing adds {', '.join(sorted(extra))} — check this is the same product")
    if missing:
        score -= 12.0 * len(missing)
        reasons.append(f"invoice says {', '.join(sorted(missing))}, listing does not")

    strength_verified = bool(
        query_strength and candidate.get("strength")
        and not _strengths_conflict(query_strength, candidate.get("strength"))
    )
    if strength_verified:
        score += 8.0
        reasons.append(f"strength {query_strength} matches")
    elif query_strength and not candidate.get("strength"):
        reasons.append("listing does not state a strength — not verified")
    elif not query_strength:
        reasons.append("invoice states no strength — cannot verify this is the right one")

    form_agrees = bool(
        query_form and candidate.get("form")
        and normalize_name(query_form) == normalize_name(candidate["form"])
    )
    if form_agrees:
        score += 4.0
    elif query_form and candidate.get("form"):
        score -= 10.0
        reasons.append(f"form differs: invoice {query_form}, listing {candidate['form']}")

    score = max(0.0, min(100.0, score))
    if score < MIN_SCORE:
        return None

    return MatchCandidate(
        slug=candidate["slug"],
        source=candidate["source"],
        url=candidate["url"],
        display=candidate.get("display") or listing_brand,
        listing_brand=listing_brand,
        listing_strength=candidate.get("strength"),
        listing_form=candidate.get("form"),
        score=round(score, 1),
        brand_score=float(brand_score),
        strength_verified=strength_verified,
        form_agrees=form_agrees,
        reasons=reasons,
    )


def find_matches(index, name: str, pack: Optional[str] = None, limit: int = 5) -> list[MatchCandidate]:
    """Ranked candidates for an invoice item name.

    The name is run through the same parser the catalogue uses, so the query
    is compared on brand/strength/form rather than raw text - "MONTICOPE
    SUSPENSION 60 ML" and "MONTICOPE SUSP" ask the same question.
    """
    parsed = parse_product_name(name, pack)
    brand = normalize_name(parsed.brand.value or name)
    if not brand:
        return []

    rows = index.candidates(brand)
    scored = []
    for row in rows:
        candidate = score_candidate(brand, parsed.strength.value, parsed.form.value, row)
        if candidate:
            scored.append(candidate)

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:limit]
