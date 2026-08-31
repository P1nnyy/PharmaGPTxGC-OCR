import pytest
from extraction.normalizers.azure_invoice_normalizer import (
    is_discount_label,
    resolve_gstin_owners,
    _strip_border_artifacts,
    _footer_pairs,
    _is_quantity_total_label,
    score_footer_table,
    _footer_label_and_value,
    normalize_azure_invoice,
    normalize_header,
    parse_split_quantity,
)
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

def test_footer_discount_alias_dis_amt_extraction():
    """Verify footer discount aliases like DIS AMT hydrate invoice.discount."""
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
                    {"rowIndex": 1, "columnIndex": 0, "content": "RAMA MED"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "1"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "RM1"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "100.00"},
                ],
            },
            {
                "rowCount": 4,
                "columnCount": 2,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "SUB TOTAL"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "100.00"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "DIS AMT"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "5.50"},
                    {"rowIndex": 2, "columnIndex": 0, "content": "SGST"},
                    {"rowIndex": 2, "columnIndex": 1, "content": "2.75"},
                    {"rowIndex": 3, "columnIndex": 0, "content": "GRAND TOTAL"},
                    {"rowIndex": 3, "columnIndex": 1, "content": "100.00"},
                ],
            },
        ],
    }

    invoice = normalize_azure_invoice(raw_data)
    assert invoice.subtotal == 100.0
    assert invoice.discount == 5.5
    assert invoice.sgst == 2.75
    assert invoice.grand_total == 100.0

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

def test_split_quantity_parsing():
    """Verify that billed quantity and free quantity columns are mapped and parsed separately (with decimal and noise support)."""
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                "rowCount": 3,
                "columnCount": 6,
                "cells": [
                    # Row 0 - Headers
                    {"rowIndex": 0, "columnIndex": 0, "content": "Product Name"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Sale Qty"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Free Qty"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "Total Qty"},
                    {"rowIndex": 0, "columnIndex": 4, "content": "Rate"},
                    {"rowIndex": 0, "columnIndex": 5, "content": "Amount"},

                    # Row 1 - MEDICINE A (Split Quantity)
                    {"rowIndex": 1, "columnIndex": 0, "content": "MEDICINE A"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "5.50"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "0.50"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "6,00"},
                    {"rowIndex": 1, "columnIndex": 4, "content": "100.00"},
                    {"rowIndex": 1, "columnIndex": 5, "content": "550.00"},

                    # Row 2 - MEDICINE B (Billed Quantity only)
                    {"rowIndex": 2, "columnIndex": 0, "content": "MEDICINE B"},
                    {"rowIndex": 2, "columnIndex": 1, "content": "10"},
                    {"rowIndex": 2, "columnIndex": 2, "content": ""},
                    {"rowIndex": 2, "columnIndex": 3, "content": "10"},
                    {"rowIndex": 2, "columnIndex": 4, "content": "20.00"},
                    {"rowIndex": 2, "columnIndex": 5, "content": "200.00"},
                ]
            }
        ]
    }
    invoice = normalize_azure_invoice(raw_data)
    assert len(invoice.line_items) == 2

    # MED A
    item1 = invoice.line_items[0]
    assert item1.name == "MEDICINE A"
    assert item1.quantity == 5.5
    assert item1.free_quantity == 0.5
    assert item1.amount == 550.0

    # MED B
    item2 = invoice.line_items[1]
    assert item2.name == "MEDICINE B"
    assert item2.quantity == 10
    assert item2.free_quantity is None
    assert item2.amount == 200.0

@pytest.mark.parametrize(
    ("raw_value", "expected_quantity", "expected_free_quantity"),
    [
        ("5.50 + 0.50", 5.5, 0.5),
        ("2+.5", 2.0, 0.5),
        ("5,50 + 0,50", 5.5, 0.5),
        ("2\n+\n1", 2.0, 1.0),
        ("2.75\n+ .25", 2.75, 0.25),
    ],
)
def test_parse_split_quantity_helper(raw_value, expected_quantity, expected_free_quantity):
    parsed = parse_split_quantity(raw_value)
    assert parsed == {
        "quantity": expected_quantity,
        "free_quantity": expected_free_quantity,
    }


def test_parse_split_quantity_helper_does_not_split_plain_decimal():
    assert parse_split_quantity("2.75") is None


def test_same_cell_split_quantity_is_parsed_into_billed_and_free_quantity():
    raw_data = {
        "modelId": "prebuilt-invoice",
        "tables": [
            {
                "rowCount": 2,
                "columnCount": 8,
                "cells": [
                    # Row 0 - Headers
                    {"rowIndex": 0, "columnIndex": 0, "content": "S."},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Qty."},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Product Name"},
                    {"rowIndex": 0, "columnIndex": 3, "content": "Batch"},
                    {"rowIndex": 0, "columnIndex": 4, "content": "HSN"},
                    {"rowIndex": 0, "columnIndex": 5, "content": "M.R.P"},
                    {"rowIndex": 0, "columnIndex": 6, "content": "Rate"},
                    {"rowIndex": 0, "columnIndex": 7, "content": "Amount"},

                    # Row 1 - Same-cell split quantity
                    {"rowIndex": 1, "columnIndex": 0, "content": "1"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "2.75 + .25"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "ARBITEL AM"},
                    {"rowIndex": 1, "columnIndex": 3, "content": "ARHS0076"},
                    {"rowIndex": 1, "columnIndex": 4, "content": "30049079"},
                    {"rowIndex": 1, "columnIndex": 5, "content": "262.50"},
                    {"rowIndex": 1, "columnIndex": 6, "content": "200.00"},
                    {"rowIndex": 1, "columnIndex": 7, "content": "550.06"},
                ],
            }
        ],
    }

    invoice = normalize_azure_invoice(raw_data)
    assert len(invoice.line_items) == 1

    item = invoice.line_items[0]
    assert item.name == "ARBITEL AM"
    assert item.quantity == 2.75
    assert item.free_quantity == 0.25
    assert item.quantity + item.free_quantity == 3.0
    assert item.amount == 550.06
    assert item.amount != item.rate * (item.quantity + item.free_quantity)
    assert item.hsn == "30049079"
    assert item.batch == "ARHS0076"


# ==========================================================================
# Vertically offset columns
#
# From a real invoice (ENN PEE MEDICOS, A002111) where the Batch column is
# typeset about half a row below its neighbours. Azure files each cell by
# vertical position, so the "Batch" header landed in the first DATA row and
# every batch value one row below its true row - producing an entire column
# of blanks plus phantom rows carrying the stray values.
# ==========================================================================

