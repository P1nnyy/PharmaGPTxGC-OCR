import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
results_dir = PROJECT_ROOT / "results"
json_path = list(results_dir.glob("*7e9a0d92*.json"))[0]

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

metadata = data.get("metadata", {})
metrics = metadata.get("metrics", {})

print("\n--- metadata.metrics.final_column_semantics ---")
print(json.dumps(metrics.get("final_column_semantics"), indent=2))

print("\n--- metadata.metrics.semantic_debug.final_column_semantics ---")
print(json.dumps((metrics.get("semantic_debug") or {}).get("final_column_semantics"), indent=2))

print("\n--- metadata.metrics.column_semantic_cache keys and types ---")
cache = metrics.get("column_semantic_cache", {})
for table_id, data_cache in cache.items():
    if not isinstance(data_cache, dict):
        continue
    print(f"Table: {table_id}")
    for col_id, info in data_cache.items():
        if not col_id.startswith("_") and isinstance(info, dict):
            print(f"  {col_id}: type={info.get('type')}")
