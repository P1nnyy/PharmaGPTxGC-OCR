"""Tax periods: the MMYYYY strings a return is filed for.

Which period a sale lands in decides which return it is reported in, so these
are pinned by test even though no arithmetic happens here. The financial year
runs April to March, and GST quarters follow it rather than the calendar.
"""

import pytest

from core.tax_periods import (
    PeriodError,
    financial_year_of_period,
    is_valid_period,
    months_in_quarter,
    period_bounds,
    period_label,
    period_of,
    quarter_of_period,
)


class TestPeriodOf:
    def test_reads_an_iso_date_into_mmyyyy(self):
        assert period_of("2026-09-10") == "092026"

    def test_pads_a_single_digit_month(self):
        assert period_of("2026-04-01") == "042026"

    def test_refuses_an_unreadable_date(self):
        with pytest.raises(PeriodError):
            period_of("not-a-date")
        with pytest.raises(PeriodError):
            period_of(None)


class TestIsValidPeriod:
    @pytest.mark.parametrize("period", ["012026", "092026", "122026"])
    def test_accepts_a_real_month(self, period):
        assert is_valid_period(period)

    @pytest.mark.parametrize(
        "period", ["132026", "002026", "9-2026", "2026-09", "092026x", "", None, "92026"]
    )
    def test_refuses_anything_else(self, period):
        # "92026" is refused rather than read as September: an unpadded month
        # is ambiguous against a two-digit year and guessing would file a
        # return into the wrong month.
        assert not is_valid_period(period)


class TestPeriodBounds:
    def test_covers_the_whole_month(self):
        assert period_bounds("092026") == ("2026-09-01", "2026-09-30")

    def test_handles_february_in_a_leap_year(self):
        assert period_bounds("022028") == ("2028-02-01", "2028-02-29")

    def test_handles_february_in_a_common_year(self):
        assert period_bounds("022026") == ("2026-02-01", "2026-02-28")

    def test_refuses_an_invalid_period(self):
        with pytest.raises(PeriodError):
            period_bounds("132026")


class TestFinancialYear:
    def test_april_starts_the_financial_year(self):
        assert financial_year_of_period("042026") == 2026

    def test_march_belongs_to_the_year_before(self):
        assert financial_year_of_period("032026") == 2025

    def test_january_belongs_to_the_year_before(self):
        assert financial_year_of_period("012026") == 2025


class TestQuarters:
    @pytest.mark.parametrize(
        "period,expected",
        [
            ("042026", (2026, 1)),
            ("062026", (2026, 1)),
            ("072026", (2026, 2)),
            ("102026", (2026, 3)),
            ("012027", (2026, 4)),
            ("032027", (2026, 4)),
        ],
    )
    def test_quarters_follow_the_financial_year(self, period, expected):
        assert quarter_of_period(period) == expected

    def test_lists_the_months_of_a_quarter(self):
        assert months_in_quarter(2026, 1) == ["042026", "052026", "062026"]

    def test_q4_crosses_the_calendar_year(self):
        assert months_in_quarter(2026, 4) == ["012027", "022027", "032027"]

    def test_refuses_an_impossible_quarter(self):
        with pytest.raises(PeriodError):
            months_in_quarter(2026, 5)


class TestPeriodLabel:
    def test_reads_as_a_person_would_say_it(self):
        assert period_label("092026") == "Sep 2026"
