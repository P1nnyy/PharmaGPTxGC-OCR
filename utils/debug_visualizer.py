import os
import cv2
import numpy as np
from typing import Any, Dict, List
from core.logger import logger
from models.layout_models import OCRBlock, TableRegion

def _safe_anchor_x(block: OCRBlock) -> float:
    """Debug-only numeric marker; avoid importing optional anchor internals at module import."""
    anchor = getattr(block, "anchor_x", None)
    if anchor is not None:
        return float(anchor)
    if block.normalized_geometry:
        return float(block.normalized_geometry.max_x)
    return 0.0

def _ensure_output_dir(output_path: str) -> None:
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

def draw_debug_visualization(blocks: List[OCRBlock], regions: List[TableRegion], image_width: float, image_height: float, output_path: str):
    """
    Renders a debug image visualizing the spatial reconstruction.
    """
    try:
        image_width = int(image_width)
        image_height = int(image_height)
        
        # 3. Validate canvas dimensions before allocation
        if image_width <= 0 or image_height <= 0:
            raise ValueError(f"Invalid canvas dimensions: width={image_width}, height={image_height}")
            
        # 4. Validate OpenCV canvas creation
        canvas = np.ones((image_height, image_width, 3), dtype=np.uint8) * 255
        
        if canvas.shape != (image_height, image_width, 3):
            raise RuntimeError(f"Failed to allocate OpenCV canvas with shape {(image_height, image_width, 3)}")
        if canvas.dtype != np.uint8:
            raise RuntimeError(f"Invalid canvas dtype: {canvas.dtype}")

        # 2. Add explicit logging
        logger.info(f"Generating debug visualization: dims={image_width}x{image_height}, blocks={len(blocks)}, regions={len(regions)}, path={output_path}")
        
        # Colors (BGR for OpenCV)
        COLOR_RAW_POLYGON = (200, 200, 200)
        COLOR_NORMALIZED_BBOX = (255, 150, 150)
        COLOR_ANCHOR = (0, 0, 255)
        COLOR_TABLE = (0, 0, 0)
        COLOR_CELL = (0, 200, 0)
        COLOR_ROW = (0, 100, 200)
        
        # 1. Draw raw polygons and bounding boxes
        for block in blocks:
            poly = block.polygon
            if len(poly) == 4:
                pts = np.array([[int(p[0]), int(p[1])] for p in poly], np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(canvas, [pts], isClosed=True, color=COLOR_RAW_POLYGON, thickness=1)
                
            if block.normalized_geometry:
                geom = block.normalized_geometry
                assert geom.max_x >= geom.min_x, f"Invalid block X ordering: {geom.min_x} to {geom.max_x}"
                assert geom.max_y >= geom.min_y, f"Invalid block Y ordering: {geom.min_y} to {geom.max_y}"
                assert np.isfinite([geom.min_x, geom.max_x, geom.min_y, geom.max_y]).all(), "NaN/Inf in block geometry"
                
                pt1 = (int(geom.min_x), int(geom.min_y))
                pt2 = (int(geom.max_x), int(geom.max_y))
                cv2.rectangle(canvas, pt1, pt2, COLOR_NORMALIZED_BBOX, 1)
                
                cv2.putText(canvas, block.text[:10], (int(geom.min_x) + 2, int(geom.min_y) + 12), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
                
                # Draw numeric anchors
                if block.is_numeric:
                    anchor_x = int(_safe_anchor_x(block))
                    anchor_y = int(geom.center_y)
                    cv2.circle(canvas, (anchor_x, anchor_y), 3, COLOR_ANCHOR, -1)
                    
        # 2. Draw TSR Grids
        for region in regions:
            if region.geometry:
                rg = region.geometry
                assert rg.max_x >= rg.min_x, f"Invalid region X ordering: {rg.min_x} to {rg.max_x}"
                assert rg.max_y >= rg.min_y, f"Invalid region Y ordering: {rg.min_y} to {rg.max_y}"
                assert np.isfinite([rg.min_x, rg.max_x, rg.min_y, rg.max_y]).all(), "NaN/Inf in region geometry"
                
                pt1 = (int(rg.min_x), int(rg.min_y))
                pt2 = (int(rg.max_x), int(rg.max_y))
                cv2.rectangle(canvas, pt1, pt2, COLOR_TABLE, 3)
                
                text_y = max(0, int(rg.min_y) - 5)
                cv2.putText(canvas, f"Region: {region.region_type.value} | Engine: {region.source_engine}", 
                            (int(rg.min_x), text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_TABLE, 1)
                
            for row in region.rows:
                if row.geometry:
                    rg = row.geometry
                    cv2.rectangle(canvas, (int(rg.min_x), int(rg.min_y)), (int(rg.max_x), int(rg.max_y)), COLOR_ROW, 2)
                    
            for cell in region.cells:
                if cell.geometry:
                    cg = cell.geometry
                    cv2.rectangle(canvas, (int(cg.min_x), int(cg.min_y)), (int(cg.max_x), int(cg.max_y)), COLOR_CELL, 1)
                    
                    # Annotate cell ID
                    text_label = f"{cell.row_id},{cell.col_id}"
                    cv2.putText(canvas, text_label, (int(cg.min_x) + 2, int(cg.min_y) + 12), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_CELL, 1)
                    
        _ensure_output_dir(output_path)
        
        # 5. Check cv2.imwrite success
        success = cv2.imwrite(output_path, canvas)
        if not success:
            raise RuntimeError(f"cv2.imwrite failed to save image to {output_path}")
            
        # 6. Add final logger
        logger.info(f"Saved visualization to {output_path}")
        
    except Exception as e:
        logger.exception(f"Failed to generate debug visualization: {e}")

def draw_debug_visualization_v2(blocks: List[OCRBlock], regions: List[TableRegion], image_width: float, image_height: float, output_path: str, visual_rows: List[Dict[str, Any]] = None, merge_audit: List[Dict[str, Any]] = None):
    """
    TASK 4: Advanced Visualizer rendering visual vs semantic layers and fusion connectors.
    """
    try:
        image_width = int(image_width)
        image_height = int(image_height)
        
        # Allocate white canvas
        canvas = np.ones((image_height, image_width, 3), dtype=np.uint8) * 255
        
        # Layer Colors (BGR)
        COLOR_TEXT = (100, 100, 100)
        COLOR_VISUAL_ROW = (200, 200, 255) # Light blue thin boxes
        COLOR_SEMANTIC_ROW = (0, 150, 0)   # Dark green thick boxes
        COLOR_MERGE_SUCCESS = (0, 255, 0)  # Bright green arrows
        COLOR_MERGE_REJECT = (0, 0, 255)   # Red X line
        
        # --- 1. Render Visual Rows (Input State) ---
        if visual_rows:
            for v_row in visual_rows:
                geom = v_row.get("geometry")
                if geom:
                    cv2.rectangle(canvas, (int(geom.min_x), int(geom.min_y)), (int(geom.max_x), int(geom.max_y)), COLOR_VISUAL_ROW, 1)
                    cv2.putText(canvas, "V-Row", (int(geom.min_x) + 5, int(geom.min_y) + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.3, COLOR_VISUAL_ROW, 1)

        # --- 2. Render Semantic Rows (Output State) ---
        for region in regions:
             for row in region.rows:
                 if row.geometry:
                     g = row.geometry
                     # Thicker border for semantic composite
                     cv2.rectangle(canvas, (int(g.min_x), int(g.min_y)), (int(g.max_x), int(g.max_y)), COLOR_SEMANTIC_ROW, 2)
                     
                     # Show Stability Score
                     score = getattr(row, 'stability', 1.0)
                     label = f"SEMANTIC ROW [S={score:.2f}]"
                     cv2.putText(canvas, label, (int(g.min_x) + 2, int(g.max_y) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_SEMANTIC_ROW, 1)

        # --- 3. Render Merge Action Audit Trail (Connectors) ---
        if merge_audit and visual_rows:
             v_row_map = {r["row_id"]: r["geometry"] for r in visual_rows if r.get("geometry")}
             
             for action in merge_audit:
                 p_id = action.get("prev_id")
                 c_id = action.get("curr_id")
                 success = action.get("should_merge", False)
                 
                 g1 = v_row_map.get(p_id)
                 g2 = v_row_map.get(c_id)
                 
                 if g1 and g2:
                     start_pt = (int(g1.min_x + 30), int(g1.center_y))
                     end_pt = (int(g2.min_x + 30), int(g2.center_y))
                     
                     if success:
                         # Draw Success Arrow linking them
                         cv2.arrowedLine(canvas, start_pt, end_pt, COLOR_MERGE_SUCCESS, 2, tipLength=0.3)
                     else:
                         # Draw explicit rejection line/marker
                         mid_pt = (int((start_pt[0] + end_pt[0])/2), int((start_pt[1] + end_pt[1])/2))
                         cv2.line(canvas, (mid_pt[0]-10, mid_pt[1]-10), (mid_pt[0]+10, mid_pt[1]+10), COLOR_MERGE_REJECT, 2)
                         cv2.line(canvas, (mid_pt[0]+10, mid_pt[1]-10), (mid_pt[0]-10, mid_pt[1]+10), COLOR_MERGE_REJECT, 2)
                         # Print reject reason small
                         cv2.putText(canvas, action.get("reason", ""), (mid_pt[0] + 15, mid_pt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.3, COLOR_MERGE_REJECT, 1)

        # --- 4. Draw basic text overlay for spatial reference ---
        for b in blocks:
             if b.normalized_geometry:
                 g = b.normalized_geometry
                 cv2.putText(canvas, b.text[:8], (int(g.min_x), int(g.center_y)), cv2.FONT_HERSHEY_SIMPLEX, 0.3, COLOR_TEXT, 1)
                 
        _ensure_output_dir(output_path)
        cv2.imwrite(output_path, canvas)
        logger.info(f"Saved v2 visualization showing multiline graph to {output_path}")
        
    except Exception as e:
        logger.exception(f"V2 viz failure: {e}")
