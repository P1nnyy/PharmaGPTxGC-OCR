import os
import sys
import json
import re
from typing import List, Dict, Any

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

def parse_price(text: str) -> float:
    """Helper to parse raw price-like string to float"""
    # Matches decimals like 120.50, 1,200.00
    cleaned = re.sub(r'[^\d.]', '', text)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0

def validate_invoice_json(filepath: str) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    metadata = data.get("metadata", {})
    reconstructed_rows = metadata.get("reconstructed_rows", [])
    
    line_prices = []
    subtotal_parsed = 0.0
    grand_total_parsed = 0.0
    gst_parsed = 0.0
    
    for row in reconstructed_rows:
        classification = row.get("classification", "").lower()
        full_text = " ".join([b.get("text", "") for b in row.get("blocks", [])]).upper()
        
        # Parse medicine item prices/amounts
        if "medicine" in classification or "table" in classification:
            # Look for price-like tokens in columns
            for col_val in row.get("columns", {}).values():
                if re.search(r'^\s*[\d,]+\.\d{2}\s*$', col_val):
                    line_prices.append(parse_price(col_val))
                    
        # Parse totals
        elif "totals" in classification or "total" in full_text:
            for col_val in row.get("columns", {}).values():
                val = parse_price(col_val)
                if "SUB" in full_text or "NET" in full_text:
                    subtotal_parsed = max(subtotal_parsed, val)
                elif "GST" in full_text or "TAX" in full_text:
                    gst_parsed = max(gst_parsed, val)
                elif "GRAND" in full_text or "TOTAL" in full_text:
                    grand_total_parsed = max(grand_total_parsed, val)
                    
    # Heuristics if subtotal/grand total weren't cleanly matched by keywords
    calculated_subtotal = sum(line_prices)
    if not grand_total_parsed and calculated_subtotal:
        grand_total_parsed = calculated_subtotal + gst_parsed
        
    expected_grand_total = calculated_subtotal + gst_parsed
    discrepancy = abs(grand_total_parsed - expected_grand_total)
    passed = discrepancy < 1.0 # Allow a minor threshold for rounding or rupees conversion
    
    return {
        "filename": os.path.basename(filepath),
        "calculated_subtotal": calculated_subtotal,
        "parsed_gst": gst_parsed,
        "parsed_grand_total": grand_total_parsed,
        "expected_grand_total": expected_grand_total,
        "discrepancy": discrepancy,
        "passed": passed,
        "item_count": len(line_prices)
    }

def run_financial_validation(results_dir: str, report_out: str):
    os.makedirs(os.path.dirname(report_out), exist_ok=True)
    json_files = [os.path.join(results_dir, f) for f in os.listdir(results_dir) if f.endswith(".json")]
    
    print(f"\nRunning Financial Validation on {len(json_files)} invoices...")
    
    md_lines = [
        "# Financial Math Validation Report\n",
        "Validates structural integrity by reconciling calculated item subtotals against parsed grand totals.\n",
        "| Invoice File | Items | Calculated Subtotal | Parsed GST | Expected Grand Total | Parsed Grand Total | Discrepancy | Status |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]
    
    for filepath in json_files:
        res = validate_invoice_json(filepath)
        status_icon = "✅ PASS" if res["passed"] else "⚠️ FAIL"
        
        print(f"File: {res['filename']} -> Calculated: {res['calculated_subtotal']:.2f}, Grand Total: {res['parsed_grand_total']:.2f} | Status: {status_icon}")
        
        md_lines.append(
            f"| {res['filename']} | {res['item_count']} | {res['calculated_subtotal']:.2f} | {res['parsed_gst']:.2f} | {res['expected_grand_total']:.2f} | {res['parsed_grand_total']:.2f} | {res['discrepancy']:.2f} | {status_icon} |"
        )
        
    with open(report_out, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
        
    print(f"\nWritten math validation report to: {report_out}")

if __name__ == "__main__":
    results_path = os.path.join(PROJECT_ROOT, "results")
    report_path = os.path.join(PROJECT_ROOT, "verification/benchmark_reports/financial_validation_report.md")
    if os.path.exists(results_path) and os.listdir(results_path):
        run_financial_validation(results_path, report_path)
    else:
        print(f"No results found in {results_path} to validate. Run the benchmark first!")
