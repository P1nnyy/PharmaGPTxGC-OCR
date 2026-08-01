"""Pulls catalogue structure out of the one string an invoice actually gives us.

The problem
-----------
A pharma invoice names an item however the distributor's software felt like
naming it. Across real bills this system has processed, the same catalogue
facts arrive in incompatible shapes:

    LIPIGO 10 MG              strength in the name, form absent
    LIVO-LUK SOLUTION 200ML   form and pack volume in the name, no strength
    MONTICOPE SUSPENSION 60 ML   same, spaced differently
    RANIDOM-MPS SUSP          form abbreviated, pack absent entirely
    NUROKIND LC TAB           form abbreviated, strength absent
    NITROLONG-2.6 MANKINDS    strength as a bare number, manufacturer inlined
    DONEP                     nothing but a brand

Some invoices carry a separate pack column ("10'S", "1*10"); most don't. So
the fields the catalogue needs - strength, form, pack size, units per pack -
are sometimes in the name, sometimes in a sibling column, and sometimes
nowhere at all.

Why this proposes rather than decides
-------------------------------------
Every field here is returned as a value *plus a confidence and the substring
it came from*, never as a bare fact. Two reasons:

1. The parse is genuinely uncertain. "30GM" is a pack weight on a cream and a
   strength on a sachet, and the name alone often can't settle it.
2. Getting it wrong is expensive in a specific way: pack multiplier feeds
   tablet-level stock, so mistaking a 10-tablet strip for a 15-tablet one
   silently corrupts every stock count derived from it afterwards.

So the parse pre-fills a review form, and a human confirms. What this module
buys is that the human is correcting three fields instead of typing seven.

Units: MG/MCG/IU/% are read as strength, while ML/GM/L are read as pack
measure. That split is not arbitrary - it is what the observed names do.
"200ML" on LIVO-LUK is the bottle, not the dose; "10 MG" on LIPIGO is the
dose, not the bottle. Bare numbers hanging off a hyphen (NITROLONG-2.6) are
offered as a strength at low confidence, because that is a real convention
but also indistinguishable from a brand that simply contains a number.
"""

import re
from typing import Any, List, Optional

from pydantic import BaseModel

# Dosage forms as they actually appear, mapped to a canonical label and the
# unit a single dispensable item is counted in. Longer phrases are matched
# first so "EYE DROPS" doesn't get shortened to "DROPS", which would lose the
# route and with it the reason two same-brand products are different items.
_FORMS: List[tuple[str, str, str]] = [
    # (pattern alternatives, canonical form, base unit)
    (r"EYE\s*/?\s*EAR\s+DROPS?", "Eye/Ear Drops", "ML"),
    (r"EYE\s+DROPS?|E\.?D\b", "Eye Drops", "ML"),
    (r"EAR\s+DROPS?", "Ear Drops", "ML"),
    (r"NASAL\s+DROPS?", "Nasal Drops", "ML"),
    (r"NASAL\s+SPRAY", "Nasal Spray", "ML"),
    (r"MOUTH\s*WASH|GARGLE", "Mouthwash", "ML"),
    (r"RESPULES?|NEBULISER|NEBULIZER", "Respule", "RESPULE"),
    (r"ROTACAPS?", "Rotacap", "CAPSULE"),
    (r"INHALER|METERED\s+DOSE", "Inhaler", "UNIT"),
    (r"SUPPOSITOR(?:Y|IES)", "Suppository", "UNIT"),
    (r"TABLETS?|TABS?\b|TAB\b", "Tablet", "TABLET"),
    (r"CAPSULES?|CAPS?\b", "Capsule", "CAPSULE"),
    (r"SUSPENSION|SUSP\b", "Suspension", "ML"),
    (r"SYRUPS?|SYP\b|SYR\b", "Syrup", "ML"),
    (r"INJECTIONS?|INJ\b", "Injection", "VIAL"),
    (r"VIALS?", "Vial", "VIAL"),
    (r"AMPOULES?|AMPS?\b", "Ampoule", "AMPOULE"),
    (r"SACHETS?|SACH\b", "Sachet", "SACHET"),
    (r"GRANULES?", "Granules", "SACHET"),
    (r"OINTMENTS?|OINT\b", "Ointment", "GM"),
    (r"CREAMS?|CRM\b", "Cream", "GM"),
    (r"LOTIONS?", "Lotion", "ML"),
    (r"SHAMPOO", "Shampoo", "ML"),
    (r"SOAPS?", "Soap", "UNIT"),
    (r"POWDERS?|PWD\b", "Powder", "GM"),
    (r"SOLUTIONS?|SOLN\b", "Solution", "ML"),
    (r"DROPS?\b", "Drops", "ML"),
    (r"SPRAYS?", "Spray", "ML"),
    (r"GELS?\b", "Gel", "GM"),
    (r"KITS?\b", "Kit", "KIT"),
]

