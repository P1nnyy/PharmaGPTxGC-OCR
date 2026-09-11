"""Statutory due dates, and the three-year bar.

Every date here is fixed by law rather than by us, so each one is pinned. A
wrong due date does not fail loudly — it produces a calendar that looks right
and files a return late, and the shop finds out through a late fee.

The QRMP cases get the most attention because that is where a calendar built on
monthly dates and then adjusted goes wrong: a QRMP filer's obligations are not
the monthly ones moved, they are *different obligations* in different months.
"""

from datetime import date

import pytest

from core.gst_calendar import (
    GSTR1,
    GSTR2B,
    GSTR3B,
    IFF,
    PMT06,
    TIME_BAR_YEARS,
    financial_year_months,
    financial_year_of,
    obligations_for_financial_year,
    obligations_for_month,
    position_in_quarter,
    qrmp_3b_day,
    quarter_of_month,
)


def kinds(obligations) -> dict:
    return {o.kind: o for o in obligations}


class TestMonthlyFiler:
    def test_gstr1_is_due_on_the_eleventh_of_the_next_month(self):
        due = kinds(obligations_for_month("092026", "MONTHLY"))[GSTR1].due_date
        assert due == date(2026, 10, 11)

    def test_gstr3b_is_due_on_the_twentieth(self):
        due = kinds(obligations_for_month("092026", "MONTHLY"))[GSTR3B].due_date
        assert due == date(2026, 10, 20)

    def test_gstr2b_arrives_on_the_fourteenth_and_is_not_a_filing(self):
        # It is generated for you. Missing it is not an offence, so it must not
        # be counted as something that falls due.
        block = kinds(obligations_for_month("092026", "MONTHLY"))[GSTR2B]
        assert block.due_date == date(2026, 10, 14)
        assert block.is_filing is False
        assert block.barred_on is None

    def test_a_december_period_rolls_into_the_next_year(self):
        due = kinds(obligations_for_month("122026", "MONTHLY"))[GSTR1].due_date
        assert due == date(2027, 1, 11)

    def test_a_monthly_filer_has_no_pmt06_or_iff(self):
        found = kinds(obligations_for_month("092026", "MONTHLY"))
        assert PMT06 not in found and IFF not in found

    def test_each_month_covers_only_itself(self):
        obligation = kinds(obligations_for_month("092026", "MONTHLY"))[GSTR1]
        assert obligation.covers_months == ("092026",)


class TestQrmpFiler:
    def test_the_first_two_months_carry_a_payment_not_a_return(self):
        for period in ("072026", "082026"):
            found = kinds(obligations_for_month(period, "QUARTERLY", "27"))
            assert set(found) == {PMT06, IFF}
            assert GSTR1 not in found and GSTR3B not in found

    def test_pmt06_is_due_on_the_twenty_fifth(self):
        due = kinds(obligations_for_month("072026", "QUARTERLY", "27"))[PMT06].due_date
        assert due == date(2026, 8, 25)

    def test_iff_is_optional(self):
        iff = kinds(obligations_for_month("072026", "QUARTERLY", "27"))[IFF]
        assert iff.is_optional is True
        assert iff.due_date == date(2026, 8, 13)

    def test_the_quarters_last_month_carries_both_returns(self):
        found = kinds(obligations_for_month("092026", "QUARTERLY", "27"))
        assert set(found) == {GSTR1, GSTR2B, GSTR3B}

    def test_quarterly_gstr1_is_due_on_the_thirteenth(self):
        due = kinds(obligations_for_month("092026", "QUARTERLY", "27"))[GSTR1].due_date
        assert due == date(2026, 10, 13)

    def test_a_quarterly_return_covers_all_three_months(self):
        obligation = kinds(obligations_for_month("092026", "QUARTERLY", "27"))[GSTR1]
        assert obligation.covers_months == ("072026", "082026", "092026")

    def test_gstr2b_is_quarterly_for_a_qrmp_shop(self):
        # One statement for the quarter, not one a month.
        block = kinds(obligations_for_month("092026", "QUARTERLY", "27"))[GSTR2B]
        assert block.covers_months == ("072026", "082026", "092026")

    def test_a_quarter_spanning_the_calendar_year_still_groups_correctly(self):
        obligation = kinds(obligations_for_month("032027", "QUARTERLY", "27"))[GSTR1]
        assert obligation.covers_months == ("012027", "022027", "032027")
        assert obligation.due_date == date(2027, 4, 13)


