import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
results_dir = PROJECT_ROOT / "results"
json_path = list(results_dir.glob("*7e9a0d92*.json"))[0]

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

metrics = data.get("metadata", {}).get("metrics", {})
final_semantics = metrics.get("final_column_semantics", {}).get("heuristic_region_7", {})
semantic_debug = metrics.get("semantic_debug", {}).get("heuristic_region_7", {})
column_semantic_cache = metrics.get("column_semantic_cache", {}).get("heuristic_region_7", {})

print("=== FINAL SEMANTICS FOR HEURISTIC_REGION_7 ===")
print(json.dumps(final_semantics, indent=2))

print("\n=== SEMANTIC DEBUG FOR HEURISTIC_REGION_7 ===")
for col_id, debug in semantic_debug.items():
    if not col_id.startswith("_"):
        print(f"Column {col_id}: type={debug.get('type')}, confidence={debug.get('confidence')}")
        metrics_col = debug.get("metrics", {})
        print(f"  weighted_votes: {metrics_col.get('weighted_votes')}")
        print(f"  header_votes: {metrics_col.get('header_votes')}")
        print(f"  qty_pattern_count: {metrics_col.get('qty_pattern_count')}/{metrics_col.get('sample_size')}")
        print(f"  compound_qty_pattern_count: {metrics_col.get('compound_qty_pattern_count')}/{metrics_col.get('sample_size')}")
        print(f"  alpha_density: {metrics_col.get('alpha_density')}")
