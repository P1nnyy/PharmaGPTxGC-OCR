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

from extraction.normalizers.form_indicators import (
    forms_conflict,
    read_name_modifier,
    read_pack_code,
    strip_pack_code,
)

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

# "1*10", "10 X 10", "5x1", "60X5ML" - a count of things by the size of each.
# The trailing unit is captured because it changes the arithmetic: 10X10 is a
# hundred tablets, but 60X5ML is sixty vials of 5ml, not three hundred of
# anything. No \b after the digits - a boundary never occurs between "5" and
# "ML", which silently dropped every unit-suffixed pack on the floor.
_PACK_GRID_RE = re.compile(
    r"(?<![\d.])(?P<outer>\d+)\s*[*xX×]\s*(?P<inner>\d+)\s*"
    r"(?P<unit>ML|GM|GRAM|G|L|LTR)?(?![A-Z0-9])",
    re.IGNORECASE,
)

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


def _parse_pack_token(
    token: str,
) -> tuple[Optional[str], Optional[int], Optional[str], Optional[Any]]:
    """Reads a pack expression into (display, units_per_pack, evidence, form_code).

    "1*10" is one strip of ten and "10*10" is ten strips of ten, so the
    multiplier is the product of both numbers - taking only the second would
    under-count a box by a factor of ten and quietly halve, or worse, the
    stock figures derived from it.

    A trailing form code is removed before the numbers are read and returned
    alongside them. "1x10TA" otherwise parses to nothing at all: the letters
    defeat the numeric patterns, so the pack falls through as opaque text and
    the item is left with no units per pack - which is most of a real
    catalogue, since TA/CA/T suffixes are the common case rather than the
    exception.
    """
    if not token:
        return None, None, None, None

    text = str(token).upper().strip()

    form_code, code_text = read_pack_code(text)
    if form_code:
        stripped = strip_pack_code(text)
        # Only accept the split if numbers remain; otherwise the "code" was
        # the whole value (a pack column reading just "VIAL"), which is a
        # form statement and not a quantity.
        if re.search(r"\d", stripped):
            display, multiplier, evidence = _parse_numeric_pack(stripped, form_code, code_text)
            return display, multiplier, evidence, form_code
        return text, None, text, form_code

    display, multiplier, evidence = _parse_numeric_pack(text, None, None)
    return display, multiplier, evidence, None


def _parse_numeric_pack(
    text: str, form_code: Optional[Any], code_text: Optional[str]
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """The numeric half of a pack expression, once any form code is removed."""

    grid = _PACK_GRID_RE.search(text)
    if grid:
        outer = int(grid.group("outer"))
        inner = int(grid.group("inner"))
        unit = grid.group("unit")

        # A code saying the trailing number is a MEASURE rather than a count
        # settles the arithmetic: "1X200M" is one 200ml bottle, not two
        # hundred of anything, and "1x10TA" is ten tablets. Same shape, and
        # only the code distinguishes them - which is why reading it matters
        # beyond just labelling the form.
        if not unit and form_code is not None and not form_code.counts_units:
            unit = form_code.base_unit

        if unit:
            # "60X5ML" is sixty containers holding 5ml each. The dispensable
            # item is the container, so the count is the outer number; the
            # inner one describes what is inside it and must not be
            # multiplied in.
            unit = {"GRAM": "GM", "LTR": "L"}.get(unit.upper(), unit.upper())
            return f"{outer}x{inner}{unit}", outer, grid.group(0)
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

    # A bare number in a dedicated pack column is a count - unless a code
    # already said it measures contents. "60 ML" strips to "60", and reading
    # that as sixty dispensable units turns one syrup bottle into sixty of
    # them, and every stock and valuation figure downstream with it.
    bare = re.fullmatch(r"(\d+(?:\.\d+)?)", text)
    if bare:
        value = bare.group(1)
        if form_code is not None and not form_code.counts_units:
            return f"{value}{form_code.base_unit}", 1, text
        n = int(float(value))
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

    pack_code = None

    if pack_column and str(pack_column).strip():
        pack_display, pack_multiplier, pack_evidence, pack_code = _parse_pack_token(str(pack_column))
        pack_confidence = 0.9 if pack_display else 0.0

    if pack_display is None:
        grid = _PACK_GRID_RE.search(working)
        count = _PACK_COUNT_RE.search(working)
        measure = _MEASURE_RE.search(working)
        source = grid.group(0) if grid else (count.group(0) if count else (measure.group(0) if measure else None))
        if source:
            pack_display, pack_multiplier, pack_evidence, _ = _parse_pack_token(source)
            pack_confidence = 0.75
            claimed.append(source)

    if pack_display:
        parsed.pack_size = ParsedField(value=pack_display, confidence=pack_confidence, evidence=pack_evidence)
    if pack_multiplier is not None:
        parsed.pack_multiplier = ParsedField(
            value=pack_multiplier, confidence=pack_confidence, evidence=pack_evidence
        )

    # --- form, from the coded hints ---------------------------------------
    # Precedence is by directness of the statement: a form word spelled out in
    # the name beats a code in the pack column, which beats a release marker
    # that only implies a solid oral dose.
    if pack_code and pack_code.form:
        if not parsed.form.known:
            parsed.form = ParsedField(
                value=pack_code.form,
                confidence=pack_code.confidence,
                evidence=f"pack column “{pack_evidence or pack_column}”",
            )
        elif forms_conflict(parsed.form.value, pack_code.form):
            # The name and the pack column name different medicines' forms.
            # Neither is discarded and neither wins silently - the confidence
            # drops so the review queue surfaces it for a human.
            parsed.form = ParsedField(
                value=parsed.form.value,
                confidence=0.3,
                evidence=(
                    f"name says {parsed.form.value}, pack column says "
                    f"{pack_code.form} — these disagree"
                ),
            )

    if pack_code and not parsed.base_unit.known:
        parsed.base_unit = ParsedField(
            value=pack_code.base_unit,
            confidence=pack_code.confidence,
            evidence=f"pack column “{pack_evidence or pack_column}”",
        )

    if not parsed.form.known:
        hint = read_name_modifier(raw)
        if hint:
            parsed.form = ParsedField(value=hint.form, confidence=hint.confidence, evidence=hint.note)
            if not parsed.base_unit.known:
                parsed.base_unit = ParsedField(
                    value=hint.base_unit, confidence=hint.confidence, evidence=hint.note
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
