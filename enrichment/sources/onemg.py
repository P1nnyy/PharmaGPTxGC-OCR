"""Reads catalogue facts from a Tata 1mg drug listing.

Why the page state and not the markup
-------------------------------------
The rendered HTML identifies fields with build-hashed class names like
`RxOOSSubstitute__imageContainer__h5DDo`, which change on every deploy - a
scraper written against them breaks silently and starts returning nothing,
or worse, the wrong element's text. The page instead ships its React store
inline as `window.__INITIAL_STATE__`, and inside it a schema.org Drug object
under `metaData.schema.drug`.

Preference order is therefore: schema.org fields first (a published vocabulary
with stable names), then the site's own `sku`/`priceData` structures for what
schema.org has no field for - pack size and units per pack. Both are read
defensively: a missing branch yields a null field, never an exception, because
one changed key upstream should cost a suggestion, not the review screen.

What this does NOT take
-----------------------
* HSN - not published here. It stays sourced from the invoice, which is the
  authoritative document for how the item was actually taxed.
* Schedule - the listing distinguishes prescription from OTC but not
  Schedule H from H1. The Rx note is passed through as evidence and the
  schedule field is left for a human, since the difference is a record-keeping
  obligation and a wrong answer is a compliance failure.
* Price - captured only so a reviewer can eyeball the match against what they
  were billed. A catalogue MRP would compete with the batch-level MRP the
  invoice recorded, and there would be no way to tell which the books meant.
"""

import json
import re
from typing import Any, Optional

from core.logger import logger
from enrichment.sources.base import ProductFacts

SOURCE_NAME = "1mg"
BASE_URL = "https://www.1mg.com"

_STATE_MARKER = "window.__INITIAL_STATE__"

# "10 tablets", "30 ml", "1 strip of 15 tablets"
_PACK_QTY_RE = re.compile(r"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z]+)")
_TAG_RE = re.compile(r"<[^>]+>")
_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)")

# 1mg's dosageForm vocabulary onto the dispensing unit a pharmacy counts in.
_FORM_TO_UNIT = {
    "tablet": "TABLET",
    "capsule": "CAPSULE",
    "syrup": "ML",
    "suspension": "ML",
    "solution": "ML",
    "drops": "ML",
    "eye drop": "ML",
    "ear drop": "ML",
    "injection": "VIAL",
    "vial": "VIAL",
    "ampoule": "AMPOULE",
    "sachet": "SACHET",
    "granules": "SACHET",
    "powder": "GM",
    "cream": "GM",
    "ointment": "GM",
    "gel": "GM",
    "lotion": "ML",
    "spray": "ML",
    "inhaler": "UNIT",
    "respule": "RESPULE",
}


