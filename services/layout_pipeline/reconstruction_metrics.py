from typing import Any, Dict


def _count_or_none(value: Any):
    if value is None:
        return None
    try:
        return len(value)
    except Exception:
        return None


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


def _safe_int(value: Any):
    if value is None:
        return None
    try:
        return int(value)
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


def _count_item_row_sources(item_rows_clean: Any) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not isinstance(item_rows_clean, list):
        return counts
    for row in item_rows_clean:
        if not isinstance(row, dict):
            source = "unknown"
        else:
            source = row.get("source") or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return counts


def _dominant_source(source_counts: Dict[str, int]) -> str:
    if not source_counts:
        return "unknown"
    return sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _validation_error_reasons(errors: Any) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not isinstance(errors, list):
        return counts
    for error in errors:
        reason = error.get("reason") if isinstance(error, dict) else None
        if not reason:
            reason = "unknown"
        for part in str(reason).split(";"):
            key = part.strip() or "unknown"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _missing_key_column_counts(item_rows_clean: Any) -> Dict[str, int]:
    counts = {"hsn": 0, "qty": 0, "rate": 0}
    if not isinstance(item_rows_clean, list):
        return counts
    for row in item_rows_clean:
        if not isinstance(row, dict):
            continue
        reasons = set(row.get("confidence_reasons") or [])
        if not row.get("hsn") or "missing_hsn" in reasons:
            counts["hsn"] += 1
        if not row.get("qty") or "missing_qty" in reasons:
            counts["qty"] += 1
        if not row.get("rate") or "missing_rate" in reasons:
            counts["rate"] += 1
    return counts


def _non_empty_cell_count(table: Any):
    cells = getattr(table, "cells", None)
    if cells is None:
        return None
    count = 0
    for cell in cells:
        text = getattr(cell, "text", None)
        mapped_ids = getattr(cell, "mapped_block_ids", None)
        if (isinstance(text, str) and text.strip()) or bool(mapped_ids):
            count += 1
    return count


def build_row_handoff_summary(
    selected_topology_source: Any = None,
    topology_source: Any = None,
    selected_main_table: Any = None,
    item_rows_clean: Any = None,
    clean_item_row_validation_errors: Any = None,
    reconciliation_result: Dict[str, Any] = None,
    graph_metrics: Dict[str, Any] = None,
    heuristic_metrics: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Build diagnostics explaining selected topology versus final clean item-row source."""
    reconciliation_result = reconciliation_result or {}
    graph_metrics = graph_metrics or {}
    heuristic_metrics = heuristic_metrics or {}

    rows = getattr(selected_main_table, "rows", None)
    columns = getattr(selected_main_table, "columns", None)
    cells = getattr(selected_main_table, "cells", None)
    item_rows_clean_count = _count_or_none(item_rows_clean)
    source_counts = _count_item_row_sources(item_rows_clean)
    dominant_source = _dominant_source(source_counts)
    validation_reason_counts = _validation_error_reasons(clean_item_row_validation_errors)
    missing_key_counts = _missing_key_column_counts(item_rows_clean)

    reconciliation_rows_math_failed = _safe_int(reconciliation_result.get("rows_math_failed"))
    reconciliation_rows_math_passed = _safe_int(reconciliation_result.get("rows_math_passed"))
    candidate_graph_math_failures = _safe_int(graph_metrics.get("row_math_fail_count"))
    candidate_heuristic_math_failures = _safe_int(heuristic_metrics.get("row_math_fail_count"))
    selected_column_count = _count_or_none(columns)

    mismatch_reasons = []
    if (
        selected_topology_source == "document_graph_candidate"
        and dominant_source == "raw_ocr_coordinate_reconstruction"
    ):
        mismatch_reasons.append("graph_selected_but_item_rows_clean_uses_raw_ocr")

    if selected_column_count is not None and selected_column_count >= 4 and any(missing_key_counts.values()):
        missing = [
            field
            for field, count in missing_key_counts.items()
            if count > 0
        ]
        mismatch_reasons.append("selected_table_has_many_columns_but_clean_rows_missing_" + "_".join(missing))

    if (
        candidate_graph_math_failures is not None
        and reconciliation_rows_math_failed is not None
        and reconciliation_rows_math_failed > candidate_graph_math_failures + 1
    ):
        mismatch_reasons.append("final_reconciliation_math_failures_exceed_candidate_graph_failures")

    notes = [
        "item_rows_clean_source_is_generated_by_table_segmenter",
        "candidate_graph_math_failures_are_from_row_validator_candidate_scoring",
        "reconciliation_rows_math_failed_is_from_financial_reconciler",
    ]
    if selected_main_table is None:
        notes.append("selected_main_table_unavailable")
    if item_rows_clean_count is None:
        notes.append("item_rows_clean_unavailable")

    return {
        "selected_topology_source": selected_topology_source or "unknown",
        "topology_source": topology_source or "unknown",
        "selected_main_table_id": getattr(selected_main_table, "table_id", None) or "unknown",
        "selected_main_table_source": getattr(selected_main_table, "source_engine", None) or "unknown",
        "selected_main_table_rows": _count_or_none(rows),
        "selected_main_table_columns": selected_column_count,
        "selected_main_table_cells": _count_or_none(cells),
        "selected_main_table_non_empty_cells": _non_empty_cell_count(selected_main_table),
        "item_rows_clean_count": item_rows_clean_count,
        "item_rows_clean_sources": source_counts,
        "dominant_item_rows_clean_source": dominant_source,
        "item_rows_clean_low_confidence_count": (
            sum(1 for row in item_rows_clean if isinstance(row, dict) and row.get("low_confidence"))
            if isinstance(item_rows_clean, list)
            else None
        ),
        "clean_item_row_validation_error_count": _count_or_none(clean_item_row_validation_errors),
        "clean_item_row_validation_error_reasons": validation_reason_counts,
        "reconciliation_rows_math_failed": reconciliation_rows_math_failed,
        "reconciliation_rows_math_passed": reconciliation_rows_math_passed,
        "candidate_graph_math_failures": candidate_graph_math_failures,
        "candidate_heuristic_math_failures": candidate_heuristic_math_failures,
        "handoff_mismatch": bool(mismatch_reasons),
        "handoff_mismatch_reasons": mismatch_reasons,
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
