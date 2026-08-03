"""Reads catalogue facts from a PharmEasy listing.

Where 1mg hides its data in a React store, PharmEasy publishes proper
server-rendered schema.org JSON-LD - a `Drug` and a `Product` node inside an
`@graph`. That is a published vocabulary rather than one site's internal
state, so it is both easier to read and far less likely to move underneath
us; it is preferred over any markup on the page for exactly that reason.

What each node contributes:

    Drug.dosageForm           "TABLET"                -> form
    Drug.availableStrength    {value: 5.0, unit: mg}  -> strength, structured
    Drug.activeIngredient     "Zolpidem(5.0 Mg)"      -> composition
    Drug.manufacturer         legalName               -> manufacturer
    Drug.prescriptionStatus   schema.org/PrescriptionOnly
    Product.brand.name        "ZOLFRESH"              -> brand, already clean

Pack size is the one thing the JSON-LD omits, and the one thing PharmEasy's
URL gives away for free: `zolfresh-5mg-strip-of-15-tablets-864`. That is
parsed from the slug in enrichment/index.py, so it is known before this
module is ever called and does not require fetching the page at all.

Same deliberate omissions as the 1mg source: no HSN (not published; the
invoice is authoritative for how an item was actually taxed) and no schedule
(the listing separates prescription-only from OTC but not Schedule H from H1,
and guessing between them is a compliance claim nobody checked).
"""

import json
import re
from typing import Any, Optional

from core.logger import logger
from enrichment.sources.base import ProductFacts

SOURCE_NAME = "PharmEasy"
BASE_URL = "https://pharmeasy.in"

_LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)

# PharmEasy's dosageForm vocabulary onto the unit a pharmacy counts in.
_FORM_TO_UNIT = {
    "tablet": "TABLET",
    "capsule": "CAPSULE",
    "syrup": "ML",
    "suspension": "ML",
    "solution": "ML",
    "drop": "ML",
    "injection": "VIAL",
    "vial": "VIAL",
    "ampoule": "AMPOULE",
    "sachet": "SACHET",
    "granule": "SACHET",
    "powder": "GM",
    "cream": "GM",
    "ointment": "GM",
    "gel": "GM",
    "lotion": "ML",
    "spray": "ML",
    "inhaler": "UNIT",
    "respule": "RESPULE",
}


def _graph_nodes(html: str) -> list[dict]:
    """Every JSON-LD node on the page, flattened out of any @graph wrapper."""
    nodes: list[dict] = []
    for block in _LD_JSON_RE.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            # One malformed block should not discard the others.
            continue
        for entry in data if isinstance(data, list) else [data]:
            if not isinstance(entry, dict):
                continue
            graph = entry.get("@graph")
            if isinstance(graph, list):
                nodes.extend(n for n in graph if isinstance(n, dict))
            else:
                nodes.append(entry)
    return nodes


def _node_of_type(nodes: list[dict], wanted: str) -> Optional[dict]:
    for node in nodes:
        if node.get("@type") == wanted:
            return node
    return None


def _trim_decimal(value: str) -> str:
    """5.0 -> 5, but 2.5 stays 2.5."""
    value = value.strip()
    return value[:-2] if value.endswith(".0") else value


def _strength_from(drug: dict) -> Optional[str]:
    """Prefers the structured DrugStrength over parsing the ingredient text.

    availableStrength states value and unit separately, so there is no
    guessing where the number ends. Combination products state BOTH as
    parallel plus-separated lists:

        strengthValue = "500.0 + 125.0"
        strengthUnit  = "mg+mg"

    which have to be zipped, not concatenated - joining the raw strings
    produces "500.0 + 125MG+MG", a value that is not a dose at all and would
    be written into the catalogue verbatim if a reviewer accepted it.
    """
    strength = drug.get("availableStrength")
    if isinstance(strength, dict):
        raw_value = strength.get("strengthValue")
        raw_unit = strength.get("strengthUnit")
        if raw_value and raw_unit:
            values = [v for v in re.split(r"\s*\+\s*", str(raw_value)) if v.strip()]
            units = [u for u in re.split(r"\s*\+\s*", str(raw_unit)) if u.strip()]
            if values:
                # A single unit covers every value ("5/10" with unit "mg");
                # otherwise each value takes the unit in the same position.
                if len(units) == 1:
                    units = units * len(values)
                if len(units) == len(values):
                    return "+".join(
                        f"{_trim_decimal(v)}{u.strip().upper()}" for v, u in zip(values, units)
                    )
                # Shapes disagree - fall through to the ingredient text
                # rather than emit a value stitched together on a guess.

    # Fall back to the ingredient string: "Zolpidem(5.0 Mg)".
    ingredient = drug.get("activeIngredient")
    if isinstance(ingredient, str):
        match = re.search(r"([\d.]+)\s*(MCG|MG|IU|ML|GM|%)", ingredient, re.IGNORECASE)
        if match:
            value = match.group(1)
            if value.endswith(".0"):
                value = value[:-2]
            return f"{value}{match.group(2).upper()}"
    return None


def _dig(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def facts_from_html(html: str, source_url: str) -> Optional[ProductFacts]:
    nodes = _graph_nodes(html)
    if not nodes:
        logger.warning(f"[ENRICH] No JSON-LD found at {source_url}")
        return None

    drug = _node_of_type(nodes, "Drug") or {}
    product = _node_of_type(nodes, "Product") or {}
    if not drug and not product:
        return None

    listing_name = drug.get("name") or product.get("name")

    form_raw = drug.get("dosageForm")
    form = str(form_raw).strip().title() if form_raw else None

    base_unit = None
    if form:
        for keyword, unit in _FORM_TO_UNIT.items():
            if keyword in form.lower():
                base_unit = unit
                break

    # Brand comes straight from the Brand node, already isolated from the
    # strength and form - no stripping required, unlike the 1mg listing name.
    brand = _dig(product, "brand", "name")
    if isinstance(brand, str):
        brand = brand.strip().upper() or None
    else:
        brand = None

    manufacturer = (
        _dig(drug, "manufacturer", "legalName")
        or _dig(product, "manufacturer", "name")
        or _dig(drug, "manufacturer", "name")
    )
    if isinstance(manufacturer, str):
        manufacturer = manufacturer.strip() or None
    else:
        manufacturer = None

    prescription_note = None
    status = drug.get("prescriptionStatus")
    if isinstance(status, str):
        prescription_note = (
            "Prescription required" if "PrescriptionOnly" in status else "Over the counter"
        )

    price = _dig(product, "offers", "price") or _dig(drug, "offers", "price")
    try:
        listed_mrp = float(price) if price is not None else None
    except (TypeError, ValueError):
        listed_mrp = None

    composition = drug.get("activeIngredient")

    return ProductFacts(
        source=SOURCE_NAME,
        source_url=source_url,
        listing_name=listing_name,
        brand=brand,
        strength=_strength_from(drug),
        form=form,
        # pack_size / pack_multiplier are read from the URL slug during
        # indexing, where they are available without a network request.
        base_unit=base_unit,
        manufacturer=manufacturer,
        composition=composition if isinstance(composition, str) else None,
        listed_mrp=listed_mrp,
        prescription_note=prescription_note,
        unavailable=["hsn", "schedule"],
    )
