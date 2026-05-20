import os
import sys
import json

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.spatial_reconstruction import reconstruct_layout

def main():
    results_dir = os.path.join(PROJECT_ROOT, "results")
    if not os.path.exists(results_dir):
        print(f"Results directory {results_dir} does not exist!")
        return

    json_files = [
        f for f in os.listdir(results_dir)
        if f.endswith(".json") and f != "debug_output.json"
    ]

    print(f"Found {len(json_files)} cached result files to reconstruct.")

    for i, filename in enumerate(json_files):
        filepath = os.path.join(results_dir, filename)
        print(f"[{i+1}/{len(json_files)}] Reconstructing layout for {filename}...")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            metadata = data.get("metadata")
            if not metadata or not isinstance(metadata, dict):
                print(f"  Skipping: no metadata dictionary found.")
                continue

            blocks = metadata.get("blocks")
            if not blocks:
                print(f"  Skipping: no blocks found inside metadata.")
                continue

            # Run layout reconstruction offline with benchmark_mode=True
            reconstruction_data = reconstruct_layout(
                blocks,
                debug=False,
                reconstruct_mode="heuristic",
                benchmark_mode=True
            )

            # Keep existing metadata keys but update with reconstruction output
            metadata.update(reconstruction_data)
            data["metadata"] = metadata
            data["cached"] = False  # Mark as fresh/updated

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"  Successfully reconstructed and updated cache.")

        except Exception as e:
            print(f"  Error processing: {e}")

if __name__ == "__main__":
    main()
