"""Matching an invoice's item name against a local reference catalogue.

This is the file where a mistake becomes a wrong dose in permanent master
data, so the rules below are deliberately stricter than the ones that would
maximise how many products get filled in.

What makes this hard
--------------------
The reference holds ~254,000 Indian products, and the names cluster densely.
Blocking on the first word of a real catalogue gives 3-23 candidates that
disagree on up to nine different strengths:

    GLYCOMET GP 1 / GP 2 / GP 2 FORTE / GP 2-850 / GP STAR 2-1000 ...
    TELPLUS / TELPLUS TRIO
    ZERODOL P / ZERODOL SP / ZERODOL MR

Picking the best-scoring row out of that is how a 15-tablet strip becomes a
10-tablet one and a 40mg telmisartan becomes 10mg. Fuzzy similarity cannot
separate these: TELPLUS against TELPLUS TRIO scores in the nineties on any
ratio, and they are different medicines.

The three rules that do the work
--------------------------------
1. **A word we state that the reference lacks disqualifies the row.** If the
   invoice says TELPLUS TRIO and the row says Telplus, the row is not this
   product. The converse is not symmetric: the reference carries fuller names
   than invoices do, so a word only IT states is forgiven when it is a known
   release suffix (PR, SR, XR...), which changes the release profile but not
   the strength, form or manufacturer this module proposes.

2. **Bare numbers must match exactly, not merely overlap.** GLYCOMET GP 2/850
   and GP 3/850 share the 850; an intersection test calls them the same
   product. When our name states any number, the row's numbers must be the
   same set.

3. **Fields are filled by consensus among survivors, never by the winner.**
   If six rows survive and they disagree on strength, no strength is proposed
   however confident the top row looks. Only what every survivor agrees on is
   offered. This is what makes the ambiguous cases safe by construction rather
   than by tuning: the system's answer to GLYCOMET is "these all agree it is a
   USV tablet, and they disagree about the dose", which is the truth.

Combination products
--------------------
44% of the reference is multi-ingredient, and for those `primary_strength` is
the strength of whichever ingredient happened to be listed first - not the
product's strength. Telplus Tablet reports 10mg, and is Cilnidipine 10mg with
Telmisartan 40mg. Recording "TELPLUS 10MG" would read to a pharmacist as a
10mg telmisartan tablet.

That figure is unusable, but it does not follow that the strength is unknowable
- and refusing every combination outright was leaving strengths blank that the
invoice had stated plainly. The invoice names the component it means:

    TRIOLMESAR 20      Olmesartan 20mg + Amlodipine 5mg      -> 20MG
    GLYCOMET GP 2/850  Glimepiride 2mg + Metformin 850mg     -> 2MG+850MG
    DIAPRIDE M4        Glimepiride 4mg + Metformin 1000mg    -> 4MG
    TELPLUS            Cilnidipine 10mg + Telmisartan 40mg   -> nothing to say

So the numbers printed on our own line select which ingredient strengths
apply, and only a name that pins nothing leaves the field blank. The
composition travels with every proposal either way.

Nothing here writes. It returns a proposal with its evidence, and the existing
PATCH remains the only path that can change a Product.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from rapidfuzz import fuzz

from extraction.normalizers.product_parser import normalize_name

# Words describing the presentation rather than the product. Present in both
# our names and the reference's, and never a distinguishing feature.
FORM_WORDS = {
    "TABLET", "TABLETS", "TAB", "TABS", "CAPSULE", "CAPSULES", "CAP", "CAPS",
    "SYRUP", "SYP", "SYR", "SUSPENSION", "SUSP", "INJECTION", "INJ", "VIAL",
    "CREAM", "CRM", "OINTMENT", "OINT", "GEL", "DROP", "DROPS", "SOLUTION",
    "SOLN", "SOL", "POWDER", "SPRAY", "INHALER", "RESPULE", "RESPULES", "ROTACAP",
    "AMPOULE", "AMPOULES", "AMP", "AMPS", "GARGLE", "MOUTHWASH", "SHAMPOO", "SOAP",
    "ROTACAPS", "ROTOCAP", "ROTOCAPS", "SACHET", "LOTION", "KIT", "ORAL", "OTHER",
    "EYE", "EAR", "NASAL",
}

# Packaging prose. The reference spells its pack out in the name - "Hyperneb
# 3% Respules (4ml Each)", "strip of 10" - and none of it identifies a
# product. Left in, EACH alone was enough to reject the one correct listing
# for a Cipla nebuliser that the index plainly contained.
#
# Deliberately excludes SET and COMBIPACK: those say the item is a kit rather
# than a single unit, which IS a different product.
PACKAGING_WORDS = {
    "EACH", "OF", "WITH", "AND", "PACK", "BOTTLE", "JAR", "BOX", "TUBE",
    "REFILL", "STRIP", "STRIPS", "SACHETS",
}

# Flavours. A syrup is sold in half a dozen of them and the reference spells
# each one out - "Emeset Syrup Juicy Lemon" - while the invoice says only
# EMESET SYRUP. The flavour does not change the form, the maker or what is in
# it, which is everything this module proposes.
#
# Forgiven on the reference side only, like the release suffixes: an invoice
# that does name a flavour is saying something, and should still have to match.
FLAVOUR_WORDS = {
    "JUICY", "LEMON", "MINT", "ORANGE", "STRAWBERRY", "VANILLA", "MANGO",
    "PINEAPPLE", "BANANA", "CHOCOLATE", "RASPBERRY", "APPLE", "COLA",
    "BUBBLEGUM", "HONEY", "GINGER", "ELAICHI", "PAAN", "KESAR", "FLAVOUR",
    "FLAVOR", "FLAVOURED", "SUGARFREE",
}

# Release and format suffixes. The reference states them; invoices usually do
# not. They separate one product from its sibling in how it releases, not in
# strength, form or manufacturer - so forgiving them on the reference side
# widens what we can match without widening what we can get wrong.
MODIFIERS = {"PR", "SR", "XR", "ER", "CR", "OD", "LA", "MD", "DT", "MR", "XL", "NEW"}

# Pack expressions, removed from the name before anything in it is read as a
# variant number. "TRIOLMESAR 20 15'S" states one dose (20) and one pack (15);
# leaving the 15 in makes it a two-number product matching nothing at all.
_PACK_RE = re.compile(
    r"\(?\b(\d+)\s*['`‘’]?\s*S\b\)?"          # 15'S  15 'S  120S  10`S
    r"|\b(\d+)\s*(?:TAB|TABS|CAP|CAPS)\b"               # 20TAB
    r"|\b\d+\s*[X*]\s*(\d+)\s*(?:GM|ML|MG|G)?",          # 1*10  1X15  1X20GM
    re.IGNORECASE,
)

# Abbreviations distributors use for a route of administration. Expanded
# BEFORE the name is split, because the separator is the whole signal: "E/D"
# is eye drops, but once normalisation flattens the slash it becomes the two
# tokens E and D - and D is a real product marker, so MOXI-P E\D was a
# candidate to match "Moxi D Eye Drop", a different medicine. Reading it as a
# near-miss was bad; reading it as a different product would have been worse.
_ABBREVIATIONS = (
    (re.compile(r"\bE\s*[/\\.]\s*D(?:ROPS?)?\b", re.IGNORECASE), " EYE DROPS "),
    (re.compile(r"\bEYE\s*[/\\]\s*D(?:ROPS?)?\b", re.IGNORECASE), " EYE DROPS "),
    (re.compile(r"\bEAR\s*[/\\]\s*D(?:ROPS?)?\b", re.IGNORECASE), " EAR DROPS "),
    (re.compile(r"\bEYEDROPS?\b", re.IGNORECASE), " EYE DROPS "),
    (re.compile(r"\bE\s*[/\\]\s*E\b", re.IGNORECASE), " EYE EAR "),
)


def expand_abbreviations(name: str) -> str:
    for pattern, replacement in _ABBREVIATIONS:
        name = pattern.sub(replacement, name)
    return name

# A number welded to a dose unit is a strength, not part of the brand. Reading
# 1GM as a brand word made GLYCOMET 1GM unmatchable against every Glycomet row.
_STRENGTH_TOKEN_RE = re.compile(r"^(\d+(?:\.\d+)?)(MG|MCG|GM|G|IU|ML|%)$")
_STRENGTH_VALUE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(MG|MCG|GM|G|IU|ML|%)")

# How close two words must be to count as the same word spelled differently
# rather than as an extra word. Matches the duplicate finder's threshold.
_WORD_MATCH_RATIO = 85.0
# Below this the names are not the same product line at all.
_MIN_WORD_SIMILARITY = 70.0

# The reference's dosage_form vocabulary mapped onto the catalogue's own
# canonical labels and the unit a single dispensable item is counted in.
# "other" is deliberately absent: it names nothing, and proposing it would
# overwrite a blank with a non-answer.
FORM_MAP: dict[str, tuple[str, str]] = {
    "tablet": ("Tablet", "TABLET"),
    "capsule": ("Capsule", "CAPSULE"),
    "syrup": ("Syrup", "ML"),
    "suspension": ("Suspension", "ML"),
    "injection": ("Injection", "VIAL"),
    "drops": ("Drops", "ML"),
    "cream": ("Cream", "GM"),
    "ointment": ("Ointment", "GM"),
    "gel": ("Gel", "GM"),
    "solution": ("Solution", "ML"),
    "powder": ("Powder", "GM"),
    "spray": ("Spray", "ML"),
    "inhaler": ("Inhaler", "UNIT"),
    "respules": ("Respule", "RESPULE"),
}


def canon_strength(text: Any) -> Optional[tuple[float, str]]:
    """A comparable (value, unit) so 1GM and 1000mg are recognised as one dose."""
    if text in (None, ""):
        return None
    match = _STRENGTH_VALUE_RE.match(str(text).upper().replace(" ", ""))
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2)
    if unit in ("GM", "G"):
        return (value * 1000, "MG")
    if unit == "MCG":
        return (value / 1000, "MG")
    return (value, unit)


def strip_pack(name: Optional[str]) -> tuple[str, Optional[float]]:
    """Removes pack expressions, returning the cleaned name and the pack count."""
    found: list[float] = []

    def take(match: re.Match) -> str:
        for group in match.groups():
            if group:
                found.append(float(group))
                break
        return " "

    return _PACK_RE.sub(take, name or ""), (found[-1] if found else None)


@dataclass
class NameParts:
    """One name split into the three things that behave differently."""

    words: list[str] = field(default_factory=list)        # brand words
    numbers: list[str] = field(default_factory=list)      # bare variant numbers
    strengths: list[str] = field(default_factory=list)    # doses stated inline

    @property
    def compact(self) -> str:
        return "".join(self.words)


def _split_fused(token: str) -> list[str]:
    """Separates letters welded to digits, unless the token is a dose.

    Distributors run the two together - ECOSPRIN GOLD20, SUSTANON 250INJ -
    where the reference spells them apart, and a fused token matches nothing.
    A strength is left whole: 625MG is one fact, not a 625 beside an MG.
    """
    if _STRENGTH_TOKEN_RE.match(token):
        return [token]
    # Only a single letters/digits boundary is split. Splitting on every digit
    # would shatter a word with an OCR'd zero inside it - MONTIC0PE became
    # MONTIC, 0, PE - and that is precisely the spelling the matcher has to
    # forgive, not one it should take apart.
    boundary = re.fullmatch(r"([A-Z]+)(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)([A-Z]+)", token)
    if not boundary:
        return [token]
    return [g for g in boundary.groups() if g]


def split_name(name: Optional[str]) -> NameParts:
    parts = NameParts()
    for whole in normalize_name(expand_abbreviations(name or "")).split():
        for token in _split_fused(whole):
            if not token or token in FORM_WORDS or token in PACKAGING_WORDS:
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", token):
                parts.numbers.append(token)
            elif _STRENGTH_TOKEN_RE.match(token):
                parts.strengths.append(token)
            else:
                parts.words.append(token)
    return parts


def unexplained_words(
    subject: NameParts, other: NameParts, forgive_modifiers: bool = False
) -> list[str]:
    """Words in `subject` that `other` has nothing to account for.

    A word is accounted for when it appears inside the other name with its
    spaces removed (a separator moved), or when some word over there is nearly
    the same word (an OCR misread). Anything left is a claim one name makes
    and the other does not.
    """
    extra = []
    for word in subject.words:
        if word in other.compact:
            continue
        if any(fuzz.ratio(word, candidate) >= _WORD_MATCH_RATIO for candidate in other.words):
            continue
        if forgive_modifiers and (word in MODIFIERS or word in FLAVOUR_WORDS):
            continue
        extra.append(word)
    return extra


@dataclass
class Query:
    """What we know about our own product, prepared for matching."""

    parts: NameParts
    pack_multiplier: Optional[float] = None
    manufacturer: Optional[str] = None
    known_strength: Optional[str] = None
    known_form: Optional[str] = None


def build_query(
    name: Optional[str],
    pack_multiplier: Optional[float] = None,
    manufacturer: Optional[str] = None,
    strength: Optional[str] = None,
    form: Optional[str] = None,
) -> Query:
    cleaned, pack_from_name = strip_pack(name)
    return Query(
        parts=split_name(cleaned),
        # A pack the catalogue already knows beats one read out of the name.
        pack_multiplier=pack_multiplier or pack_from_name,
        manufacturer=manufacturer,
        known_strength=strength,
        known_form=form,
    )


def block_key(name: Optional[str]) -> Optional[str]:
    """The bucket a name is looked up in: its first brand word.

    Deliberately not a prefix of the whole string - the reference and the
    invoice agree on the first word far more reliably than on anything after
    it, and a bucket is at worst a few hundred rows.
    """
    parts = split_name(strip_pack(name)[0])
    return parts.words[0] if parts.words else None


def score_row(query: Query, row: dict) -> Optional[dict]:
    """Scores one reference row, or rejects it.

    Rejection is a stronger statement than a low score: it means something the
    row states contradicts something we state, and no amount of name
    similarity should be allowed to outweigh that.
    """
    theirs = row.get("_parts") or split_name(row.get("brand_name"))
    if not theirs.words or not query.parts.words:
        return None

    # Words the reference adds and we forgive - a release suffix, a flavour -
    # are left out of the similarity itself. Otherwise the floor rejects the
    # pair before the forgiveness ever applies: EMESET against "Emeset Syrup
    # Juicy Lemon" scores about 50 on the full word lists, and no amount of
    # allowing LEMON afterwards can rescue a candidate already discarded.
    theirs_compared = [
        w for w in theirs.words
        if w in query.parts.words or (w not in MODIFIERS and w not in FLAVOUR_WORDS)
    ] or theirs.words

    similarity = fuzz.token_sort_ratio(
        " ".join(query.parts.words), " ".join(theirs_compared)
    )
    if similarity < _MIN_WORD_SIMILARITY:
        return None

    reasons: list[str] = []

    # Rule 1 - asymmetric, see the module docstring.
    ours_extra = unexplained_words(query.parts, theirs)
    if ours_extra:
        return None
    theirs_extra = unexplained_words(theirs, query.parts, forgive_modifiers=True)
    if theirs_extra:
        return None

    # Rule 2 - a figure we state pins the variant exactly.
    #
    # Compared as numbers rather than as tokens, because the two sides classify
    # the same figure differently: BETADINE SOL 10 states a bare 10 while
    # "Betadine 10% Solution" states it as a strength, and matching the token
    # lists rejected a row that names the identical product.
    #
    # Still equality, not membership. GLYCOMET GP 2 must not reach
    # Glycomet-GP 2/850 - same glimepiride, different metformin, different
    # medicine - and only requiring every figure to be accounted for on both
    # sides keeps them apart.
    if query.parts.numbers and stated_figures(query.parts) != stated_figures(theirs):
        return None

    # A dose stated in our own name, or already held on the product, must
    # agree with one of the row's - ANY of them, not its "primary" one.
    #
    # primary_strength is whichever ingredient the source listed first, and on
    # a combination that is arbitrary. JALRA DP 100MG is a perfect name match
    # for Jalra-DP Tablet SR, whose ingredients are Dapagliflozin 10mg and
    # Vildagliptin 100mg; comparing against the column alone reads 100 against
    # 10 and throws away the one correct listing. The invoice names a real
    # component, so the test is membership, not equality with the first.
    stated = query.parts.strengths[0] if query.parts.strengths else query.known_strength
    ours_dose = canon_strength(stated)
    theirs_doses = [d for d in (canon_strength(v) for v in row_strengths(row)) if d]
    dose_agrees = bool(ours_dose) and any(d == ours_dose for d in theirs_doses)
    if ours_dose and theirs_doses and not dose_agrees:
        return None

    # A strength stated in THEIR name must agree with one stated in ours.
    # Checking only the row's primary_strength column is not enough: Hyperneb
    # 3% and Hyperneb 7% are different medicines and the column is empty for
    # both, so without this they both survive and the answer is decided by
    # whatever the two happen to share.
    #
    # Compared within a unit family, because a reference name routinely states
    # a volume alongside a dose - "(4ml Each)" - and 4ML says nothing about
    # whether the percentages agree.
    for stated_ours in query.parts.strengths:
        ours_value = canon_strength(stated_ours)
        if not ours_value:
            continue
        theirs_same_family = [
            v for v in (canon_strength(t) for t in theirs.strengths)
            if v and v[1] == ours_value[1]
        ]
        if theirs_same_family and not any(
            abs(v[0] - ours_value[0]) < 1e-9 for v in theirs_same_family
        ):
            return None

    if query.known_form and row.get("dosage_form"):
        mapped = FORM_MAP.get(str(row["dosage_form"]).lower())
        if mapped and mapped[0].upper() != str(query.known_form).upper():
            return None

    score = float(similarity)
    if query.parts.numbers:
        score += 12
        reasons.append(f"Both name the variant {', '.join(query.parts.numbers)}.")
    if dose_agrees:
        score += 8
        reasons.append(f"Stated strength agrees ({stated}).")

    pack = _to_float(row.get("pack_size"))
    if query.pack_multiplier and pack:
        if abs(pack - float(query.pack_multiplier)) < 0.01:
            score += 10
            reasons.append(f"Pack of {int(pack)} matches the invoice.")
        else:
            # Not disqualifying: one brand is sold in several pack sizes, and
            # the rest of the record still describes the same medicine.
            score -= 15
    if query.manufacturer and row.get("manufacturer"):
        # Invoices abbreviate the maker to a few characters (MICR, CIPL,
        # ZYDU), so this compares prefixes rather than whole names.
        ours = normalize_name(query.manufacturer)
        if ours and normalize_name(row["manufacturer"]).startswith(ours[:4]):
            score += 8
            reasons.append(f"Manufacturer agrees ({row['manufacturer']}).")
    if row.get("discontinued"):
        score -= 5

    return {"row": row, "score": round(score, 1), "reasons": reasons}


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def stated_figures(parts: "NameParts") -> set:
    """Every dose-or-variant figure a name states, however it was written.

    A bare 10 and a 10% are the same claim about the product; which of the two
    a name happens to use is a spelling difference, not a difference in what is
    being said.
    """
    figures = {float(n) for n in parts.numbers}
    for strength in parts.strengths:
        canon = canon_strength(strength)
        if canon:
            figures.add(canon[0])
        else:
            figures.update(float(v) for v in re.findall(r"\d+(?:\.\d+)?", strength))
    return figures


def row_strengths(row: dict) -> list[str]:
    """Every strength a reference row states, in listed order.

    Falls back to primary_strength for rows with no ingredient breakdown, so
    single-ingredient listings behave exactly as before.
    """
    raw = row.get("ingredient_strengths")
    if raw:
        values = [v.strip() for v in str(raw).split("|") if v.strip()]
        if values:
            return values
    primary = row.get("primary_strength")
    return [str(primary)] if primary else []


def name_numbers(parts: "NameParts") -> list[float]:
    """Every number the invoice's own name states, wherever it sits.

    Not the same as `parts.numbers`, which only holds tokens that are numbers
    entire. A combination is routinely printed as one token - GLYCOMET GP
    2/850 - and both figures in it are meaningful, so the digits are read out
    of every token here.
    """
    found: list[float] = []
    for token in parts.words + parts.numbers + parts.strengths:
        for run in re.findall(r"\d+(?:\.\d+)?", token):
            found.append(float(run))
    return found


def pin_combination_strength(parts: "NameParts", row: dict) -> Optional[str]:
    """The strength of a combination, when the invoice's name settles it.

    A combination has one strength per ingredient, and the source's
    "primary_strength" is just whichever was listed first - for Telplus that
    is Cilnidipine 10mg, while the product a pharmacist means by Telplus is
    40mg telmisartan. Proposing that figure would be worse than proposing
    nothing.

    But the invoice usually is not silent. It prints TRIOLMESAR 20, and the
    row is Olmesartan Medoxomil 20mg + Amlodipine 5mg: the 20 names a
    component, so the strength is not a guess at all. GLYCOMET GP 2/850 names
    both of them. TELPLUS names neither, and only then is there nothing
    honest to say.

    So the rule is: read the numbers off our own name, and keep only the
    ingredient strengths they select. Returns them in the row's own ingredient
    order, joined with '+', or None when the name pins nothing.
    """
    strengths = row_strengths(row)
    if not strengths:
        return None

    stated = name_numbers(parts)
    if not stated:
        return None

    matched = []
    for strength in strengths:
        canon = canon_strength(strength)
        if not canon:
            continue
        # Compare against the number as printed AND against its mg-equivalent,
        # so a name saying 1 matches an ingredient recorded as 1gm.
        if any(
            abs(value - canon[0]) < 1e-9 or _same_as_printed(value, strength)
            for value in stated
        ):
            matched.append(strength.upper().replace(" ", ""))

    if not matched:
        return None
    return "+".join(matched)


def _same_as_printed(value: float, strength: str) -> bool:
    """True when the name's number equals the strength's own printed figure."""
    printed = re.match(r"\s*(\d+(?:\.\d+)?)", str(strength))
    return bool(printed) and abs(float(printed.group(1)) - value) < 1e-9


def _agree(rows: list[dict], read) -> tuple[Any, int]:
    """The single value every row agrees on, and how many distinct ones there were."""
    values = {read(r) for r in rows if read(r) not in (None, "", [])}
    return (values.pop() if len(values) == 1 else None), len(values)


def propose(query: Query, rows: list[dict], limit: int = 8) -> dict:
    """Turns surviving candidates into field proposals, or into a reason there are none.

    Only unanimous fields are proposed. A field the survivors disagree about is
    reported as contested and left for a person, because the disagreement IS
    the finding: it says the invoice name does not identify the product
    precisely enough to settle that field.
    """
    scored = [s for s in (score_row(query, row) for row in rows) if s]
    scored.sort(key=lambda s: -s["score"])
    survivors = scored[:limit]

    if not survivors:
        return {
            "status": "no_match",
            "fields": {},
            "contested": [],
            "candidates": [],
            "message": "No reference product matches this name closely enough to be sure.",
        }

    winners = [s["row"] for s in survivors]

    form_value, form_variants = _agree(winners, lambda r: (r.get("dosage_form") or "").lower())
    pack_value, pack_variants = _agree(winners, lambda r: _to_float(r.get("pack_size")))
    maker_value, maker_variants = _agree(winners, lambda r: r.get("manufacturer"))

    # Strength. For a single-ingredient row it is simply the row's strength.
    # For a combination it is whatever the INVOICE's own figures pin down -
    # see pin_combination_strength.
    combos = [r for r in winners if (r.get("ingredient_count") or 1) > 1]
    pinned_by_name = None
    if combos:
        pinned = {pin_combination_strength(query.parts, r) for r in winners}
        pinned.discard(None)
        # Unanimous among survivors, exactly as every other field.
        pinned_by_name = pinned.pop() if len(pinned) == 1 else None
        strength_value, strength_variants = pinned_by_name, 0
    else:
        strength_value, strength_variants = _agree(winners, lambda r: r.get("primary_strength"))

    fields: dict[str, Any] = {}
    contested: list[dict] = []

    mapped_form = FORM_MAP.get(form_value or "")
    if mapped_form:
        fields["form"] = mapped_form[0]
        fields["base_unit"] = mapped_form[1]
    elif form_variants > 1:
        contested.append({
            "field": "form",
            "reason": f"The {len(winners)} matching listings disagree about the dosage form.",
        })

    if strength_value:
        fields["strength"] = str(strength_value).upper()
    elif combos:
        example = next((r.get("composition") for r in winners if r.get("composition")), None)
        contested.append({
            "field": "strength",
            "reason": (
                "This is a combination product and the invoice name states no figure that "
                "identifies a component"
                + (f" ({example})" if example else "")
                + " — the reference records a strength per ingredient, and picking one "
                "would misread the product."
            ),
        })
    elif strength_variants > 1:
        contested.append({
            "field": "strength",
            "reason": f"The {len(winners)} matching listings state {strength_variants} different strengths.",
        })

    # The reference knows which pack sizes a brand is sold in. The invoice
    # knows which one was actually bought, and on that question it outranks
    # the reference absolutely - it is a record of a real transaction. So a
    # reference pack that contradicts the invoice is never proposed; it is
    # reported, because the contradiction is worth a look either way (a 15s
    # strip billed for a brand the reference only lists in 10s is either a
    # pack the data does not have or a misread quantity).
    known_pack = _to_float(query.pack_multiplier)
    if pack_value and known_pack and abs(pack_value - known_pack) >= 0.01:
        contested.append({
            "field": "pack_multiplier",
            "reason": (
                f"The invoice bills this as a pack of {known_pack:g}, but the reference "
                f"lists this product only as a pack of {pack_value:g} — keeping the invoice's figure."
            ),
        })
    elif pack_value and not known_pack:
        fields["pack_multiplier"] = pack_value
    elif pack_variants > 1 and not known_pack:
        contested.append({
            "field": "pack_multiplier",
            "reason": f"This brand is sold in {pack_variants} pack sizes; the invoice has to settle which.",
        })

    if maker_value:
        fields["manufacturer"] = maker_value

    # The salt line. Pharmacists identify a substitute by what is in it, not by
    # the brand, so this is the field that makes two differently-named products
    # comparable at all. Consensus-checked like everything else: survivors that
    # disagree about the composition are describing different medicines, and
    # the honest output is then no composition.
    composition_value, composition_variants = _agree(winners, lambda r: r.get("composition"))
    if composition_value:
        fields["composition"] = composition_value
    elif composition_variants > 1:
        contested.append({
            "field": "composition",
            "reason": f"The {len(winners)} matching listings state different compositions.",
        })

    top = survivors[0]["row"]
    return {
        "status": "ok",
        "fields": fields,
        "contested": contested,
        "match_count": len(survivors),
        "score": survivors[0]["score"],
        "reasons": survivors[0]["reasons"],
        # The composition travels with every proposal. For combinations it is
        # the answer to the strength question that we refused to guess at.
        "composition": top.get("composition"),
        "therapeutic_class": top.get("therapeutic_class"),
        "listed_price": _to_float(top.get("price_inr")),
        "candidates": [
            {
                "brand_name": s["row"].get("brand_name"),
                "manufacturer": s["row"].get("manufacturer"),
                "dosage_form": s["row"].get("dosage_form"),
                "primary_strength": s["row"].get("primary_strength"),
                "pack_size": _to_float(s["row"].get("pack_size")),
                "composition": s["row"].get("composition"),
                "discontinued": bool(s["row"].get("discontinued")),
                "score": s["score"],
            }
            for s in survivors
        ],
    }
