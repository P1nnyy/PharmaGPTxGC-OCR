"""Date parsing shared by extraction and reporting.

Invoice dates arrive as whatever the supplier printed and the OCR engine read
back — `03/08/2026`, `3-8-26`, `3 Aug 2026`, sometimes already ISO. Reporting
needs one canonical form: every date is stored as `YYYY-MM-DD` so month
bucketing, financial-year filters and expiry maths are string comparisons
rather than per-call-site parsing.

Two distinct kinds of date live on an invoice and they do NOT parse the same
way:

  * invoice dates are day-precision (`03/08/2026`)
  * batch expiry is month-precision (`08/26` means "good through August")

They get separate functions because collapsing them loses the distinction that
an expiry with no day means end-of-month, not the 1st.
"""

import calendar
import re
from datetime import date
from typing import Optional

# Day-first is the Indian convention and the one printed on the invoices this
# system reads. It is only a tie-breaker: an unambiguous component (a value
# above 12 cannot be a month) always wins over it.
_DAY_FIRST_DEFAULT = True

_MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC_RE = re.compile(r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})$")
_TEXTUAL_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-]*([A-Za-z]{3,9})[\s\-,]*(\d{2,4})$", re.I)
# The separators here are mandatory, unlike the day-first pattern above: with
# them optional, "Aug 2026" parses as month=Aug day=20 year=26 because the
# 4-digit year splits happily into two groups.
_TEXTUAL_LEADING_RE = re.compile(
    r"^([A-Za-z]{3,9})[\s\-]+(\d{1,2})(?:st|nd|rd|th)?[\s\-,]+(\d{2,4})$", re.I
)

# The leading group allows four digits so a year-first expiry ("2026/08") is
# captured and disambiguated below, rather than failing to match at all.
_MONTH_YEAR_RE = re.compile(r"^(\d{1,4})[/\-.](\d{2,4})$")
_MONTH_YEAR_TEXT_RE = re.compile(r"^([A-Za-z]{3,9})[\s\-/.]*(\d{2,4})$")


def _expand_year(year: int) -> int:
    """Expands a 2-digit year. Invoices and expiries are both near-present, so
    the 1970s pivot that `strptime` uses would misread `26` as 2026 correctly
    but `70` as 1970 — fine here, since a pharma date in the 1900s is not a
    real case and a wrong century is more obvious than a wrong decade."""
    if year >= 100:
        return year
    return 2000 + year if year < 70 else 1900 + year


def _safe_date(year: int, month: int, day: int) -> Optional[str]:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_invoice_date(value: Optional[str]) -> Optional[str]:
    """Returns `YYYY-MM-DD`, or None when the value cannot be read as a date.

    None is deliberate: a date we could not parse must not silently become
    today, or 1970, or the string it arrived as. Callers surface it as missing
    so the invoice shows up in the data-quality report instead of quietly
    landing in the wrong month.
    """
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    # Already ISO (possibly with a time component from a datetime round-trip).
    text = text.split("T")[0].strip()

    iso = _ISO_RE.match(text)
    if iso:
        year, month, day = (int(g) for g in iso.groups())
        return _safe_date(year, month, day)

    numeric = _NUMERIC_RE.match(text)
    if numeric:
        first, second, third = (int(g) for g in numeric.groups())

        # A 4-digit leading component can only be a year: 2026/08/03.
        if first > 31:
            return _safe_date(_expand_year(first), second, third)

        year = _expand_year(third)
        # An out-of-range component disambiguates the order on its own; the
        # day-first default only applies when both readings are possible.
        if first > 12:
            day, month = first, second
        elif second > 12:
            month, day = first, second
        elif _DAY_FIRST_DEFAULT:
            day, month = first, second
        else:
            month, day = first, second
        return _safe_date(year, month, day)

    textual = _TEXTUAL_RE.match(text)
    if textual:
        day_s, month_s, year_s = textual.groups()
        month = _MONTH_NAMES.get(month_s.lower())
        if month:
            return _safe_date(_expand_year(int(year_s)), month, int(day_s))

    leading = _TEXTUAL_LEADING_RE.match(text)
    if leading:
        month_s, day_s, year_s = leading.groups()
        month = _MONTH_NAMES.get(month_s.lower())
        if month:
            return _safe_date(_expand_year(int(year_s)), month, int(day_s))

    return None


def normalize_expiry(value: Optional[str]) -> Optional[str]:
    """Returns the last day of the expiry month as `YYYY-MM-DD`, or None.

    Pharma expiry is month-precision — `08/26` on the strip means the stock is
    good through the whole of August 2026. Resolving to the last day of the
    month rather than the 1st is what makes a "days until expiry" figure match
    what a pharmacist would say, and avoids writing off stock 30 days early.
    """
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    # Month-precision forms are checked first. Doing it the other way round
    # lets the day-precision parser reach a value like "Aug 2026" and read the
    # year's leading digits as a day.
    month = year = None

    month_year = _MONTH_YEAR_RE.match(text)
    if month_year:
        first, second = (int(g) for g in month_year.groups())
        # MM/YY or MM/YYYY. A leading value above 12 has to be the year.
        if first > 12:
            year, month = _expand_year(first), second
        else:
            month, year = first, _expand_year(second)

    if month is None:
        textual = _MONTH_YEAR_TEXT_RE.match(text)
        if textual:
            month_s, year_s = textual.groups()
            month = _MONTH_NAMES.get(month_s.lower())
            year = _expand_year(int(year_s))

    if month and year and 1 <= month <= 12:
        return _safe_date(year, month, calendar.monthrange(year, month)[1])

    # Not a month/year form — some suppliers do print a full expiry date, and
    # when they were that precise it is kept as-is rather than rounded out to
    # the end of the month.
    return normalize_invoice_date(text)


def financial_year_bounds(fy_start_year: int) -> tuple[str, str]:
    """Inclusive ISO bounds of an Indian financial year: 1 April to 31 March.

    `financial_year_bounds(2026)` covers FY 2026-27.
    """
    return f"{fy_start_year}-04-01", f"{fy_start_year + 1}-03-31"


def financial_year_of(iso_date: str) -> Optional[int]:
    """The FY start year an ISO date falls in. 2026-03-31 is FY 2025-26."""
    parsed = _ISO_RE.match(iso_date or "")
    if not parsed:
        return None
    year, month, _ = (int(g) for g in parsed.groups())
    return year if month >= 4 else year - 1
