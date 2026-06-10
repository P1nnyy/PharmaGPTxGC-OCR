from services.layout_pipeline.canonical_invoice import build_canonical_invoice


def test_canonical_adapter_extracts_item_rows_from_clean_rows():
    canonical = build_canonical_invoice({
        "item_rows_clean": [
            {"row_id": "r1", "product": "ABC TAB", "qty": "2", "ptr": "10.00", "amount": "20.00"}
        ],
        "invoice_confidence": 0.8,
    })

    assert len(canonical.item_rows) == 1
    assert canonical.item_rows[0].product == "ABC TAB"
    assert canonical.item_rows[0].rate == "10.00"
    assert canonical.item_rows[0].source_path == "item_rows_clean[0]"


def test_canonical_adapter_extracts_item_rows_from_alternate_shape():
    canonical = build_canonical_invoice({
        "reconstructed_item_rows": [
            {"visual_row_id": "v1", "description": "XYZ CAP", "quantity": "1", "rate": "5", "line_amount": "5"}
        ],
        "overall_confidence": 0.7,
    })

    assert len(canonical.item_rows) == 1
    assert canonical.item_rows[0].row_id == "v1"
    assert canonical.item_rows[0].product == "XYZ CAP"
    assert canonical.item_rows[0].amount == "5"


def test_canonical_adapter_extracts_footer_fields_from_dict():
    canonical = build_canonical_invoice({
        "totals": {
            "subtotal": 100.0,
            "discount": 5.0,
            "sgst": 2.5,
            "cgst": 2.5,
            "grand_total": 100.0,
        }
    })

    assert canonical.get_footer_value("subtotal") == 100.0
    assert canonical.get_footer_value("grand_total") == 100.0


def test_canonical_adapter_handles_empty_result_safely():
    canonical = build_canonical_invoice({})

    assert canonical.item_rows == []
    assert canonical.footer_fields == []
    assert "no_item_rows" in canonical.issues
    assert "missing_invoice_confidence" in canonical.issues
