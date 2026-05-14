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
    score = float(confidence) * 100.0 if confidence is not None else float(metadata.get("invoice_confidence") or 0) * 100.0
    status = str(rec.get("status", "")).upper()
    passed = status == "PASS" if status else score >= 70.0
    instrumentation = metrics.get("instrumentation") or {}
    confidence_variance = instrumentation.get("confidence_variance") or (metrics.get("confidence_hierarchy") or {}).get("confidence_variance") or {}

    return {
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
    }

def _reconstruction_schema_result(filepath: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    metadata = data.get("metadata", {})
    rows = metadata.get("detected_table_rows") or [
        row for row in metadata.get("reconstructed_rows", [])
        if row.get("classification") in ("table", "medicine_table")
    ]
    if not rows and not metadata.get("structured_tables"):
        return None

    return {
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
    }

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

    global_pass = 0
    total_integrity = 0.0
    fallback_count = 0
    schema_sources = {}
    confidence_variances = []

    md = [
        "# Topology Integrity & Financial Validation Dashboard\n",
        "Reads live runtime metrics first, then falls back to reconstructed rows or LLM extraction.\n",
        "| File | Score | Status | Items | Math Confirmed | Diff | TSR % | Heuristic Fallback | Semantic Rejects | Source Path |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for f in files:
        try:
            res = validate_invoice_json(f)
        except Exception as e:
            log.error("validation_file_error", filepath=f, error=str(e))
            continue

        icon = "✅ PASS" if res["passed"] else "❌ FAIL"
        tsr_pct = res.get("tsr_contribution_percent")
        tsr_pct_str = "n/a" if tsr_pct is None else f"{float(tsr_pct):.1f}"
        fallback_used = res.get("heuristic_fallback_used")
        fallback_str = "n/a" if fallback_used is None else str(bool(fallback_used))
        semantic_rejects = res.get("semantic_rejection_count")
        semantic_rejects_str = "n/a" if semantic_rejects is None else str(semantic_rejects)
        md.append(
            f"| {res['filename']} | **{res['integrity_score']}** | {icon} "
            f"| {res['items']} | {res['math_confirmed_rows']} | {res['discrepancy']} "
            f"| {tsr_pct_str} | {fallback_str} | {semantic_rejects_str} | `{res['schema_source_path']}` |"
        )

        if res["passed"]:
            global_pass += 1
        if res.get("heuristic_fallback_used"):
            fallback_count += 1
        schema_sources[res["schema_source_path"]] = schema_sources.get(res["schema_source_path"], 0) + 1
        conf_var = res.get("confidence_variance") or {}
        row_var = conf_var.get("row_confidence_variance")
        if row_var is not None:
            confidence_variances.append(float(row_var))
        total_integrity += res["integrity_score"]

    avg_int = total_integrity / len(files) if files else 0.0
    pass_rate = (global_pass / len(files) * 100) if files else 0.0

    md.append(f"\n## Summary Aggregates\n")
    md.append(f"- **Pass Rate:** {pass_rate:.1f}%")
    md.append(f"- **Average Integrity Score:** {avg_int:.1f} / 100")
    md.append(f"- **Heuristic Fallback Frequency:** {fallback_count}/{len(files)}")
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
