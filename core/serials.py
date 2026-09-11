"""Rule 46(b) invoice serials.

A tax invoice's number is how a filed return identifies it, and the rule is
specific: consecutive, unique within a financial year, at most sixteen
characters, and drawn from alphanumerics plus `-` and `/` only.

This module deliberately mirrors `frontend/src/features/sell/serial.ts`. The
device formats a serial offline and the server validates it when the bill
eventually syncs; if the two disagreed about what a valid serial is, a bill
that was already printed and handed to a customer would be rejected on arrival,
which is the one outcome the offline design exists to prevent.

The length guard is enforced at *allocation* time rather than at sale time for
the same reason. A device that has already sold twenty bills cannot usefully be
told that its serial is too long.
"""

import re
from typing import Optional

RULE_46B = re.compile(r"^[A-Za-z0-9/-]{1,16}$")
PREFIX_ALLOWED = re.compile(r"^[A-Za-z0-9/-]*$")
MAX_SERIAL_LENGTH = 16


class SerialError(ValueError):
    """Raised when a serial or series cannot be accepted."""


def is_valid_serial(serial: Optional[str]) -> bool:
    return bool(serial and isinstance(serial, str) and RULE_46B.match(serial))


def format_serial(prefix: str, sequence: int, pad_to: int) -> str:
    """`CTR-` + 42 -> `CTR-000042`.

    Zero-padded so the series sorts lexicographically as well as numerically,
    which is what makes "the last bill of the day" a sort rather than a scan.
    """
    if not PREFIX_ALLOWED.match(prefix or ""):
        raise SerialError(
            f"{prefix!r} is not a usable series prefix. Rule 46(b) allows letters, "
            "digits, hyphens and slashes only."
        )
    serial = f"{prefix}{str(sequence).zfill(pad_to)}"
    if len(serial) > MAX_SERIAL_LENGTH:
        raise SerialError(
            f"{serial!r} is {len(serial)} characters. Rule 46(b) allows at most "
            f"{MAX_SERIAL_LENGTH} — shorten the series prefix."
        )
    return serial


def parse_serial(serial: str) -> "tuple[str, int]":
    """Splits a serial back into `(prefix, sequence)`."""
    match = re.match(r"^(.*?)(\d+)$", serial or "")
    if not match:
        raise SerialError(f"{serial!r} does not end in a sequence number.")
    return match.group(1), int(match.group(2))


def financial_year_of(iso_date: str) -> int:
    """The FY start year an ISO date falls in. 2026-03-31 is FY 2025-26."""
    match = re.match(r"^(\d{4})-(\d{2})", iso_date or "")
    if not match:
        raise SerialError(f"Could not read {iso_date!r} as a date.")
    year, month = int(match.group(1)), int(match.group(2))
    return year if month >= 4 else year - 1


def series_key(pharmacy_id: str, prefix: str, financial_year: int) -> str:
    """The counter a block is allocated from.

    One counter per workspace, series and financial year. The year is part of
    the key because serials are unique *within* a year and the sequence starts
    again at 1 in April.
    """
    return f"{pharmacy_id}::{prefix}::{financial_year}"