def _offset_batch_table():
    """Header row has no Batch label; it sits in the first data row instead,
    and each batch value is one row lower than the item it belongs to. Row 3
    is the phantom the offset creates - batch only, no other content."""
    rows = [
        # r0: header - note column 5 is EMPTY where "Batch" should be
        [(0, 0, "S."), (0, 1, "Qty"), (0, 2, "Product Name"), (0, 3, "HSN"), (0, 4, "Amount")],
        [(1, 0, "1."), (1, 1, "2"), (1, 2, "ALPHA TAB"), (1, 3, "3004"), (1, 4, "100.00")],
        [(2, 0, "2."), (2, 1, "3"), (2, 2, "BETA CAP"), (2, 3, "3004"), (2, 4, "200.00")],
        [(4, 0, "3."), (4, 1, "1"), (4, 2, "GAMMA SYP"), (4, 3, "3004"), (4, 4, "300.00")],
    ]
    cells = [{"rowIndex": r, "columnIndex": c, "content": v} for row in rows for (r, c, v) in row]
    # column 5: header label in the first data row, then values one row down,
    # with r3 a phantom row holding only a batch value
    cells += [
        {"rowIndex": 1, "columnIndex": 5, "content": "Batch"},
        {"rowIndex": 2, "columnIndex": 5, "content": "BATCH-A"},
        {"rowIndex": 3, "columnIndex": 5, "content": "BATCH-B"},
        {"rowIndex": 4, "columnIndex": 5, "content": "BATCH-C"},
    ]
    return {
        "modelId": "prebuilt-invoice",
        "documents": [{"fields": {"InvoiceId": {"value": "A002111"}}}],
        "tables": [{"rowCount": 5, "columnCount": 6, "cells": cells}],
    }


def test_offset_batch_column_is_realigned_to_correct_items():
    invoice = normalize_azure_invoice(_offset_batch_table())
    got = [(i.name, i.batch) for i in invoice.line_items]
    assert got == [("ALPHA TAB", "BATCH-A"), ("BETA CAP", "BATCH-B"), ("GAMMA SYP", "BATCH-C")]


def test_offset_column_does_not_create_phantom_line_item():
    """The stray row the offset creates must not survive as an extra item."""
    invoice = normalize_azure_invoice(_offset_batch_table())
    assert len(invoice.line_items) == 3
    assert all(i.name for i in invoice.line_items)


def test_offset_realignment_is_skipped_when_counts_disagree():
    """If the values can't be matched 1:1 to the items, no batch is assigned -
    a wrong batch number is worse than a missing one, it's what a recall is
    traced by."""
    raw = _offset_batch_table()
    # drop one batch value so 3 items have only 2 values available
    raw["tables"][0]["cells"] = [
        c for c in raw["tables"][0]["cells"]
        if not (c["columnIndex"] == 5 and c["content"] == "BATCH-B")
    ]
    invoice = normalize_azure_invoice(raw)
    assert all(not i.batch for i in invoice.line_items)


def test_normal_table_is_unaffected_by_offset_detection():
    """A correctly typeset table must take the unchanged path."""
    cells = [
        {"rowIndex": 0, "columnIndex": 0, "content": "Product Name"},
        {"rowIndex": 0, "columnIndex": 1, "content": "Batch"},
        {"rowIndex": 0, "columnIndex": 2, "content": "Amount"},
        {"rowIndex": 1, "columnIndex": 0, "content": "ALPHA TAB"},
        {"rowIndex": 1, "columnIndex": 1, "content": "BATCH-A"},
        {"rowIndex": 1, "columnIndex": 2, "content": "100.00"},
    ]
    raw = {"modelId": "prebuilt-invoice", "documents": [], "tables": [{"rowCount": 2, "columnCount": 3, "cells": cells}]}
    invoice = normalize_azure_invoice(raw)
    assert [(i.name, i.batch) for i in invoice.line_items] == [("ALPHA TAB", "BATCH-A")]


# ==========================================================================
# Handwritten tick marks in the Qty column
# ==========================================================================

def test_selection_marks_are_stripped_from_cells():
    """Azure annotates a detected tick as ':selected:' inline; it is never
    part of the printed value and breaks numeric parsing."""
    cells = [
        {"rowIndex": 0, "columnIndex": 0, "content": "Product Name"},
        {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
        {"rowIndex": 0, "columnIndex": 2, "content": "Amount"},
        {"rowIndex": 1, "columnIndex": 0, "content": "ALPHA TAB"},
        {"rowIndex": 1, "columnIndex": 1, "content": "4\n:selected:"},
        {"rowIndex": 1, "columnIndex": 2, "content": "100.00"},
    ]
    raw = {"modelId": "prebuilt-invoice", "documents": [], "tables": [{"rowCount": 2, "columnCount": 3, "cells": cells}]}
    invoice = normalize_azure_invoice(raw)
    assert invoice.line_items[0].quantity == 4


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("v1", 1.0),        # tick read as a letter
        ("L2", 2.0),
        ("+1", 1.0),
        ("-3", 3.0),        # tick read as a sign - never a negative quantity
        ("L-1", 1.0),
        ("৳ 1", 1.0),  # tick read as a currency glyph
        # tick AND digit both read as letters: drop the tick, map the rest
        ("VI", 1.0),
        ("NI", 1.0),
        ("LI", 1.0),
        ("VZ", 2.0),
        ("VS", 5.0),
        ("VA", None),       # 'A' maps to no digit - left blank, not guessed
        ("x", None),        # nothing after the tick
    ],
)
def test_tick_marked_quantity_recovery(cell, expected):
    from extraction.normalizers.azure_invoice_normalizer import salvage_tick_marked_qty
    assert salvage_tick_marked_qty(cell) == expected


