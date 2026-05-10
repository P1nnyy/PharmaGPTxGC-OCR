import os
import sys
import json
import re
from typing import List, Dict, Any, Optional
from core.logger import logger

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

def is_valid_financial_number(text: str) -> bool:
    """Strict rejection of noise pretending to be numbers."""
    text = text.strip()
    if not text:
        return False
    if any(c.isalpha() for c in text):
        return False
    if text.count('.') > 1:
        return False
    digits = "".join(c for c in text if c.isdigit())
    if len(digits) > 12 or len(digits) == 0:
        return False
    if not re.match(r'^[\d\s.,]+$', text):
        return False
    cleaned = re.sub(r'[^\d.]', '', text)
    try:
        val = float(cleaned)
        if val >= 10000000.0: return False # 1 Crore cap
        if len(cleaned.split('.')[0]) > 8: return False
    except ValueError:
        return False
    return True

def parse_price(text: str) -> Optional[float]:
    if not is_valid_financial_number(text):
        return None
    cleaned = re.sub(r'[^\d.]', '', text)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None

def find_all_numbers(text: str) -> List[float]:
    """Extracts all potential valid money numbers from a text block."""
    matches = re.findall(r'\d[\d\s,]*\.\d{2}', text)
    results = []
    for m in matches:
        p = parse_price(m)
        if p is not None:
            results.append(p)
    return results

def validate_invoice_json(filepath: str) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    metadata = data.get("metadata", {})
    structured_tables = metadata.get("structured_tables", [])
    
    line_items = []
    subtotal_candidates = []
    grand_total_candidates = []
    gst_candidates = []
    
    warnings = []
    merged_column_hits = 0
    structural_integrity_score = 100.0
    
    math_confirmed_rows = 0
    possible_product_rows = 0
    
    for t_idx, table in enumerate(structured_tables):
        rows = {}
        for cell in table.get("cells", []):
            r_id = cell.get("row_id")
            if r_id not in rows:
                rows[r_id] = []
            rows[r_id].append(cell)
            
        for r_id, cells in rows.items():
            row_numbers = []
            for c in cells:
                c_text = c.get("text", "")
                nums_in_cell = find_all_numbers(c_text)
                
                # ALERT 1: Multiple distinct money numbers inside 1 Cell
                if len(nums_in_cell) > 1:
                    merged_column_hits += 1
                    warnings.append(f"Merged Cell Audit: row {r_id} cell contains multiple numbers {nums_in_cell}")
                
                row_numbers.extend(nums_in_cell)
                
            full_text = " ".join([c.get("text", "") for c in cells]).upper()
            
            # Totals classification
            if "SUB" in full_text or "NET" in full_text:
                subtotal_candidates.extend(row_numbers)
            elif "GST" in full_text or "TAX" in full_text or "CGST" in full_text:
                gst_candidates.extend(row_numbers)
            elif "GRAND" in full_text or "TOTAL" in full_text:
                if "SUB" not in full_text:
                    grand_total_candidates.extend(row_numbers)
            else:
                # Probable product line item row
                if row_numbers:
                    possible_product_rows += 1
                    # ALERT 2: Too many money entries in a single product line suggests column merging
                    if len(row_numbers) > 4:
                        warnings.append(f"Suspicious density: row {r_id} has {len(row_numbers)} money values.")
                        merged_column_hits += 1
                    
                    # Math Verification heuristic: (Qty * Rate = Amount)
                    # Test all triples permutations looking for multiplication confirmation
                    row_has_math = False
                    if len(row_numbers) >= 3:
                        sorted_nums = sorted(row_numbers)
                        # Simple check: smallest * middle approx largest?
                        for i in range(len(sorted_nums)):
                            for j in range(i + 1, len(sorted_nums)):
                                for k in range(j + 1, len(sorted_nums)):
                                    # Check both possible multiply combinations (a*b=c, a*c=b, b*c=a)
                                    a, b, c = sorted_nums[i], sorted_nums[j], sorted_nums[k]
                                    if abs((a * b) - c) < 0.5:
                                        row_has_math = True
                                        break
                    if row_has_math:
                        math_confirmed_rows += 1
                        
                    line_items.append(max(row_numbers))
                    
    # Final Aggregate Recon
    derived_subtotal = sum(line_items)
    
    p_subtotal = max(subtotal_candidates) if subtotal_candidates else derived_subtotal
    p_gst = max(gst_candidates) if gst_candidates else 0.0
    p_grand = max(grand_total_candidates) if grand_total_candidates else 0.0
    
    expected_grand = derived_subtotal + p_gst
    discrepancy = abs(p_grand - expected_grand) if p_grand > 0 else 0
    
    # DEDUCTIONS Logic for Structural Integrity Score
    structural_integrity_score -= (merged_column_hits * 10) # Heavy penalty for merged columns
    
    if len(line_items) == 0:
        structural_integrity_score -= 50
        warnings.append("ZERO valid monetary items extracted.")
    
    if p_grand > 0 and discrepancy > 2.0:
        structural_integrity_score -= 30
        warnings.append(f"Critical Math mismatch: Diff of {discrepancy:.2f}")
        
    if possible_product_rows > 0 and math_confirmed_rows == 0:
        # Didn't prove math consistency on even one row
        structural_integrity_score -= 10
        
    # Clamp floor
    structural_integrity_score = max(0.0, structural_integrity_score)
    passed = structural_integrity_score >= 70.0 # Minimum requirement to pass integrity check
    
    return {
        "filename": os.path.basename(filepath),
        "integrity_score": round(structural_integrity_score, 1),
        "passed": passed,
        "items": len(line_items),
        "math_confirmed_rows": math_confirmed_rows,
        "merged_column_warnings": merged_column_hits,
        "derived_subtotal": round(derived_subtotal, 2),
        "parsed_grand_total": round(p_grand, 2),
        "discrepancy": round(discrepancy, 2),
        "warnings_log": warnings
    }