class TestQrmp3bStateGroups:
    def test_group_x_states_file_on_the_twenty_second(self):
        for state in ("27", "33", "29", "24", "36"):  # MH, TN, KA, GJ, TS
            assert qrmp_3b_day(state) == 22

    def test_group_y_states_file_on_the_twenty_fourth(self):
        for state in ("07", "09", "19", "03", "08"):  # DL, UP, WB, PB, RJ
            assert qrmp_3b_day(state) == 24

    def test_the_due_date_follows_the_state(self):
        maharashtra = kinds(obligations_for_month("092026", "QUARTERLY", "27"))[GSTR3B]
        delhi = kinds(obligations_for_month("092026", "QUARTERLY", "07"))[GSTR3B]
        assert maharashtra.due_date == date(2026, 10, 22)
        assert delhi.due_date == date(2026, 10, 24)

    def test_an_unknown_state_gets_the_earlier_date(self):
        # Telling a shop it has until the 24th when the real date was the 22nd
        # creates a late filing. The reverse costs two days of float.
        assert qrmp_3b_day(None) == 22
        assert qrmp_3b_day("") == 22
        assert qrmp_3b_day("99") == 22


class TestThreeYearBar:
    def test_a_return_is_barred_three_years_after_its_due_date(self):
        obligation = kinds(obligations_for_month("092026", "MONTHLY"))[GSTR1]
        assert obligation.due_date == date(2026, 10, 11)
        assert obligation.barred_on == date(2029, 10, 11)
        assert TIME_BAR_YEARS == 3

    def test_a_period_past_the_bar_reports_itself_as_barred(self):
        obligation = kinds(obligations_for_month("042022", "MONTHLY"))[GSTR1]
        assert obligation.is_time_barred(date(2026, 9, 11)) is True

    def test_a_period_inside_the_bar_is_not(self):
        obligation = kinds(obligations_for_month("092026", "MONTHLY"))[GSTR1]
        assert obligation.is_time_barred(date(2026, 9, 11)) is False

    def test_days_until_barred_counts_down(self):
        obligation = kinds(obligations_for_month("082023", "MONTHLY"))[GSTR3B]
        # Due 2023-09-20, barred 2026-09-20.
        assert obligation.days_until_barred(date(2026, 9, 11)) == 9

    def test_a_statement_that_is_never_filed_has_no_bar(self):
        block = kinds(obligations_for_month("092026", "MONTHLY"))[GSTR2B]
        assert block.barred_on is None
        assert block.days_until_barred(date(2026, 9, 11)) is None


class TestFinancialYear:
    def test_runs_april_to_march(self):
        months = financial_year_months(2026)
        assert months[0] == "042026"
        assert months[-1] == "032027"
        assert len(months) == 12

    def test_a_date_before_april_belongs_to_the_previous_year(self):
        assert financial_year_of(date(2027, 3, 31)) == 2026
        assert financial_year_of(date(2027, 4, 1)) == 2027

    def test_quarters_follow_the_financial_year(self):
        assert quarter_of_month(4) == 1   # April is Q1
        assert quarter_of_month(3) == 4   # March is Q4

    def test_position_in_quarter_identifies_the_payment_months(self):
        assert position_in_quarter(4) == 1
        assert position_in_quarter(5) == 2
        assert position_in_quarter(6) == 3

    def test_a_monthly_year_has_three_obligations_a_month(self):
        assert len(obligations_for_financial_year(2026, "MONTHLY")) == 36

    def test_a_qrmp_year_is_payments_plus_four_quarter_ends(self):
        # Eight payment months carrying PMT-06 and IFF, four quarter ends
        # carrying GSTR-1, 2B and 3B.
        every = obligations_for_financial_year(2026, "QUARTERLY", "27")
        assert len(every) == 8 * 2 + 4 * 3

    def test_the_year_comes_back_in_due_date_order(self):
        every = obligations_for_financial_year(2026, "MONTHLY")
        assert [o.due_date for o in every] == sorted(o.due_date for o in every)

    def test_frequency_is_never_assumed(self):
        monthly = obligations_for_financial_year(2026, "MONTHLY")
        quarterly = obligations_for_financial_year(2026, "QUARTERLY", "27")
        assert len(monthly) != len(quarterly)
        assert sum(1 for o in monthly if o.kind == GSTR1) == 12
        assert sum(1 for o in quarterly if o.kind == GSTR1) == 4
