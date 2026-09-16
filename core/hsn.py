"""HSN codes and unit quantity codes, validated against the stored GSTN master.

The house rule is short — "HSN codes are validated against a stored GSTN master
list. An HSN not in the master cannot be selected" — and the reason is that the
portal's Table 12 is a dropdown, not a text box. A code that is merely
plausible, say a real product filed under a chapter someone guessed at, is not
rejected when it is typed. It is rejected when the return is filed, which is
after the month has closed and usually after the person who knew what the
product was has stopped thinking about it. Validating here moves that failure
back to a point where it is still cheap.

Two other things this module decides, both of which change what is filed:

**Digit length.** A shop reports HSN at 4 digits up to ₹5 crore of aggregate
turnover and 6 above it. The threshold is on *aggregate* turnover, PAN-wide, so
it is not something this module can work out on its own — it is told. What it
does enforce is that a code carries at least as many digits as the shop owes,
because a 6-digit filer reporting `3004` has under-reported and the return is
rejected.

**UQC.** Table 12 wants a unit from GSTN's own list. A pharmacy says "strip",
"vial", "bottle"; the portal has never heard of a strip. `normalize_uqc` maps
what the shop says onto what the portal takes, and refuses rather than guessing
when there is no mapping — a wrong unit on a filed return is a wrong return.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DATA = Path(__file__).resolve().parent.parent / "data" / "gstn"

# ₹5 crore, in paise. The turnover threshold that moves a shop from 4-digit HSN
# reporting to 6-digit. Written out rather than as 5e9 so it is greppable and
# so no float ever touches a statutory threshold.
AATO_SIX_DIGIT_THRESHOLD_PAISE = 5_00_00_000_00

# What the two policies mean in digits. Named so that a stored policy string is
# self-describing in the database rather than being a bare number whose meaning
# has to be looked up.
HSN_DIGIT_POLICIES = {"FOUR_DIGIT": 4, "SIX_DIGIT": 6}

# The lengths Table 12 accepts. A chapter heading is two digits and is in
# GSTN's master, but no return has ever been filed on one.
FILABLE_LENGTHS = (4, 6, 8)

# How a code was matched against the master.
EXACT = "EXACT"                    # the code itself is listed
PARENT_MATCHED = "PARENT_MATCHED"  # a longer code, reported under its parent


class HsnError(ValueError):
    """Raised when an HSN or UQC cannot be accepted."""


@dataclass(frozen=True)
class HsnResolution:
    """What was given, what will be filed, and how the two are related.

    `code` is what the distributor printed and `reported` is what goes into
    Table 12. They differ only on a roll-up, and keeping both is the point:
    the return needs the parent, and anyone auditing the return needs to see
    the code the line actually carried.
    """

    code: str
    reported: str
    match: str

    @property
    def rolled_up(self) -> bool:
        return self.match == PARENT_MATCHED


def _load(name: str) -> dict:
    with open(_DATA / name, encoding="utf-8") as handle:
        return json.load(handle)


def _master() -> dict:
    global _MASTER_CACHE
    if _MASTER_CACHE is None:
        _MASTER_CACHE = _load("hsn_master.json")["codes"]
    return _MASTER_CACHE


def _uqc_data() -> dict:
    global _UQC_CACHE
    if _UQC_CACHE is None:
        _UQC_CACHE = _load("uqc.json")
    return _UQC_CACHE


_MASTER_CACHE: Optional[dict] = None
_UQC_CACHE: Optional[dict] = None


# ------------------------------------------------------------------ HSN


def normalize_hsn(code: Optional[str]) -> str:
    """Strips the spaces and dots people type between digit groups."""
    if code is None:
        return ""
    return "".join(ch for ch in str(code) if ch.isdigit())


def is_known(code: Optional[str]) -> bool:
    """True if the code is in the stored master."""
    return normalize_hsn(code) in _master()


def describe(code: Optional[str]) -> Optional[str]:
    """The master's description of a code, for showing next to it in review."""
    return _master().get(normalize_hsn(code))


def policy_digits(policy: Optional[str]) -> int:
    """Digits owed under a stored policy name. Defaults to the stricter 6.

    Defaulting up rather than down is deliberate: reporting more digits than
    required is accepted by the portal, reporting fewer is not. An unset policy
    should cost a shop a little extra precision, not a rejected return.
    """
    return HSN_DIGIT_POLICIES.get(policy or "", 6)


