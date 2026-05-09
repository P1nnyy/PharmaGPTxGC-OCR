import os
import sys
import cv2
import json
import numpy as np
from typing import List, Dict, Any

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

def draw_layout_debug(image_path: str, json_path: str, output_path: str):
    """
    Overlays robust OCR/TSR annotations and saves specifically into verification/visualizations/.
    High-visibility markers:
    - OCR Polygons: Light Blue (255, 200, 100)
    - Reconstructed Rows: Orange (0, 128, 255)
    - Columns / Cells: Green (0, 200, 0)
    - Orphan Tokens: BRIGHT MAGENTA (255, 0, 255)
    """
    if not os.path.exists(image_path) or not os.path.exists(json_path):
        print(f"Skipping visualization: Missing image or JSON for {os.path.basename(image_path)}")
        return

    canvas = cv2.imread(image_path)
    if canvas is None:
        print(f"Failed to load image: {image_path}")
        return

    h, w, _ = canvas.shape
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    metadata = data.get("metadata", {})
    blocks = metadata.get("blocks", [])
    structured_tables = metadata.get("structured_tables", [])
    
    # Track mapped IDs to isolate orphans
    mapped_ids = set()
    for table in structured_tables:
        for cell in table.get("cells", []):
            mapped_ids.update(cell.get("mapped_block_ids", []))
            
    # Draw OCR tokens & flag orphans in bright magenta
    for b in blocks:
        poly = b.get("polygon", [])
        is_orphan = b.get("id") not in mapped_ids
        
        color = (255, 0, 255) if is_orphan else (255, 200, 100) # Magenta if orphan, light blue otherwise
        thickness = 2 if is_orphan else 1
        
        if len(poly) == 4:
            pts = np.array([[int(pt[0]), int(pt[1])] for pt in poly], np.int32)
            cv2.polylines(canvas, [pts.reshape((-1, 1, 2))], isClosed=True, color=color, thickness=thickness)
            
            # Label text
            label = b.get("text", "")[:10]
            if is_orphan:
                label = f"[ORPHAN] {label}"
            cv2.putText(canvas, label, (int(poly[0][0]), int(poly[0][1]) - 4), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

    # Draw Table structure regions
    for table_idx, table in enumerate(structured_tables):
        geom = table.get("geometry")
        if geom:
            pt1 = (int(geom["min_x"]), int(geom["min_y"]))
            pt2 = (int(geom["max_x"]), int(geom["max_y"]))
            cv2.rectangle(canvas, pt1, pt2, (0, 0, 255), 3) # Table boundaries in red
            
            # Label table region type
            cv2.putText(canvas, f"Table: {table.get('region_type', 'unknown')}", (pt1[0], pt1[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
        # Draw cells
        for cell in table.get("cells", []):
            cg = cell.get("geometry")
            if cg:
                pt1 = (int(cg["min_x"]), int(cg["min_y"]))
                pt2 = (int(cg["max_x"]), int(cg["max_y"]))
                cv2.rectangle(canvas, pt1, pt2, (0, 200, 0), 1) # Green cell lines
                
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, canvas)
    print(f"✅ Saved layout debug visualization to: {output_path}")

def render_all_visualizations():
    image_dir = os.path.join(PROJECT_ROOT, "test_images")
    results_dir = os.path.join(PROJECT_ROOT, "results")
    vis_dir = os.path.join(PROJECT_ROOT, "verification/visualizations")
    
    if not os.path.exists(image_dir) or not os.path.exists(results_dir):
        print("Missing test_images/ or results/ directories.")
        return
        
    for f in os.listdir(image_dir):
        if f.lower().endswith((".jpg", ".jpeg", ".png")):
            img_path = os.path.join(image_dir, f)
            json_path = os.path.join(results_dir, f + ".json")
            out_path = os.path.join(vis_dir, f"annotated_{f}")
            draw_layout_debug(img_path, json_path, out_path)

if __name__ == "__main__":
    render_all_visualizations()