def test_quantity_is_never_negative():
    cells = [
        {"rowIndex": 0, "columnIndex": 0, "content": "Product Name"},
        {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
        {"rowIndex": 0, "columnIndex": 2, "content": "Amount"},
        {"rowIndex": 1, "columnIndex": 0, "content": "ALPHA TAB"},
        {"rowIndex": 1, "columnIndex": 1, "content": "-3"},
        {"rowIndex": 1, "columnIndex": 2, "content": "100.00"},
    ]
    raw = {"modelId": "prebuilt-invoice", "documents": [], "tables": [{"rowCount": 2, "columnCount": 3, "cells": cells}]}
    invoice = normalize_azure_invoice(raw)
    assert invoice.line_items[0].quantity == 3


# ==========================================================================
# Wrapped continuation rows
# ==========================================================================

def test_wrapped_values_are_absorbed_into_the_item_above():
    """On a continuation page the batch/expiry/HSN can wrap onto a following
    row that has no product or amount. That is the tail of the item above,
    not a new item."""
    cells = [
        {"rowIndex": 0, "columnIndex": 0, "content": "Product Name"},
        {"rowIndex": 0, "columnIndex": 1, "content": "Batch"},
        {"rowIndex": 0, "columnIndex": 2, "content": "Exp"},
        {"rowIndex": 0, "columnIndex": 3, "content": "Amount"},
        {"rowIndex": 1, "columnIndex": 0, "content": "VONEFI 20 MG"},
        {"rowIndex": 1, "columnIndex": 3, "content": "162.93"},
        # wrapped tail - batch and expiry only
        {"rowIndex": 2, "columnIndex": 1, "content": "HTL0189"},
        {"rowIndex": 2, "columnIndex": 2, "content": "9/27"},
    ]
    raw = {"modelId": "prebuilt-invoice", "documents": [], "tables": [{"rowCount": 3, "columnCount": 4, "cells": cells}]}
    invoice = normalize_azure_invoice(raw)
    assert len(invoice.line_items) == 1
    item = invoice.line_items[0]
    assert item.name == "VONEFI 20 MG"
    assert item.batch == "HTL0189"
    assert item.expiry == "9/27"


def test_multiline_expiry_cell_keeps_only_this_rows_value():
    """A merged cell holding two rows' expiries must not concatenate into
    nonsense like '4/281/28'."""
    from extraction.normalizers.azure_invoice_normalizer import clean_expiry_string
    assert clean_expiry_string("4/28\n1/28") == "4/28"


# ==========================================================================
# OCR-tolerant header matching
#
# Header labels were previously matched as exact strings, so every new
# misreading silently dropped a whole column: "QTY." read as "OTY." on the
# Arora Bros invoice lost every quantity. Matching on a look-alike-collapsed
# form absorbs that class.
# ==========================================================================

def test_misread_qty_header_still_maps():
    """The observed failure: Q read as O."""
    assert normalize_header("OTY.") == "quantity_pcs"
    assert normalize_header("OTY") == "quantity_pcs"


@pytest.mark.parametrize(
    "misread,expected",
    [
        ("0TY", "quantity_pcs"),          # Q -> 0
        ("8ATCH", "batch"),               # B -> 8
        ("EXPlRY", "expiry"),             # I -> l
        ("H5N", "hsn"),                   # S -> 5
        ("RA7E", "rate"),                 # T -> 7
        ("AMOUN7", "amount"),
        ("Gross Amt", "gross_amount"),
        ("GrossAmt", "gross_amount"),     # spacing lost
        ("M.R.P", "mrp"),
    ],
)
def test_look_alike_header_variants(misread, expected):
    assert normalize_header(misread) == expected


def test_tax_columns_never_collapse_into_each_other():
    """The dangerous case for any fuzzy matching: SGST/CGST/IGST differ by a
    single character. They must stay distinct, because mapping one onto
    another silently mis-files tax on every row."""
    from extraction.normalizers.azure_invoice_normalizer import ocr_visual_key
    keys = {ocr_visual_key(x) for x in ("sgst", "cgst", "igst")}
    assert len(keys) == 3


def test_no_two_concepts_share_aocr_visual_key():
    """Guards the look-alike table: if a future label makes two different
    concepts collapse together, that key is dropped rather than guessed - and
    this test makes the collision visible instead of silent."""
    from extraction.normalizers.azure_invoice_normalizer import (
        _EXACT_HEADER_MAP, ocr_visual_key,
    )
    by_key = {}
    for label, concept in _EXACT_HEADER_MAP.items():
        by_key.setdefault(ocr_visual_key(label), set()).add(concept)
    collisions = {k: v for k, v in by_key.items() if len(v) > 1}
    assert not collisions, f"look-alike collisions: {collisions}"


def test_unknown_header_still_returns_none():
    """The fallback must not map arbitrary text onto a column."""
    assert normalize_header("Delivery Instructions") is None
    assert normalize_header("Transporter") is None


def test_misread_qty_header_recovers_the_whole_column():
    """End to end: with the header misread, every quantity must still land."""
    cells = [
        {"rowIndex": 0, "columnIndex": 0, "content": "SN"},
        {"rowIndex": 0, "columnIndex": 1, "content": "OTY."},
        {"rowIndex": 0, "columnIndex": 2, "content": "ITEM NAME"},
        {"rowIndex": 0, "columnIndex": 3, "content": "AMOUNT"},
        {"rowIndex": 1, "columnIndex": 0, "content": "1"},
        {"rowIndex": 1, "columnIndex": 1, "content": "4.00"},
        {"rowIndex": 1, "columnIndex": 2, "content": "STERIVON H/S"},
        {"rowIndex": 1, "columnIndex": 3, "content": "152.00"},
        {"rowIndex": 2, "columnIndex": 0, "content": "2"},
        {"rowIndex": 2, "columnIndex": 1, "content": "10.00"},
        {"rowIndex": 2, "columnIndex": 2, "content": "BACIFYL 5 ML"},
        {"rowIndex": 2, "columnIndex": 3, "content": "173.00"},
    ]
    raw = {"modelId": "prebuilt-invoice", "documents": [], "tables": [{"rowCount": 3, "columnCount": 4, "cells": cells}]}
    invoice = normalize_azure_invoice(raw)
    assert [i.quantity for i in invoice.line_items] == [4, 10]


# ==========================================================================
# Totals block edge cases (Arora Bros, GST-15168)
# ==========================================================================

def _footer_only(rows):
    cells = [
        {"rowIndex": r, "columnIndex": c, "content": v}
        for r, row in enumerate(rows) for c, v in enumerate(row) if v
    ]
    return {
        "modelId": "prebuilt-invoice",
        "documents": [],
        "tables": [
            {   # item table so the footer table isn't also treated as items
                "rowCount": 2, "columnCount": 3,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Product Name"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
                    {"rowIndex": 0, "columnIndex": 2, "content": "Amount"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "ALPHA"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "1"},
                    {"rowIndex": 1, "columnIndex": 2, "content": "2277.50"},
                ],
            },
            {"rowCount": len(rows), "columnCount": max(len(r) for r in rows), "cells": cells},
        ],
    }


def test_discount_printed_as_negative_is_stored_as_magnitude():
    """Invoices print the deduction as "-151.42". Every consumer subtracts
    the discount, so keeping the sign would add it back as a surcharge."""
    invoice = normalize_azure_invoice(_footer_only([
        ["", "TOTAL", "2277.50"],
        ["", "DISCOUNT", "-151.42"],
        ["", "Net Amount", "2278.00"],
    ]))
    assert invoice.discount == 151.42


def test_footer_label_found_when_stray_text_shares_the_row():
    """The amount-in-words line sits in column 0 beside "Round Off"; reading
    the first two populated cells would take the words as the label and
    "Round Off" as its value."""
    invoice = normalize_azure_invoice(_footer_only([
        ["", "TOTAL", "2277.50"],
        ["", "CGST", "75.86"],
        ["", "SGST", "75.86"],
        ["Rs. : Two Thousand Two Hundred Seventy Eight Only", "Round Off", "0.20"],
        ["CHALLAN BILL:", "Net Amount", "2278.00"],
    ]))
    assert invoice.roundoff == 0.20
    assert invoice.grand_total == 2278.00
    assert invoice.cgst == 75.86


def test_arora_bros_totals_reconcile():
    """subtotal - discount + tax + roundoff == the printed net amount."""
    invoice = normalize_azure_invoice(_footer_only([
        ["", "TOTAL", "2277.50"],
        ["", "DISCOUNT", "-151.42"],
        ["", "CGST", "75.86"],
        ["", "SGST", "75.86"],
        ["Rs. : Two Thousand Two Hundred Seventy Eight Only", "Round Off", "0.20"],
        ["CHALLAN BILL:", "Net Amount", "2278.00"],
    ]))
    derived = (
        invoice.subtotal - invoice.discount + invoice.cgst + invoice.sgst + invoice.roundoff
    )
    assert round(derived, 2) == invoice.grand_total == 2278.00