def policy_for_aato(aato_paise: Optional[int]) -> str:
    """The digit policy a turnover implies.

    Unknown turnover resolves to the stricter policy for the reason above. The
    threshold is *aggregate* turnover across every GSTIN on the PAN, which this
    module cannot see — the caller supplies it.
    """
    if aato_paise is None:
        return "SIX_DIGIT"
    return "SIX_DIGIT" if aato_paise > AATO_SIX_DIGIT_THRESHOLD_PAISE else "FOUR_DIGIT"


def resolve_hsn(code: Optional[str], required_digits: int = 4) -> HsnResolution:
    """Works out what a line's code will be filed as, or refuses it.

    Length is checked before membership so that a shop reporting `3004` when it
    owes six digits is told about the digits — which it can fix by picking a
    more specific code — rather than being told its code is unknown, which it
    is not.

    A code longer than the shop files at is rolled up to its parent. A
    distributor prints `30049079` because the customs tariff is eight digits
    deep; a shop under ₹5 crore files `3004`. Those are the same
    classification stated at two depths, and rejecting the line would be
    rejecting a *correct* code for being too precise — which is what this
    module did until the master was the full GSTN list and the problem became
    visible on real invoices.

    Roll-up only ever goes towards fewer digits, and only onto a parent GSTN
    actually lists. Inventing `3099` to accommodate `30999999` would be the
    guess this module exists to prevent.
    """
    normalized = normalize_hsn(code)
    if not normalized:
        raise HsnError("No HSN code.")
    if len(normalized) not in FILABLE_LENGTHS:
        raise HsnError(
            f"{normalized!r} is {len(normalized)} digits. An HSN is 4, 6 or 8 digits."
        )
    if len(normalized) < required_digits:
        raise HsnError(
            f"{normalized!r} is {len(normalized)} digits, but this shop reports HSN at "
            f"{required_digits}. Choose a more specific code."
        )

    parent = normalized[:required_digits]
    if parent != normalized and parent in _master():
        return HsnResolution(code=normalized, reported=parent, match=PARENT_MATCHED)

    if normalized in _master():
        # Listed, but its parent is not - which GSTN's own list does not do.
        # Filing the longer code is legal, since more digits than owed are
        # always accepted, so a code this specific is reported as it stands
        # rather than refused over a gap in the hierarchy above it.
        return HsnResolution(code=normalized, reported=normalized, match=EXACT)

    raise HsnError(
        f"{normalized!r} is not in the GSTN master list"
        + (
            f", and nor is {parent!r}, the {required_digits}-digit code it would be "
            "reported under. "
            if parent != normalized
            else ", so the portal will not accept it. "
        )
        + "Check the product's classification."
    )


def validate_hsn(code: Optional[str], required_digits: int = 4) -> str:
    """The code that will be filed, or an explanation of what is wrong.

    Returns the *reported* code, so a rolled-up line hands back the parent
    rather than the eight-digit code that was passed in.
    """
    return resolve_hsn(code, required_digits).reported


# ------------------------------------------------------------------ UQC


def valid_uqcs() -> dict:
    """GSTN's UQC list, code to description."""
    return dict(_uqc_data()["codes"])


def is_valid_uqc(code: Optional[str]) -> bool:
    return str(code or "").strip().upper() in _uqc_data()["codes"]


def normalize_uqc(unit: Optional[str]) -> Optional[str]:
    """Maps what a pharmacy calls a unit onto a UQC the portal accepts.

    Returns None rather than a fallback when there is no mapping. `OTH` exists
    in the list and would always "work", but filing every unmapped unit as
    OTHERS turns a fixable data problem into a permanently vague return.
    """
    text = str(unit or "").strip().upper()
    if not text:
        return None
    if text in _uqc_data()["codes"]:
        return text
    aliases = _uqc_data()["pharmacy_aliases"]
    mapped = aliases.get(text)
    return mapped if mapped in _uqc_data()["codes"] else None


def validate_uqc(unit: Optional[str]) -> str:
    """Returns the UQC, or explains what is wrong."""
    normalized = normalize_uqc(unit)
    if normalized is None:
        if str(unit or "").strip():
            raise HsnError(
                f"{unit!r} is not a unit the portal recognises. Map it to one of "
                "GSTN's unit quantity codes."
            )
        raise HsnError("No unit of measure.")
    return normalized
