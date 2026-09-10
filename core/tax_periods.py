"""Tax periods — the `MMYYYY` strings a GST return is filed for.

Distinct from `services/reports/periods.py`, deliberately. That module resolves
a *reporting window* a user asked to look at; this one identifies the *filing
period* a document legally belongs to. They use different formats because they
answer different questions, and collapsing them would let a report's date
picker silently decide which return a sale is filed in.

The financial year runs April to March, and GST quarters follow it: Q1 is
April to June. A shop on QRMP files GSTR-1 quarterly, so the lock that stops a
filed period being edited has to be expressible over a quarter as well as a
month — hence `months_in_quarter`.
"""

import calendar
import re
from typing import Optional

_PERIOD_RE = re.compile(r"^(0[1-9]|1[0-2])(\d{4})$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

# Q1 is April-June, following the financial year rather than the calendar.
_QUARTER_MONTHS = {1: (4, 6), 2: (7, 9), 3: (10, 12), 4: (1, 3)}


class PeriodError(ValueError):
    """Raised when a tax period cannot be read. Carries a user-facing message."""


def is_valid_period(period: Optional[str]) -> bool:
    """True for a well-formed `MMYYYY`.

    An unpadded month like `92026` is refused rather than read as September:
    it is ambiguous against a two-digit year, and guessing would file a return
    into the wrong month.
    """
    return bool(period and isinstance(period, str) and _PERIOD_RE.match(period))


def _parts(period: Optional[str]) -> "tuple[int, int]":
    if not is_valid_period(period):
        raise PeriodError(f"{period!r} is not a tax period. Use MMYYYY, e.g. 092026.")
    match = _PERIOD_RE.match(period)  # type: ignore[arg-type]
    return int(match.group(1)), int(match.group(2))


def period_of(iso_date: Optional[str]) -> str:
    """The filing period an ISO date falls in."""
    match = _ISO_RE.match(iso_date or "")
    if not match:
        raise PeriodError(f"Could not read {iso_date!r} as a date.")
    year, month, _ = (int(g) for g in match.groups())
    return f"{month:02d}{year:04d}"


def period_bounds(period: str) -> "tuple[str, str]":
    """Inclusive ISO bounds of the period."""
    month, year = _parts(period)
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def financial_year_of_period(period: str) -> int:
    """The FY start year the period belongs to. 032026 is FY 2025-26."""
    month, year = _parts(period)
    return year if month >= 4 else year - 1


def quarter_of_period(period: str) -> "tuple[int, int]":
    """`(financial year start, quarter number)` for the period."""
    month, _ = _parts(period)
    for quarter, (first, last) in _QUARTER_MONTHS.items():
        if first <= month <= last:
            return financial_year_of_period(period), quarter
    raise PeriodError(f"{period!r} has no quarter.")  # unreachable for a valid period


def months_in_quarter(fy_start_year: int, quarter: int) -> "list[str]":
    """Every `MMYYYY` in a GST quarter, in order.

    Needed because a QRMP shop files one GSTR-1 for the quarter: filing it has
    to lock all three months, not just the one the user clicked.
    """
    if quarter not in _QUARTER_MONTHS:
        raise PeriodError("Quarter must be 1, 2, 3 or 4 (Q1 is April to June).")
    first, last = _QUARTER_MONTHS[quarter]
    # Q4 (Jan-Mar) falls in the calendar year after the financial year began.
    year = fy_start_year if first >= 4 else fy_start_year + 1
    return [f"{month:02d}{year:04d}" for month in range(first, last + 1)]


def period_label(period: str) -> str:
    """`092026` as `Sep 2026`, for anything a person reads."""
    month, year = _parts(period)
    return f"{calendar.month_abbr[month]} {year}"
