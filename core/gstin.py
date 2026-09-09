"""GSTIN parsing and validation.

A GSTIN is 15 characters and self-describing: `22AAAAA0000A1Z5` is state code
22, PAN `AAAAA0000A`, entity number 1, a literal Z, and a checksum. Validating
it properly matters more here than it looks - the number is what tells a scan
which party on an invoice is us, so a typo would silently swap buyer and
seller on every future bill rather than failing visibly.

The checksum is the standard mod-36 scheme, so a transposed pair of
characters is caught at entry instead of at the first scan.
"""

import re
from typing import Optional

_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SHAPE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")

# GST state codes. The first two digits decide whether a purchase is
# intra-state (CGST + SGST) or inter-state (IGST), so this is not decoration -
# it is what makes the tax split on a scanned invoice checkable.
STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory",
}


class GstinError(ValueError):
    """Raised when a GSTIN cannot be accepted."""


def normalize(gstin: str) -> str:
    """Upper-cased with spaces stripped - how people actually type it."""
    return re.sub(r"\s+", "", (gstin or "")).upper()


def checksum_char(first_fourteen: str) -> str:
    """The 15th character implied by the first 14."""
    total = 0
    for i, ch in enumerate(first_fourteen):
        value = _CHARSET.index(ch)
        factor = 1 if i % 2 == 0 else 2
        product = value * factor
        total += product // 36 + product % 36
    return _CHARSET[(36 - (total % 36)) % 36]


def validate(gstin: str) -> str:
    """Returns the normalised GSTIN, or explains precisely what is wrong."""
    value = normalize(gstin)
    if not value:
        raise GstinError("GSTIN is required.")
    if len(value) != 15:
        raise GstinError(f"A GSTIN is 15 characters; this one has {len(value)}.")
    if not _SHAPE.match(value):
        raise GstinError(
            "That does not look like a GSTIN. The shape is 2 digits, 5 letters, "
            "4 digits, a letter, one more character, then Z and a check character."
        )
    if value[:2] not in STATE_CODES:
        raise GstinError(f"'{value[:2]}' is not a valid GST state code.")
    expected = checksum_char(value[:14])
    if value[14] != expected:
        # Almost always a typo rather than fraud, so say so plainly.
        raise GstinError("That GSTIN's check character is wrong - please re-read it.")
    return value


def parse(gstin: str) -> dict:
    """Everything the number tells us, once it is known to be valid."""
    value = validate(gstin)
    return {
        "gstin": value,
        "state_code": value[:2],
        "state": STATE_CODES[value[:2]],
        # The PAN is embedded, so a pharmacy never has to type it twice.
        "pan": value[2:12],
    }


def state_code_of(gstin: Optional[str]) -> Optional[str]:
    """The GST state code, or None if the value does not carry a real one.

    Checked against the published list rather than just taken as the first
    two characters: OCR noise like "garbage" or a truncated read would
    otherwise yield a confident-looking "ga" that is not a state at all.
    """
    value = normalize(gstin or "")
    code = value[:2]
    return code if code in STATE_CODES else None


def same_state(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    """Whether two GSTINs are in one state - the CGST+SGST vs IGST question.

    None when either side is unknown or unreadable, so a caller can tell
    "different states" apart from "we could not tell". The distinction decides
    whether tax is split into CGST and SGST or booked entirely as IGST, and a
    misread number must not produce a confident wrong answer: comparing raw
    prefixes would read a garbled GSTIN as a different state and silently
    reclassify an intra-state purchase as inter-state.
    """
    code_a, code_b = state_code_of(a), state_code_of(b)
    if code_a is None or code_b is None:
        return None
    return code_a == code_b
