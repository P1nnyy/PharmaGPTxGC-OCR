import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
results_dir = PROJECT_ROOT / "results"
json_path = list(results_dir.glob("*7e9a0d92*.json"))[0]

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

metadata = data.get("metadata", {})
table = [t for t in metadata.get("structured_tables", []) if t.get("table_id") == "heuristic_region_7"][0]

print("=== row_15 Cells in heuristic_region_7 ===")
for cell in table.get("cells", []):
    if cell.get("row_id") == "row_15":
        print(f"col_id: {cell.get('col_id')}, text: '{cell.get('text')}', mapped_block_ids: {cell.get('mapped_block_ids')}")
