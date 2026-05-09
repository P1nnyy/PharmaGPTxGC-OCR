import os
import sys

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from verification.scripts.compare_ocr_results import generate_comparison_summary
from verification.scripts.validate_invoice_math import run_financial_validation
from verification.scripts.render_layout_debug import render_all_visualizations

def run_pipeline():
    print("=================================================================")
    print(" Starting Full Pipeline SQA Verification Workspace")
    print("=================================================================")
    
    results_dir = os.path.join(PROJECT_ROOT, "results")
    
    # 1. Compare OCR result metrics
    comp_rep = os.path.join(PROJECT_ROOT, "verification/comparisons/ocr_comparison_report.md")
    generate_comparison_summary(results_dir, comp_rep)
    
    # 2. Run financial validation math
    math_rep = os.path.join(PROJECT_ROOT, "verification/benchmark_reports/financial_validation_report.md")
    run_financial_validation(results_dir, math_rep)
    
    # 3. Render high-vis layouts
    render_all_visualizations()
    
    # 4. Consolidate results
    cons_rep = os.path.join(PROJECT_ROOT, "verification/benchmark_reports/consolidated_report.md")
    
    md_content = f"""# PharmaGPTxGC Consolidated Pipeline Verification Report

This report summarizes structural and mathematical evaluations performed on the active OCR + TSR reasoning engine.

## 1. Directory Structure Status
- Comparison summaries: `verification/comparisons/`
- Financial validation: `verification/benchmark_reports/`
- Rendered visual layouts: `verification/visualizations/`

## 2. Evaluation Summary
- **OCR comparisons**: Completed (Report: [ocr_comparison_report.md](../comparisons/ocr_comparison_report.md))
- **Accounting Math**: Completed (Report: [financial_validation_report.md](financial_validation_report.md))
- **Visual Grid Inspection**: Successfully drawn and archived to visualizations folder.
"""
    with open(cons_rep, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print("\n=================================================================")
    print(f" SQA Suite Complete! Consolidated report saved: {cons_rep}")
    print("=================================================================")

if __name__ == "__main__":
    run_pipeline()
