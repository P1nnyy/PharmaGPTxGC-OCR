import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
results_dir = PROJECT_ROOT / "results"
json_path = list(results_dir.glob("*7e9a0d92*.json"))[0]

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Extract metrics
metrics = data.get("metadata", {}).get("metrics", {})
final_semantics = metrics.get("final_column_semantics", {})
semantic_debug = metrics.get("semantic_debug", {})
column_semantic_cache = metrics.get("column_semantic_cache", {})
semantic_rejection_summary = metrics.get("semantic_rejection_summary", {})

print("\n=== METADATA FINAL SEMANTICS ===")
print("final_column_semantics:", json.dumps(final_semantics, indent=2))

print("\n=== COLUMN SEMANTIC CACHE ===")
print("column_semantic_cache:", json.dumps(column_semantic_cache, indent=2))

print("\n=== SEMANTIC REJECTION SUMMARY ===")
print("rejection_summary:", json.dumps(semantic_rejection_summary, indent=2))

# Let's inspect structured_tables
print("\n=== STRUCTURED TABLES IN RESULT ===")
for table in data.get("metadata", {}).get("structured_tables", []) or []:
    table_id = table.get("table_id")
    print(f"\nTable: {table_id}")
    print(f"Number of columns: {len(table.get('columns', []))}")
    print(f"Number of cells: {len(table.get('cells', []))}")
    
    # Print column ids and geometries
    print("Columns:")
    for col in table.get("columns", []):
        col_id = col.get("col_id")
        geom = col.get("geometry") or {}
        print(f"  {col_id}: min_x={geom.get('min_x')}, max_x={geom.get('max_x')}, center_x={geom.get('center_x')}")
        
    # Print cell text sample for first few rows
    cells_by_row = {}
    for cell in table.get("cells", []):
        row_id = cell.get("row_id")
        col_id = cell.get("col_id")
        text = cell.get("text")
        cells_by_row.setdefault(row_id, {})[col_id] = text
        
    print("Sample Rows (First 5):")
    row_ids = sorted(cells_by_row.keys(), key=lambda r: int(r.split("_")[-1]) if r.split("_")[-1].isdigit() else r)
    for r_id in row_ids[:5]:
        print(f"  Row {r_id}:")
        for col in table.get("columns", []):
            col_id = col.get("col_id")
            val = cells_by_row[r_id].get(col_id, "N/A")
            print(f"    {col_id}: '{val}'")