# Strength: a number (possibly a combination like 500+125 or 5/10) followed by
# a dose unit. Anchored on the unit rather than the number so "10 MG" and
# "10MG" collapse to the same reading.
_STRENGTH_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?(?:\s*[+/]\s*\d+(?:\.\d+)?)*)\s*"
    r"(?P<unit>MCG|MG|IU|KIU|%)(?![A-Z])",
    re.IGNORECASE,
)

# Pack measure: a volume or weight, which on these invoices describes the
# container rather than the dose.
_MEASURE_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ML|GM|GRAM|G|L|LTR)(?![A-Z])",
    re.IGNORECASE,
)

# "1*10", "10 X 10", "5x1" - strips per pack by units per strip.
_PACK_GRID_RE = re.compile(r"\b(?P<outer>\d+)\s*[*xX×]\s*(?P<inner>\d+)\b")

# "10'S", "10S", "15 'S" - a flat count per pack.
_PACK_COUNT_RE = re.compile(r"\b(?P<count>\d+)\s*['’]?\s*S\b", re.IGNORECASE)

# A bare number hanging off a hyphen, e.g. NITROLONG-2.6. Real convention for
# stating strength, but indistinguishable from a brand that contains a number.
_HYPHEN_NUMBER_RE = re.compile(r"-\s*(?P<value>\d+(?:\.\d+)?)\b")

_SCHEDULES = ["Schedule H", "Schedule H1", "Schedule X", "Schedule G", "Narcotic", "OTC"]


class ParsedField(BaseModel):
    """One catalogue field the parser is offering, with how much to trust it.

    confidence is a blunt three-band signal, not a calibrated probability:
    >=0.8 the name stated it outright, ~0.5 it was inferred from a sibling
    fact, <=0.4 it is a guess worth showing but not worth trusting.
    """

    value: Optional[Any] = None
    confidence: float = 0.0
    evidence: Optional[str] = None

    @property
    def known(self) -> bool:
        return self.value is not None


class ParsedProduct(BaseModel):
    brand: ParsedField = ParsedField()
    strength: ParsedField = ParsedField()
    form: ParsedField = ParsedField()
    pack_size: ParsedField = ParsedField()
    pack_multiplier: ParsedField = ParsedField()
    base_unit: ParsedField = ParsedField()
    # Field names the catalogue still needs a human to supply. This is the
    # list the review queue sorts and filters on.
    unresolved: List[str] = []
    # Deterministic identity for the SKU this name appears to describe.
    identity_key: str = ""


def normalize_name(name: str) -> str:
    """Collapses an invoice's rendering of a name to a comparable key.

    Punctuation is reduced but not deleted: "DYNAPAR QPS" and "DYNAPAR-QPS"
    are the same product, while "MAHAFLOX" and "MAHAFLOX-LP" are not, so
    hyphens become spaces rather than vanishing.

    Separators sitting BETWEEN two digits are left alone. Flattening those
    would turn 0.5MG into 5MG and 5/10MG into 5 10MG - a tenfold dosing error
    written into the catalogue by a whitespace rule.
    """
    if not name:
        return ""
    text = str(name).upper()
    # Park intra-numeric separators out of reach of the punctuation sweep.
    text = re.sub(r"(?<=\d)\.(?=\d)", "\x00", text)
    text = re.sub(r"(?<=\d)/(?=\d)", "\x01", text)
    text = re.sub(r"[\-_/\\.,()\[\]]+", " ", text)
    text = text.replace("\x00", ".").replace("\x01", "/")
    text = re.sub(r"['’]", "'", text)
    return re.sub(r"\s+", " ", text).strip()


