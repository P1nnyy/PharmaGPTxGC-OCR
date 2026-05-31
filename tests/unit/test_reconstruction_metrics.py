import json
from types import SimpleNamespace

from services.layout_pipeline.reconstruction_metrics import build_tsr_candidate_decision_summary


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