# ==========================================================================
# GST rate when only one half of the split is readable
#
# From the Arora Bros invoice: items 1-2 are taxed at 9% SGST + 9% CGST = 18%,
# but the CGST value merged into the neighbouring C.D. column ("9.0015.20 %")
# leaving the CGST cell empty. Requiring both halves reported those lines as
# 0%, which then flowed into inventory as tax-free stock.
# ==========================================================================

def test_lone_sgst_implies_the_matching_cgst_half():
    from extraction.normalizers.azure_invoice_normalizer import extract_gst_percent
    assert extract_gst_percent("9.00", "", None) == 18.0


def test_lone_cgst_implies_the_matching_sgst_half():
    from extraction.normalizers.azure_invoice_normalizer import extract_gst_percent
    assert extract_gst_percent("", "2.50", None) == 5.0


def test_both_halves_present_are_summed():
    from extraction.normalizers.azure_invoice_normalizer import extract_gst_percent
    assert extract_gst_percent("2.50", "2.50", None) == 5.0
    assert extract_gst_percent("9.00", "9.00", None) == 18.0


def test_zero_half_beside_a_real_half_is_treated_as_unread():
    """A 0/9 split is not valid under GST - it is a half that failed to read,
    so reporting 9% instead of 18% would halve the tax on the line."""
    from extraction.normalizers.azure_invoice_normalizer import extract_gst_percent
    assert extract_gst_percent("0.00", "9.00", None) == 18.0
    assert extract_gst_percent("9.00", "0.00", None) == 18.0


def test_genuinely_zero_rated_line_stays_zero():
    from extraction.normalizers.azure_invoice_normalizer import extract_gst_percent
    assert extract_gst_percent("0.00", "0.00", None) == 0.0


def test_igst_is_used_whole_not_doubled():
    """Inter-state supply carries a single IGST rate, not two halves."""
    from extraction.normalizers.azure_invoice_normalizer import extract_gst_percent
    assert extract_gst_percent("", "", "18.00") == 18.0


def test_no_gst_information_returns_none():
    from extraction.normalizers.azure_invoice_normalizer import extract_gst_percent
    assert extract_gst_percent("", "", "") is None


def test_missing_cgst_cell_still_yields_full_rate_end_to_end():
    """The real shape: the CGST cell is empty because its value was absorbed
    by the column beside it."""
    cells = [
        {"rowIndex": 0, "columnIndex": 0, "content": "ITEM NAME"},
        {"rowIndex": 0, "columnIndex": 1, "content": "SGST\n(*)"},
        {"rowIndex": 0, "columnIndex": 2, "content": "CGST\n(*)"},
        {"rowIndex": 0, "columnIndex": 3, "content": "C.D."},
        {"rowIndex": 0, "columnIndex": 4, "content": "AMOUNT"},
        {"rowIndex": 1, "columnIndex": 0, "content": "STERIVON H/S"},
        {"rowIndex": 1, "columnIndex": 1, "content": "9.00"},
        # CGST cell empty - its value was merged into C.D. below
        {"rowIndex": 1, "columnIndex": 3, "content": "9.0015.20 %"},
        {"rowIndex": 1, "columnIndex": 4, "content": "152.00"},
    ]
    raw = {"modelId": "prebuilt-invoice", "documents": [], "tables": [{"rowCount": 2, "columnCount": 5, "cells": cells}]}
    invoice = normalize_azure_invoice(raw)
    assert invoice.line_items[0].gst_percent == 18.0


# --------------------------------------------------------------------------
# Totals printed beside a GST-class matrix (S.G. Pharma Traders)
# --------------------------------------------------------------------------

class TestHybridFooterRow:
    """A footer row carrying two things at once.

    S.G. Pharma prints a GST-rate matrix and a totals list side by side in one
    table, so a single row holds both a class breakdown and a label/value pair:

        GST 5,00% | 2530.86 | ... | 116.98 | Total Qty 26 | SGST PAYBLE | 58.49

    Taking the first label-ish cell paired "Total Qty" - it contains "total" -
    with the literal text "SGST PAYBLE", and the row's actual figure was never
    reached. The tax silently came out empty on an invoice that states it
    plainly twice over.
    """

    def _row(self, *cells):
        return list(cells)

    def test_the_quantity_total_is_captured_not_discarded(self):
        """The printed quantity total is an independent witness to the
        quantity column: the columns are read cell by cell and this is read
        once, so a free-quantity digit misread on one row shows up as a
        disagreement instead of passing unnoticed."""
        row = self._row("GST 5,00%", "2530.86", "0.00", "191,45", "58.49", "58.49",
                        "116.98", "Total Qty\n-\n26", "SGST PAYBLE", "58.49")
        assert ("Total Qty", "26") in _footer_pairs(row)

    def test_a_quantity_total_is_never_read_as_money(self):
        """"Total Qty" carries the word "total", and _is_footer_label accepts
        anything containing it. Booking 26 as the amount payable is the
        failure this guards."""
        assert _is_quantity_total_label("total qty")
        assert _is_quantity_total_label("total qty :-")
        assert _is_quantity_total_label("total quantity")
        assert not _is_quantity_total_label("total items")
        assert not _is_quantity_total_label("grand total")
        assert not _is_quantity_total_label("sub total")

    def test_the_real_pair_is_found_past_a_count_label(self):
        """A row carrying both a count and a money figure must surrender both.

        Reporting only one pair per row is what hid the discount on S.G.
        Pharma: "Total Items" sat to the left of "DIS AMT" in the same row and
        won. The caller keeps the pairs naming a money field and ignores the
        counts, so handing it everything is both correct and sufficient.
        """
        row = self._row("GST 5,00%", "2530.86", "0.00", "191,45", "58.49", "58.49",
                        "116.98", "Total Qty\n26", "SGST PAYBLE", "58.49")
        assert ("SGST PAYBLE", "58.49") in _footer_pairs(row)

    def test_a_label_and_its_amount_in_one_cell_are_split(self):
        """S.G. Pharma packs both into a single cell on two lines, so no
        amount of looking at neighbouring cells would find the figure."""
        assert ("DIS AMT.", "87.83") in _footer_pairs(["Total Items :-\n3", "DIS AMT.\n87.83"])

    def test_a_count_label_does_not_shadow_the_discount_beside_it(self):
        pairs = dict(_footer_pairs(["Total Items :-\n3", "DIS AMT.\n87.83"]))
        assert pairs.get("DIS AMT.") == "87.83"

    def test_a_separator_on_its_own_line_does_not_lose_the_pair(self):
        """OCR breaks the ":-" of "Total Qty :- 26" onto its own line often
        enough to matter. Partitioning at the first newline left the value
        glued to the separator, which parses as no number, so the pair - and
        with it the invoice's own quantity total - was dropped in silence."""
        pairs = dict(_footer_pairs(["Total Qty\n-\n26"]))
        assert pairs.get("Total Qty") == "26"

    def test_the_two_line_form_still_pairs(self):
        assert dict(_footer_pairs(["Total Qty\n26"])).get("Total Qty") == "26"

    def test_a_cell_of_pure_junk_lines_yields_nothing(self):
        assert _footer_pairs(["Total Qty\n-\n:-"]) == []

    def test_a_matrix_header_does_not_swallow_the_row(self):
        """TOTAL/SCHEME are column headings, not a label and its amount."""
        row = self._row("CLASS", "TOTAL", "SCHEME", "DISCOUNT", "SGST", "CGST",
                        "TOTAL GST", "", "TOTAL .", "2530.86")
        assert _footer_label_and_value(row) == ("TOTAL .", "2530.86")

    def test_a_label_with_no_number_anywhere_still_reports_itself(self):
        """Rows that genuinely have no figure must not regress to silence."""
        label, value = _footer_label_and_value(self._row("Round Off", "in words only"))
        assert label == "Round Off"

    def test_such_a_table_scores_as_a_footer(self):
        """Selection has to agree with extraction about where a label is, or
        the table is never handed to the reader that could parse it."""
        grid = [
            ["CLASS", "TOTAL", "SCHEME", "DISCOUNT", "SGST", "CGST", "TOTAL GST", "", "TOTAL .", "2530.86"],
            ["GST 0.00%", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "Total Items :-\n8", "DIS AMT", "191.45"],
            ["GST 5,00%", "2530.86", "0.00", "191,45", "58.49", "58.49", "116.98", "Total Qty\n26", "SGST PAYBLE", "58.49"],
            ["GST 12.00%", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "", "CGST PAYBLE", "58.49"],
        ]
        assert score_footer_table(grid) >= 3

    def test_tax_reaches_the_invoice_end_to_end(self):
        cells = [
            {"rowIndex": 0, "columnIndex": 0, "content": "ITEM"},
            {"rowIndex": 0, "columnIndex": 1, "content": "QTY"},
            {"rowIndex": 0, "columnIndex": 2, "content": "AMOUNT"},
            {"rowIndex": 1, "columnIndex": 0, "content": "ALPHA TAB"},
            {"rowIndex": 1, "columnIndex": 1, "content": "2"},
            {"rowIndex": 1, "columnIndex": 2, "content": "100.00"},
        ]
        footer = [
            {"rowIndex": 0, "columnIndex": 0, "content": "GST 5,00%"},
            {"rowIndex": 0, "columnIndex": 1, "content": "2530.86"},
            {"rowIndex": 0, "columnIndex": 2, "content": "Total Qty\n26"},
            {"rowIndex": 0, "columnIndex": 3, "content": "SGST PAYBLE"},
            {"rowIndex": 0, "columnIndex": 4, "content": "58.49"},
            {"rowIndex": 1, "columnIndex": 0, "content": "GST 12.00%"},
            {"rowIndex": 1, "columnIndex": 1, "content": "0.00"},
            {"rowIndex": 1, "columnIndex": 2, "content": ""},
            {"rowIndex": 1, "columnIndex": 3, "content": "CGST PAYBLE"},
            {"rowIndex": 1, "columnIndex": 4, "content": "58.49"},
        ]
        raw = {
            "modelId": "prebuilt-invoice",
            "documents": [],
            "tables": [
                {"rowCount": 2, "columnCount": 3, "cells": cells},
                {"rowCount": 2, "columnCount": 5, "cells": footer},
            ],
        }
        invoice = normalize_azure_invoice(raw)
        assert invoice.sgst == 58.49
        assert invoice.cgst == 58.49


