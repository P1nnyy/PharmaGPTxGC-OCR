from typing import Any, Dict


def _safe_count(value: Any) -> int:
    try:
        return len(value)
    except Exception:
        return 0


def _safe_float(value: Any):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_shape(candidate: Any) -> Dict[str, Any]:
    if candidate is None:
        return {
            "available": False,
            "rows": None,
            "columns": None,
            "cells": None,
            "confidence": None,
        }
    return {
        "available": True,
        "rows": _safe_count(getattr(candidate, "rows", None)),
        "columns": _safe_count(getattr(candidate, "columns", None)),
        "cells": _safe_count(getattr(candidate, "cells", None)),
        "confidence": _safe_float(getattr(candidate, "topology_confidence", None)),
    }


def _item_rows_from_metrics(metrics: Dict[str, Any]) -> Any:
    row_count = metrics.get("row_count")
    item_row_ratio = metrics.get("item_row_ratio")
    if row_count is None or item_row_ratio is None:
        return None
    try:
        return int(round(float(row_count) * float(item_row_ratio)))
    except (TypeError, ValueError):
        return None


def _candidate_summary(
    candidate: Any,
    metrics: Dict[str, Any],
    score: Any,
    source: str,
    blocked_by=None,
) -> Dict[str, Any]:
    metrics = metrics or {}
    blocked_by = blocked_by or []
    shape = _candidate_shape(candidate)
    missing_req_cols = metrics.get("missing_req_cols")
    if isinstance(missing_req_cols, (list, tuple, set)):
        semantic_gaps = len(missing_req_cols)
    else:
        semantic_gaps = None

    return {
        **shape,
        "item_rows": _item_rows_from_metrics(metrics),
        "math_failures": metrics.get("row_math_fail_count"),
        "semantic_gaps": semantic_gaps,
        "score": _safe_float(score),
        "confidence": shape["confidence"],
        "source": source,
        "blocked_by": list(blocked_by),
    }


def build_tsr_candidate_decision_summary(
    heuristic_candidate: Any = None,
    heuristic_metrics: Dict[str, Any] = None,
    heuristic_score: Any = None,
    graph_candidate: Any = None,
    graph_metrics: Dict[str, Any] = None,
    graph_score: Any = None,
    graph_selection_blocked_reason: Any = None,
    selected_topology_source: Any = None,
    selected_candidate_reason: Any = None,
    tsr_status_metric: Dict[str, Any] = None,
    tsr_metadata: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Build a JSON-safe diagnostics-only summary of TSR candidate selection."""
    tsr_status_metric = tsr_status_metric or {}
    tsr_metadata = tsr_metadata or {}
    notes = []

    graph_blockers = [graph_selection_blocked_reason] if graph_selection_blocked_reason else []

    ppstructure_enabled = bool(tsr_status_metric.get("ppstructure_enabled"))
    ppstructure_skipped_reason = tsr_status_metric.get("ppstructure_skipped_reason")
    ppstructure_success = bool(tsr_status_metric.get("ppstructure_success"))
    ppstructure_blockers = []
    if not ppstructure_enabled:
        ppstructure_blockers.append(ppstructure_skipped_reason or "disabled_by_config")
    elif tsr_status_metric.get("ppstructure_zero_output"):
        ppstructure_blockers.append("zero_tables_cells")
    elif tsr_status_metric.get("fallback_used"):
        ppstructure_blockers.append("confidence_below_threshold")

    ppstructure_score = tsr_metadata.get("orientation_score")
    ppstructure_confidence = tsr_status_metric.get("ppstructure_confidence")
    if ppstructure_enabled and ppstructure_score is None:
        notes.append("ppstructure_score_not_available_without_recomputing")

    if heuristic_score is None or graph_score is None:
        notes.append("candidate_score_not_available_without_ranking")

    return {
        "candidates": {
            "heuristic_anchor": _candidate_summary(
                heuristic_candidate,
                heuristic_metrics or {},
                heuristic_score,
                "heuristic_anchor",
                blocked_by=[],
            ),
            "graph": _candidate_summary(
                graph_candidate,
                graph_metrics or {},
                graph_score,
                "document_graph_candidate",
                blocked_by=graph_blockers,
            ),
            "ppstructure": {
                "available": ppstructure_success,
                "enabled": ppstructure_enabled,
                "skipped_reason": ppstructure_skipped_reason,
                "rows": None,
                "columns": None,
                "cells": tsr_status_metric.get("ppstructure_cells_attempted"),
                "score": _safe_float(ppstructure_score),
                "confidence": _safe_float(ppstructure_confidence),
                "source": "ppstructure",
                "blocked_by": ppstructure_blockers,
            },
        },
        "selected": selected_topology_source or "unknown",
        "reason": selected_candidate_reason or "unknown",
        "notes": notes,
    }


def _compute_tsr_confidence(table_regions) -> float:
    """
    Evaluate aggregate TSR output quality to decide if PPStructure topology is trustworthy.
    Returns 0.0-1.0 confidence score.

    Signals checked:
    - At least one table detected
    - Tables have reasonable cell counts
    - topology_confidence values from the engine are acceptable
    """
    if not table_regions:
        return 0.0

    confidences = [tr.topology_confidence for tr in table_regions]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    # Check for degenerate tables (tables with zero cells)
    total_cells = sum(len(tr.cells) for tr in table_regions)
    if total_cells == 0:
        return 0.0

    # A single table with very few cells on a full invoice is suspicious
    if len(table_regions) == 1 and total_cells < 3:
        avg_confidence *= 0.5

    return round(avg_confidence, 3)


def _invoice_footer_tax_source_counts(invoice_reconciliation: Dict[str, Any]) -> Dict[str, int]:
    footer_labels = {
        "parsed_subtotal",
        "discount",
        "roundoff",
        "cr_dr_note",
        "parsed_grand_total",
    }
    tax_labels = {"sgst", "cgst", "igst"}
    footer_rows = set()
    tax_rows = set()

    for source_map in (
        invoice_reconciliation.get("sources") or {},
        invoice_reconciliation.get("ignored_sources") or {},
    ):
        for label, source_or_sources in source_map.items():
            sources = source_or_sources if isinstance(source_or_sources, list) else [source_or_sources]
            for source in sources:
                if not isinstance(source, dict):
                    continue
                row_key = (source.get("table_id"), source.get("row_id"))
                if not row_key[0] or not row_key[1]:
                    continue
                if label in tax_labels:
                    tax_rows.add(row_key)
                elif label in footer_labels:
                    footer_rows.add(row_key)

    return {
        "footer_rows_count": len(footer_rows),
        "tax_rows_count": len(tax_rows),
    }