def _strip_tags(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = _TAG_RE.sub("", value).strip()
    return text or None


def _dig(obj: Any, *path: str) -> Any:
    """Walks a nested dict, returning None the moment the path stops existing.

    The whole extractor leans on this: upstream owns this shape and can change
    it without notice, so every read has to tolerate the branch being gone.
    """
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def extract_initial_state(html: str) -> Optional[dict]:
    """Pulls the inline React store out of a 1mg page.

    Uses a JSON decoder positioned at the assignment rather than a regex to
    the end of the line - the object contains escaped braces and quotes in
    drug descriptions, which a regex would truncate mid-structure.
    """
    index = html.find(_STATE_MARKER)
    if index == -1:
        return None

    start = html.find("{", index)
    if start == -1:
        return None

    try:
        state, _ = json.JSONDecoder().raw_decode(html[start:])
        return state
    except ValueError as e:
        logger.warning(f"[ENRICH] 1mg page state did not parse: {e}")
        return None


def _parse_pack(price_data: dict) -> tuple[Optional[str], Optional[int]]:
    """Reads pack size and units per pack.

    sellingQuantity is the count the site sells the pack in and is the field
    that makes tablet-level stock possible, so it is preferred over anything
    inferred from the display text.
    """
    pack_text = price_data.get("packSizes")
    pack_size = _strip_tags(pack_text) if pack_text else None

    multiplier = price_data.get("sellingQuantity")
    if isinstance(multiplier, (int, float)) and multiplier > 0:
        multiplier = int(multiplier)
    else:
        multiplier = None

    # Fall back to the display text ("10 tablets") when the numeric field is
    # absent, but only for countable units - "30 ml" is a volume, and calling
    # it thirty dispensable units would inflate every stock figure derived
    # from it thirtyfold.
    if multiplier is None and pack_size:
        match = _PACK_QTY_RE.search(pack_size)
        if match:
            unit = match.group("unit").lower()
            if unit.startswith(("tab", "cap", "sachet", "vial", "amp", "piece", "unit")):
                multiplier = int(float(match.group("qty")))

    return pack_size, multiplier


def _parse_strength(drug_schema: dict, composition: Optional[str]) -> Optional[str]:
    """Prefers the dose stated in the composition over the product title.

    drugUnit reads "20mg Tablet" - the dose plus the form - while the
    composition reads "Duloxetine (20mg)". Both agree here, but the
    composition is the one that stays correct for combination products, where
    the title often carries only the headline salt's strength.
    """
    # Upper-cased throughout: the catalogue stores "20MG", so returning
    # "20mg" here would read as a difference from the parsed value and make
    # an agreeing source look like a conflicting one.
    if composition:
        doses = re.findall(r"\(([^)]*\d[^)]*)\)", composition)
        if doses:
            return "+".join(d.strip().replace(" ", "").upper() for d in doses)

    drug_unit = drug_schema.get("drugUnit")
    if isinstance(drug_unit, str):
        match = re.search(r"\d+(?:\.\d+)?\s*(?:MCG|MG|IU|ML|GM|%)", drug_unit, re.IGNORECASE)
        if match:
            return match.group(0).replace(" ", "").upper()
    return None


def _parse_price(state: dict) -> Optional[float]:
    raw = _dig(state, "drugPageReducer", "dynamicData", "priceBox", "priceList")
    if isinstance(raw, list) and raw:
        text = _dig(raw[0], "mrp", "price")
        if isinstance(text, str):
            match = _PRICE_RE.search(text)
            if match:
                return float(match.group(1))
    offer_price = _dig(
        state, "drugPageReducer", "staticData", "metaData", "schema", "drug", "offers", "price"
    )
    if isinstance(offer_price, (int, float)):
        return float(offer_price)
    return None


def facts_from_state(state: dict, source_url: str) -> Optional[ProductFacts]:
    """Maps a parsed page state onto catalogue-shaped facts."""
    page = _dig(state, "drugPageReducer")
    if not isinstance(page, dict):
        return None

    static = page.get("staticData") or {}
    dynamic = page.get("dynamicData") or {}
    sku = static.get("sku") or {}
    drug_schema = _dig(static, "metaData", "schema", "drug") or {}

    listing_name = sku.get("name") or _dig(static, "productConfig", "entity_name")

    composition = _strip_tags(_dig(sku, "summary", "salt_composition", "display_text"))
    form = drug_schema.get("dosageForm") or sku.get("pack_form")
    form = form.strip().title() if isinstance(form, str) and form.strip() else None

    pack_size, multiplier = _parse_pack(dynamic.get("priceData") or {})

    manufacturer = (
        _dig(drug_schema, "marketer", "legalName")
        or _dig(sku, "marketer", "name")
        or _dig(sku, "manufacturer", "name")
    )

    prescription_note = _strip_tags(
        _dig(sku, "summary", "prescription_required", "header")
    )
    if prescription_note:
        # The header carries a trailing "Why?" help link whose anchor text
        # survives tag stripping.
        prescription_note = re.sub(r"\s*Why\?\s*$", "", prescription_note).strip() or None
    if not prescription_note and drug_schema.get("prescriptionStatus"):
        prescription_note = str(drug_schema["prescriptionStatus"]).title()

    base_unit = None
    if form:
        for keyword, unit in _FORM_TO_UNIT.items():
            if keyword in form.lower():
                base_unit = unit
                break

    # The brand is the listing name with the dose and form stripped back off,
    # so it lines up with how the catalogue stores brands.
    brand = None
    if listing_name:
        brand = re.sub(
            r"\s*\d+(?:\.\d+)?\s*(?:MCG|MG|IU|ML|GM|%)\b", " ", listing_name, flags=re.IGNORECASE
        )
        if form:
            brand = re.sub(rf"\b{re.escape(form)}s?\b", " ", brand, flags=re.IGNORECASE)
        # Upper-cased to match how the catalogue stores brands. A listing's
        # own casing ("PICOlex") would otherwise be written straight into the
        # record and sit inconsistently beside every parser-derived brand.
        brand = re.sub(r"\s+", " ", brand).strip().upper() or None

    facts = ProductFacts(
        source=SOURCE_NAME,
        source_url=source_url,
        listing_name=listing_name,
        brand=brand,
        strength=_parse_strength(drug_schema, composition),
        form=form,
        pack_size=pack_size,
        pack_multiplier=multiplier,
        base_unit=base_unit,
        manufacturer=manufacturer if isinstance(manufacturer, str) else None,
        composition=composition,
        listed_mrp=_parse_price(state),
        prescription_note=prescription_note,
        # Stated explicitly so the review screen can say "this source does not
        # publish it" rather than showing an empty box that looks like a
        # source asserting the field is blank.
        unavailable=["hsn", "schedule"],
    )
    return facts


def facts_from_html(html: str, source_url: str) -> Optional[ProductFacts]:
    state = extract_initial_state(html)
    if state is None:
        logger.warning(f"[ENRICH] No page state found at {source_url}")
        return None
    return facts_from_state(state, source_url)
