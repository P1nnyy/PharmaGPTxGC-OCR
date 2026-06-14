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

def test_cm_associates_format():
    """Verify normalization of C M Associates invoice format with custom table headers, comma decimals, and horizontal summary parser."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "documents": [
            {
                "fields": {
                    "InvoiceId": {"value": "CMPKT-25-1033518"},
                    "VendorName": {"value": "C M ASSOCIATES PVT LTD"},
                    "CustomerName": {"value": "RAM CHAND & SONS"}
                }
            }
        ],
        "tables": [
            {
                # TABLE 2 - Horizontal summary footer table
                "rowCount": 4,
                "columnCount": 13,
                "cells": [
                    # Row 0 - Headers
                    {"rowIndex": 0, "columnIndex": 0, "content": "Particulars"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Pes"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Gros Ami"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "Sch Amt"},
                    {"rowIndex": 0, "columnIndex": 4, "content": "Oth Disc Amt"},
                    {"rowIndex": 0, "columnIndex": 5, "content": "Oth Disc Amt\nNon-Taxable"},
                    {"rowIndex": 0, "columnIndex": 6, "content": "Trashle Amt"},
                    {"rowIndex": 0, "columnIndex": 7, "content": "THE Amt"},
                    {"rowIndex": 0, "columnIndex": 8, "content": "Total Margin"},
                    {"rowIndex": 0, "columnIndex": 9, "content": "Margin %"},
                    {"rowIndex": 0, "columnIndex": 10, "content": "Net Amt"},
                    {"rowIndex": 0, "columnIndex": 11, "content": "Credit\nNate Ami"},
                    {"rowIndex": 0, "columnIndex": 12, "content": "Net Payable"},
                    
                    # Row 1 - CGST slab
                    {"rowIndex": 1, "columnIndex": 0, "content": "CGST 0,000 + SGST 0.000"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "22"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "990.88"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "0.00"},
                    {"rowIndex": 1, "columnIndex": 4, "content": "0,00"},
                    {"rowIndex": 1, "columnIndex": 5, "content": "0.00"},
                    {"rowIndex": 1, "columnIndex": 6, "content": "990.88"},
                    {"rowIndex": 1, "columnIndex": 7, "content": "0.00"},
                    
                    # Row 2 - GST slab
                    {"rowIndex": 2, "columnIndex": 0, "content": "OGST 2 500 - SGST 2.500"},
                    {"rowIndex": 2, "columnIndex": 1, "content": "17"},
                    {"rowIndex": 2, "columnIndex": 2, "content": "2180.20"},
                    {"rowIndex": 2, "columnIndex": 3, "content": "78.48"},
                    {"rowIndex": 2, "columnIndex": 4, "content": "0.00"},
                    {"rowIndex": 2, "columnIndex": 5, "content": "0.00"},
                    {"rowIndex": 2, "columnIndex": 6, "content": "2161.72"},
                    {"rowIndex": 2, "columnIndex": 7, "content": "105.06"},
                    
                    # Row 3 - Total row
                    {"rowIndex": 3, "columnIndex": 0, "content": "Total"},
                    {"rowIndex": 3, "columnIndex": 1, "content": "39"},
                    {"rowIndex": 3, "columnIndex": 2, "content": "3171.08"},
                    {"rowIndex": 3, "columnIndex": 3, "content": "78.48"},
                    {"rowIndex": 3, "columnIndex": 4, "content": "0.00"},
                    {"rowIndex": 3, "columnIndex": 5, "content": "0.00"},
                    {"rowIndex": 3, "columnIndex": 6, "content": "3092.60"},
                    {"rowIndex": 3, "columnIndex": 7, "content": "105.06"},
                    {"rowIndex": 3, "columnIndex": 8, "content": "743.00"},
                    {"rowIndex": 3, "columnIndex": 9, "content": "21.23"},
                    {"rowIndex": 3, "columnIndex": 10, "content": "3198.00"},
                    {"rowIndex": 3, "columnIndex": 11, "content": "0,00"},
                    {"rowIndex": 3, "columnIndex": 12, "content": "3198.00"},
                ]
            },
            {
                # TABLE 3 - Items table
                "rowCount": 4,
                "columnCount": 18,
                "cells": [
                    # Row 0 - Headers
                    {"rowIndex": 0, "columnIndex": 0, "content": "51"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "PCHde"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Tiem Description"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "HSN"},
                    {"rowIndex": 0, "columnIndex": 4, "content": "UFC"},
                    {"rowIndex": 0, "columnIndex": 5, "content": "MRP"},
                    {"rowIndex": 0, "columnIndex": 6, "content": "CH"},
                    {"rowIndex": 0, "columnIndex": 7, "content": "t'es"},
                    {"rowIndex": 0, "columnIndex": 8, "content": "Total\n0y"},
                    {"rowIndex": 0, "columnIndex": 9, "content": "Grass\nAmt"},
                    {"rowIndex": 0, "columnIndex": 10, "content": "SCH\nAmt"},
                    {"rowIndex": 0, "columnIndex": 11, "content": "Die %"},
                    {"rowIndex": 0, "columnIndex": 12, "content": "Dise\nAmt"},
                    {"rowIndex": 0, "columnIndex": 13, "content": "Taxable\nAmt"},
                    {"rowIndex": 0, "columnIndex": 14, "content": "OTT\n%"},
                    {"rowIndex": 0, "columnIndex": 15, "content": "HOWWY\nCIGET"},
                    {"rowIndex": 0, "columnIndex": 16, "content": "ØGET\nAmt"},
                    {"rowIndex": 0, "columnIndex": 17, "content": "Net Amt"},
                    
                    # Row 1
                    {"rowIndex": 1, "columnIndex": 0, "content": "1"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "50895798"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "OB CRISSCROSS GUM\nCARE B2G2 SFT"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "96032100"},
                    {"rowIndex": 1, "columnIndex": 4, "content": "36"},
                    {"rowIndex": 1, "columnIndex": 5, "content": "160.09"},
                    {"rowIndex": 1, "columnIndex": 6, "content": "0"},
                    {"rowIndex": 1, "columnIndex": 7, "content": "1"},
                    {"rowIndex": 1, "columnIndex": 8, "content": "1"},
                    {"rowIndex": 1, "columnIndex": 9, "content": "126.99"},
                    {"rowIndex": 1, "columnIndex": 10, "content": "0.00"},
                    {"rowIndex": 1, "columnIndex": 11, "content": "0.00"},
                    {"rowIndex": 1, "columnIndex": 12, "content": "0.00"},
                    {"rowIndex": 1, "columnIndex": 13, "content": "126,99"},
                    {"rowIndex": 1, "columnIndex": 14, "content": "5.00"},
                    {"rowIndex": 1, "columnIndex": 15, "content": "3.17"},
                    {"rowIndex": 1, "columnIndex": 16, "content": "3.17"},
                    {"rowIndex": 1, "columnIndex": 17, "content": "133.13"},
                    
                    # Row 2
                    {"rowIndex": 2, "columnIndex": 0, "content": "2"},
                    {"rowIndex": 2, "columnIndex": 1, "content": "80895637"},
                    {"rowIndex": 2, "columnIndex": 2, "content": "Vaporub 5gm RTM"},
                    {"rowIndex": 2, "columnIndex": 3, "content": "30049011"},
                    {"rowIndex": 2, "columnIndex": 4, "content": "54"},
                    {"rowIndex": 2, "columnIndex": 5, "content": "345.00"},
                    {"rowIndex": 2, "columnIndex": 6, "content": "0"},
                    {"rowIndex": 2, "columnIndex": 7, "content": "1"},
                    {"rowIndex": 2, "columnIndex": 8, "content": "1"},
                    {"rowIndex": 2, "columnIndex": 9, "content": "255,90"},
                    {"rowIndex": 2, "columnIndex": 10, "content": "8.96"},
                    {"rowIndex": 2, "columnIndex": 11, "content": "0.00"},
                    {"rowIndex": 2, "columnIndex": 12, "content": "0.00"},
                    {"rowIndex": 2, "columnIndex": 13, "content": "246.94"},
                    {"rowIndex": 2, "columnIndex": 14, "content": "5.00"},
                    {"rowIndex": 2, "columnIndex": 15, "content": "6.17"},
                    {"rowIndex": 2, "columnIndex": 16, "content": "6.17"},
                    {"rowIndex": 2, "columnIndex": 17, "content": "259.23"},
                    
                    # Row 3 - Total Row
                    {"rowIndex": 3, "columnIndex": 0, "content": ""},
                    {"rowIndex": 3, "columnIndex": 1, "content": ""},
                    {"rowIndex": 3, "columnIndex": 2, "content": "Total"},
                    {"rowIndex": 3, "columnIndex": 3, "content": ""},
                    {"rowIndex": 3, "columnIndex": 4, "content": ""},
                    {"rowIndex": 3, "columnIndex": 5, "content": ""},
                    {"rowIndex": 3, "columnIndex": 6, "content": "0"},
                    {"rowIndex": 3, "columnIndex": 7, "content": "39"},
                    {"rowIndex": 3, "columnIndex": 8, "content": "19"},
                    {"rowIndex": 3, "columnIndex": 9, "content": "3171.08"},
                    {"rowIndex": 3, "columnIndex": 10, "content": "78.48"},
                    {"rowIndex": 3, "columnIndex": 11, "content": ""},
                    {"rowIndex": 3, "columnIndex": 12, "content": "0.00"},
                    {"rowIndex": 3, "columnIndex": 13, "content": "3092.60"},
                    {"rowIndex": 3, "columnIndex": 14, "content": ""},
                    {"rowIndex": 3, "columnIndex": 15, "content": "52.53"},
                    {"rowIndex": 3, "columnIndex": 16, "content": "52 53"},
                    {"rowIndex": 3, "columnIndex": 17, "content": "3197,66"},
                ]
            }
        ]
    }
    
    invoice = normalize_azure_invoice(raw_data)
    
    # Assertions for item table extraction
    assert len(invoice.line_items) == 2
    
    # Row 1
    assert invoice.line_items[0].name == "OB CRISSCROSS GUM CARE B2G2 SFT"
    assert invoice.line_items[0].hsn == "96032100"
    assert invoice.line_items[0].pack == "36"
    assert invoice.line_items[0].mrp == 160.09
    assert invoice.line_items[0].quantity == 1 # from Total 0y
    assert invoice.line_items[0].discount == 0.0
    assert invoice.line_items[0].gst_percent == 5.0 # from OTT %
    assert invoice.line_items[0].amount == 133.13 # Net Amt
    
    # Row 2
    assert invoice.line_items[1].name == "Vaporub 5gm RTM"
    assert invoice.line_items[1].hsn == "30049011"
    assert invoice.line_items[1].pack == "54"
    assert invoice.line_items[1].mrp == 345.00
    assert invoice.line_items[1].quantity == 1
    assert invoice.line_items[1].discount == 8.96
    assert invoice.line_items[1].gst_percent == 5.0
    assert invoice.line_items[1].amount == 259.23 # Net Amt with comma cleaning fallback
    
    # Total row skipped
    # Verify summary Total row details
    assert invoice.subtotal == 3171.08 # Gros Ami
    assert invoice.discount == 78.48 # Sch Amt + Oth Disc Amt
    assert invoice.grand_total == 3198.00 # Net Payable
    
    # Verify tax details extracted from item table total row
    assert invoice.cgst == 52.53
    assert invoice.sgst == 52.53
    
    # Verify SGST is not 17.0 (from Pes column)
    assert invoice.sgst != 17.0

def test_mahajan_medical_agencies_format():
    """Verify normalization of Mahajan Medical Agencies format with multiple Value columns under tax slab headers."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                "rowCount": 3,
                "columnCount": 18,
                "cells": [
                    # Row 0 - Headers
                    {"rowIndex": 0, "columnIndex": 0, "content": "S."},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Qty."},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Free"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "Mfr"},
                    {"rowIndex": 0, "columnIndex": 4, "content": "Pack"},
                    {"rowIndex": 0, "columnIndex": 5, "content": "Product Name"},
                    {"rowIndex": 0, "columnIndex": 6, "content": ""},
                    {"rowIndex": 0, "columnIndex": 7, "content": "Batch"},
                    {"rowIndex": 0, "columnIndex": 8, "content": "Exp"},
                    {"rowIndex": 0, "columnIndex": 9, "content": "HSN"},
                    {"rowIndex": 0, "columnIndex": 10, "content": "M.R.P"},
                    {"rowIndex": 0, "columnIndex": 11, "content": "Rate"},
                    {"rowIndex": 0, "columnIndex": 12, "content": "Dis"},
                    {"rowIndex": 0, "columnIndex": 13, "content": "SGST"},
                    {"rowIndex": 0, "columnIndex": 14, "content": "Value"},
                    {"rowIndex": 0, "columnIndex": 15, "content": "CGST"},
                    {"rowIndex": 0, "columnIndex": 16, "content": "Value"},
                    {"rowIndex": 0, "columnIndex": 17, "content": "Amount"},

                    # Row 1 - ROSULIP
                    {"rowIndex": 1, "columnIndex": 0, "content": "1"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "2"},
                    {"rowIndex": 1, "columnIndex": 2, "content": ""},
                    {"rowIndex": 1, "columnIndex": 3, "content": "CIPL"},
                    {"rowIndex": 1, "columnIndex": 4, "content": "1×10"},
                    {"rowIndex": 1, "columnIndex": 5, "content": "ROSULIP 20 TABS"},
                    {"rowIndex": 1, "columnIndex": 6, "content": ""},
                    {"rowIndex": 1, "columnIndex": 7, "content": ""},
                    {"rowIndex": 1, "columnIndex": 8, "content": "7/27\n/28"},
                    {"rowIndex": 1, "columnIndex": 9, "content": "30049099"},
                    {"rowIndex": 1, "columnIndex": 10, "content": "320.83"},
                    {"rowIndex": 1, "columnIndex": 11, "content": "244.44"},
                    {"rowIndex": 1, "columnIndex": 12, "content": "|0.00"},
                    {"rowIndex": 1, "columnIndex": 13, "content": "2.50"},
                    {"rowIndex": 1, "columnIndex": 14, "content": "11.49"},
                    {"rowIndex": 1, "columnIndex": 15, "content": "2.50"},
                    {"rowIndex": 1, "columnIndex": 16, "content": "11.49"},
                    {"rowIndex": 1, "columnIndex": 17, "content": "488.88"},

                    # Row 2 - METOLAR
                    {"rowIndex": 2, "columnIndex": 0, "content": "2"},
                    {"rowIndex": 2, "columnIndex": 1, "content": "3"},
                    {"rowIndex": 2, "columnIndex": 2, "content": ""},
                    {"rowIndex": 2, "columnIndex": 3, "content": "CIPL"},
                    {"rowIndex": 2, "columnIndex": 4, "content": "1X15"},
                    {"rowIndex": 2, "columnIndex": 5, "content": "METOLAR 25 TABS"},
                    {"rowIndex": 2, "columnIndex": 6, "content": ""},
                    {"rowIndex": 2, "columnIndex": 7, "content": "55A0346"},
                    {"rowIndex": 2, "columnIndex": 8, "content": ""},
                    {"rowIndex": 2, "columnIndex": 9, "content": "30049074"},
                    {"rowIndex": 2, "columnIndex": 10, "content": "42.63"},
                    {"rowIndex": 2, "columnIndex": 11, "content": "32.48"},
                    {"rowIndex": 2, "columnIndex": 12, "content": "0.00"},
                    {"rowIndex": 2, "columnIndex": 13, "content": "2.50"},
                    {"rowIndex": 2, "columnIndex": 14, "content": "2.29"},
                    {"rowIndex": 2, "columnIndex": 15, "content": "2.50"},
                    {"rowIndex": 2, "columnIndex": 16, "content": "2.29"},
                    {"rowIndex": 2, "columnIndex": 17, "content": "97.44"},
                ]
            }
        ]
    }
    
    invoice = normalize_azure_invoice(raw_data)
    assert len(invoice.line_items) == 2

    # Assertions for ROSULIP
    item1 = invoice.line_items[0]
    assert item1.name == "ROSULIP 20 TABS"
    assert item1.quantity == 2
    assert item1.free_quantity is None
    assert item1.hsn == "30049099"
    assert item1.mrp == 320.83
    assert item1.rate == 244.44
    assert item1.discount == 0.0
    assert item1.gst_percent == 5.0
    assert item1.amount == 488.88

    # Assertions for METOLAR
    item2 = invoice.line_items[1]
    assert item2.name == "METOLAR 25 TABS"
    assert item2.quantity == 3
    assert item2.batch == "55A0346"
    assert item2.mrp == 42.63
    assert item2.rate == 32.48
    assert item2.amount == 97.44

