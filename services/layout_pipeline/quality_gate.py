from __future__ import annotations

from typing import Any, Dict

from services.layout_pipeline.canonical_invoice import CanonicalInvoice
from services.layout_pipeline.layout_profile import EXPECTED_FOOTER_FIELDS


DEFAULT_CONFIDENCE_THRESHOLD = 0.40


def evaluate_invoice_quality(canonical_invoice: CanonicalInvoice, raw_result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    raw_result = raw_result if isinstance(raw_result, dict) else {}
    metrics = canonical_invoice.metrics or {}
    reasons = []
    confidence = canonical_invoice.confidence
    item_row_count = len(canonical_invoice.item_rows)
    footer_field_count = len(canonical_invoice.footer_fields)

    ocr_blocks = raw_result.get("blocks")
    raw_token_count = metrics.get("raw_token_count")
    if raw_result.get("pipeline_crashed") or raw_result.get("error") or raw_result.get("errors"):
        reasons.append("pipeline_error")
    if isinstance(ocr_blocks, list) and len(ocr_blocks) == 0:
        reasons.append("no_ocr_blocks")
    elif raw_token_count == 0:
        reasons.append("no_ocr_blocks")
    if raw_result.get("fast_fail"):
        reasons.append(f"fast_fail:{raw_result.get('fast_fail_reason') or 'unknown'}")
    metrics_obj = raw_result.get("metrics") if isinstance(raw_result.get("metrics"), dict) else {}
    if raw_result.get("fast_fail_reason") == "no_valid_table_candidate" or metrics_obj.get("no_valid_table_candidate"):
        reasons.append("no_valid_table_candidate")
    if metrics_obj.get("selected_table_available") is False or raw_result.get("selected_table_available") is False:
        reasons.append("no_valid_table_candidate")
    table_sanity = metrics_obj.get("table_sanity") if isinstance(metrics_obj.get("table_sanity"), dict) else {}
    selected_id = table_sanity.get("selected_candidate_id")
    if selected_id:
        for candidate in table_sanity.get("per_candidate", []):
            if isinstance(candidate, dict) and candidate.get("table_id") == selected_id and "coordinate_space_violation" in (candidate.get("rejection_reasons") or []):
                reasons.append("coordinate_space_violation")
    if item_row_count == 0:
        reasons.append("no_item_rows")

    if confidence is None:
        reasons.append("missing_invoice_confidence")
    elif confidence <= 0.0:
        reasons.append("zero_invoice_confidence")
    elif confidence < DEFAULT_CONFIDENCE_THRESHOLD:
        reasons.append("low_invoice_confidence")

    rows_math_passed = _safe_int(metrics.get("rows_math_passed"))
    rows_math_failed = _safe_int(metrics.get("rows_math_failed"))
    row_math_details_count = _safe_int(metrics.get("row_math_details_count"))
    row_math_repair = raw_result.get("row_math_repair") if isinstance(raw_result.get("row_math_repair"), dict) else {}
    repair_summary = row_math_repair.get("summary") if isinstance(row_math_repair.get("summary"), dict) else {}
    repair_candidates = _safe_int(repair_summary.get("candidate_count")) or 0
    repair_applied = _safe_int(repair_summary.get("applied_count")) or 0
    repair_still_failed = _safe_int(repair_summary.get("still_failed_count"))
    if item_row_count > 0 and rows_math_passed is None and rows_math_failed is None:
        reasons.append("row_math_metrics_missing")
    elif item_row_count > 0 and (rows_math_passed or 0) == 0 and (rows_math_failed or 0) == 0:
        if row_math_details_count in (None, 0):
            reasons.append("row_math_metrics_missing")
        else:
            reasons.append("row_math_unmeasurable")
    elif rows_math_failed is not None:
        measurable = (rows_math_passed or 0) + rows_math_failed
        repaired_all_checked = repair_applied > 0 and repair_still_failed == 0
        if rows_math_failed > 0 and not repaired_all_checked and (measurable == 0 or rows_math_failed / measurable >= 0.5):
            reasons.append("row_math_failed_high")
    if repair_candidates > repair_applied:
        reasons.append("row_math_repair_candidates_unapplied")

    missing_footer_fields = [
        field for field in EXPECTED_FOOTER_FIELDS
        if canonical_invoice.get_footer_value(field) in (None, "")
    ]
    if missing_footer_fields:
        reasons.append("footer_fields_missing:" + ",".join(missing_footer_fields))

    # ── Wide-table quality checks ──────────────────────────────────
    metrics_obj = raw_result.get("metrics") if isinstance(raw_result.get("metrics"), dict) else {}
    wide_diag = metrics_obj.get("wide_table_diagnostics") or raw_result.get("wide_table_diagnostics") or {}
    if isinstance(wide_diag, dict) and wide_diag.get("wide_table_mode"):
        # Check 1: Wide table collapsed below minimum column count
        estimated_cols = wide_diag.get("estimated_column_count", 0)
        # Use the canonical table column count from metrics if available
        actual_col_count = metrics_obj.get("column_count") or metrics_obj.get("col_count") or 0
        if isinstance(actual_col_count, int) and actual_col_count < 10 and estimated_cols >= 10:
            reasons.append("wide_table_collapsed")
        if wide_diag.get("column_expansion_failed"):
            reasons.append("wide_table_column_expansion_failed")

    # Check 2: Excessive UNKNOWN semantic columns
    semantic_results = metrics_obj.get("semantic_column_results") or {}
    if isinstance(semantic_results, dict):
        total_cols = 0
        unknown_cols = 0
        for table_data in semantic_results.values():
            if not isinstance(table_data, dict):
                continue
            for col_id, col_data in table_data.items():
                if col_id.startswith("_"):
                    continue
                if isinstance(col_data, dict):
                    total_cols += 1
                    if col_data.get("type") == "unknown":
                        unknown_cols += 1
        if total_cols >= 4 and unknown_cols > total_cols * 0.5:
            reasons.append(f"excessive_unknown_columns:{unknown_cols}/{total_cols}")

    reasons = list(dict.fromkeys(reasons))
    hard_fail_reasons = {"pipeline_error", "no_ocr_blocks", "no_item_rows", "no_valid_table_candidate", "coordinate_space_violation"}
    if any(reason in hard_fail_reasons or reason.startswith("fast_fail:") for reason in reasons):
        status = "failed"
    elif reasons:
        status = "needs_review"
    else:
        status = "ok"

    return {
        "status": status,
        "reasons": reasons,
        "confidence": confidence,
        "confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
        "item_row_count": item_row_count,
        "footer_field_count": footer_field_count,
        "metrics": {
            "rows_math_passed": rows_math_passed,
            "rows_math_failed": rows_math_failed,
            "row_math_details_count": row_math_details_count,
            "missing_footer_fields": missing_footer_fields,
            "row_math_repair_candidates": repair_candidates,
            "row_math_repairs_applied": repair_applied,
            "row_math_repair_still_failed": repair_still_failed,
        },
        "safe_for_erp": status == "ok",
    }


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
