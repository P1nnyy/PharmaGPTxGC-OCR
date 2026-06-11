import pytest
from extraction.normalizers.azure_invoice_normalizer import normalize_azure_invoice
from extraction.normalizers.canonical_invoice import CanonicalInvoice

def test_detect_item_table_by_headers():
    """Verify that the normalizer detects the correct table based on headers."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                # Irrelevant table
                "rowCount": 2,
                "columnCount": 2,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Terms"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Credit"},
                ]
            },
            {
                # Item table
                "rowCount": 2,
                "columnCount": 4,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Product Name"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Batch No"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "Amount"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "CROCIN"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "5"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "B123"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "100.00"},
                ]
            }
        ]
    }
    invoice = normalize_azure_invoice(raw_data)
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].name == "CROCIN"
    assert invoice.line_items[0].quantity == 5
    assert invoice.line_items[0].batch == "B123"
    assert invoice.line_items[0].amount == 100.00
    assert invoice.raw_engine_metadata["selected_item_table_index"] == 1

def test_extract_multiple_line_items():
    """Verify multiple rows extraction and filtering of summary rows."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                "rowCount": 4,
                "columnCount": 4,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Particulars"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Batch"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "Value"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "MED 1"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "2"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "BT1"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "50.00"},
                    {"rowIndex": 2, "columnIndex": 0, "content": "MED 2"},
                    {"rowIndex": 2, "columnIndex": 1, "content": "1"},
                    {"rowIndex": 2, "columnIndex": 2, "content": "BT2"},
                    {"rowIndex": 2, "columnIndex": 3, "content": "30.00"},
                    # Row 3 is a summary row inside the grid
                    {"rowIndex": 3, "columnIndex": 0, "content": "SUB TOTAL"},
                    {"rowIndex": 3, "columnIndex": 1, "content": ""},
                    {"rowIndex": 3, "columnIndex": 2, "content": ""},
                    {"rowIndex": 3, "columnIndex": 3, "content": "80.00"},
                ]
            }
        ]
    }
    invoice = normalize_azure_invoice(raw_data)
    assert len(invoice.line_items) == 2
    assert invoice.line_items[0].name == "MED 1"
    assert invoice.line_items[1].name == "MED 2"

def test_qty_correction_multiline():
    """Verify multiline quantity parsing returns the last numeric line."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                "rowCount": 2,
                "columnCount": 4,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Product"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Batch"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "Amount"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "ASPIRIN"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "1\n3"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "B-ASP"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "45.0"},
                ]
            }
        ]
    }
    invoice = normalize_azure_invoice(raw_data)
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].quantity == 3

def test_qty_correction_from_serial():
    """Verify quantity fallback from serial column when quantity is empty."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                "rowCount": 2,
                "columnCount": 4,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "S."},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Product"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Qty"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "Amount"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "3\n2"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "PARACETAMOL"},
                    {"rowIndex": 1, "columnIndex": 2, "content": ""},
                    {"rowIndex": 1, "columnIndex": 3, "content": "60"},
                ]
            }
        ]
    }
    invoice = normalize_azure_invoice(raw_data)
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].quantity == 2

def test_gst_percent_summation():
    """Verify combined GST calculation from SGST and CGST or IGST."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                "rowCount": 3,
                "columnCount": 6,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Product"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Amount"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "SGST"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "CGST"},
                    {"rowIndex": 0, "columnIndex": 4, "content": "IGST"},
                    {"rowIndex": 0, "columnIndex": 5, "content": "Qty"},
                    # SGST + CGST
                    {"rowIndex": 1, "columnIndex": 0, "content": "MED A"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "100.0"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "2.50"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "2.50"},
                    {"rowIndex": 1, "columnIndex": 4, "content": ""},
                    {"rowIndex": 1, "columnIndex": 5, "content": "1"},
                    # IGST only
                    {"rowIndex": 2, "columnIndex": 0, "content": "MED B"},
                    {"rowIndex": 2, "columnIndex": 1, "content": "200.0"},
                    {"rowIndex": 2, "columnIndex": 2, "content": ""},
                    {"rowIndex": 2, "columnIndex": 3, "content": ""},
                    {"rowIndex": 2, "columnIndex": 4, "content": "18.0"},
                    {"rowIndex": 2, "columnIndex": 5, "content": "2"},
                ]
            }
        ]
    }
    invoice = normalize_azure_invoice(raw_data)
    assert len(invoice.line_items) == 2
    assert invoice.line_items[0].gst_percent == 5.0
    assert invoice.line_items[1].gst_percent == 18.0

def test_footer_table_extraction():
    """Verify footer key-value extraction for totals."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                # Item table
                "rowCount": 2,
                "columnCount": 3,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Product"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Amount"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "STUFF"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "2"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "10.0"},
                ]
            },
            {
                # Footer table
                "rowCount": 5,
                "columnCount": 2,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "SUB TOTAL"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "100.00"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "Discount 5%"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "5.00"},
                    {"rowIndex": 2, "columnIndex": 0, "content": "SGST 2.5%"},
                    {"rowIndex": 2, "columnIndex": 1, "content": "2.50"},
                    {"rowIndex": 3, "columnIndex": 0, "content": "CGST 2.5%"},
                    {"rowIndex": 3, "columnIndex": 1, "content": "2.50"},
                    {"rowIndex": 4, "columnIndex": 0, "content": "GRAND TOTAL"},
                    {"rowIndex": 4, "columnIndex": 1, "content": "100.00"},
                ]
            }
        ]
    }
    invoice = normalize_azure_invoice(raw_data)
    assert invoice.subtotal == 100.00
    assert invoice.discount == 5.00
    assert invoice.sgst == 2.50
    assert invoice.cgst == 2.50
    assert invoice.grand_total == 100.00

def test_no_item_table_resilience():
    """Verify normalizer handles absence of valid item table gracefully."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": []
    }
    invoice = normalize_azure_invoice(raw_data)
    assert isinstance(invoice, CanonicalInvoice)
    assert len(invoice.line_items) == 0
    assert "No valid line item table found" in invoice.raw_engine_metadata["warnings"][0]

def test_confidence_grading():
    """Verify confidence rules (0.85, 0.65, 0.40)."""
    # 1. High confidence (Item table, items extracted, grand total found)
    high_raw = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                "rowCount": 2,
                "columnCount": 3,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Product"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Amount"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "A"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "1"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "100"},
                ]
            },
            {
                "rowCount": 1,
                "columnCount": 2,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "GRAND TOTAL"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "100"},
                ]
            }
        ]
    }
    high_inv = normalize_azure_invoice(high_raw)
    assert high_inv.confidence == 0.85

    # 2. Medium confidence (Header/totals found but line items missing)
    med_raw = {
        "modelId": "prebuilt-invoice",
        "documents": [
            {
                "fields": {
                    "InvoiceId": {"value": "INV-XYZ"}
                }
            }
        ],
        "tables": []
    }
    med_inv = normalize_azure_invoice(med_raw)
    assert med_inv.confidence == 0.65

    # 3. Low confidence (Neither line items nor header metadata found)
    low_raw = {
        "modelId": "prebuilt-invoice",
        "tables": []
    }
    low_inv = normalize_azure_invoice(low_raw)
    assert low_inv.confidence == 0.40
