import pytest

from core.dates import (
    financial_year_bounds,
    financial_year_of,
    normalize_expiry,
    normalize_invoice_date,
)


class TestNormalizeInvoiceDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-08-03", "2026-08-03"),
            ("2026-8-3", "2026-08-03"),
            ("2026-08-03T00:00:00", "2026-08-03"),
            ("2026/08/03", "2026-08-03"),
        ],
    )
    def test_iso_and_year_first_forms(self, raw, expected):
        assert normalize_invoice_date(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("03/08/2026", "2026-08-03"),
            ("03-08-2026", "2026-08-03"),
            ("03.08.2026", "2026-08-03"),
            ("3-8-26", "2026-08-03"),
        ],
    )
    def test_day_first_is_the_default(self, raw, expected):
        """Indian invoices print DD/MM. The ambiguous case must resolve that way."""
        assert normalize_invoice_date(raw) == expected

    def test_unambiguous_day_wins_over_default(self):
        assert normalize_invoice_date("13/08/2026") == "2026-08-13"

    def test_unambiguous_month_position_overrides_default(self):
        """08/13 cannot be DD/MM, so it must be read as MM/DD despite the default."""
        assert normalize_invoice_date("08/13/2026") == "2026-08-13"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("3 Aug 2026", "2026-08-03"),
            ("3rd Aug 2026", "2026-08-03"),
            ("03 August 2026", "2026-08-03"),
            ("Aug 3, 2026", "2026-08-03"),
            ("AUG 3 2026", "2026-08-03"),
        ],
    )
    def test_textual_months(self, raw, expected):
        assert normalize_invoice_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "garbage", "not/a/date", "99/99/9999"])
    def test_unreadable_values_return_none(self, raw):
        """None, never a fallback. A guessed date lands the invoice in the wrong
        month; a missing one shows up in the data-quality report."""
        assert normalize_invoice_date(raw) is None

    def test_impossible_calendar_date_is_rejected(self):
        assert normalize_invoice_date("29/02/2025") is None

    def test_valid_leap_day_is_accepted(self):
        assert normalize_invoice_date("29/02/2024") == "2024-02-29"

    def test_two_digit_year_pivots_to_this_century(self):
        assert normalize_invoice_date("03/08/26") == "2026-08-03"


class TestNormalizeExpiry:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("08/26", "2026-08-31"),
            ("11/2026", "2026-11-30"),
            ("2/26", "2026-02-28"),
            ("02/2024", "2024-02-29"),
            ("12/26", "2026-12-31"),
        ],
    )
    def test_month_precision_resolves_to_month_end(self, raw, expected):
        """"08/26" on a strip means good through August. Resolving to the 1st
        would write the stock off a month early."""
        assert normalize_expiry(raw) == expected

    @pytest.mark.parametrize("raw,expected", [("Aug 2026", "2026-08-31"), ("AUG-26", "2026-08-31")])
    def test_textual_month_year(self, raw, expected):
        assert normalize_expiry(raw) == expected

    def test_a_year_leading_form_is_read_as_year_month(self):
        assert normalize_expiry("2026/08") == "2026-08-31"

    @pytest.mark.parametrize("raw,expected", [("2026-08-15", "2026-08-15"), ("15/08/2026", "2026-08-15")])
    def test_full_dates_are_kept_precise(self, raw, expected):
        """When the supplier printed a day, don't round it out to month end."""
        assert normalize_expiry(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "13/26", "nonsense"])
    def test_unreadable_values_return_none(self, raw):
        assert normalize_expiry(raw) is None


class TestFinancialYear:
    def test_bounds_run_april_to_march(self):
        assert financial_year_bounds(2026) == ("2026-04-01", "2027-03-31")

    @pytest.mark.parametrize(
        "iso,expected",
        [
            ("2026-04-01", 2026),
            ("2027-03-31", 2026),
            ("2026-03-31", 2025),
            ("2026-12-31", 2026),
        ],
    )
    def test_fy_of_a_date(self, iso, expected):
        assert financial_year_of(iso) == expected

    def test_march_and_april_fall_in_different_years(self):
        """The FY boundary is the one date bug that silently misfiles a quarter."""
        assert financial_year_of("2026-03-31") != financial_year_of("2026-04-01")
