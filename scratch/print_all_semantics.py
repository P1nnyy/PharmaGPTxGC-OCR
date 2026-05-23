import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
results_dir = PROJECT_ROOT / "results"
json_path = list(results_dir.glob("*7e9a0d92*.json"))[0]

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

metrics = data.get("metadata", {}).get("metrics", {})
final_semantics = metrics.get("final_column_semantics", {})
selected_source = data.get("metadata", {}).get("selected_topology_source")
print(f"Selected Topology Source: {selected_source}")

for table_id, semantics in final_semantics.items():
    print(f"\n=== Table: {table_id} ===")
    print(json.dumps(semantics, indent=2))
