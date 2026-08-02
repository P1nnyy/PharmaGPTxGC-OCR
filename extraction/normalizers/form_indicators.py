"""Reads dosage form out of the coded hints distributors bury in invoices.

Two separate vocabularies, and conflating them is the trap
----------------------------------------------------------
An invoice states the form twice, in two different codes, and the SAME letters
mean different things in each place:

    pack column   "1x10TA"           TA = tablet
                  "1x10 T"           T  = tablet
                  "1X10CA"           CA = capsule
                  "1X200M"           M  = millilitres
                  "1×20GM"           GM = grams

    product name  "JALRA DP 100MG SR"   SR = sustained release  -> a tablet
                  "PRAMIPEX ER 1.5"     ER = extended release   -> a tablet
                  "SIZODON MD 0.5"      MD = mouth dissolving   -> a tablet

`CR` in a pack column is cream; `CR` after a brand name is controlled release.
`DR` in a pack column is drops; `DR` after a brand name is delayed release.
So the two vocabularies are kept strictly apart and each is only consulted for
the field it belongs to. A single merged table would confidently label a
controlled-release tablet as a cream.

Why an allowlist, never a guess
-------------------------------
Most short tokens trailing an Indian brand name are SALT abbreviations, not
forms - and they outnumber the form hints:

    DICLOMOL SP     SP = serratiopeptidase
    MONTAIR LC      LC = levocetirizine
    SILODAL D 8     D  = dutasteride
    RANIDOM MPS     MPS = magaldrate + polysilane
    CLAVOSAF CV     CV = clavulanic acid

None of these say anything about dosage form. So only tokens on the explicit
list below are read as hints, and anything unrecognised is left alone rather
than guessed at. An unknown suffix produces no form, which the review queue
already knows how to ask about.

On confidence
-------------
These abbreviations have no published standard - the industry press notes
plainly that they are inconsistent and have caused prescribing errors. TA, T,
CA, M, GM and ML are the codes observed in this system's own invoices and are
scored highest; the rest are conventional and scored lower. Every reading is a
proposal carrying its evidence, and a human confirms it, exactly as with the
rest of the catalogue.
"""

import re
from typing import NamedTuple, Optional

# --------------------------------------------------------------------------
# Pack-column codes
# --------------------------------------------------------------------------

class PackCode(NamedTuple):
    form: Optional[str]
    base_unit: str
    # True when the trailing number counts dispensable items ("1x10TA" is ten
    # tablets), False when it measures contents ("1x20GM" is one 20g tube).
    # Getting this backwards inflates or deflates every derived stock figure.
    counts_units: bool
    confidence: float


# Codes seen in this system's own invoices score 0.85; conventional ones that
# have not yet appeared here score 0.6, so a reviewer can tell which readings
# rest on evidence and which on convention.
_OBSERVED = 0.85
_CONVENTION = 0.6

PACK_CODES: dict[str, PackCode] = {
    # --- counted solids (observed) ---
    "TA": PackCode("Tablet", "TABLET", True, _OBSERVED),
    "T": PackCode("Tablet", "TABLET", True, _OBSERVED),
    "CA": PackCode("Capsule", "CAPSULE", True, _OBSERVED),
    # --- measured contents (observed) ---
    "ML": PackCode(None, "ML", False, _OBSERVED),
    "M": PackCode(None, "ML", False, _OBSERVED),
    "GM": PackCode(None, "GM", False, _OBSERVED),
    # --- counted solids (conventional) ---
    "TAB": PackCode("Tablet", "TABLET", True, _CONVENTION),
    "TB": PackCode("Tablet", "TABLET", True, _CONVENTION),
    "TAS": PackCode("Tablet", "TABLET", True, _CONVENTION),
    "CAP": PackCode("Capsule", "CAPSULE", True, _CONVENTION),
    "CP": PackCode("Capsule", "CAPSULE", True, _CONVENTION),
    "CAS": PackCode("Capsule", "CAPSULE", True, _CONVENTION),
    "VL": PackCode("Vial", "VIAL", True, _CONVENTION),
    "VIAL": PackCode("Vial", "VIAL", True, _CONVENTION),
    "AMP": PackCode("Ampoule", "AMPOULE", True, _CONVENTION),
    "AM": PackCode("Ampoule", "AMPOULE", True, _CONVENTION),
    "INJ": PackCode("Injection", "VIAL", True, _CONVENTION),
    "SAC": PackCode("Sachet", "SACHET", True, _CONVENTION),
    "SACH": PackCode("Sachet", "SACHET", True, _CONVENTION),
    "SA": PackCode("Sachet", "SACHET", True, _CONVENTION),
    "RS": PackCode("Respule", "RESPULE", True, _CONVENTION),
    "RESP": PackCode("Respule", "RESPULE", True, _CONVENTION),
    "KT": PackCode("Kit", "KIT", True, _CONVENTION),
    "KIT": PackCode("Kit", "KIT", True, _CONVENTION),
    "PC": PackCode(None, "UNIT", True, _CONVENTION),
    "PCS": PackCode(None, "UNIT", True, _CONVENTION),
    "NO": PackCode(None, "UNIT", True, _CONVENTION),
    "NOS": PackCode(None, "UNIT", True, _CONVENTION),
    # --- measured contents (conventional) ---
    "GR": PackCode(None, "GM", False, _CONVENTION),
    "G": PackCode(None, "GM", False, _CONVENTION),
    "LTR": PackCode(None, "L", False, _CONVENTION),
    "SY": PackCode("Syrup", "ML", False, _CONVENTION),
    "SYP": PackCode("Syrup", "ML", False, _CONVENTION),
    "SYR": PackCode("Syrup", "ML", False, _CONVENTION),
    "SUS": PackCode("Suspension", "ML", False, _CONVENTION),
    "SUSP": PackCode("Suspension", "ML", False, _CONVENTION),
    "SU": PackCode("Suspension", "ML", False, _CONVENTION),
    "DRP": PackCode("Drops", "ML", False, _CONVENTION),
    "DROP": PackCode("Drops", "ML", False, _CONVENTION),
    "CRM": PackCode("Cream", "GM", False, _CONVENTION),
    "CREAM": PackCode("Cream", "GM", False, _CONVENTION),
    "OINT": PackCode("Ointment", "GM", False, _CONVENTION),
    "OI": PackCode("Ointment", "GM", False, _CONVENTION),
    "GEL": PackCode("Gel", "GM", False, _CONVENTION),
    "LOT": PackCode("Lotion", "ML", False, _CONVENTION),
    "POW": PackCode("Powder", "GM", False, _CONVENTION),
    "PW": PackCode("Powder", "GM", False, _CONVENTION),
    "TUB": PackCode(None, "GM", False, _CONVENTION),
}

