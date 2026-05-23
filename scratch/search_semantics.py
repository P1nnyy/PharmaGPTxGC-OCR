import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
results_dir = PROJECT_ROOT / "results"
json_path = list(results_dir.glob("*7e9a0d92*.json"))[0]

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

def find_keys(d, target, path=""):
    if isinstance(d, dict):
        for k, v in d.items():
            current_path = f"{path}.{k}" if path else k
            if k == target or v == target:
                print(f"Match: {current_path} -> {v}")
            find_keys(v, target, current_path)
    elif isinstance(d, list):
        for i, item in enumerate(d):
            find_keys(item, target, f"{path}[{i}]")

print("Searching for 'anchor_col_0'...")
find_keys(data, "anchor_col_0")

print("\nSearching for 'anchor_col_1'...")
find_keys(data, "anchor_col_1")

print("\nSearching for 'quantity' values...")
find_keys(data, "quantity")

print("\nSearching for 'free_quantity' values...")
find_keys(data, "free_quantity")
