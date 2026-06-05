import os
import sys
import numpy as np
from pathlib import Path
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.ocr_engine import process_image
from services.layout_pipeline.geometry import process_blocks
from services.layout_pipeline.skew import apply_skew_normalization
from services.tsr.heuristic_tsr import HeuristicTSREngine
from services.layout_pipeline.row_clustering import cluster_into_rows
from services.layout_pipeline.row_classification import classify_rows
from services.layout_pipeline.multiline_merging import merge_multiline_rows
from services.layout_pipeline.column_projection import project_column_boundaries, get_last_projection_debug

def main():
    img_path = REPO_ROOT / "test_images/cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG"
    image = Image.open(img_path).convert("RGB")
    ocr_result = process_image(image)
    blocks = ocr_result.get("blocks", [])
    
    for i, b in enumerate(blocks):
        if "id" not in b:
            b["id"] = f"block_{i}"
            
    ocr_blocks = process_blocks(blocks)
    ocr_blocks = apply_skew_normalization(ocr_blocks)
    
    # Let's run TSR Table Detection to find the 6th region
    # Note that heuristic_tsr selects the winning angle first
    engine = HeuristicTSREngine()
    
    # We can replicate the winning rotation selection logic:
    xs, ys = [], []
    for b in ocr_blocks:
        if b.normalized_geometry:
            xs.extend([b.normalized_geometry.min_x, b.normalized_geometry.max_x])
            ys.extend([b.normalized_geometry.min_y, b.normalized_geometry.max_y])
    max_x = max(xs) if xs else 1000.0
    max_y = max(ys) if ys else 1000.0

    candidates = []
    from services.tsr.heuristic_tsr import rotate_blocks
    for angle in [0, 90, 180, 270]:
        rotated_blocks = rotate_blocks(ocr_blocks, angle)
        try:
            reconstructed_rows = cluster_into_rows(rotated_blocks)
            reconstructed_rows = classify_rows(reconstructed_rows)
            reconstructed_rows, _ = merge_multiline_rows(reconstructed_rows)
            num_rows = len(reconstructed_rows)
            num_med_rows = sum(1 for r in reconstructed_rows if r.classification == "Medicine Table Row")
            score = (num_med_rows * 100) + (num_rows * 5)
        except Exception:
            score = float("-inf")
            reconstructed_rows = []
        candidates.append({
            "angle": angle,
            "score": score,
            "blocks": rotated_blocks,
            "reconstructed_rows": reconstructed_rows
        })
    winner = max(candidates, key=lambda x: x["score"])
    winner_angle = winner["angle"]
    winner_blocks = winner["blocks"]
    
    print(f"Winner angle: {winner_angle}")
    
    # Now run _detect_tables_single on winner_blocks
    reconstructed_rows = cluster_into_rows(winner_blocks)
    reconstructed_rows = classify_rows(reconstructed_rows)
    reconstructed_rows, _ = merge_multiline_rows(reconstructed_rows)
    
    segmented_regions = []
    if reconstructed_rows:
        current_segment = [reconstructed_rows[0]]
        current_class = reconstructed_rows[0].classification
        
        for row in reconstructed_rows[1:]:
            if row.classification == current_class:
                current_segment.append(row)
            else:
                segmented_regions.append((current_class, current_segment))
                current_segment = [row]
                current_class = row.classification
        if current_segment:
            segmented_regions.append((current_class, current_segment))
            
    # Locate region_idx = 6
    target_idx = 6
    if target_idx >= len(segmented_regions):
        print(f"Error: only {len(segmented_regions)} regions found.")
        return
        
    classification, region_rows = segmented_regions[target_idx]
    print(f"\nRegion {target_idx}: Classification={classification}, row count={len(region_rows)}")
    
    region_blocks = []
    for r in region_rows:
        region_blocks.extend(r.blocks)
        
    print(f"Total blocks in region: {len(region_blocks)}")
    print("\n--- OCR Blocks inside the Region ---")
    for i, r_row in enumerate(region_rows):
        print(f"\nRow {i}:")
        row_blocks = r_row.blocks
        for b in row_blocks:
            g = b.normalized_geometry
            print(f"  Block ID: {b.id:10} | Text: {b.text:25} | X Range: [{g.min_x:.2f}, {g.max_x:.2f}] | Y Range: [{g.min_y:.2f}, {g.max_y:.2f}]")
            
    print("\n--- Raw Gaps Between Adjacent Blocks Per Row ---")
    for i, r_row in enumerate(region_rows):
        print(f"\nRow {i}:")
        row_blocks = r_row.blocks
        # Sorted by min_x
        sorted_row_blocks = sorted(row_blocks, key=lambda b: b.normalized_geometry.min_x if b.normalized_geometry else 0)
        for idx in range(len(sorted_row_blocks) - 1):
            b1 = sorted_row_blocks[idx]
            b2 = sorted_row_blocks[idx+1]
            gap = b2.normalized_geometry.min_x - b1.normalized_geometry.max_x
            print(f"  Gap between '{b1.text}' and '{b2.text}': {gap:.2f}px (X1: [{b1.normalized_geometry.min_x:.1f}, {b1.normalized_geometry.max_x:.1f}], X2: [{b2.normalized_geometry.min_x:.1f}, {b2.normalized_geometry.max_x:.1f}])")
            
    # Compute projection and examine gaps seen by global projection
    # 1. Define workspace dimensions
    valid_blocks = [b for b in region_blocks if b.normalized_geometry]
    max_x = int(max(b.normalized_geometry.max_x for b in valid_blocks)) + 50
    
    # 2. Histogram
    hist = np.zeros(max_x, dtype=float)
    for b in valid_blocks:
        g = b.normalized_geometry
        start = max(0, int(g.min_x))
        end = min(max_x, int(g.max_x))
        if end > start:
            hist[start:end] += 1.0
            
    # Convolve
    kernel_size = 15
    kernel = np.ones(kernel_size) / kernel_size
    smoothed = np.convolve(hist, kernel, mode='same')
    threshold = 0.1
    mask = smoothed > threshold
    
    changes = np.diff(mask.astype(int))
    starts = np.where(changes == 1)[0] + 1
    ends = np.where(changes == -1)[0] + 1
    if mask[0]:
        starts = np.insert(starts, 0, 0)
    if mask[-1]:
        ends = np.append(ends, len(mask) - 1)
        
    raw_columns = list(zip(starts, ends))
    
    print("\n--- Global Projection Column Detection ---")
    print(f"Raw histogram peak ranges (columns before merging): {len(raw_columns)}")
    for idx, col in enumerate(raw_columns):
        print(f"  Raw Col {idx}: [{col[0]}, {col[1]}] width: {col[1] - col[0]}")
        
    # Gaps between raw columns
    print("\n--- Gaps between Raw Columns ---")
    for idx in range(len(raw_columns) - 1):
        c1 = raw_columns[idx]
        c2 = raw_columns[idx+1]
        gap = c2[0] - c1[1]
        print(f"  Gap between Col {idx} and Col {idx+1}: {gap}px")
        
    # Run projection boundary output
    final_bounds = project_column_boundaries(region_blocks)
    debug_info = get_last_projection_debug()
    print("\n--- Column Projection Debug Info ---")
    for k, v in debug_info.items():
        print(f"  {k}: {v}")
        
if __name__ == "__main__":
    main()
