"""
Topology Integrity & Financial Validation — THIN WRAPPER.

Delegates ALL validation logic to the live services.financial_reconciler module.
Preserves backward-compatible function signatures consumed by:
  - scripts/run_benchmark.sh
  - verification/scripts/run_full_verification.py
"""

import os
import sys
import json
from typing import List, Dict, Any, Optional

try:
    import structlog
    log = structlog.get_logger()
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO)
    class _CompatLogger:
        def __init__(self):
            self._logger = logging.getLogger(__name__)
        def info(self, event, **kwargs):
            self._logger.info("%s %s", event, kwargs)
        def warning(self, event, **kwargs):
            self._logger.warning("%s %s", event, kwargs)
        def error(self, event, **kwargs):
            self._logger.error("%s %s", event, kwargs)
    log = _CompatLogger()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

def _first_dict_value(data: Dict[str, Any]) -> Dict[str, Any]:
    for value in data.values():
        if isinstance(value, dict):
            return value
    return {}

def _sum_row_validation(row_validation: Dict[str, Any]) -> Dict[str, int]:
    totals = {
        "items": 0,
        "math_confirmed_rows": 0,
        "math_failed_rows": 0,
    }
    for value in row_validation.values():
        if not isinstance(value, dict):
            continue
        totals["items"] += int(value.get("total_rows", 0) or 0)
        totals["math_confirmed_rows"] += int(value.get("financial_passes", 0) or 0)
        totals["math_failed_rows"] += int(value.get("financial_failures", 0) or 0)
    return totals

def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default

def _metric(metrics: Dict[str, Any], key: str, default: Any = None) -> Any:
    if key in metrics:
        return metrics.get(key)
    instrumentation = metrics.get("instrumentation") or {}
    return instrumentation.get(key, default)

def _extract_type_map(data: Dict[str, Any]) -> Dict[str, str]:
    type_map = {}
    if not isinstance(data, dict):
        return type_map
    for col_id, meta in data.items():
        if str(col_id).startswith("_"):
            continue
        if isinstance(meta, dict):
            semantic_type = meta.get("type")
        else:
            semantic_type = meta
        if semantic_type:
            type_map[str(col_id)] = str(semantic_type).lower()
    return type_map

def _semantic_map_from(value: Any, main_table_id: Optional[str]) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    if main_table_id and isinstance(value.get(main_table_id), dict):
        return _extract_type_map(value[main_table_id])

    direct = _extract_type_map(value)
    if direct:
        return direct

    for nested in value.values():
        if isinstance(nested, dict):
            nested_map = _extract_type_map(nested)
            if nested_map:
                return nested_map
    return {}

def _semantic_breakdown(final_semantics: Dict[str, str]) -> Dict[str, int]:
    breakdown: Dict[str, int] = {}
    for semantic_type in final_semantics.values():
        key = str(semantic_type or "unknown").lower()
        breakdown[key] = breakdown.get(key, 0) + 1
    return breakdown

def _format_breakdown(breakdown: Dict[str, int]) -> str:
    if not breakdown:
        return "n/a"
    return ", ".join(f"{key}:{breakdown[key]}" for key in sorted(breakdown))

def _select_main_table_id(
    metadata: Dict[str, Any],
    metrics: Dict[str, Any],
    row_validation: Dict[str, Any],
    reconciliation: Dict[str, Any],
) -> Optional[str]:
    for source in (row_validation, reconciliation):
        if isinstance(source, dict):
            for key, value in source.items():
                if isinstance(value, dict) and not str(key).startswith("_"):
                    return str(key)

    semantic_debug = metrics.get("semantic_debug") or {}
    for source in (
        semantic_debug.get("final_column_semantics"),
        metrics.get("final_column_semantics"),
        metrics.get("column_semantic_cache"),
    ):
        if isinstance(source, dict):
            for key, value in source.items():
                if isinstance(value, dict) and not str(key).startswith("_"):
                    return str(key)

    topology_debug = metrics.get("topology_debug") or {}
    main_tables = topology_debug.get("main_tables") or []
    if main_tables and isinstance(main_tables[0], dict):
        table_id = main_tables[0].get("table_id")
        if table_id:
            return str(table_id)

    structured_tables = metadata.get("structured_tables") or []
    if structured_tables:
        best = max(
            structured_tables,
            key=lambda table: (
                len(table.get("rows") or []),
                len(table.get("cells") or []),
                len(table.get("columns") or []),
            ),
        )
        return best.get("table_id")
    return None

