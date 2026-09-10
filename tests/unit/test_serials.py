"""Rule 46(b) invoice serials.

A serial is what a filed return identifies a bill by, so the rules are not
cosmetic: consecutive, unique within a financial year, at most sixteen
characters, and only alphanumerics plus `-` and `/`.

These mirror `frontend/src/features/sell/serial.ts` deliberately. A serial
formatted on a device and the same serial validated on the server must agree
about what it is, or a bill issued offline would be rejected when it syncs.
"""

import pytest

from core.serials import (
    SerialError,
    financial_year_of,
    format_serial,
    is_valid_serial,
    parse_serial,
    series_key,
)


class TestValidity:
    @pytest.mark.parametrize("serial", ["A1", "CTR-000001", "2026/27-0001", "ABCDEFGHIJKLMNOP"])
    def test_accepts_a_rule_46b_serial(self, serial):
        assert is_valid_serial(serial)

    @pytest.mark.parametrize(
        "serial",
        [
            "",
            "A" * 17,          # over sixteen characters
            "CTR 000001",      # space
            "CTR_000001",      # underscore
            "CTR#1",           # punctuation
            "CTR.1",
            None,
        ],
    )
    def test_refuses_anything_else(self, serial):
        assert not is_valid_serial(serial)


class TestFormatting:
    def test_pads_the_sequence(self):
        assert format_serial("CTR-", 42, 6) == "CTR-000042"

    def test_refuses_a_serial_that_would_exceed_sixteen_characters(self):
        # The guard has to fire when the block is allocated, not when the
        # bill is issued: a device that has already sold cannot be told its
        # serial is too long.
        with pytest.raises(SerialError):
            format_serial("A-VERY-LONG-PREFIX-", 1, 6)

    def test_refuses_a_prefix_with_illegal_characters(self):
        with pytest.raises(SerialError):
            format_serial("CTR_", 1, 6)


class TestParsing:
    def test_splits_a_serial_into_prefix_and_sequence(self):
        assert parse_serial("CTR-000042") == ("CTR-", 42)

    def test_handles_a_bare_numeric_serial(self):
        assert parse_serial("000042") == ("", 42)

    def test_refuses_a_serial_with_no_trailing_number(self):
        with pytest.raises(SerialError):
            parse_serial("CTR-ABC")


class TestFinancialYear:
    def test_april_starts_the_year(self):
        assert financial_year_of("2026-04-01") == 2026

    def test_march_belongs_to_the_year_before(self):
        assert financial_year_of("2026-03-31") == 2025


class TestSeriesKey:
    def test_is_unique_per_workspace_series_and_year(self):
        a = series_key("ph-1", "CTR-", 2026)
        assert a != series_key("ph-2", "CTR-", 2026)
        assert a != series_key("ph-1", "CTR2-", 2026)
        # Serials are unique *within* a financial year, so the counter resets
        # each year and the key has to carry it.
        assert a != series_key("ph-1", "CTR-", 2027)

    def test_is_stable(self):
        assert series_key("ph-1", "CTR-", 2026) == series_key("ph-1", "CTR-", 2026)
