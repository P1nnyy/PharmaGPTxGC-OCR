"""When each GST return is due, and when it can no longer be filed at all.

Every date in this module is statutory. None of it is derived from anything the
shop does, and none of it is guessed — which is why it lives here as reference
data rather than being computed at a call site, and why the state-group table
is written out in full instead of being approximated.

**Nothing here assumes monthly.** A shop on QRMP files GSTR-1 and GSTR-3B once
a quarter, pays tax monthly through PMT-06 for the first two months, and gets a
*quarterly* GSTR-2B rather than a monthly one. A calendar built on monthly dates
and then adjusted would produce a plausible-looking schedule that is wrong in
four different ways, so the obligations are generated from the frequency.

The three-year bar is the one nobody expects. Section 39(11) and Section 37(4),
as amended by the Finance Act 2023 and operative from July 2025, stop a return
being filed **more than three years after its due date**. Not a penalty — the
portal refuses. Any period still unfiled past that point can never be regularised,
and the input credit and liability in it are frozen wherever they stand. It is
tracked here because a shop with an old unfiled period usually does not know.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

# --------------------------------------------------------------- obligations

GSTR1 = "GSTR1"
GSTR3B = "GSTR3B"
PMT06 = "PMT06"
GSTR2B = "GSTR2B"
IFF = "IFF"

# What each one is, in words a shopkeeper would use.
OBLIGATION_LABELS = {
    GSTR1: "GSTR-1 — outward supplies",
    GSTR3B: "GSTR-3B — summary return and tax payment",
    PMT06: "PMT-06 — monthly tax payment",
    GSTR2B: "GSTR-2B — inward credit statement",
    IFF: "IFF — invoice furnishing (optional)",
}

# Due days of the month, by obligation. Written as data so the branch on
# filing frequency picks a number rather than a code path.
_GSTR1_MONTHLY_DAY = 11
_GSTR1_QUARTERLY_DAY = 13
_IFF_DAY = 13
_GSTR2B_DAY = 14
_GSTR3B_MONTHLY_DAY = 20
_PMT06_DAY = 25

# QRMP GSTR-3B is due on the 22nd or the 24th depending on where the shop is
# registered. Both groups are written out in full: an abbreviation here would
# be a wrong due date for whichever state got left out.
_QRMP_3B_DAY_22 = {
    "22",  # Chhattisgarh
    "23",  # Madhya Pradesh
    "24",  # Gujarat
    "26",  # Dadra and Nagar Haveli and Daman and Diu
    "27",  # Maharashtra
    "29",  # Karnataka
    "30",  # Goa
    "31",  # Lakshadweep
    "32",  # Kerala
    "33",  # Tamil Nadu
    "34",  # Puducherry
    "35",  # Andaman and Nicobar Islands
    "36",  # Telangana
    "37",  # Andhra Pradesh
}

_QRMP_3B_DAY_24 = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12",
    "13", "14", "15", "16", "17", "18", "19", "20", "21", "38",
}

# Returns filed more than this long after their due date are refused outright.
TIME_BAR_YEARS = 3


def qrmp_3b_day(state_code: Optional[str]) -> int:
    """The QRMP GSTR-3B due day for a state.

    An unrecognised state code gets the **earlier** date. Telling a shop it has
    until the 24th when the real date was the 22nd creates a late filing; the
    reverse costs them two days of float. Only one of those is a problem.
    """
    code = (state_code or "").strip()
    if code in _QRMP_3B_DAY_24:
        return 24
    return 22


# ------------------------------------------------------------------ periods


def _month_add(anchor: date, months: int) -> date:
    """`anchor` moved by whole months, clamped to the last valid day."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    following = date(year + (month == 12), (month % 12) + 1, 1)
    return (following - timedelta(days=1)).day


def _on(year: int, month: int, day: int) -> date:
    """A date in a month, clamped if the month is short."""
    return date(year, month, min(day, _days_in_month(year, month)))


def financial_year_months(fy_start_year: int) -> list:
    """The twelve `MMYYYY` periods of a financial year, April to March."""
    months = [f"{month:02d}{fy_start_year}" for month in range(4, 13)]
    months += [f"{month:02d}{fy_start_year + 1}" for month in range(1, 4)]
    return months