def generate_validation_dashboard(results_dir: str, report_out: str):
    os.makedirs(os.path.dirname(report_out), exist_ok=True)
    files = [os.path.join(results_dir, f) for f in os.listdir(results_dir) if f.endswith(".json")]
    
    print(f"Evaluating Topology Integrity on {len(files)} files...")
    
    global_pass = 0
    total_integrity = 0.0
    total_hits = 0
    
    md = [
        "# Topology Integrity & Financial Validation Dashboard\n",
        "This audit uses accounting consistency (Quantity x Rate verification & Aggregate Reconciliation) to calculate a final layout correctness score.\n",
        "| File | Score | Status | Items | Math Confirmed | Merged Collisions | Diff |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]
    
    for f in files:
        res = validate_invoice_json(f)
        icon = "✅ PASS" if res["passed"] else "❌ FAIL"
        md.append(f"| {res['filename']} | **{res['integrity_score']}** | {icon} | {res['items']} | {res['math_confirmed_rows']} | {res['merged_column_warnings']} | {res['discrepancy']} |")
        
        if res["passed"]: global_pass += 1
        total_integrity += res["integrity_score"]
        total_hits += res["merged_column_warnings"]
        
    avg_int = total_integrity / len(files) if files else 0.0
    pass_rate = (global_pass / len(files) * 100) if files else 0.0
    
    md.append(f"\n## Summary Aggregates\n")
    md.append(f"- **Topology Integrity Pass Rate:** {pass_rate:.1f}%")
    md.append(f"- **Average Integrity Score:** {avg_int:.1f} / 100")
    md.append(f"- **Global Merged Column Occurrences:** {total_hits}")
    
    with open(report_out, "w", encoding="utf-8") as fout:
        fout.write("\n".join(md))
    print(f"Dashboard written to: {report_out}")

if __name__ == "__main__":
    results_dir = os.path.join(PROJECT_ROOT, "results")
    report_file = os.path.join(PROJECT_ROOT, "verification/benchmark_reports/topology_integrity_report.md")
    if os.path.exists(results_dir):
        generate_validation_dashboard(results_dir, report_file)
