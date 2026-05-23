from pathlib import Path
import os
import sys
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from services.spatial_reconstruction import reconstruct_layout
from services.qty_parser import parse_quantity
from services.financial_reconciler import DiscountAwareVerifier, normalize_indian_decimal

def _parse_numeric(text: str) -> Optional[float]:
    if not text:
        return None
    normalized = normalize_indian_decimal(text)
    cleaned = re.sub(r'[₹$,\s]', '', normalized.strip())
    try:
        return float(cleaned)
    except ValueError:
        return None

def determine_failure_cause(
    diag: Dict[str, Any],
    prod_text: str,
    qty_text: str,
    rate_text: str,
    amount_text: str,
    parsed_qty: Optional[float],
    parsed_rate: Optional[float],
    parsed_amount: Optional[float],
    missing_cols: List[str],
    penalties: List[str]
) -> str:
    """Group failures into one of the 9 requested causes."""
    # 1. amount column missing
    if "amount" in missing_cols or not amount_text.strip():
        return "amount column missing"
        
    # 2. product column missing
    if not prod_text.strip():
        return "product column missing"

    # 3. row is not a true item row
    combined_text = f"{prod_text} {qty_text} {rate_text} {amount_text}".upper()
    non_item_keywords = ["TOTAL", "SUBTOTAL", "GRAND TOTAL", "NET AMOUNT", "NET PAYABLE", "CGST", "SGST", "IGST", "GST", "ROUND OFF", "CARRY FORWARD", "PAGE", "INVOICE TOTAL"]
    # If the product cell contains strong non-item row tokens
    if any(k in prod_text.upper() for k in non_item_keywords) or diag.get("row_role") != "item_row":
        return "row is not a true item row"

    # 4. qty cell contains product/header/footer text
    qty_upper = qty_text.upper()
    if any(c.isalpha() for c in qty_text.strip().replace(" ", "")) and not re.search(r'^\d+(\.\d+)?(\s*[+x*]\s*\d+(\.\d+)?)?$', qty_text.strip()):
        if any(h in qty_upper for h in ["QTY", "QUANTITY", "PRODUCT", "ITEM", "TOTAL", "RATE"]):
            return "qty cell contains product/header/footer text"
        # If it has significant alphabetic text
        alpha_chars = sum(1 for c in qty_text if c.isalpha())
        if alpha_chars > 3:
            return "qty cell contains product/header/footer text"

    # 5. rate/amount columns merged
    # Multiple decimals glued (e.g. 12.345.67) or very long number
    if amount_text.count('.') >= 2 and re.search(r'\d+\.\d+\.\d+', amount_text):
        return "rate/amount columns merged"
    if rate_text.count('.') >= 2 and re.search(r'\d+\.\d+\.\d+', rate_text):
        return "rate/amount columns merged"

    # 6. cell assignment to wrong column
    # If qty contains decimals that look like rates, or if semantic mismatches are present
    if any(p.startswith("semantic_mismatch") for p in penalties):
        return "cell assignment to wrong column"

    # 7. parser failure
    # If the column semantics are present but the parser failed to extract numeric values
    if parsed_qty is None and qty_text.strip():
        return "parser failure"
    if parsed_rate is None and rate_text.strip():
        return "parser failure"
    if parsed_amount is None and amount_text.strip():
        return "parser failure"

    # 8. GST/discount affecting calculation
    # If we have parsed values but they don't match simple qty * rate, and GST or discount is present
    if parsed_qty is not None and parsed_rate is not None and parsed_amount is not None:
        simple_expected = parsed_qty * parsed_rate
        if abs(simple_expected - parsed_amount) > 1.0:
            # Check if there is discount or GST text
            return "GST/discount affecting calculation"

    return "unknown"