def quarter_of_month(month: int) -> int:
    """GST quarters follow the financial year: Q1 is April to June."""
    return {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2,
            10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[month]


def position_in_quarter(month: int) -> int:
    """1, 2 or 3 — which month of its quarter this is.

    PMT-06 and IFF apply to the first two months only, because the third is
    covered by the quarterly return itself.
    """
    return {4: 1, 5: 2, 6: 3, 7: 1, 8: 2, 9: 3,
            10: 1, 11: 2, 12: 3, 1: 1, 2: 2, 3: 3}[month]


# -------------------------------------------------------------- obligations


@dataclass(frozen=True)
class Obligation:
    """One thing the shop has to do, and when."""

    kind: str
    label: str
    # The tax period it covers - a month for monthly things, the quarter's
    # last month for quarterly ones, matching how the portal identifies them.
    period: str
    covers_months: tuple
    due_date: date
    # False for things that become *available* rather than fall due: GSTR-2B is
    # generated for you, and missing it is not an offence.
    is_filing: bool = True
    is_optional: bool = False
    note: str = ""

    @property
    def barred_on(self) -> Optional[date]:
        """The day this can no longer be filed at all, ever."""
        if not self.is_filing:
            return None
        return _month_add(self.due_date, TIME_BAR_YEARS * 12)

    def days_until(self, today: date) -> int:
        return (self.due_date - today).days

    def days_until_barred(self, today: date) -> Optional[int]:
        barred = self.barred_on
        return None if barred is None else (barred - today).days

    def is_time_barred(self, today: date) -> bool:
        barred = self.barred_on
        return barred is not None and today > barred


def _monthly_obligations(period: str, year: int, month: int) -> list:
    """A monthly filer's obligations for one month."""
    following = _month_add(date(year, month, 1), 1)
    return [
        Obligation(
            kind=GSTR1, label=OBLIGATION_LABELS[GSTR1], period=period,
            covers_months=(period,),
            due_date=_on(following.year, following.month, _GSTR1_MONTHLY_DAY),
            note="Outward supplies for the month.",
        ),
        Obligation(
            kind=GSTR2B, label=OBLIGATION_LABELS[GSTR2B], period=period,
            covers_months=(period,),
            due_date=_on(following.year, following.month, _GSTR2B_DAY),
            is_filing=False,
            note="Generated by the portal. Reconcile it before filing 3B — the "
                 "credit you may claim is capped by what is in here.",
        ),
        Obligation(
            kind=GSTR3B, label=OBLIGATION_LABELS[GSTR3B], period=period,
            covers_months=(period,),
            due_date=_on(following.year, following.month, _GSTR3B_MONTHLY_DAY),
            note="Tax is payable with this return.",
        ),
    ]


def _quarterly_obligations(
    period: str, year: int, month: int, state_code: Optional[str]
) -> list:
    """A QRMP filer's obligations for one month.

    Most months carry only a payment. The quarter's last month carries the two
    returns and the quarterly 2B, which is why a schedule built on monthly
    dates and then adjusted gets QRMP wrong - the obligations are not the same
    ones moved, they are different obligations.
    """
    following = _month_add(date(year, month, 1), 1)
    slot = position_in_quarter(month)
    obligations = []

    if slot in (1, 2):
        obligations.append(
            Obligation(
                kind=PMT06, label=OBLIGATION_LABELS[PMT06], period=period,
                covers_months=(period,),
                due_date=_on(following.year, following.month, _PMT06_DAY),
                note="Tax for the month, paid while the return itself waits for "
                     "the end of the quarter.",
            )
        )
        obligations.append(
            Obligation(
                kind=IFF, label=OBLIGATION_LABELS[IFF], period=period,
                covers_months=(period,),
                due_date=_on(following.year, following.month, _IFF_DAY),
                is_optional=True,
                note="Optional. Only worth doing if you raise B2B invoices and "
                     "your buyer wants the credit before the quarter ends.",
            )
        )
        return obligations

    # The quarter's last month: both returns, and the quarterly 2B.
    quarter_months = tuple(
        f"{m:02d}{y}" for m, y in _quarter_month_pairs(year, month)
    )
    obligations.append(
        Obligation(
            kind=GSTR1, label=OBLIGATION_LABELS[GSTR1], period=period,
            covers_months=quarter_months,
            due_date=_on(following.year, following.month, _GSTR1_QUARTERLY_DAY),
            note="One return for the whole quarter.",
        )
    )
    obligations.append(
        Obligation(
            kind=GSTR2B, label=OBLIGATION_LABELS[GSTR2B], period=period,
            covers_months=quarter_months,
            due_date=_on(following.year, following.month, _GSTR2B_DAY),
            is_filing=False,
            note="A QRMP shop gets one 2B for the quarter, not one a month.",
        )
    )
    obligations.append(
        Obligation(
            kind=GSTR3B, label=OBLIGATION_LABELS[GSTR3B], period=period,
            covers_months=quarter_months,
            due_date=_on(following.year, following.month, qrmp_3b_day(state_code)),
            note=f"Due on the {qrmp_3b_day(state_code)}th for this state. "
                 "Tax already paid through PMT-06 is set off here.",
        )
    )
    return obligations


def _quarter_month_pairs(year: int, last_month: int) -> list:
    """The three (month, year) pairs of the quarter ending in `last_month`."""
    pairs = []
    anchor = date(year, last_month, 1)
    for back in (2, 1, 0):
        moved = _month_add(anchor, -back)
        pairs.append((moved.month, moved.year))
    return pairs


def obligations_for_month(
    period: str, frequency: str, state_code: Optional[str] = None
) -> list:
    """Everything owed in respect of one tax period."""
    month, year = int(period[:2]), int(period[2:])
    if (frequency or "MONTHLY").upper() == "QUARTERLY":
        return _quarterly_obligations(period, year, month, state_code)
    return _monthly_obligations(period, year, month)


def obligations_for_financial_year(
    fy_start_year: int, frequency: str, state_code: Optional[str] = None
) -> list:
    """The whole year's schedule, in due-date order."""
    every = []
    for period in financial_year_months(fy_start_year):
        every.extend(obligations_for_month(period, frequency, state_code))
    return sorted(every, key=lambda o: (o.due_date, o.kind))


def financial_year_of(day: date) -> int:
    """The FY start year a date falls in. April to March."""
    return day.year if day.month >= 4 else day.year - 1
