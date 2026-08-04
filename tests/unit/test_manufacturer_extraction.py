"""Reading the maker from the invoice's own Mfr/Company column.

Why this matters more than the online lookup
--------------------------------------------
Public drug listings only help for products they actually carry, and the match
has to clear a confidence bar to be trusted. A regional or house-brand item -
which is much of an Indian distributor's book - matches nothing, so the
listing route leaves the field permanently blank.

The supplier, meanwhile, printed the maker on the bill. Every invoice format
in this system carries it: "Mfr" on Enn Pee and Gurkirat, "Company Name" on
Arora Bros. That is a direct statement from the party selling the goods, so it
is read as evidence and offered for confirmation like any other parsed field.
"""

import pytest

from extraction.normalizers.azure_invoice_normalizer import (
    _clean_manufacturer,
    normalize_azure_invoice,
    normalize_header,
)


@pytest.mark.parametrize(
    "header",
    ["Mfr", "MFR", "mfr.", "Mfg", "Manufacturer", "Company", "Company Name", "Marketed By"],
)
def test_manufacturer_column_headers_are_recognised(header):
    assert normalize_header(header) == "manufacturer"


def test_multiline_company_header_is_recognised():
    """Arora Bros prints it as two stacked lines in one cell."""
    assert normalize_header("COMPANY\nNAME") == "manufacturer"


# --------------------------------------------------------------------------
# Cleaning the cell
# --------------------------------------------------------------------------

def test_maker_code_is_normalised_to_upper():
    assert _clean_manufacturer("  intas  ") == "INTAS"


def test_neighbouring_column_spillover_is_trimmed():
    """Observed on the Sunshade line: the pack size "(50" from the product
    name ran into the company cell, giving "(50LEEFORD"."""
    assert _clean_manufacturer("(50LEEFORD") == "LEEFORD"


def test_company_starting_with_a_digit_is_not_truncated():
    """Guards the spillover trim: 3M is a real manufacturer, and stripping its
    leading digit would leave a single letter."""
    assert _clean_manufacturer("3M") == "3M"


def test_only_this_rows_line_is_taken():
    """A merged cell can pick up the row below; the maker for this row is the
    one printed on it."""
    assert _clean_manufacturer("ALLI\nALGE") == "ALLI"


def test_purely_numeric_cell_is_rejected():
    """A bare number is a figure from an adjacent column, not a company."""
    assert _clean_manufacturer("12345") is None


def test_overlong_text_is_rejected():
    """A whole sentence means the column swallowed something else; storing it
    would put prose on a field a pharmacist reads as the maker."""
    long_text = "Goods once sold will not be taken back or exchanged under any circumstances"
    assert _clean_manufacturer(long_text) is None


def test_blank_cell_yields_nothing():
    assert _clean_manufacturer("") is None
    assert _clean_manufacturer(None) is None


# --------------------------------------------------------------------------
# End to end through the normalizer
# --------------------------------------------------------------------------

def _invoice_with_company_column(company_value: str):
    cells = [
        {"rowIndex": 0, "columnIndex": 0, "content": "ITEM NAME"},
        {"rowIndex": 0, "columnIndex": 1, "content": "COMPANY\nNAME"},
        {"rowIndex": 0, "columnIndex": 2, "content": "BATCH"},
        {"rowIndex": 0, "columnIndex": 3, "content": "QTY"},
        {"rowIndex": 0, "columnIndex": 4, "content": "AMOUNT"},
        {"rowIndex": 1, "columnIndex": 0, "content": "SUNSHADE ULTRA BLOCK LT-50"},
        {"rowIndex": 1, "columnIndex": 1, "content": company_value},
        {"rowIndex": 1, "columnIndex": 2, "content": "BLFB6004"},
        {"rowIndex": 1, "columnIndex": 3, "content": "1"},
        {"rowIndex": 1, "columnIndex": 4, "content": "260.00"},
    ]
    return {
        "modelId": "prebuilt-invoice",
        "documents": [],
        "tables": [{"rowCount": 2, "columnCount": 5, "cells": cells}],
    }


def test_manufacturer_reaches_the_line_item():
    invoice = normalize_azure_invoice(_invoice_with_company_column("LEEFORD"))
    assert invoice.line_items[0].manufacturer == "LEEFORD"


def test_spillover_cleaned_end_to_end():
    invoice = normalize_azure_invoice(_invoice_with_company_column("(50LEEFORD"))
    assert invoice.line_items[0].manufacturer == "LEEFORD"


def test_invoice_without_a_company_column_leaves_it_unset():
    """Formats that don't name the maker must not invent one."""
    cells = [
        {"rowIndex": 0, "columnIndex": 0, "content": "Product Name"},
        {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
        {"rowIndex": 0, "columnIndex": 2, "content": "Amount"},
        {"rowIndex": 1, "columnIndex": 0, "content": "ALPHA TAB"},
        {"rowIndex": 1, "columnIndex": 1, "content": "2"},
        {"rowIndex": 1, "columnIndex": 2, "content": "100.00"},
    ]
    raw = {"modelId": "prebuilt-invoice", "documents": [], "tables": [{"rowCount": 2, "columnCount": 3, "cells": cells}]}
    invoice = normalize_azure_invoice(raw)
    assert invoice.line_items[0].manufacturer is None
