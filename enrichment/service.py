"""Turns a catalogue product into ranked, human-checkable suggestions.

Nothing in this module writes to the catalogue. It returns what a reference
listing claims, alongside what the product currently holds, and the review UI
asks a person to decide. That separation is the point: the existing PATCH
remains the only path that can change a Product, so enrichment can never
quietly overwrite something a pharmacist confirmed.

Network use is deliberately lopsided. Matching is local and free, so every
candidate gets scored; fetching costs a request to someone else's server, so
only the top candidates are pulled, and only when a person asked.
"""

from typing import Optional

import requests
from pydantic import BaseModel

from core.logger import logger
from enrichment.index import open_index
from enrichment.matcher import MatchCandidate, STRONG_SCORE, find_matches
from enrichment.sources import onemg
from enrichment.sources.base import ProductFacts

# How many matches get their product page fetched. The rest are returned as
# name-level matches only - enough for a reviewer to spot the right one and
# ask for it specifically.
DEFAULT_FETCH_TOP = 2

REQUEST_TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "PharmaGPTCatalogueLookup/1.0 (pharmacy inventory reconciliation; "
        "contact: admin@pharmagpt.co)"
    )
}


class FieldSuggestion(BaseModel):
    field: str
    current: Optional[str] = None
    suggested: Optional[str] = None
    # True when the product already holds this value - shown as confirmation
    # rather than as a change to make.
    agrees: bool = False
    # True when a human already approved the current value. The UI warns
    # before letting a lookup override one of these.
    confirmed: bool = False


class Suggestion(BaseModel):
    match: MatchCandidate
    facts: Optional[ProductFacts] = None
    fields: list[FieldSuggestion] = []
    # Set when the match is strong AND its strength was actually verified.
    # Deliberately not called "safe to apply" - it still requires a click.
    high_confidence: bool = False


class EnrichmentResult(BaseModel):
    product_id: str
    query: str
    suggestions: list[Suggestion] = []
    # Why there is nothing to show, when there is nothing to show. An empty
    # list means very different things depending on this.
    status: str = "ok"
    message: Optional[str] = None


_COMPARE_FIELDS = (
    "brand", "strength", "form", "pack_size",
    "pack_multiplier", "base_unit", "manufacturer",
)


def _fetch_page(url: str, session: requests.Session) -> Optional[str]:
    try:
        response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        # A reference site being slow or unreachable must never take the
        # review screen down with it.
        logger.warning(f"[ENRICH] Could not fetch {url}: {type(e).__name__}: {e}")
        return None


def _diff_fields(product: dict, facts: ProductFacts) -> list[FieldSuggestion]:
    confirmed = set(product.get("confirmed_fields") or [])
    rows = []
    for field in _COMPARE_FIELDS:
        suggested = getattr(facts, field, None)
        if suggested in (None, "", []):
            continue
        current = product.get(field)
        rows.append(
            FieldSuggestion(
                field=field,
                current=None if current in (None, "", []) else str(current),
                suggested=str(suggested),
                agrees=(
                    current is not None
                    and str(current).strip().upper() == str(suggested).strip().upper()
                ),
                confirmed=field in confirmed,
            )
        )
    return rows


def enrich_product(product: dict, fetch_top: int = DEFAULT_FETCH_TOP) -> EnrichmentResult:
    """Looks the product up against the reference index and returns suggestions."""
    query = (
        product.get("canonical_name")
        or product.get("brand")
        or ""
    )
    # Prefer the spelling an invoice actually printed - it is what the
    # reference listing's own name most resembles.
    aliases = product.get("aliases") or []
    if aliases:
        query = aliases[0].get("raw_name") or query

    result = EnrichmentResult(product_id=product.get("id", ""), query=query)

    if not query.strip():
        result.status = "no_query"
        result.message = "This product has no name to look up."
        return result

    index = open_index()
    if index is None:
        result.status = "no_index"
        result.message = (
            "Reference catalogue has not been built yet. "
            "Run: python scripts/build_reference_index.py"
        )
        return result

    try:
        matches = find_matches(index, query, product.get("pack_size"))
    finally:
        index.close()

    if not matches:
        result.status = "no_match"
        result.message = (
            f"No listing matched “{query}”. This is expected for hospital "
            f"supplies, surgicals, and locally-branded items."
        )
        return result

    session = requests.Session()
    for position, match in enumerate(matches):
        suggestion = Suggestion(match=match)

        if position < fetch_top and match.source == onemg.SOURCE_NAME:
            html = _fetch_page(match.url, session)
            if html:
                facts = onemg.facts_from_html(html, match.url)
                if facts:
                    suggestion.facts = facts
                    suggestion.fields = _diff_fields(product, facts)

        suggestion.high_confidence = bool(
            match.score >= STRONG_SCORE and match.strength_verified and suggestion.facts
        )
        result.suggestions.append(suggestion)

    return result
