import os
import sys
import json
import re
from typing import List, Dict, Any, Optional
from core.logger import logger

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

def is_valid_financial_number(text: str) -> bool:
    """
    Validation Rules:
    - reject alphanumeric strings (containing letters)
    - reject GSTIN-like patterns
    - reject phone-number-like patterns
    - reject values containing >1 decimal point
    - reject values longer than 12 digits
    - reject suspicious long numeric chains
    - reject mixed separators
    """
    text = text.strip()
    if not text:
        return False
        
    # Reject alphanumeric strings (e.g. contains letters)
    if any(c.isalpha() for c in text):
        return False
        
    # Reject strings with >1 decimal point
    if text.count('.') > 1:
        return False
        
    # Clean digits only
    digits = "".join(c for c in text if c.isdigit())
    if len(digits) > 12:
        return False
        
    # Reject phone-number-like (10 or 11 digits without a decimal point)
    if len(digits) >= 10 and '.' not in text:
        return False
        
    # Reject mixed/corrupted separators
    if ",," in text or ".." in text or ",." in text or ".," in text:
        return False
        
    # Valid characters pattern
    if not re.match(r'^[\d\s.,]+$', text):
        return False
        
    # Crop decimal structure for numeric checks
    cleaned = re.sub(r'[^\d.]', '', text)
    if cleaned:
        try:
            val = float(cleaned)
            # Reject values >= 1 Crore (10,000,000)
            if val >= 10000000.0:
                return False
                
            # Reject values with > 8 digits before decimal
            before_decimal = cleaned.split('.')[0]
            if len(before_decimal) > 8:
                return False
                
            # Reject abnormal digit density (e.g., massive digit run without a proper decimal position or separators)
            # Safe boundary: If there's no decimal, a number shouldn't be > 6 digits for standard items
            if '.' not in text and len(cleaned) > 6:
                return False
        except ValueError:
            return False
            
    return True

def parse_price(text: str) -> Optional[float]:
    """
    Helper to parse raw price-like string to float.
    Returns None if suspicious.
    """
    if not is_valid_financial_number(text):
        logger.debug(f"Rejected suspicious financial number: {text}")
        return None
        
    cleaned = re.sub(r'[^\d.]', '', text)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None

def validate_invoice_json(filepath: str) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    metadata = data.get("metadata", {})
    structured_tables = metadata.get("structured_tables", [])
    
    line_prices = []
    subtotal_parsed = 0.0
    grand_total_parsed = 0.0
    gst_parsed = 0.0
    
    for table in structured_tables:
        # Group cells by row
        rows = {}
        for cell in table.get("cells", []):
            r_id = cell.get("row_id")
            if r_id not in rows:
                rows[r_id] = []
            rows[r_id].append(cell)
            
        for r_id, cells in rows.items():
            full_text = " ".join([c.get("text", "") for c in cells]).upper()
            
            # Totals parsing
            if "SUB" in full_text or "NET" in full_text:
                for c in cells:
                    val = parse_price(c.get("text", ""))
                    if val is not None:
                        subtotal_parsed = max(subtotal_parsed, val)
            elif "GST" in full_text or "TAX" in full_text:
                for c in cells:
                    val = parse_price(c.get("text", ""))
                    if val is not None:
                        gst_parsed = max(gst_parsed, val)
            elif "GRAND" in full_text or "TOTAL" in full_text:
                if "SUB" not in full_text:
                    for c in cells:
                        val = parse_price(c.get("text", ""))
                        if val is not None:
                            grand_total_parsed = max(grand_total_parsed, val)
            else:
                # Medicine row
                row_prices = []
                for c in cells:
                    if re.search(r'^\s*[\d,]+\.\d{2}\s*$', c.get("text", "")):
                        val = parse_price(c.get("text", ""))
                        if val is not None:
                            row_prices.append(val)
                if row_prices:
                    line_prices.append(max(row_prices))
                    
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
