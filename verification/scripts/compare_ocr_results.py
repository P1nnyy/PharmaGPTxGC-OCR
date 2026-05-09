import os
import sys
import json
from typing import List, Dict, Any

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

def load_json(filepath: str) -> Dict[str, Any]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load {filepath}: {e}")
        return {}

def analyze_reconstruction(data: Dict[str, Any]) -> Dict[str, Any]:
    metadata = data.get("metadata", {})
    blocks = metadata.get("blocks", [])
    reconstructed_rows = metadata.get("reconstructed_rows", [])
    structured_tables = metadata.get("structured_tables", [])
    
    total_blocks = len(blocks)
    total_rows = len(reconstructed_rows)
    
    # Calculate mapped token IDs to find orphans
    mapped_ids = set()
    total_cells = 0
    column_counts = []
    
    for table in structured_tables:
        total_cells += len(table.get("cells", []))
        column_counts.append(len(table.get("columns", [])))
        for cell in table.get("cells", []):
            mapped_ids.update(cell.get("mapped_block_ids", []))
            
    orphans = [b for b in blocks if b.get("id") not in mapped_ids]
    orphan_count = len(orphans)
    ioa_success = (len(mapped_ids) / total_blocks * 100) if total_blocks else 100.0
    
    # Check for merged columns (heuristically detecting MRP or Rate merged with Qty)
    merged_columns = 0
    for row in reconstructed_rows:
        cols_dict = row.get("columns", {})
        for col_id, text in cols_dict.items():
            # If a single column contains multiple numeric-like tokens (e.g. "10 120.00")
            import re
            numbers = re.findall(r'\b\d+(?:\.\d{2})?\b', text)
            if len(numbers) >= 2:
                merged_columns += 1
                
    return {
        "total_blocks": total_blocks,
        "total_rows": total_rows,
        "total_cells": total_cells,
        "avg_cols_per_table": (sum(column_counts) / len(column_counts)) if column_counts else 0,
        "orphan_count": orphan_count,
        "ioa_success_rate": ioa_success,
        "merged_numeric_cols_estimate": merged_columns,
        "low_confidence_blocks": len([b for b in blocks if b.get("confidence", 1.0) and b.get("confidence", 1.0) < 0.7])
    }

def generate_comparison_summary(results_dir: str, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    json_files = [os.path.join(results_dir, f) for f in os.listdir(results_dir) if f.endswith(".json")]
    
    print(f"\nComparing {len(json_files)} OCR Results inside: {results_dir}")
    print(f"{'File':<30} | {'Rows':<5} | {'Cells':<5} | {'Orphans':<7} | {'IoA %':<6} | {'LowConf':<7}")
    print("-" * 75)
    
    md_lines = [
        "# OCR Layout Reconstruction Comparisons Summary\n",
        f"Analyzed directory: `{results_dir}`  ",
        f"Total reports: {len(json_files)}\n",
        "| File | Rows | Cells | Orphans | IoA Success | Low Conf Blocks | Est. Merged Cols |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]
    
    for filepath in json_files:
        filename = os.path.basename(filepath)
        data = load_json(filepath)
        if not data:
            continue
            
        metrics = analyze_reconstruction(data)
        
        print(f"{filename[:30]:<30} | {metrics['total_rows']:<5} | {metrics['total_cells']:<5} | {metrics['orphan_count']:<7} | {metrics['ioa_success_rate']:<5.1f}% | {metrics['low_confidence_blocks']:<7}")
        
        md_lines.append(
            f"| {filename} | {metrics['total_rows']} | {metrics['total_cells']} | {metrics['orphan_count']} | {metrics['ioa_success_rate']:.1f}% | {metrics['low_confidence_blocks']} | {metrics['merged_numeric_cols_estimate']} |"
        )
        
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
        
    print(f"\nWritten comparison Markdown summary report to: {output_path}")

if __name__ == "__main__":
    results_path = os.path.join(PROJECT_ROOT, "results")
    output_rep = os.path.join(PROJECT_ROOT, "verification/comparisons/ocr_comparison_report.md")
    if os.path.exists(results_path) and os.listdir(results_path):
        generate_comparison_summary(results_path, output_rep)
    else:
        print(f"No results found in {results_path} to compare. Run the benchmark first!")