# Longest first so "TAB" is never shortened to "TA", and "SUSP" not to "SU".
_PACK_CODE_ALTERNATION = "|".join(sorted(PACK_CODES, key=len, reverse=True))
# Anchored at the end of the token: the code trails the numbers ("1x10TA"),
# optionally after a space ("1x10 T"), which is how these actually appear.
PACK_CODE_RE = re.compile(rf"\s*(?P<code>{_PACK_CODE_ALTERNATION})\s*$", re.IGNORECASE)


def read_pack_code(token: Optional[str]) -> tuple[Optional[PackCode], Optional[str]]:
    """Returns (code, matched_text) for a trailing form code in a pack token."""
    if not token:
        return None, None
    match = PACK_CODE_RE.search(str(token).strip())
    if not match:
        return None, None
    return PACK_CODES[match.group("code").upper()], match.group("code")


def strip_pack_code(token: str) -> str:
    """Removes a trailing form code so the numbers can be parsed on their own."""
    return PACK_CODE_RE.sub("", str(token).strip()).strip()


# --------------------------------------------------------------------------
# Product-name modifiers
# --------------------------------------------------------------------------

class FormHint(NamedTuple):
    form: Optional[str]
    base_unit: Optional[str]
    confidence: float
    note: str


# Modified-release markers. These say how the drug is released, which only
# implies that it is a solid oral dose - it could be a tablet or a capsule.
# Scored low for exactly that reason: the hint is real but under-determined,
# and the reviewer picks between two plausible answers rather than being
# handed one.
_RELEASE_MODIFIERS = {
    "SR": "sustained release",
    "ER": "extended release",
    "XR": "extended release",
    "XL": "extended release",
    "CR": "controlled release",
    "DR": "delayed release",
    "MR": "modified release",
    "LA": "long acting",
    "TR": "timed release",
    "OD": "once daily",
    "CD": "controlled delivery",
    "PR": "prolonged release",
}

# Markers that name the dosage form outright rather than its release profile,
# so they identify a tablet specifically.
_TABLET_MODIFIERS = {
    "DT": "dispersible tablet",
    "MD": "mouth dissolving",
    "MDT": "mouth dissolving tablet",
    "ODT": "orally disintegrating tablet",
    "MT": "melt tablet",
    "FC": "film coated",
    "EC": "enteric coated",
    "CHEW": "chewable",
}

_MODIFIER_ALTERNATION = "|".join(
    sorted(set(_RELEASE_MODIFIERS) | set(_TABLET_MODIFIERS), key=len, reverse=True)
)
_MODIFIER_RE = re.compile(rf"(?:^|[\s\-])(?P<code>{_MODIFIER_ALTERNATION})(?=[\s\-]|\d|$)")


def read_name_modifier(name: Optional[str]) -> Optional[FormHint]:
    """Reads a release or tablet marker from a product name.

    Only the tokens listed above are considered. Short suffixes on Indian
    brand names are usually SALT abbreviations - SP, LC, MPS, CV, D - and
    reading those as dosage forms would attach a confident, wrong form to a
    large share of the catalogue.
    """
    if not name:
        return None

    match = _MODIFIER_RE.search(str(name).upper())
    if not match:
        return None

    code = match.group("code")
    if code in _TABLET_MODIFIERS:
        return FormHint("Tablet", "TABLET", 0.7, f"{code} = {_TABLET_MODIFIERS[code]}")

    return FormHint(
        "Tablet",
        "TABLET",
        0.45,
        f"{code} = {_RELEASE_MODIFIERS[code]}, so a solid oral dose — "
        f"confirm whether tablet or capsule",
    )


def forms_conflict(a: Optional[str], b: Optional[str]) -> bool:
    """True when two readings name genuinely different dosage forms.

    Liquid forms are treated as one family: a pack column reading "SY" and a
    name saying "SUSPENSION" disagree on wording, not on what the pharmacist
    is holding, and flagging that as a contradiction would bury the real
    conflicts - a name saying SYRUP against a pack column saying TA.
    """
    if not a or not b or a == b:
        return False

    families = (
        {"Tablet", "Capsule"},
        {"Syrup", "Suspension", "Solution", "Drops", "Eye Drops", "Ear Drops", "Lotion"},
        {"Cream", "Ointment", "Gel"},
        {"Injection", "Vial", "Ampoule"},
    )
    for family in families:
        if a in family and b in family:
            return False
    return True
