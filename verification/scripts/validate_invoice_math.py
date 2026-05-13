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
import structlog
from typing import List, Dict, Any, Optional

log = structlog.get_logger()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

# Import the LIVE reconciler — single source of truth
from services.financial_reconciler import (
    validate_invoice_json as _live_validate,
    compute_integrity_score,
)


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

    # The benchmark result JSON stores the LLM extraction under metadata.llm_extraction
    llm_data = data.get("metadata", {}).get("llm_extraction")

    if not llm_data:
        log.warning("no_llm_extraction_found", filepath=filepath)
        # Fall back to trying the top-level data as invoice JSON
        llm_data = data

    # Delegate to the live reconciler
    live_result = _live_validate(llm_data)

    # Map live reconciler output to backward-compatible shape
    integrity_score = float(live_result.get("integrity_score", 0))
    passed = integrity_score >= 70.0

    return {
        "filename": os.path.basename(filepath),
        "integrity_score": round(integrity_score, 1),
        "passed": passed,
        "items": live_result.get("total_rows", 0),
        "math_confirmed_rows": live_result.get("rows_math_passed", 0),
        "merged_column_warnings": 0,  # Live reconciler doesn't track merged columns
        "derived_subtotal": float(live_result.get("derived_subtotal", 0)),
        "parsed_grand_total": float(live_result.get("parsed_grand_total", 0)),
        "discrepancy": float(live_result.get("grand_total_discrepancy", 0)),
        "warnings_log": live_result.get("warnings", []),
    }


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

    md = [
        "# Topology Integrity & Financial Validation Dashboard\n",
        "Delegated to live `services.financial_reconciler.validate_invoice_json()`.\n",
        "| File | Score | Status | Items | Math Confirmed | Diff |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for f in files:
        try:
            res = validate_invoice_json(f)
        except Exception as e:
            log.error("validation_file_error", filepath=f, error=str(e))
            continue

        icon = "✅ PASS" if res["passed"] else "❌ FAIL"
        md.append(
            f"| {res['filename']} | **{res['integrity_score']}** | {icon} "
            f"| {res['items']} | {res['math_confirmed_rows']} | {res['discrepancy']} |"
        )

        if res["passed"]:
            global_pass += 1
        total_integrity += res["integrity_score"]

    avg_int = total_integrity / len(files) if files else 0.0
    pass_rate = (global_pass / len(files) * 100) if files else 0.0

    md.append(f"\n## Summary Aggregates\n")
    md.append(f"- **Pass Rate:** {pass_rate:.1f}%")
    md.append(f"- **Average Integrity Score:** {avg_int:.1f} / 100")

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
