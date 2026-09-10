"""Which months one GSTR-1 covers.

The single place that turns "this shop, this period" into a filing window. It
exists so that no aggregator, validator or route has to know whether the shop
is on QRMP - they iterate `FilingPeriod.months` and are correct either way.

Getting this wrong is not a rounding error. A quarterly filer aggregated by
month files three returns where one was due, and each of them is missing two
thirds of the quarter's supplies.
"""

from typing import Optional

from core.tax_periods import (
    PeriodError,
    financial_year_of_period,
    is_valid_period,
    months_in_quarter,
    period_bounds,
    period_label,
    quarter_of_period,
)
from services.gstr1.model import FilingPeriod

_QUARTER_LABELS = {1: "Apr-Jun", 2: "Jul-Sep", 3: "Oct-Dec", 4: "Jan-Mar"}


def resolve_filing_period(period: str, frequency: Optional[str]) -> FilingPeriod:
    """The window a return covers, given the period asked for and how the shop files.

    `period` is any month inside the window. For a QRMP shop that means asking
    for August and being handed July to September - deliberately, because the
    user picks a month from a calendar and the return they are filing is the
    quarter that month sits in.
    """
    if not is_valid_period(period):
        raise PeriodError(f"{period!r} is not a tax period. Use MMYYYY, e.g. 092026.")

    if (frequency or "MONTHLY").upper() != "QUARTERLY":
        start, end = period_bounds(period)
        return FilingPeriod(
            label=period_label(period),
            frequency="MONTHLY",
            months=(period,),
            start_date=start,
            end_date=end,
            financial_year=financial_year_of_period(period),
        )

    financial_year, quarter = quarter_of_period(period)
    months = tuple(months_in_quarter(financial_year, quarter))
    start, _ = period_bounds(months[0])
    _, end = period_bounds(months[-1])
    # The calendar year the quarter's months fall in, which for Q4 is the year
    # after the financial year began.
    calendar_year = period_label(months[0]).split()[-1]
    return FilingPeriod(
        label=f"{_QUARTER_LABELS[quarter]} {calendar_year}",
        frequency="QUARTERLY",
        months=months,
        start_date=start,
        end_date=end,
        financial_year=financial_year,
        quarter=quarter,
    )