def _match_form(text: str) -> Optional[tuple[str, str, str]]:
    """Returns (canonical_form, base_unit, matched_text) for the first form
    vocabulary entry present, searching longest/most-specific first."""
    for pattern, canonical, unit in _FORMS:
        match = re.search(rf"\b(?:{pattern})", text, re.IGNORECASE)
        if match:
            return canonical, unit, match.group(0)
    return None


def _normalize_strength(value: str, unit: str) -> str:
    compact = re.sub(r"\s+", "", value)
    return f"{compact}{unit.upper()}"


def _parse_pack_token(token: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Reads a pack expression into (display, units_per_pack, evidence).

    "1*10" is one strip of ten and "10*10" is ten strips of ten, so the
    multiplier is the product of both numbers - taking only the second would
    under-count a box by a factor of ten and quietly halve, or worse, the
    stock figures derived from it.
    """
    if not token:
        return None, None, None

    text = str(token).upper().strip()

    grid = _PACK_GRID_RE.search(text)
    if grid:
        outer = int(grid.group("outer"))
        inner = int(grid.group("inner"))
        return f"{outer}*{inner}", outer * inner, grid.group(0)

    count = _PACK_COUNT_RE.search(text)
    if count:
        n = int(count.group("count"))
        return f"{n}'S", n, count.group(0)

    measure = _MEASURE_RE.search(text)
    if measure:
        value = measure.group("value")
        unit = measure.group("unit").upper()
        unit = {"GRAM": "GM", "LTR": "L"}.get(unit, unit)
        # A bottle or tube is one dispensable item; the volume describes its
        # contents, not a count of units inside it.
        return f"{value}{unit}", 1, measure.group(0)

    # A bare integer in a dedicated pack column is a count.
    bare = re.fullmatch(r"(\d+)", text)
    if bare:
        n = int(bare.group(1))
        return f"{n}'S", n, text

    return text or None, None, text or None


def _strip_spans(text: str, spans: List[str]) -> str:
    """Removes already-claimed substrings so what remains can serve as the brand."""
    result = text
    for span in spans:
        if span:
            result = result.replace(span, " ")
    return re.sub(r"\s+", " ", result).strip(" -*/")


def build_identity_key(
    brand: Optional[str],
    strength: Optional[str],
    form: Optional[str],
    pack_size: Optional[str],
) -> str:
    """Deterministic SKU key. Unknown components collapse to '?'.

    Two names that are both missing a strength therefore land on the SAME key
    and merge - which is the correct default, since most repeat items really
    are the same item. When that default is wrong (one DONEP is 5mg, the other
    10mg), the merged product carries a missing_strength flag and the price
    spread across its observations is what surfaces the mistake for splitting.
    Merging-then-splitting is recoverable; silently keeping every raw spelling
    apart is the catalogue sprawl this whole section exists to prevent.
    """
    parts = [
        normalize_name(brand or "") or "?",
        (strength or "?").upper(),
        (form or "?").upper(),
        (pack_size or "?").upper(),
    ]
    return "|".join(parts)


def parse_product_name(name: Optional[str], pack_column: Optional[str] = None) -> ParsedProduct:
    """Extracts catalogue structure from an invoice item name.

    pack_column is the invoice's separate pack/UOM column when it has one; it
    outranks anything found in the name, because a dedicated column is a
    deliberate statement whereas a token inside a name is an inference.
    """
    parsed = ParsedProduct()

    raw = (name or "").strip()
    if not raw:
        parsed.unresolved = ["brand", "strength", "form", "pack_size", "pack_multiplier", "base_unit"]
        parsed.identity_key = build_identity_key(None, None, None, None)
        return parsed

    working = normalize_name(raw)
    claimed: List[str] = []

    # --- form -------------------------------------------------------------
    form_hit = _match_form(working)
    if form_hit:
        canonical, base_unit, matched = form_hit
        parsed.form = ParsedField(value=canonical, confidence=0.85, evidence=matched)
        parsed.base_unit = ParsedField(value=base_unit, confidence=0.7, evidence=matched)
        claimed.append(matched)

    # --- strength ---------------------------------------------------------
    strength_hit = _STRENGTH_RE.search(working)
    if strength_hit:
        parsed.strength = ParsedField(
            value=_normalize_strength(strength_hit.group("value"), strength_hit.group("unit")),
            confidence=0.9,
            evidence=strength_hit.group(0),
        )
        claimed.append(strength_hit.group(0))

    # --- pack -------------------------------------------------------------
    pack_display: Optional[str] = None
    pack_multiplier: Optional[int] = None
    pack_confidence = 0.0
    pack_evidence: Optional[str] = None

    if pack_column and str(pack_column).strip():
        pack_display, pack_multiplier, pack_evidence = _parse_pack_token(str(pack_column))
        pack_confidence = 0.9 if pack_display else 0.0

    if pack_display is None:
        grid = _PACK_GRID_RE.search(working)
        count = _PACK_COUNT_RE.search(working)
        measure = _MEASURE_RE.search(working)
        source = grid.group(0) if grid else (count.group(0) if count else (measure.group(0) if measure else None))
        if source:
            pack_display, pack_multiplier, pack_evidence = _parse_pack_token(source)
            pack_confidence = 0.75
            claimed.append(source)

    if pack_display:
        parsed.pack_size = ParsedField(value=pack_display, confidence=pack_confidence, evidence=pack_evidence)
    if pack_multiplier is not None:
        parsed.pack_multiplier = ParsedField(
            value=pack_multiplier, confidence=pack_confidence, evidence=pack_evidence
        )

    # A volume/weight pack implies the base unit even when no form word
    # appeared - "DYNAPAR QPS 30 ML" names no form but is plainly a liquid.
    if not parsed.base_unit.known and pack_display:
        implied = re.search(r"(ML|GM|L)$", pack_display, re.IGNORECASE)
        if implied:
            parsed.base_unit = ParsedField(
                value=implied.group(1).upper(), confidence=0.5, evidence=pack_display
            )

    # --- brand ------------------------------------------------------------
    brand = _strip_spans(working, claimed)

    # Weak strength signals, considered only once the pack and dose readings
    # above have taken their numbers, so this can't steal one of theirs.
    if not parsed.strength.known:
        trailing = re.search(r"\s(\d+(?:\.\d+)?)$", brand)
        hyphen = _HYPHEN_NUMBER_RE.search(raw.upper())
        if trailing:
            parsed.strength = ParsedField(
                value=trailing.group(1), confidence=0.4, evidence=trailing.group(0).strip()
            )
            brand = brand[: trailing.start()].strip()
        elif hyphen:
            value = hyphen.group("value")
            parsed.strength = ParsedField(value=value, confidence=0.35, evidence=hyphen.group(0))
            # Drop it from the brand too, so NITROLONG-2.6 and NITROLONG 2.6MG
            # can still converge on one brand once a human confirms the unit.
            brand = re.sub(rf"\b{re.escape(value)}\b", " ", brand)
            brand = re.sub(r"\s+", " ", brand).strip()

    parsed.brand = ParsedField(
        value=brand or normalize_name(raw),
        confidence=0.8 if brand else 0.3,
        evidence=raw,
    )

    # --- what still needs a human ----------------------------------------
    parsed.unresolved = [
        field
        for field in ("strength", "form", "pack_size", "pack_multiplier", "base_unit")
        if not getattr(parsed, field).known
    ]

    parsed.identity_key = build_identity_key(
        parsed.brand.value,
        parsed.strength.value,
        parsed.form.value,
        parsed.pack_size.value,
    )
    return parsed


def infer_schedule(name: Optional[str]) -> ParsedField:
    """Reads a schedule only when the invoice literally prints one.

    Schedule is a regulatory classification, not something recoverable from a
    brand name - inferring "Schedule H" because a molecule is usually
    prescription-only would put a compliance claim in the catalogue that
    nobody checked. Left blank for the pharmacist to set.
    """
    text = (name or "").upper()
    for schedule in _SCHEDULES:
        if re.search(rf"\b{re.escape(schedule.upper())}\b", text):
            return ParsedField(value=schedule, confidence=0.9, evidence=schedule)
    return ParsedField()
