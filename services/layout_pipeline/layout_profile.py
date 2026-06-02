from __future__ import annotations

from typing import Any, Dict, List

from services.layout_pipeline.canonical_invoice import CanonicalInvoice


EXPECTED_FOOTER_FIELDS = ("subtotal", "discount", "sgst", "cgst", "grand_total")


def classify_layout_profile(canonical_invoice: CanonicalInvoice, raw_result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    raw_result = raw_result if isinstance(raw_result, dict) else {}
    metrics = canonical_invoice.metrics or {}
    missing_footer = [
        field for field in EXPECTED_FOOTER_FIELDS
        if canonical_invoice.get_footer_value(field) in (None, "")
    ]
    rows_missing_core = [
        row.row_id for row in canonical_invoice.item_rows
        if row.qty in (None, "") or row.rate in (None, "") or row.amount in (None, "")
    ]

    row_math_passed = _safe_int(metrics.get("rows_math_passed"))
    row_math_failed = _safe_int(metrics.get("rows_math_failed"))
    item_row_count = len(canonical_invoice.item_rows)
    footer_field_count = len(canonical_invoice.footer_fields)
    confidence = canonical_invoice.confidence
    row_math_missing = item_row_count > 0 and row_math_passed is None and row_math_failed is None
    row_math_failure_rate = None
    if row_math_passed is not None or row_math_failed is not None:
        passed = row_math_passed or 0
        failed = row_math_failed or 0
        denominator = passed + failed
        row_math_failure_rate = (failed / denominator) if denominator else None

    issues: List[str] = []
    if missing_footer:
        issues.append("footer_missing")
    if "grand_total" in missing_footer:
        issues.append("grand_total_missing")
    if row_math_missing:
        issues.append("row_math_metrics_missing")
    if row_math_failure_rate is not None and row_math_failure_rate >= 0.5:
        issues.append("row_math_risk")
    if rows_missing_core:
        issues.append("item_row_core_fields_missing")
    if confidence is None or confidence < 0.4:
        issues.append("low_confidence")

    if row_math_failure_rate is not None and row_math_failure_rate >= 0.5:
        profile = "row_math_risk"
    elif missing_footer and item_row_count >= 1:
        profile = "borderless_footer_risk" if footer_field_count <= 2 else "footer_missing"
    elif item_row_count >= 8 and rows_missing_core:
        profile = "dense_pharma_table"
    elif item_row_count and not missing_footer and not issues:
        profile = "standard_like"
    elif missing_footer:
        profile = "footer_missing"
    else:
        profile = "unknown"

    return {
        "profile": profile,
        "signals": {
            "item_row_count": item_row_count,
            "footer_field_count": footer_field_count,
            "missing_footer_fields": missing_footer,
            "row_math_passed": row_math_passed,
            "row_math_failed": row_math_failed,
            "row_math_missing": row_math_missing,
            "row_math_failure_rate": row_math_failure_rate,
            "rows_missing_qty_rate_amount": len(rows_missing_core),
            "confidence": confidence,
            "raw_token_count": metrics.get("raw_token_count"),
            "ocr_block_count": metrics.get("ocr_block_count"),
        },
        "issues": issues,
    }


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