def _find_table(metadata: Dict[str, Any], metrics: Dict[str, Any], table_id: Optional[str]) -> Dict[str, Any]:
    structured_tables = metadata.get("structured_tables") or []
    if table_id:
        for table in structured_tables:
            if table.get("table_id") == table_id:
                return table
    if structured_tables:
        return max(
            structured_tables,
            key=lambda table: (
                len(table.get("rows") or []),
                len(table.get("cells") or []),
                len(table.get("columns") or []),
            ),
        )

    topology_debug = metrics.get("topology_debug") or {}
    main_tables = topology_debug.get("main_tables") or []
    if table_id:
        for table in main_tables:
            if table.get("table_id") == table_id:
                return table
    return main_tables[0] if main_tables else {}

def _row_validation_for_table(row_validation: Dict[str, Any], table_id: Optional[str]) -> Dict[str, Any]:
    if not isinstance(row_validation, dict):
        return {}
    if table_id and isinstance(row_validation.get(table_id), dict):
        return row_validation[table_id]
    return _first_dict_value(row_validation)

def _item_row_cell_stats(table: Dict[str, Any], table_row_validation: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = table_row_validation.get("row_diagnostics") if isinstance(table_row_validation, dict) else None
    if isinstance(diagnostics, list) and diagnostics:
        item_diags = [d for d in diagnostics if d.get("row_role") == "item_row"] or diagnostics
        counts = [
            _safe_int(d.get("populated_count"), _safe_int(d.get("cell_count"), 0))
            for d in item_diags
        ]
        counts = [c for c in counts if c >= 0]
        if counts:
            return {
                "avg_cells_per_item_row": round(sum(counts) / len(counts), 2),
                "one_cell_item_rows_count": sum(1 for count in counts if count <= 1),
            }

    rows = table.get("rows") or []
    cells = table.get("cells") or table.get("current_reconstructed_cells") or []
    if not rows:
        return {"avg_cells_per_item_row": 0.0, "one_cell_item_rows_count": 0}

    row_roles = {
        row.get("row_id"): row.get("row_role", "unknown_row")
        for row in rows
        if isinstance(row, dict)
    }
    item_row_ids = [row_id for row_id, role in row_roles.items() if role == "item_row"] or list(row_roles.keys())
    counts = []
    for row_id in item_row_ids:
        row_cells = [cell for cell in cells if cell.get("row_id") == row_id]
        populated = [cell for cell in row_cells if str(cell.get("text") or "").strip()]
        counts.append(len(populated) if populated else len(row_cells))

    if not counts:
        return {"avg_cells_per_item_row": 0.0, "one_cell_item_rows_count": 0}
    return {
        "avg_cells_per_item_row": round(sum(counts) / len(counts), 2),
        "one_cell_item_rows_count": sum(1 for count in counts if count <= 1),
    }

def _extract_topology_fields(
    filepath: str,
    data: Dict[str, Any],
    row_validation: Optional[Dict[str, Any]] = None,
    reconciliation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = data.get("metadata") or {}
    metrics = metadata.get("metrics") or {}
    row_validation = row_validation if row_validation is not None else (metrics.get("row_validation") or {})
    reconciliation = reconciliation if reconciliation is not None else (metrics.get("financial_reconciliation") or {})

    main_table_id = _select_main_table_id(metadata, metrics, row_validation, reconciliation)
    main_table = _find_table(metadata, metrics, main_table_id)
    table_row_validation = _row_validation_for_table(row_validation, main_table_id)
    cell_stats = _item_row_cell_stats(main_table, table_row_validation)

    semantic_debug = metrics.get("semantic_debug") or {}
    final_semantics = (
        _semantic_map_from(semantic_debug.get("final_column_semantics"), main_table_id)
        or _semantic_map_from(metrics.get("final_column_semantics"), main_table_id)
        or _semantic_map_from(metrics.get("column_semantic_cache"), main_table_id)
    )
    semantic_breakdown = _semantic_breakdown(final_semantics)
    semantic_types = set(semantic_breakdown.keys())

    anchor_repair = metrics.get("anchor_repair") or {}
    missing_semantic_columns = []
    if isinstance(table_row_validation, dict):
        missing_semantic_columns = table_row_validation.get("missing_semantic_columns") or []

    topology_debug = metrics.get("topology_debug") or {}
    topology_main = {}
    for table in topology_debug.get("main_tables") or []:
        if not main_table_id or table.get("table_id") == main_table_id:
            topology_main = table
            break

    row_count = len(main_table.get("rows") or [])
    col_count = len(main_table.get("columns") or [])
    if not row_count:
        row_count = _safe_int(topology_main.get("row_count"), _safe_int(table_row_validation.get("total_rows"), 0))
    if not col_count:
        col_count = _safe_int(topology_main.get("column_count"), 0)

    topology_source = (
        metadata.get("topology_source")
        or metrics.get("topology_source")
        or (metrics.get("tsr_status") or {}).get("topology_source")
        or main_table.get("source_engine")
        or "unknown"
    )
    invoice_confidence = (
        _safe_float(metadata.get("invoice_confidence"), None)
        or _safe_float((metrics.get("confidence_hierarchy") or {}).get("invoice_confidence"), None)
        or _safe_float(metrics.get("invoice_confidence"), None)
        or 0.0
    )

    return {
        "filename": os.path.basename(filepath),
        "topology_source": topology_source,
        "invoice_confidence": round(float(invoice_confidence), 3),
        "raw_token_count": _safe_int(metrics.get("raw_token_count"), len(metadata.get("blocks") or [])),
        "table_count": _safe_int(metrics.get("table_count"), len(metadata.get("structured_tables") or [])),
        "main_table_id": main_table_id or "unknown",
        "main_table_row_count": row_count,
        "main_table_column_count": col_count,
        "avg_cells_per_item_row": cell_stats["avg_cells_per_item_row"],
        "one_cell_item_rows_count": cell_stats["one_cell_item_rows_count"],
        "anchor_repair_enabled": bool(anchor_repair.get("enabled", False)),
        "before_column_count": _safe_int(anchor_repair.get("before_column_count"), 0),
        "after_column_count": _safe_int(anchor_repair.get("after_column_count"), 0),
        "final_semantic_breakdown": semantic_breakdown,
        "has_product_column": "product" in semantic_types,
        "has_batch_column": "batch" in semantic_types,
        "has_expiry_column": "expiry" in semantic_types,
        "has_qty_column": bool({"quantity", "qty", "free_quantity"} & semantic_types),
        "has_rate_column": "rate" in semantic_types,
        "has_amount_column": "amount" in semantic_types,
        "quarantined_cell_count": _safe_int(
            semantic_debug.get("quarantined_cell_count"),
            _safe_int(_metric(metrics, "quarantined_cell_count"), 0),
        ),
        "missing_semantic_columns_count": len(missing_semantic_columns),
        "missing_semantic_columns": missing_semantic_columns,
    }

def _runtime_schema_result(filepath: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    metadata = data.get("metadata", {})
    metrics = metadata.get("metrics") or {}
    reconciliation = metrics.get("financial_reconciliation") or {}
    row_validation = metrics.get("row_validation") or {}

    if not reconciliation and not row_validation:
        return None

    row_totals = _sum_row_validation(row_validation)
    rec = _first_dict_value(reconciliation)
    confidence = rec.get("confidence")
    score = _safe_float(rec.get("integrity_score"), None)
    if score is None:
        score = float(confidence) * 100.0 if confidence is not None else float(metadata.get("invoice_confidence") or 0) * 100.0
    status = str(rec.get("status", "")).upper()
    passed = status == "PASS" if status else score >= 70.0
    instrumentation = metrics.get("instrumentation") or {}
    confidence_variance = instrumentation.get("confidence_variance") or (metrics.get("confidence_hierarchy") or {}).get("confidence_variance") or {}
    topology_fields = _extract_topology_fields(filepath, data, row_validation, reconciliation)

    result = {
        "filename": os.path.basename(filepath),
        "integrity_score": round(score, 1),
        "passed": passed,
        "items": row_totals["items"] or rec.get("total_rows", 0),
        "math_confirmed_rows": row_totals["math_confirmed_rows"],
        "merged_column_warnings": metrics.get("numeric_merge_suspicions", 0),
        "derived_subtotal": float(rec.get("derived_subtotal", 0) or 0),
        "parsed_grand_total": float(rec.get("parsed_grand_total", 0) or 0),
        "discrepancy": float(rec.get("grand_total_discrepancy", 0) or 0),
        "warnings_log": rec.get("warnings", []),
        "schema_source_path": "metadata.metrics.financial_reconciliation",
        "tsr_contribution_percent": instrumentation.get("tsr_contribution_percent", metrics.get("tsr_contribution_percent")),
        "heuristic_fallback_used": instrumentation.get("heuristic_fallback_used", metrics.get("heuristic_fallback_used")),
        "semantic_rejection_count": instrumentation.get("semantic_rejection_count", metrics.get("semantic_rejection_count", 0)),
        "confidence_variance": confidence_variance,
        "financial_status": status or ("PASS" if passed else "FAIL"),
        "financial_score": round(score, 1),
    }
    result.update(topology_fields)
    return result

def _reconstruction_schema_result(filepath: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    metadata = data.get("metadata", {})
    rows = metadata.get("detected_table_rows") or [
        row for row in metadata.get("reconstructed_rows", [])
        if row.get("classification") in ("table", "medicine_table")
    ]
    if not rows and not metadata.get("structured_tables"):
        return None

    topology_fields = _extract_topology_fields(filepath, data)
    result = {
        "filename": os.path.basename(filepath),
        "integrity_score": 0.0,
        "passed": False,
        "items": len(rows),
        "math_confirmed_rows": 0,
        "merged_column_warnings": 0,
        "derived_subtotal": 0.0,
        "parsed_grand_total": 0.0,
        "discrepancy": 0.0,
        "warnings_log": ["Runtime metrics missing; counted reconstructed table rows only."],
        "schema_source_path": "metadata.detected_table_rows",
        "tsr_contribution_percent": None,
        "heuristic_fallback_used": None,
        "semantic_rejection_count": None,
        "confidence_variance": {},
        "financial_status": "MISSING",
        "financial_score": 0.0,
    }
    result.update(topology_fields)
    return result

def _llm_schema_result(filepath: str, llm_data: Dict[str, Any]) -> Dict[str, Any]:
    from services.financial_reconciler import validate_invoice_json as _live_validate
    live_result = _live_validate(llm_data)
    integrity_score = float(live_result.get("integrity_score", 0))
    return {
        "filename": os.path.basename(filepath),
        "integrity_score": round(integrity_score, 1),
        "passed": integrity_score >= 70.0,
        "items": live_result.get("total_rows", 0),
        "math_confirmed_rows": live_result.get("rows_math_passed", 0),
        "merged_column_warnings": 0,
        "derived_subtotal": float(live_result.get("derived_subtotal", 0)),
        "parsed_grand_total": float(live_result.get("parsed_grand_total", 0)),
        "discrepancy": float(live_result.get("grand_total_discrepancy", 0)),
        "warnings_log": live_result.get("warnings", []),
        "schema_source_path": "metadata.llm_extraction",
        "tsr_contribution_percent": None,
        "heuristic_fallback_used": None,
        "semantic_rejection_count": None,
        "confidence_variance": {},
        "financial_status": str(live_result.get("status", "")).upper() or "UNKNOWN",
        "financial_score": round(integrity_score, 1),
        **_extract_topology_fields(filepath, {}),
    }

def _unsupported_schema_result(filepath: str) -> Dict[str, Any]:
    return {
        "filename": os.path.basename(filepath),
        "integrity_score": 0.0,
        "passed": False,
        "items": 0,
        "math_confirmed_rows": 0,
        "merged_column_warnings": 0,
        "derived_subtotal": 0.0,
        "parsed_grand_total": 0.0,
        "discrepancy": 0.0,
        "warnings_log": ["No supported benchmark schema found."],
        "schema_source_path": "unsupported_schema",
        "tsr_contribution_percent": None,
        "heuristic_fallback_used": None,
        "semantic_rejection_count": None,
        "confidence_variance": {},
        "financial_status": "UNSUPPORTED",
        "financial_score": 0.0,
        **_extract_topology_fields(filepath, {}),
    }

def validate_invoice_json(filepath: str) -> Dict[str, Any]:
    """
    Load a benchmark result JSON and delegate to live reconciler.

    Backward-compatible return shape:
        filename, integrity_score, passed, items, math_confirmed_rows,
        merged_column_warnings, derived_subtotal, parsed_grand_total,
        discrepancy, warnings_log
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    runtime_result = _runtime_schema_result(filepath, data)
    if runtime_result:
        return runtime_result

    reconstruction_result = _reconstruction_schema_result(filepath, data)
    if reconstruction_result:
        log.warning("runtime_metrics_missing_using_reconstruction_rows", filepath=filepath)
        return reconstruction_result

    llm_data = data.get("metadata", {}).get("llm_extraction")
    if llm_data:
        return _llm_schema_result(filepath, llm_data)

    log.warning("no_supported_schema_found_falling_back_to_top_level", filepath=filepath)
    return _unsupported_schema_result(filepath)


# Preserved for run_full_verification.py backward compat
run_financial_validation = None  # defined below


def generate_validation_dashboard(results_dir: str, report_out: str):
    """Generate markdown dashboard from benchmark result JSONs."""
    os.makedirs(os.path.dirname(report_out), exist_ok=True)
    files = [
        os.path.join(results_dir, f)
        for f in os.listdir(results_dir)
        if f.endswith(".json")
    ]

    log.info("benchmark_validation_starting", file_count=len(files))

    results = []
    schema_sources = {}
    confidence_variances = []

    md = [
        "# Topology-First Benchmark Dashboard\n",
        "Reads live runtime topology metrics first, then includes financial reconciliation as a downstream signal.\n",
        "| Filename | Topology Source | Invoice Confidence | Raw Tokens | Tables | Main Table | Main Rows | Main Cols | Avg Cells / Item Row | One-Cell Item Rows | Anchor Repair | Before Cols | After Cols | Final Semantic Breakdown | Product | Batch | Expiry | Qty | Rate | Amount | Quarantined Cells | Missing Semantic Cols | Financial Status | Financial Score |",
        "| :--- | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for f in files:
        try:
            res = validate_invoice_json(f)
        except Exception as e:
            log.error("validation_file_error", filepath=f, error=str(e))
            continue

        results.append(res)
        md.append(
            f"| {res['filename']} "
            f"| {res.get('topology_source', 'unknown')} "
            f"| {res.get('invoice_confidence', 0):.3f} "
            f"| {res.get('raw_token_count', 0)} "
            f"| {res.get('table_count', 0)} "
            f"| `{res.get('main_table_id', 'unknown')}` "
            f"| {res.get('main_table_row_count', 0)} "
            f"| {res.get('main_table_column_count', 0)} "
            f"| {res.get('avg_cells_per_item_row', 0):.2f} "
            f"| {res.get('one_cell_item_rows_count', 0)} "
            f"| {bool(res.get('anchor_repair_enabled'))} "
            f"| {res.get('before_column_count', 0)} "
            f"| {res.get('after_column_count', 0)} "
            f"| {_format_breakdown(res.get('final_semantic_breakdown') or {})} "
            f"| {bool(res.get('has_product_column'))} "
            f"| {bool(res.get('has_batch_column'))} "
            f"| {bool(res.get('has_expiry_column'))} "
            f"| {bool(res.get('has_qty_column'))} "
            f"| {bool(res.get('has_rate_column'))} "
            f"| {bool(res.get('has_amount_column'))} "
            f"| {res.get('quarantined_cell_count', 0)} "
            f"| {res.get('missing_semantic_columns_count', 0)} "
            f"| {res.get('financial_status', 'UNKNOWN')} "
            f"| {res.get('financial_score', res.get('integrity_score', 0)):.1f} |"
        )

        schema_sources[res["schema_source_path"]] = schema_sources.get(res["schema_source_path"], 0) + 1
        conf_var = res.get("confidence_variance") or {}
        row_var = conf_var.get("row_confidence_variance")
        if row_var is not None:
            confidence_variances.append(float(row_var))

    md.append(f"\n## Summary Aggregates\n")
    invoice_results = [
        res for res in results
        if res.get("schema_source_path") != "unsupported_schema"
    ]
    processed = len(invoice_results)
    invoices_with_one_column_main_table = sum(
        1 for res in invoice_results
        if _safe_int(res.get("main_table_column_count"), 0) == 1
    )
    invoices_with_product_column_detected = sum(1 for res in invoice_results if res.get("has_product_column"))
    invoices_with_anchor_repair_enabled = sum(1 for res in invoice_results if res.get("anchor_repair_enabled"))
    avg_main_cols = (
        sum(_safe_int(res.get("main_table_column_count"), 0) for res in invoice_results) / processed
        if processed else 0.0
    )
    confidence_values = [
        float(res.get("invoice_confidence"))
        for res in invoice_results
        if res.get("invoice_confidence") is not None
    ]
    avg_invoice_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    ppstructure_success_count = sum(
        1 for res in invoice_results
        if res.get("topology_source") == "ppstructure"
        or (_safe_float(res.get("tsr_contribution_percent"), 0.0) or 0.0) > 0.0
    )
    heuristic_fallback_count = sum(
        1 for res in invoice_results
        if res.get("topology_source") == "heuristic_fallback"
        or (
            bool(res.get("heuristic_fallback_used"))
            and res.get("topology_source") != "heuristic_anchor"
        )
    )
    heuristic_anchor_count = sum(1 for res in invoice_results if res.get("topology_source") == "heuristic_anchor")
    financial_pass_count = sum(1 for res in invoice_results if str(res.get("financial_status")).upper() == "PASS")
    avg_financial_score = (
        sum(_safe_float(res.get("financial_score"), 0.0) or 0.0 for res in invoice_results) / processed
        if processed else 0.0
    )

    md.append(f"- **Invoices Processed:** {processed}/{len(files)}")
    md.append(f"- **invoices_with_one_column_main_table:** {invoices_with_one_column_main_table}")
    md.append(f"- **invoices_with_product_column_detected:** {invoices_with_product_column_detected}")
    md.append(f"- **invoices_with_anchor_repair_enabled:** {invoices_with_anchor_repair_enabled}")
    md.append(f"- **average_main_table_columns:** {avg_main_cols:.2f}")
    md.append(f"- **average_invoice_confidence:** {avg_invoice_confidence:.3f}")
    md.append(f"- **ppstructure_success_count:** {ppstructure_success_count}")
    md.append(f"- **heuristic_fallback_count:** {heuristic_fallback_count}")
    md.append(f"- **heuristic_anchor_count:** {heuristic_anchor_count}")
    md.append(f"- **Financial PASS Count:** {financial_pass_count}")
    md.append(f"- **Average Financial Score:** {avg_financial_score:.1f} / 100")
    md.append(f"- **Validator Schema Sources:** `{schema_sources}`")
    if confidence_variances:
        avg_var = sum(confidence_variances) / len(confidence_variances)
        md.append(f"- **Average Row Confidence Variance:** {avg_var:.6f}")

    with open(report_out, "w", encoding="utf-8") as fout:
        fout.write("\n".join(md))
    log.info("dashboard_written", path=report_out)


def _run_financial_validation(results_dir: str, report_out: str):
    """Alias consumed by run_full_verification.py."""
    generate_validation_dashboard(results_dir, report_out)


# Bind the alias
run_financial_validation = _run_financial_validation


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Topology Integrity & Financial Validation (thin wrapper)"
    )
    parser.add_argument(
        "--results-dir",
        default=os.path.join(PROJECT_ROOT, "results"),
        help="Directory containing result JSON files",
    )
    parser.add_argument(
        "--report-out",
        default=os.path.join(
            PROJECT_ROOT,
            "verification/benchmark_reports/topology_integrity_report.md",
        ),
        help="Output path for the markdown report",
    )
    args = parser.parse_args()

    if os.path.exists(args.results_dir):
        generate_validation_dashboard(args.results_dir, args.report_out)
    else:
        print(f"No results found in {args.results_dir}")