class TestBorderArtifactsInNames:
    """A printed column rule read as part of the product name.

    Azure returns "|SIZODON MD 0.5" when the border sits tight against the
    first letter. The pipe then travels into the catalogue, where it makes one
    product look like two depending on how close the ink was to the rule.
    """

    def test_a_leading_rule_is_removed(self):
        assert _strip_border_artifacts("|SIZODON MD 0.5") == "SIZODON MD 0.5"

    def test_a_pipe_inside_the_name_is_left_alone(self):
        """It may be separating something the invoice meant to keep apart."""
        assert _strip_border_artifacts("VITAMIN A|D") == "VITAMIN A|D"

    def test_a_cell_that_is_only_a_rule_yields_nothing(self):
        assert _strip_border_artifacts("|") is None

    def test_nothing_is_invented_for_a_blank(self):
        assert _strip_border_artifacts(None) is None
        assert _strip_border_artifacts("   ") is None


class TestGstinOwnership:
    """Which registration belongs to the supplier.

    Azure labels these VendorTaxId and CustomerTaxId and, on invoices printing
    both parties side by side, can label them the wrong way round - Mahajan
    Medicine Co. came back with the buyer's number as the vendor's. A purchase
    register is keyed on the supplier's GSTIN, so this is not cosmetic.
    """

    def _fields(self, vendor_xy, seller_xy, buyer_xy):
        def box(point):
            x, y = point
            return {"boundingRegions": [{"polygon": [x, y, x, y, x, y, x, y]}]}
        return {"VendorName": box(vendor_xy), "VendorTaxId": box(seller_xy),
                "CustomerTaxId": box(buyer_xy)}

    def test_the_number_nearer_the_vendor_name_is_the_sellers(self):
        # Azure's "customer" number sits beside the vendor name; its "vendor"
        # number is far away in the party block. The labels are swapped.
        fields = self._fields((1147, 2011), (1271, 597), (1297, 2060))
        seller, buyer = resolve_gstin_owners(fields, "BUYERS_GSTIN", "SELLERS_GSTIN")
        assert seller == "SELLERS_GSTIN"
        assert buyer == "BUYERS_GSTIN"

    def test_azures_labelling_stands_when_it_agrees_with_the_page(self):
        fields = self._fields((100, 100), (120, 110), (900, 900))
        seller, buyer = resolve_gstin_owners(fields, "SELLER", "BUYER")
        assert (seller, buyer) == ("SELLER", "BUYER")

    def test_an_ambiguous_layout_is_left_alone(self):
        """Both parties stacked in one block gives no usable signal, and
        guessing there trades a rare error for a common one."""
        fields = self._fields((100, 100), (120, 120), (130, 130))
        assert resolve_gstin_owners(fields, "SELLER", "BUYER") == ("SELLER", "BUYER")

    def test_without_geometry_nothing_is_reassigned(self):
        assert resolve_gstin_owners({}, "SELLER", "BUYER") == ("SELLER", "BUYER")

    def test_a_single_gstin_is_never_reassigned(self):
        assert resolve_gstin_owners({}, "SELLER", None) == ("SELLER", None)


class TestDiscountLabels:
    def test_a_leading_qualifier_does_not_hide_the_discount(self):
        """Kumar Brothers heads its discount "BILL DIS." - the qualifier comes
        first, so the dis-/disc- prefix rules never fired and the invoice
        showed no discount at all."""
        assert is_discount_label("BILL DIS.") is True

    def test_dispatch_is_not_a_discount(self):
        assert is_discount_label("Dispatch") is False

    def test_tax_labels_are_not_discounts(self):
        for label in ("SGST PAYBLE", "CGST PAYBLE", "TOTAL GST", "CR/DR NOTE"):
            assert is_discount_label(label) is False, label


