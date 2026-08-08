from datetime import date

import pytest

from services.reports.periods import (
    PeriodError,
    current_fy_start_year,
    month_sequence,
    resolve,
)


class TestCurrentFinancialYear:
    def test_april_starts_the_new_fy(self):
        assert current_fy_start_year(date(2026, 4, 1)) == 2026

    def test_march_still_belongs_to_the_previous_fy(self):
        assert current_fy_start_year(date(2026, 3, 31)) == 2025


class TestResolve:
    def test_defaults_to_the_fy_in_progress(self):
        """"This year" to a pharmacy owner means the FY, not the calendar year."""
        period = resolve(today=date(2026, 8, 5))
        assert (period.kind, period.start, period.end) == ("fy", "2026-04-01", "2027-03-31")
        assert period.label == "FY 2026-27"

    def test_explicit_fy(self):
        period = resolve(kind="fy", fy=2025)
        assert (period.start, period.end) == ("2025-04-01", "2026-03-31")

    @pytest.mark.parametrize(
        "quarter,start,end",
        [
            (1, "2026-04-01", "2026-06-30"),
            (2, "2026-07-01", "2026-09-30"),
            (3, "2026-10-01", "2026-12-31"),
            (4, "2027-01-01", "2027-03-31"),
        ],
    )
    def test_quarters_follow_the_financial_year(self, quarter, start, end):
        """Q1 is Apr-Jun, and Q4 lands in the following calendar year."""
        period = resolve(kind="quarter", fy=2026, quarter=quarter)
        assert (period.start, period.end) == (start, end)

    def test_quarter_label_names_its_fy(self):
        assert resolve(kind="quarter", fy=2026, quarter=4).label == "Q4 FY 2026-27"

    @pytest.mark.parametrize("quarter", [0, 5, None])
    def test_invalid_quarter_is_rejected(self, quarter):
        with pytest.raises(PeriodError):
            resolve(kind="quarter", fy=2026, quarter=quarter)

    def test_month_period(self):
        period = resolve(kind="month", month="2026-02")
        assert (period.start, period.end) == ("2026-02-01", "2026-02-28")
        assert period.label == "Feb 2026"

    def test_month_period_handles_leap_february(self):
        assert resolve(kind="month", month="2024-02").end == "2024-02-29"

    @pytest.mark.parametrize("month", [None, "2026", "nonsense", "2026-13"])
    def test_bad_month_is_rejected(self, month):
        with pytest.raises(PeriodError):
            resolve(kind="month", month=month)

    def test_custom_period_accepts_non_iso_input(self):
        """The period picker should tolerate the same date forms invoices use."""
        period = resolve(kind="custom", start="01/04/2026", end="30/06/2026")
        assert (period.start, period.end) == ("2026-04-01", "2026-06-30")

    def test_custom_period_rejects_reversed_bounds(self):
        with pytest.raises(PeriodError, match="after its end"):
            resolve(kind="custom", start="2026-06-30", end="2026-04-01")

    def test_unknown_kind_is_rejected(self):
        with pytest.raises(PeriodError, match="Unknown period type"):
            resolve(kind="fortnight")


class TestMonthSequence:
    def test_covers_every_month_of_an_fy_in_order(self):
        months = month_sequence(resolve(kind="fy", fy=2026))
        assert len(months) == 12
        assert months[0] == "2026-04" and months[-1] == "2027-03"

    def test_crosses_the_year_boundary(self):
        months = month_sequence(resolve(kind="quarter", fy=2026, quarter=3))
        assert months == ["2026-10", "2026-11", "2026-12"]

    def test_single_month_period_yields_one_entry(self):
        assert month_sequence(resolve(kind="month", month="2026-08")) == ["2026-08"]
