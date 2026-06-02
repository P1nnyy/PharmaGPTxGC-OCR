from services.layout_pipeline.reconstruction_forensics import build_reconstruction_forensics


def test_empty_raw_result_does_not_crash():
    report = build_reconstruction_forensics({})

    assert report["summary"]["ocr_token_count"] == 0
    assert report["summary"]["suspected_failure_layer"] == "ocr_missing"


def test_schema_path_detection_works():
    report = build_reconstruction_forensics({"blocks": [], "structured_tables": [], "quality_gate": {"status": "needs_review"}})

    paths = {entry["path"]: entry["exists"] for entry in report["schema_paths_found"]}
    assert paths["blocks"] is True
    assert paths["structured_tables"] is True
    assert paths["quality_gate"] is True
    assert paths["row_math_repair"] is False


def test_token_trace_extracts_text_and_geometry():
    report = build_reconstruction_forensics({
        "blocks": [{
            "id": "b1",
            "text": "RANIDOM",
            "confidence": 0.9,
            "polygon": [[10, 20], [60, 20], [60, 35], [10, 35]],
        }]
    })

    token = report["tokens"][0]
    assert token["token_id"] == "b1"
    assert token["text"] == "RANIDOM"
    assert token["x_min"] == 10
    assert token["y_max"] == 35


def test_row_trace_flags_footer_keyword_inside_item_row():
    report = build_reconstruction_forensics({
        "structured_rows": [{
            "row_id": "r1",
            "row_role": "item_row",
            "text": "TOTAL 100.00",
        }]
    })

    assert "footer_keyword_inside_item_row" in report["rows"][0]["issues"]
    assert report["footer_leakage_candidates"]


def test_canonical_trace_flags_missing_source_evidence():
    report = build_reconstruction_forensics({
        "canonical_invoice": {
            "item_rows": [{
                "row_id": "c1",
                "product": "ABC",
                "qty": "2",
                "rate": "10",
                "amount": "20",
                "source_path": "",
            }]
        }
    })

    trace = report["canonical_trace"][0]
    assert "qty_missing_source" in trace["fields_missing_source_evidence"]
    assert "rate_missing_source" in trace["fields_missing_source_evidence"]
    assert "amount_missing_source" in trace["fields_missing_source_evidence"]


def test_semantic_poisoning_candidate_detected_for_tax_keyword_in_amount_column():
    report = build_reconstruction_forensics({
        "structured_tables": [{
            "table_id": "t1",
            "columns": [{"col_id": "amount", "geometry": {"min_x": 100, "max_x": 200}}],
            "rows": [{"row_id": "r1", "row_role": "item_row"}],
            "cells": [{
                "row_id": "r1",
                "col_id": "amount",
                "text": "CGST 9.22",
                "mapped_block_ids": [],
            }],
        }],
        "metrics": {"final_column_semantics": {"t1": {"amount": "amount"}}},
    })

    assert report["semantic_poisoning_candidates"]
    assert "semantic_column_poisoning_candidate" in report["columns"][0]["issues"]


def test_target_product_trace_finds_target_tokens():
    report = build_reconstruction_forensics(
        {
            "blocks": [{"id": "b1", "text": "RANIDOM-MPS SUSP"}],
            "structured_rows": [{"row_id": "r1", "row_role": "item_row", "text": "RANIDOM-MPS SUSP 2.500+.500 71.34 196.19"}],
        },
        target_products=["RANIDOM"],
    )

    trace = report["target_product_trace"][0]
    assert trace["matching_tokens"]
    assert trace["matching_rows"]
    assert trace["expected_value_presence"]["2.500+.500"] is True


def test_suspected_failure_layer_insufficient_when_no_row_cell_data_exists():
    report = build_reconstruction_forensics({
        "blocks": [{"id": "b1", "text": "ABC", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
    })

    assert report["summary"]["suspected_failure_layer"] == "row_grouping_failure"

    report = build_reconstruction_forensics({
        "blocks": [{"id": "b1", "text": "ABC", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        "structured_rows": [{"row_id": "r1", "row_role": "item_row", "text": "ABC"}],
    })

    assert report["summary"]["suspected_failure_layer"] == "insufficient_debug_evidence"