class TestMultipleDiscounts:
    """An invoice that prints its discount as more than one footer row.

    Mahajan Medicos states "1st Discount 139.09" and "2nd Discount 10.00" as
    two separate lines, not one. Taking only the last label-value pair seen
    kept the second and silently dropped the first, so the invoice showed a
    discount of 10.00 against a printed total of 149.09 and its totals never
    reconciled - the reviewer saw "Formula mismatch" with no way to tell why.
    """

    def _invoice_with_two_discount_rows(self):
        item_cells = [
            {"rowIndex": 0, "columnIndex": 0, "content": "ITEM"},
            {"rowIndex": 0, "columnIndex": 1, "content": "AMOUNT"},
            {"rowIndex": 1, "columnIndex": 0, "content": "MOOV CREAM"},
            {"rowIndex": 1, "columnIndex": 1, "content": "281.14"},
        ]
        footer_cells = [
            {"rowIndex": 0, "columnIndex": 0, "content": "SUB TOTAL"},
            {"rowIndex": 0, "columnIndex": 1, "content": "2703.80"},
            {"rowIndex": 1, "columnIndex": 0, "content": "1st Discount"},
            {"rowIndex": 1, "columnIndex": 1, "content": "139.09"},
            {"rowIndex": 2, "columnIndex": 0, "content": "2nd Discount"},
            {"rowIndex": 2, "columnIndex": 1, "content": "10.00"},
            {"rowIndex": 3, "columnIndex": 0, "content": "SGST"},
            {"rowIndex": 3, "columnIndex": 1, "content": "152.69"},
            {"rowIndex": 4, "columnIndex": 0, "content": "CGST"},
            {"rowIndex": 4, "columnIndex": 1, "content": "152.69"},
            {"rowIndex": 5, "columnIndex": 0, "content": "GRAND TOTAL"},
            {"rowIndex": 5, "columnIndex": 1, "content": "2860.00"},
        ]
        return {
            "modelId": "prebuilt-invoice",
            "documents": [],
            "tables": [
                {"rowCount": 2, "columnCount": 2, "cells": item_cells},
                {"rowCount": 6, "columnCount": 2, "cells": footer_cells},
            ],
        }

    def test_both_rows_are_summed_into_the_total(self):
        invoice = normalize_azure_invoice(self._invoice_with_two_discount_rows())
        assert invoice.discount == 149.09

    def test_the_breakdown_names_both_rows(self):
        invoice = normalize_azure_invoice(self._invoice_with_two_discount_rows())
        assert invoice.discount_breakdown == [
            {"label": "1st Discount", "amount": 139.09},
            {"label": "2nd Discount", "amount": 10.0},
        ]

    def test_a_single_discount_row_produces_a_one_item_breakdown(self):
        """Most invoices state one figure; the breakdown still carries it,
        so the frontend need only branch on length rather than on presence."""
        cells = [
            {"rowIndex": 0, "columnIndex": 0, "content": "SUB TOTAL"},
            {"rowIndex": 0, "columnIndex": 1, "content": "100.00"},
            {"rowIndex": 1, "columnIndex": 0, "content": "Discount"},
            {"rowIndex": 1, "columnIndex": 1, "content": "5.00"},
            {"rowIndex": 2, "columnIndex": 0, "content": "GRAND TOTAL"},
            {"rowIndex": 2, "columnIndex": 1, "content": "95.00"},
        ]
        raw = {"modelId": "prebuilt-invoice", "documents": [],
               "tables": [{"rowCount": 3, "columnCount": 2, "cells": cells}]}
        invoice = normalize_azure_invoice(raw)
        assert invoice.discount == 5.0
        assert invoice.discount_breakdown == [{"label": "Discount", "amount": 5.0}]

    def test_no_discount_row_leaves_an_empty_breakdown(self):
        cells = [
            {"rowIndex": 0, "columnIndex": 0, "content": "SUB TOTAL"},
            {"rowIndex": 0, "columnIndex": 1, "content": "100.00"},
            {"rowIndex": 1, "columnIndex": 0, "content": "GRAND TOTAL"},
            {"rowIndex": 1, "columnIndex": 1, "content": "100.00"},
        ]
        raw = {"modelId": "prebuilt-invoice", "documents": [],
               "tables": [{"rowCount": 2, "columnCount": 2, "cells": cells}]}
        invoice = normalize_azure_invoice(raw)
        assert invoice.discount_breakdown == []

    def test_a_negative_discount_row_is_normalised_like_the_total(self):
        """A component must not disagree in sign with the total it was summed
        into - "DISCOUNT -151.42" under a "Discount -" heading reads as a
        double negative and looks like the figure is wrong."""
        cells = [
            {"rowIndex": 0, "columnIndex": 0, "content": "SUB TOTAL"},
            {"rowIndex": 0, "columnIndex": 1, "content": "1000.00"},
            {"rowIndex": 1, "columnIndex": 0, "content": "DISCOUNT"},
            {"rowIndex": 1, "columnIndex": 1, "content": "-151.42"},
            {"rowIndex": 2, "columnIndex": 0, "content": "GRAND TOTAL"},
            {"rowIndex": 2, "columnIndex": 1, "content": "848.58"},
        ]
        raw = {"modelId": "prebuilt-invoice", "documents": [],
               "tables": [{"rowCount": 3, "columnCount": 2, "cells": cells}]}
        invoice = normalize_azure_invoice(raw)
        assert invoice.discount == 151.42
        assert invoice.discount_breakdown == [{"label": "DISCOUNT", "amount": 151.42}]


# ==========================================================================
# Which column is the Amount, when the header cannot say
# ==========================================================================

def _deepak_agencies_table(header_overrides=None):
    """A GST-breakout layout whose tax and amount headers OCR'd badly.

    Taken from a real Deepak Agencies invoice: Azure returned "SUST" for SGST,
    "CUST" for CGST and "Amnulint" for Amount, so both "Value" columns claimed
    to be the Amount and the real Amount column mapped to nothing.
    """
    header = ["S", "Qty.", "Product Name", "Batch", "HSN", "M.R.P", "Rate",
              "SUST", "Value", "CUST", "Value", "Amnulint"]
    for idx, text in (header_overrides or {}).items():
        header[idx] = text
    # qty, name, batch, mrp, rate, tax value, amount
    items = [
        ("1", "GUDUCHI TAB 60", "372401160", "240.00", "176.00", "4.14", "176.00"),
        ("1", "BABY HAIR OIL", "592600093", "266.00", "195.12", "4.59", "195.12"),
        ("1", "GENTLE BABY SHAMPOO", "B992600307", "213.00", "158.10", "3.72", "158.10"),
        ("4", "ZERODOL P", "KVB0326017AS", "75.94", "57.86", "5.44", "231.44"),
        ("4", "ZERODOL-SP TAB", "FND0726002BH", "139.69", "106.43", "10.00", "425.72"),
        ("2", "OPTHACARE EYEDROPS", "762500071", "93.75", "71.43", "3.36", "142.86"),
    ]
    cells = [{"rowIndex": 0, "columnIndex": c, "content": v} for c, v in enumerate(header)]
    for r, (qty, name, batch, mrp, rate, tax, amount) in enumerate(items, start=1):
        row = [str(r), qty, name, batch, "30049069", mrp, rate, "2.50", tax, "2.50", tax, amount]
        cells += [{"rowIndex": r, "columnIndex": c, "content": v} for c, v in enumerate(row)]

    footer = [
        {"rowIndex": 0, "columnIndex": 0, "content": "TOTAL"},
        {"rowIndex": 0, "columnIndex": 1, "content": "1329.24"},
        {"rowIndex": 1, "columnIndex": 0, "content": "SGST PAYBLE"},
        {"rowIndex": 1, "columnIndex": 1, "content": "31.25"},
        {"rowIndex": 2, "columnIndex": 0, "content": "CGST PAYBLE"},
        {"rowIndex": 2, "columnIndex": 1, "content": "31.25"},
    ]
    return {
        "modelId": "prebuilt-invoice",
        "documents": [{"fields": {"InvoiceId": {"value": "A000865"}}}],
        "tables": [
            {"rowCount": len(items) + 1, "columnCount": len(header), "cells": cells},
            {"rowCount": 3, "columnCount": 2, "cells": footer},
        ],
    }