def run_audit():
    results_dir = os.path.join(PROJECT_ROOT, "results")
    filenames = sorted([f for f in os.listdir(results_dir) if f.endswith(".json") and f != "debug_output.json"])
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(PROJECT_ROOT, "forensic_runs", timestamp)
    os.makedirs(output_dir, exist_ok=True)
    
    all_failed_rows = []
    
    # Summary telemetry counts
    total_failed_rows = 0
    failures_by_invoice = {}
    failures_by_topology = {}
    failures_by_cause = {
        "qty cell contains product/header/footer text": 0,
        "rate/amount columns merged": 0,
        "amount column missing": 0,
        "product column missing": 0,
        "GST/discount affecting calculation": 0,
        "parser failure": 0,
        "cell assignment to wrong column": 0,
        "row is not a true item row": 0,
        "unknown": 0
    }
    
    repeated_patterns = {}

    for filename in filenames:
        filepath = os.path.join(results_dir, filename)
        with open(filepath, "r") as f:
            data = json.load(f)
        
        blocks = data.get("metadata", {}).get("blocks", [])
        if not blocks:
            print(f"Skipping {filename}: no blocks")
            continue
            
        print(f"Auditing {filename}...")
        out = reconstruct_layout(blocks, benchmark_mode=True)
        
        row_validation = out["metrics"].get("row_validation", {})
        selected_topology_source = out.get("selected_topology_source", "unknown")
        
        # Build cell lookup and column semantic mappings per table
        structured_tables = out.get("structured_tables", [])
        tables_by_id = {t["table_id"]: t for t in structured_tables}
        
        for table_id, t_val in row_validation.items():
            table_obj = tables_by_id.get(table_id)
            if not table_obj:
                continue
                
            # Get semantic column type cache
            col_semantics = {}
            cache = out["metrics"].get("column_semantic_cache", {})
            if table_id in cache:
                for col_id, meta in cache[table_id].items():
                    if isinstance(meta, dict):
                        col_semantics[col_id] = str(meta.get("type", "UNKNOWN")).upper()
                    else:
                        col_semantics[col_id] = str(meta).upper()
            
            # Map of row_id -> list of cells
            cells_by_row = {}
            for cell in table_obj.get("cells", []):
                r_id = cell["row_id"]
                if r_id not in cells_by_row:
                    cells_by_row[r_id] = []
                cells_by_row[r_id].append(cell)
                
            row_diags = t_val.get("row_diagnostics", [])
            missing_cols = t_val.get("missing_semantic_columns", [])
            
            for diag in row_diags:
                row_id = diag["row_id"]
                row_role = diag["row_role"]
                fin_check = diag["financial_check"]
                struct_check = diag["structural_check"]
                penalties = diag.get("penalties", [])
                
                # We audit row math failures
                is_failed = False
                if row_role == "item_row":
                    if fin_check and fin_check.startswith("FAIL"):
                        is_failed = True
                    elif struct_check and struct_check.startswith("FAIL"):
                        is_failed = True
                
                if not is_failed:
                    continue
                
                # Extract cell content per required column
                row_cells = cells_by_row.get(row_id, [])
                
                # Columns we want to extract
                cell_texts = {
                    "PRODUCT": "", "QTY": "", "FREE_QTY": "", "RATE": "", "MRP": "", "GST": "", "AMOUNT": ""
                }
                cell_block_ids = {
                    "PRODUCT": [], "QTY": [], "FREE_QTY": [], "RATE": [], "MRP": [], "GST": [], "AMOUNT": []
                }
                
                for cell in row_cells:
                    col_id = cell["col_id"]
                    col_sem = col_semantics.get(col_id, "UNKNOWN")
                    cell_text = cell.get("text", "").strip()
                    block_ids = cell.get("mapped_block_ids", [])
                    
                    if col_sem in ("PRODUCT", "DRUG_NAME"):
                        cell_texts["PRODUCT"] += (" " + cell_text) if cell_texts["PRODUCT"] else cell_text
                        cell_block_ids["PRODUCT"].extend(block_ids)
                    elif col_sem in ("QTY", "QUANTITY"):
                        cell_texts["QTY"] += (" " + cell_text) if cell_texts["QTY"] else cell_text
                        cell_block_ids["QTY"].extend(block_ids)
                    elif col_sem == "FREE_QUANTITY":
                        cell_texts["FREE_QTY"] += (" " + cell_text) if cell_texts["FREE_QTY"] else cell_text
                        cell_block_ids["FREE_QTY"].extend(block_ids)
                    elif col_sem == "RATE":
                        cell_texts["RATE"] += (" " + cell_text) if cell_texts["RATE"] else cell_text
                        cell_block_ids["RATE"].extend(block_ids)
                    elif col_sem == "MRP":
                        cell_texts["MRP"] += (" " + cell_text) if cell_texts["MRP"] else cell_text
                        cell_block_ids["MRP"].extend(block_ids)
                    elif col_sem in ("GST", "TAX"):
                        cell_texts["GST"] += (" " + cell_text) if cell_texts["GST"] else cell_text
                        cell_block_ids["GST"].extend(block_ids)
                    elif col_sem == "AMOUNT":
                        cell_texts["AMOUNT"] += (" " + cell_text) if cell_texts["AMOUNT"] else cell_text
                        cell_block_ids["AMOUNT"].extend(block_ids)

                # Parse parsed values
                parsed_qty = None
                if cell_texts["QTY"]:
                    qty_parsed = parse_quantity(cell_texts["QTY"])
                    if qty_parsed.parse_method not in ("empty", "unparsed"):
                        parsed_qty = float(qty_parsed.billed_qty)
                        
                parsed_rate = _parse_numeric(cell_texts["RATE"])
                parsed_amount = _parse_numeric(cell_texts["AMOUNT"])
                
                # Check expected calculation and formula used
                expected_cal = "n/a"
                actual_amt = str(parsed_amount) if parsed_amount is not None else "n/a"
                
                if parsed_qty is not None and parsed_rate is not None:
                    expected_cal = f"{parsed_qty} * {parsed_rate} = {round(parsed_qty * parsed_rate, 2)}"
                    
                # Determine failure cause
                cause = determine_failure_cause(
                    diag,
                    cell_texts["PRODUCT"],
                    cell_texts["QTY"],
                    cell_texts["RATE"],
                    cell_texts["AMOUNT"],
                    parsed_qty,
                    parsed_rate,
                    parsed_amount,
                    missing_cols,
                    penalties
                )
                
                # failure reason text
                fail_reason = fin_check if fin_check else struct_check
                
                # Record failed row
                failed_row_record = {
                    "filename": filename,
                    "topology": selected_topology_source,
                    "row_id": row_id,
                    "product_text": cell_texts["PRODUCT"],
                    "qty_text": cell_texts["QTY"],
                    "free_qty_text": cell_texts["FREE_QTY"],
                    "rate_text": cell_texts["RATE"],
                    "mrp_text": cell_texts["MRP"],
                    "gst_text": cell_texts["GST"],
                    "amount_text": cell_texts["AMOUNT"],
                    "parsed_qty": parsed_qty,
                    "parsed_rate": parsed_rate,
                    "parsed_amount": parsed_amount,
                    "expected_cal": expected_cal,
                    "actual_amt": actual_amt,
                    "fail_reason": fail_reason,
                    "block_ids": cell_block_ids,
                    "cause": cause
                }
                
                all_failed_rows.append(failed_row_record)
                
                # Update metrics
                total_failed_rows += 1
                failures_by_invoice[filename] = failures_by_invoice.get(filename, 0) + 1
                failures_by_topology[selected_topology_source] = failures_by_topology.get(selected_topology_source, 0) + 1
                failures_by_cause[cause] += 1
                
                # Top repeated patterns (key on failure cause + text pattern)
                pattern_key = f"{cause} | Qty cell: '{cell_texts['QTY']}' | Amount cell: '{cell_texts['AMOUNT']}'"
                repeated_patterns[pattern_key] = repeated_patterns.get(pattern_key, 0) + 1

    # Sort repeated patterns to find top 5
    sorted_patterns = sorted(repeated_patterns.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Generate the Markdown audit report
    md_content = []
    md_content.append(f"# Cell-Level Row Math Failure Forensic Audit Report")
    md_content.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md_content.append(f"\nThis report provides a granular cell-level forensic audit of all row mathematical validation failures across the 7 baseline invoices. It categorizes the root causes of failures to identify system weaknesses.")
    
    md_content.append(f"\n## 1. Executive Summary & Telemetry")
    md_content.append(f"\n### Global Metrics")
    md_content.append(f"- **Total Failed Item Rows**: {total_failed_rows}")
    
    # Table 1: Failures by Invoice
    md_content.append(f"\n### Failures by Invoice")
    md_content.append(f"| Invoice Filename | Failed Rows Count |")
    md_content.append(f"| :--- | :---: |")
    for f_name in sorted(filenames):
        cnt = failures_by_invoice.get(f_name, 0)
        md_content.append(f"| {f_name} | {cnt} |")
        
    # Table 2: Failures by Selected Topology
    md_content.append(f"\n### Failures by Selected Topology")
    md_content.append(f"| Selected Table Topology | Failed Rows Count |")
    md_content.append(f"| :--- | :---: |")
    for topo, cnt in sorted(failures_by_topology.items()):
        md_content.append(f"| {topo} | {cnt} |")
        
    # Table 3: Failures by Cause Category
    md_content.append(f"\n### Failures by Cause Category")
    md_content.append(f"| Failure Cause Category | Failed Rows Count | % of Total |")
    md_content.append(f"| :--- | :---: | :---: |")
    for cause, cnt in sorted(failures_by_cause.items(), key=lambda x: x[1], reverse=True):
        pct = (cnt / total_failed_rows * 100) if total_failed_rows > 0 else 0.0
        md_content.append(f"| {cause} | {cnt} | {pct:.1f}% |")

    # Table 4: Top 5 Repeated Failure Patterns
    md_content.append(f"\n### Top 5 Repeated Failure Patterns")
    md_content.append(f"| Failure Pattern Description | Occurrences |")
    md_content.append(f"| :--- | :---: |")
    for pat, cnt in sorted_patterns:
        md_content.append(f"| {pat} | {cnt} |")
        
    md_content.append(f"\n## 2. Granular Failed Row Cell Export")
    
    # Export every single failed row
    for i, r in enumerate(all_failed_rows, 1):
        md_content.append(f"\n---")
        md_content.append(f"\n### Failure #{i}: `{r['row_id']}` in `{r['filename']}`")
        md_content.append(f"- **Selected Topology**: `{r['topology']}`")
        md_content.append(f"- **Assigned Cause**: **{r['cause']}**")
        md_content.append(f"- **Raw Validation Status**: `{r['fail_reason']}`")
        
        md_content.append(f"\n#### Cell Level Texts & Mappings")
        md_content.append(f"| Column Semantic | Cell Text | Mapped Block IDs |")
        md_content.append(f"| :--- | :--- | :--- |")
        md_content.append(f"| PRODUCT / DRUG | {r['product_text'] or '*empty*'} | {r['block_ids']['PRODUCT'] or 'None'} |")
        md_content.append(f"| QUANTITY (QTY) | {r['qty_text'] or '*empty*'} | {r['block_ids']['QTY'] or 'None'} |")
        md_content.append(f"| FREE QUANTITY | {r['free_qty_text'] or '*empty*'} | {r['block_ids']['FREE_QTY'] or 'None'} |")
        md_content.append(f"| RATE | {r['rate_text'] or '*empty*'} | {r['block_ids']['RATE'] or 'None'} |")
        md_content.append(f"| MRP | {r['mrp_text'] or '*empty*'} | {r['block_ids']['MRP'] or 'None'} |")
        md_content.append(f"| GST / TAX | {r['gst_text'] or '*empty*'} | {r['block_ids']['GST'] or 'None'} |")
        md_content.append(f"| AMOUNT | {r['amount_text'] or '*empty*'} | {r['block_ids']['AMOUNT'] or 'None'} |")
        
        md_content.append(f"\n#### Parsed Values & Mathematical Audit")
        md_content.append(f"- **Parsed Billed Quantity**: `{r['parsed_qty']}`")
        md_content.append(f"- **Parsed Unit Rate**: `{r['parsed_rate']}`")
        md_content.append(f"- **Parsed Actual Amount**: `{r['parsed_amount']}`")
        md_content.append(f"- **Expected Amount Formula**: `{r['expected_cal']}`")
        md_content.append(f"- **Actual Row Amount**: `{r['actual_amt']}`")
        
    # Write to final location
    report_path = os.path.join(output_dir, "row_math_failure_audit.md")
    with open(report_path, "w", encoding="utf-8") as f_out:
        f_out.write("\n".join(md_content))
        
    print(f"\nSuccessfully generated audit report at: {report_path}")

if __name__ == "__main__":
    run_audit()
