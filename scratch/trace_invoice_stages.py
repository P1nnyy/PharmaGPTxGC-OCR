import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
results_dir = PROJECT_ROOT / "results"
json_path = list(results_dir.glob("*7e9a0d92*.json"))[0]

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

metadata = data.get("metadata", {})
metrics = metadata.get("metrics", {})
table = [t for t in metadata.get("structured_tables", []) if t.get("table_id") == "heuristic_region_7"][0]

print("=== TABLE COLUMNS ===")
for col in table.get("columns", []):
    print(f"Column ID: {col.get('col_id')}, bounds: {col.get('geometry')}")

print("\n=== SAMPLE CELL VALUES FOR ANCHOR_COL_0 and ANCHOR_COL_1 ===")
row_cells = {}
for cell in table.get("cells", []):
    row_id = cell.get("row_id")
    col_id = cell.get("col_id")
    row_cells.setdefault(row_id, {})[col_id] = cell

for r_id in sorted(row_cells.keys()):
    c0 = row_cells[r_id].get("anchor_col_0")
    c1 = row_cells[r_id].get("anchor_col_1")
    t0 = c0.get("text") if c0 else "N/A"
    t1 = c1.get("text") if c1 else "N/A"
    print(f"Row {r_id}: anchor_col_0='{t0}', anchor_col_1='{t1}'")

print("\n=== RAW / DEBUG SEMANTICS ===")
print(json.dumps(metrics.get("semantic_debug", {}).get("heuristic_region_7", {}).get("final_column_semantics"), indent=2))

print("\n=== COLUMN SEMANTIC CACHE / POST-QUARANTINE ===")
print(json.dumps(metrics.get("column_semantic_cache", {}).get("heuristic_region_7", {}), indent=2))