def test_misread_amount_header_is_recovered_from_the_arithmetic():
    """The Amount column is found by what reproduces qty x rate, not by its
    header - which here reads "Amnulint"."""
    invoice = normalize_azure_invoice(_deepak_agencies_table())
    amounts = [i.amount for i in invoice.line_items]
    assert amounts == [176.00, 195.12, 158.10, 231.44, 425.72, 142.86]


def test_tax_value_column_is_never_billed_as_the_line_amount():
    """Both "Value" columns are the GST breakout. Reading one as the Amount
    put the invoice's SGST figure on every line and understated it tenfold."""
    invoice = normalize_azure_invoice(_deepak_agencies_table())
    line_total = round(sum(i.amount for i in invoice.line_items), 2)
    assert line_total == 1329.24
    assert not any(i.amount in (4.14, 4.59, 3.72, 5.44, 10.00, 3.36) for i in invoice.line_items)


def test_scribble_in_a_tax_column_does_not_become_a_line_item():
    """A handwritten total lands in whatever column it sits over. It only
    became a phantom row because that column was being read as the Amount."""
    raw = _deepak_agencies_table()
    table = raw["tables"][0]
    table["rowCount"] += 1
    table["cells"].append({"rowIndex": 7, "columnIndex": 8, "content": "1798\n217\n3015"})
    invoice = normalize_azure_invoice(raw)
    assert len(invoice.line_items) == 6
    assert all(i.name for i in invoice.line_items)


def test_readable_amount_header_keeps_its_column():
    """With the header intact the arithmetic must agree with it, not move it -
    the formats already read correctly take an unchanged path."""
    invoice = normalize_azure_invoice(
        _deepak_agencies_table({7: "SGST", 9: "CGST", 11: "Amount"})
    )
    amounts = [i.amount for i in invoice.line_items]
    assert amounts == [176.00, 195.12, 158.10, 231.44, 425.72, 142.86]


def test_amount_column_is_left_alone_when_there_is_nothing_to_check_it_against():
    """No rate column and no footer means no evidence. The header's decision
    stands rather than being replaced by a guess."""
    header = ["Product Name", "Batch", "Value", "Serial"]
    rows = [
        ["ALPHA TAB", "BATCH-A", "100.00", "9001"],
        ["BETA CAP", "BATCH-B", "200.00", "9002"],
        ["GAMMA SYP", "BATCH-C", "300.00", "9003"],
    ]
    cells = [{"rowIndex": 0, "columnIndex": c, "content": v} for c, v in enumerate(header)]
    for r, row in enumerate(rows, start=1):
        cells += [{"rowIndex": r, "columnIndex": c, "content": v} for c, v in enumerate(row)]
    raw = {
        "modelId": "prebuilt-invoice",
        "documents": [],
        "tables": [{"rowCount": 4, "columnCount": 4, "cells": cells}],
    }
    invoice = normalize_azure_invoice(raw)
    assert [i.amount for i in invoice.line_items] == [100.00, 200.00, 300.00]


# ==========================================================================
# A description that wraps onto a second line (Jeevan Medicos)
# ==========================================================================

def _wrapped_description_table(header=None):
    """Jeevan Medicos prints a long name across two lines, and OCR damaged
    the Qty and Gross Amt headings: "QCy" and "Gross AntE"."""
    header = header or ["Sr.", "Item Description", "HSN", "MRP", "Batch No.",
                        "PKG", "QCy", "Rate", "Gross\nAntE"]
    rows = [
        ["1", "ROSUMAC 10 15'S", "30", "282.47", "18254976A", "15's", "1.00", "215.25", "215.25"],
        ["2", "REFRESH LIQUIGEL", "30", "177.11", "125013", "15ML", "1.00", "145.42", "145.42"],
        ["", "E/D", "", "", "", "", "", "", ""],
        ["3", "OMNACORTIL 10 MG", "30", "12.80", "13260089A", "10'S", "50.00", "10.25", "512.50"],
        ["", "TAB.", "", "", "", "", "", "", ""],
        ["4", "ROSEDAY 5 15 'S", "3004", "135.70", "48021218", "15'S", "2.00", "103.40", "206.80"],
        ["5", "GLYCOMET 500 SR", "3004", "41.97", "60002750", "20'S", "10.00", "31.98", "319.80"],
        ["", "20`S", "", "", "", "", "", "", ""],
    ]
    cells = [{"rowIndex": 0, "columnIndex": c, "content": v} for c, v in enumerate(header)]
    for r, row in enumerate(rows, start=1):
        cells += [{"rowIndex": r, "columnIndex": c, "content": v} for c, v in enumerate(row)]
    footer = [
        {"rowIndex": 0, "columnIndex": 0, "content": "TOTAL"},
        {"rowIndex": 0, "columnIndex": 1, "content": "1399.77"},
        {"rowIndex": 1, "columnIndex": 0, "content": "Discount"},
        {"rowIndex": 1, "columnIndex": 1, "content": "0.00"},
        {"rowIndex": 2, "columnIndex": 0, "content": "CGST"},
        {"rowIndex": 2, "columnIndex": 1, "content": "35.00"},
        {"rowIndex": 3, "columnIndex": 0, "content": "SGST"},
        {"rowIndex": 3, "columnIndex": 1, "content": "35.00"},
        {"rowIndex": 4, "columnIndex": 0, "content": "Grand Total"},
        {"rowIndex": 4, "columnIndex": 1, "content": "1469.77"},
    ]
    return {
        "modelId": "prebuilt-invoice",
        "documents": [{"fields": {"InvoiceId": {"value": "378"}}}],
        "tables": [
            {"rowCount": len(rows) + 1, "columnCount": len(header), "cells": cells},
            {"rowCount": 5, "columnCount": 2, "cells": footer},
        ],
    }


def test_wrapped_product_name_does_not_become_its_own_item():
    """A row carrying only a scrap of description is the tail of the name
    above. Five of them turned a 22-line invoice into 27 items."""
    invoice = normalize_azure_invoice(_wrapped_description_table())
    names = [i.name for i in invoice.line_items]
    assert names == [
        "ROSUMAC 10 15'S",
        "REFRESH LIQUIGEL E/D",
        "OMNACORTIL 10 MG TAB.",
        "ROSEDAY 5 15 'S",
        "GLYCOMET 500 SR 20`S",
    ]


