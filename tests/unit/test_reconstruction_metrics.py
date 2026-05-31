import json
from types import SimpleNamespace

from services.layout_pipeline.reconstruction_metrics import (
    build_row_handoff_summary,
    build_tsr_candidate_decision_summary,
)


def _candidate(rows=3, columns=4, cells=12, confidence=0.5):
    return SimpleNamespace(
        rows=[object() for _ in range(rows)],
        columns=[object() for _ in range(columns)],
        cells=[object() for _ in range(cells)],
        topology_confidence=confidence,
    )


def test_tsr_candidate_decision_summary_is_json_serializable():
    summary = build_tsr_candidate_decision_summary(
        heuristic_candidate=_candidate(),
        heuristic_metrics={
            "row_count": 10,
            "item_row_ratio": 0.7,
            "row_math_fail_count": 2,
            "missing_req_cols": ["rate"],
        },
        heuristic_score=82.5,
        graph_candidate=_candidate(rows=8, columns=5, cells=40, confidence=0.8),
        graph_metrics={
            "row_count": 8,
            "item_row_ratio": 0.5,
            "row_math_fail_count": 4,
            "missing_req_cols": ["amount", "rate"],
        },
        graph_score=71.25,
        graph_selection_blocked_reason="graph_row_math_regression",
        selected_topology_source="heuristic_anchor",
        selected_candidate_reason="heuristic_preferred_due_to_block_graph_row_math_regression",
        tsr_status_metric={
            "ppstructure_enabled": False,
            "ppstructure_skipped_reason": "disabled_by_config",
            "ppstructure_cells_attempted": 0,
            "ppstructure_success": False,
        },
    )

    encoded = json.dumps(summary)
    decoded = json.loads(encoded)

    assert decoded["selected"] == "heuristic_anchor"
    assert decoded["reason"] == "heuristic_preferred_due_to_block_graph_row_math_regression"
    assert decoded["candidates"]["heuristic_anchor"]["score"] == 82.5
    assert decoded["candidates"]["heuristic_anchor"]["item_rows"] == 7
    assert decoded["candidates"]["graph"]["blocked_by"] == ["graph_row_math_regression"]
    assert decoded["candidates"]["graph"]["semantic_gaps"] == 2


def test_tsr_candidate_decision_summary_uses_unknowns_for_missing_values():
    summary = build_tsr_candidate_decision_summary()

    assert summary["selected"] == "unknown"
    assert summary["reason"] == "unknown"
    assert summary["candidates"]["heuristic_anchor"]["available"] is False
    assert summary["candidates"]["heuristic_anchor"]["score"] is None
    assert summary["candidates"]["graph"]["blocked_by"] == []
    assert "candidate_score_not_available_without_ranking" in summary["notes"]


def test_tsr_candidate_decision_summary_marks_ppstructure_disabled():
    summary = build_tsr_candidate_decision_summary(
        selected_topology_source="heuristic_anchor",
        selected_candidate_reason="default_heuristic",
        tsr_status_metric={
            "ppstructure_enabled": False,
            "ppstructure_skipped_reason": "disabled_by_config",
            "ppstructure_cells_attempted": 0,
            "ppstructure_success": False,
        },
    )

    ppstructure = summary["candidates"]["ppstructure"]

    assert ppstructure["available"] is False
    assert ppstructure["enabled"] is False
    assert ppstructure["skipped_reason"] == "disabled_by_config"
    assert ppstructure["blocked_by"] == ["disabled_by_config"]


def test_row_handoff_summary_flags_graph_to_raw_ocr_mismatch():
    summary = build_row_handoff_summary(
        selected_topology_source="document_graph_candidate",
        topology_source="document_graph_candidate",
        selected_main_table=_candidate(rows=16, columns=13, cells=208, confidence=1.0),
        item_rows_clean=[
            {
                "source": "raw_ocr_coordinate_reconstruction",
                "hsn": "",
                "qty": "",
                "rate": "",
                "low_confidence": True,
                "confidence_reasons": ["missing_hsn", "missing_qty", "missing_rate"],
            }
        ],
        clean_item_row_validation_errors=[
            {"reason": "missing_hsn;missing_qty"},
        ],
        reconciliation_result={"rows_math_failed": 7, "rows_math_passed": 0},
        graph_metrics={"row_math_fail_count": 1},
        heuristic_metrics={"row_math_fail_count": 0},
    )

    encoded = json.dumps(summary)
    decoded = json.loads(encoded)

    assert decoded["handoff_mismatch"] is True
    assert "graph_selected_but_item_rows_clean_uses_raw_ocr" in decoded["handoff_mismatch_reasons"]
    assert "final_reconciliation_math_failures_exceed_candidate_graph_failures" in decoded["handoff_mismatch_reasons"]
    assert decoded["dominant_item_rows_clean_source"] == "raw_ocr_coordinate_reconstruction"
    assert decoded["item_rows_clean_sources"] == {"raw_ocr_coordinate_reconstruction": 1}
    assert decoded["clean_item_row_validation_error_reasons"] == {"missing_hsn": 1, "missing_qty": 1}


def test_row_handoff_summary_no_mismatch_when_sources_align():
    summary = build_row_handoff_summary(
        selected_topology_source="document_graph_candidate",
        topology_source="document_graph_candidate",
        selected_main_table=_candidate(rows=2, columns=3, cells=6, confidence=0.8),
        item_rows_clean=[
            {
                "source": "document_graph_candidate",
                "hsn": "300490",
                "qty": "1",
                "rate": "10.00",
                "low_confidence": False,
                "confidence_reasons": [],
            }
        ],
        clean_item_row_validation_errors=[],
        reconciliation_result={"rows_math_failed": 1, "rows_math_passed": 2},
        graph_metrics={"row_math_fail_count": 1},
        heuristic_metrics={"row_math_fail_count": 2},
    )

    assert summary["handoff_mismatch"] is False
    assert summary["handoff_mismatch_reasons"] == []
    assert summary["dominant_item_rows_clean_source"] == "document_graph_candidate"


def test_row_handoff_summary_handles_missing_values():
    summary = build_row_handoff_summary()

    assert summary["selected_topology_source"] == "unknown"
    assert summary["selected_main_table_id"] == "unknown"
    assert summary["selected_main_table_rows"] is None
    assert summary["item_rows_clean_count"] is None
    assert summary["dominant_item_rows_clean_source"] == "unknown"
    assert summary["handoff_mismatch"] is False
    json.dumps(summary)
