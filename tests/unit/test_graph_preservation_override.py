import pytest
from services.spatial_reconstruction import filter_graph_rows

def test_blocked_cgst_sgst_footer():
    # CGST 2.500 + SGST 2.500 with hint footer_candidate should be blocked/dropped, not preserved
    raw_rows = [
        {
            "row_id": "graph_row_15",
            "text": "CGST 2.500 + SGST 2.500 17 2180.20 78.48 0.00 0.00 2101.72",
            "row_type_hint": "footer_candidate"
        }
    ]
    tsr_metadata = {}
    filtered = filter_graph_rows(raw_rows, tsr_metadata)
    assert len(filtered) == 0
    assert tsr_metadata["graph_preservation_blocked_footer_tax_count"] == 1
    assert len(tsr_metadata["graph_preservation_blocked_examples"]) == 1
    assert tsr_metadata["graph_preservation_blocked_examples"][0]["row_id"] == "graph_row_15"

def test_normal_product_row_preserved():
    # A normal medicine row with batch and expiry should be preserved via Product Context Rule
    raw_rows = [
        {
            "row_id": "graph_row_20",
            "text": "TAB LUBIMOIST BATCH B123 EXP 12/28 150.00",
            "row_type_hint": "unknown"
        }
    ]
    tsr_metadata = {}
    filtered = filter_graph_rows(raw_rows, tsr_metadata)
    assert len(filtered) == 1
    assert filtered[0]["row_id"] == "graph_row_20"
    assert tsr_metadata.get("graph_preservation_blocked_footer_tax_count", 0) == 0

def test_real_header_row_preserved():
    # A real header row (contains Product Name/Item) should be preserved even if it has a GST/footer word or metadata hint
    raw_rows = [
        {
            "row_id": "graph_row_10",
            "text": "Product Name | HSN | Batch | Expiry | Qty | Rate | GST | Amount",
            "row_type_hint": "metadata_candidate"
        }
    ]
    tsr_metadata = {}
    filtered = filter_graph_rows(raw_rows, tsr_metadata)
    assert len(filtered) == 1
    assert filtered[0]["row_id"] == "graph_row_10"

def test_net_amount_grand_total_dropped():
    # A Net Amount or Grand Total row must be blocked/dropped
    raw_rows = [
        {
            "row_id": "graph_row_30",
            "text": "Net Amount 2291.00",
            "row_type_hint": "footer_candidate"
        },
        {
            "row_id": "graph_row_31",
            "text": "Grand Total 5000.00",
            "row_type_hint": "footer_candidate"
        }
    ]
    tsr_metadata = {}
    filtered = filter_graph_rows(raw_rows, tsr_metadata)
    assert len(filtered) == 0
    assert tsr_metadata["graph_preservation_blocked_footer_tax_count"] == 2