def test_quantity_and_amount_are_recovered_when_both_headers_are_unreadable():
    """Neither column can be tested without the other, so the pair is found
    together: qty x rate = amount identifies both."""
    invoice = normalize_azure_invoice(_wrapped_description_table())
    assert [i.quantity for i in invoice.line_items] == [1.0, 1.0, 50.0, 2.0, 10.0]
    assert [i.amount for i in invoice.line_items] == [215.25, 145.42, 512.50, 206.80, 319.80]


def test_footer_labelled_only_total_is_read_as_the_subtotal():
    """This format labels the subtotal "TOTAL", with Grand Total separate.

    Tested with a row whose Amount was misread — as happened on the real
    invoice, where a Gross of 215.25 came back 115.25 — because that is when
    reading the printed figure matters. Skipping it fell back to summing the
    rows, which makes the subtotal agree with the rows by construction and
    hides the very disagreement the reviewer needs to see.
    """
    raw = _wrapped_description_table()
    for cell in raw["tables"][0]["cells"]:
        if cell["rowIndex"] == 1 and cell["columnIndex"] == 8:
            cell["content"] = "115.25"
    invoice = normalize_azure_invoice(raw)
    line_total = round(sum(i.amount for i in invoice.line_items), 2)

    assert invoice.subtotal == 1399.77        # what the invoice printed
    assert line_total == 1299.77              # what the rows come to
    assert invoice.grand_total == 1469.77


def test_bare_total_that_is_a_count_is_not_read_as_the_subtotal():
    """The same word labels the item and quantity counts. Booking "TOTAL 4"
    as the subtotal made the pharmacy owe four rupees, so the figure has to
    reconcile with the rest of the footer before it is believed."""
    raw = _wrapped_description_table()
    raw["tables"][1]["cells"].append({"rowIndex": 5, "columnIndex": 0, "content": "TOTAL"})
    raw["tables"][1]["cells"].append({"rowIndex": 5, "columnIndex": 1, "content": "5"})
    raw["tables"][1]["rowCount"] = 6
    invoice = normalize_azure_invoice(raw)
    assert invoice.subtotal == 1399.77


def test_readable_qty_and_amount_headers_are_not_second_guessed():
    """With the headers intact the arithmetic must agree with them."""
    invoice = normalize_azure_invoice(_wrapped_description_table(
        header=["Sr.", "Item Description", "HSN", "MRP", "Batch No.",
                "PKG", "Qty", "Rate", "Amount"]
    ))
    assert [i.quantity for i in invoice.line_items] == [1.0, 1.0, 50.0, 2.0, 10.0]
    assert [i.amount for i in invoice.line_items] == [215.25, 145.42, 512.50, 206.80, 319.80]


def test_a_totals_note_in_the_description_column_is_dropped_not_glued_on():
    """A stray "CESS:0%=0" looks exactly like a wrapped name. Appending it
    would file a real product under a corrupted name, which is worse than the
    phantom row it replaces because it is not visibly wrong."""
    raw = _wrapped_description_table()
    table = raw["tables"][0]
    table["rowCount"] += 1
    table["cells"].append({"rowIndex": 9, "columnIndex": 1, "content": "CESS:0%=0"})
    invoice = normalize_azure_invoice(raw)
    assert len(invoice.line_items) == 5
    assert invoice.line_items[-1].name == "GLYCOMET 500 SR 20`S"


# ==========================================================================
# A watermark printed across the item table (Gurkirat Medicos)
# ==========================================================================

def _watermarked_table():
    """The seller stamps its name diagonally over the table, and OCR puts
    each word into whichever cell it crosses: "GURKIRAT" onto a second line
    of the description, "MEDICOS" onto a second line of the MRP."""
    header = ["S.", "Qty.", "Pack", "Mfg", "Product", "Batch", "Exp", "HSN",
              "MRP", "Rate", "DIS", "SGST", "CEST", "Amount"]
    row = ["1", "2.500+.500", "1º10", "STERI", "SILODOSIA 8D\nGURKIRAT", "LC5006",
           "11/27", "3004", "403.12\nMEDICOS", "307.17", "0.00", "2.50", "2.50", "767.93"]
    cells = [{"rowIndex": 0, "columnIndex": c, "content": v} for c, v in enumerate(header)]
    cells += [{"rowIndex": 1, "columnIndex": c, "content": v} for c, v in enumerate(row)]
    footer = [
        {"rowIndex": 0, "columnIndex": 0, "content": "SUB TOTAL"},
        {"rowIndex": 0, "columnIndex": 1, "content": "767.93"},
        {"rowIndex": 1, "columnIndex": 0, "content": "GRAND TOTAL"},
        {"rowIndex": 1, "columnIndex": 1, "content": "766.00"},
    ]
    return {
        "modelId": "prebuilt-invoice",
        "documents": [{"fields": {
            "InvoiceId": {"value": "A000864"},
            "VendorName": {"value": "GURKIRAT"},
        }}],
        "tables": [
            {"rowCount": 2, "columnCount": len(header), "cells": cells},
            {"rowCount": 2, "columnCount": 2, "cells": footer},
        ],
    }


def test_watermark_over_a_numeric_cell_does_not_lose_the_figure():
    """"403.12\\nMEDICOS" is unparseable as a whole, so a perfectly legible
    MRP was dropped and the column showed nothing."""
    invoice = normalize_azure_invoice(_watermarked_table())
    assert invoice.line_items[0].mrp == 403.12
    assert invoice.line_items[0].rate == 307.17
    assert invoice.line_items[0].amount == 767.93


def test_watermark_is_removed_from_the_product_name():
    """The other half of the same watermark filed the product as
    "SILODOSIA 8D GURKIRAT", which reaches the catalogue looking legitimate."""
    invoice = normalize_azure_invoice(_watermarked_table())
    assert invoice.line_items[0].name == "SILODOSIA 8D"


def test_two_numbers_in_one_cell_are_still_left_alone():
    """One numeric line is a watermark over a value; two is a merged column,
    and picking either would be a guess."""
    raw = _watermarked_table()
    for cell in raw["tables"][0]["cells"]:
        if cell["rowIndex"] == 1 and cell["columnIndex"] == 8:
            cell["content"] = "403.12\n512.60"
    invoice = normalize_azure_invoice(raw)
    assert invoice.line_items[0].mrp == "403.12\n512.60"


def test_a_name_made_only_of_the_seller_name_is_not_emptied():
    """Stripping every word would leave a nameless row, which is worse than
    a wrong one - there would be nothing left for the reviewer to correct."""
    raw = _watermarked_table()
    for cell in raw["tables"][0]["cells"]:
        if cell["rowIndex"] == 1 and cell["columnIndex"] == 4:
            cell["content"] = "GURKIRAT"
    invoice = normalize_azure_invoice(raw)
    assert invoice.line_items[0].name == "GURKIRAT"
