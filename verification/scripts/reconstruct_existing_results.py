import os
import sys
import glob
import json

# Ensure project root is in the python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from services.spatial_reconstruction import reconstruct_layout

def main():
    results_dir = os.path.join(PROJECT_ROOT, "results")
    json_files = glob.glob(os.path.join(results_dir, "*.json"))
    
    print("=" * 70)
    print(" Running Offline Spatial Reconstruction on Baseline Results")
    print("=" * 70)
    
    processed_count = 0
    
    for filepath in sorted(json_files):
        filename = os.path.basename(filepath)
        if filename == "debug_output.json":
            print(f"Skipping {filename} (unsupported debug output)")
            continue
            
        print(f"\nProcessing {filename}...")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            metadata = data.setdefault("metadata", {})
            blocks = metadata.get("blocks", [])
            
            if not blocks:
                print(f"⚠️  No blocks found in {filename}, skipping.")
                continue
                
            print(f"  Loaded {len(blocks)} OCR blocks. Running spatial reconstruction...")
            
            # Execute the reconstruction logic offline using heuristic_anchor
            # Since primary engine is heuristic_anchor, no image input is required
            reconstruct_res = reconstruct_layout(
                blocks=blocks,
                debug=True,
                reconstruct_mode="heuristic_anchor",
                image=None,
                benchmark_mode=False
            )
            
            # Update the original metadata
            metadata.update(reconstruct_res)
            
            # Save back the updated result JSON
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            # Log immediate metrics
            metrics = reconstruct_res.get("metrics", {})
            instrumentation = metrics.get("instrumentation", {})
            fallback_used = metrics.get("graph_fallback_used", False)
            source = reconstruct_res.get("topology_source", "unknown")
            
            print(f"  ✅ Done. Source: {source} | Fallback used: {fallback_used}")
            if fallback_used:
                print(f"  📊 Fallback Cell Count: {metrics.get('graph_fallback_cell_count')}")
                print(f"  📊 Fallback Mapped Tokens: {metrics.get('graph_fallback_mapped_token_count')}")
                print(f"  📊 Fallback Item Row Count: {metrics.get('graph_fallback_item_row_count')}")
                
            processed_count += 1
            
        except Exception as e:
            print(f"❌ Error processing {filename}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f" Reconstructed {processed_count} files successfully!")
    print("=" * 70)

if __name__ == "__main__":
    main()
