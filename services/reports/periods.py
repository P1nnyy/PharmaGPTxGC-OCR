"""Reporting period resolution.

Every report is pulled "for a period", and the periods that matter here are the
ones an Indian accountant asks for: a financial year running April to March, a
GST quarter inside it, or a single month. Calendar-year periods are not offered
because nothing downstream — GST returns, ITC claims, audits — uses them.

Resolution is pure: a request in, ISO bounds out. No clock reads except
`today`, which callers pass in so tests are not time-dependent.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

from core.dates import financial_year_bounds, financial_year_of, normalize_invoice_date

PeriodKind = Literal["fy", "quarter", "month", "custom"]

# GST quarters follow the financial year, not the calendar: Q1 is Apr-Jun.
_QUARTER_MONTHS = {1: (4, 6), 2: (7, 9), 3: (10, 12), 4: (1, 3)}


class PeriodError(ValueError):
    """Raised when a period request cannot be resolved. Carries a message meant
    to be shown to the user, so routers can surface it as a 400 directly."""


@dataclass(frozen=True)
class Period:
    """A resolved, inclusive reporting window."""

    kind: PeriodKind
    start: str
    end: str
    label: str
    fy_start_year: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "label": self.label,
            "fy_start_year": self.fy_start_year,
        }


def _fy_label(fy_start_year: int) -> str:
    return f"FY {fy_start_year}-{str(fy_start_year + 1)[-2:]}"


def current_fy_start_year(today: Optional[date] = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 4 else today.year - 1


def resolve(
    kind: Optional[str] = None,
    fy: Optional[int] = None,
    quarter: Optional[int] = None,
    month: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    today: Optional[date] = None,
) -> Period:
    """Resolves a period request into inclusive ISO bounds.

    Defaults to the financial year in progress, which is what a pharmacy owner
    means by "this year" and what the accountant will ask for.
    """
    today = today or date.today()
    kind = (kind or "fy").lower()

    if kind == "fy":
        year = fy if fy is not None else current_fy_start_year(today)
        start_iso, end_iso = financial_year_bounds(year)
        return Period("fy", start_iso, end_iso, _fy_label(year), year)

    if kind == "quarter":
        if quarter not in _QUARTER_MONTHS:
            raise PeriodError("Quarter must be 1, 2, 3 or 4 (Q1 is April to June).")
        year = fy if fy is not None else current_fy_start_year(today)
        first_month, last_month = _QUARTER_MONTHS[quarter]
        # Q4 (Jan-Mar) lands in the calendar year after the FY started.
        calendar_year = year if first_month >= 4 else year + 1
        start_iso = date(calendar_year, first_month, 1).isoformat()
        end_iso = _end_of_month(calendar_year, last_month)
        return Period(
            "quarter", start_iso, end_iso, f"Q{quarter} {_fy_label(year)}", year
        )

    if kind == "month":
        if not month:
            raise PeriodError("A month period needs a month in YYYY-MM form.")
        try:
            year_s, month_s = month.split("-")
            year_i, month_i = int(year_s), int(month_s)
            start_iso = date(year_i, month_i, 1).isoformat()
        except (ValueError, TypeError):
            raise PeriodError(f"Could not read {month!r} as a month. Use YYYY-MM.")
        end_iso = _end_of_month(year_i, month_i)
        label = date(year_i, month_i, 1).strftime("%b %Y")
        return Period("month", start_iso, end_iso, label, financial_year_of(start_iso))

    if kind == "custom":
        start_iso = normalize_invoice_date(start)
        end_iso = normalize_invoice_date(end)
        if not start_iso or not end_iso:
            raise PeriodError("A custom period needs a readable start and end date.")
        if start_iso > end_iso:
            raise PeriodError("The start of the period is after its end.")
        return Period(
            "custom",
            start_iso,
            end_iso,
            f"{start_iso} to {end_iso}",
            financial_year_of(start_iso),
        )

    raise PeriodError(f"Unknown period type {kind!r}. Use fy, quarter, month or custom.")


def _end_of_month(year: int, month: int) -> str:
    import calendar

    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def month_sequence(period: Period) -> list[str]:
    """Every `YYYY-MM` inside the period, in order.

    Reports render a bar per month across the whole period, including months
    with no purchases — a gap in the series is itself information ("we bought
    nothing in July"), and a query that only returns populated months would
    silently close that gap.
    """
    start_year, start_month = int(period.start[:4]), int(period.start[5:7])
    end_year, end_month = int(period.end[:4]), int(period.end[5:7])

    months = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months
