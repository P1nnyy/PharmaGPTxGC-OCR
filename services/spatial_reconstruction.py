from typing import List, Dict, Any
import math
import re
import numpy as np
from core.logger import logger
from utils.debug_visualizer import draw_debug_visualization

def _compute_base_geometry(block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes initial bounding box geometry from an OCR polygon.
    """
    polygon = block.get("polygon", [])
    if not polygon or len(polygon) < 3:
        geom = {
            "min_x": 0.0, "max_x": 0.0,
            "min_y": 0.0, "max_y": 0.0,
            "center_x": 0.0, "center_y": 0.0
        }
        block["original_geometry"] = geom
        block["normalized_geometry"] = geom.copy()
        return block
        
    xs = [pt[0] for pt in polygon]
    ys = [pt[1] for pt in polygon]
    
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    
    geom = {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
        "center_x": (min_x + max_x) / 2.0,
        "center_y": (min_y + max_y) / 2.0
    }
    
    block["original_geometry"] = geom
    block["normalized_geometry"] = geom.copy()
    
    return block

def _estimate_skew_angle(blocks: List[Dict[str, Any]]) -> float:
    angles = []
    for block in blocks:
        polygon = block.get("polygon", [])
        if len(polygon) == 4:
            # use top edge
            dy = polygon[1][1] - polygon[0][1]
            dx = polygon[1][0] - polygon[0][0]
            if dx != 0:
                angles.append(math.atan2(dy, dx))
    return float(np.median(angles)) if angles else 0.0

def _rotate_point(x, y, cx, cy, angle_rad):
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    nx = cx + (x - cx) * cos_a - (y - cy) * sin_a
    ny = cy + (x - cx) * sin_a + (y - cy) * cos_a
    return nx, ny

def _apply_skew_normalization(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    angle_rad = _estimate_skew_angle(blocks)
    logger.info(f"Dominant skew angle estimated: {math.degrees(angle_rad):.2f} degrees")
    
    if abs(angle_rad) < 0.01:
        return blocks
        
    # Find global center
    all_cx = [b["original_geometry"]["center_x"] for b in blocks if "original_geometry" in b]
    all_cy = [b["original_geometry"]["center_y"] for b in blocks if "original_geometry" in b]
    if not all_cx: return blocks
    
    global_cx = sum(all_cx) / len(all_cx)
    global_cy = sum(all_cy) / len(all_cy)
    
    for block in blocks:
        geom = block["original_geometry"]
        polygon = block.get("polygon", [])
        if len(polygon) == 4:
            rot_pts = [_rotate_point(pt[0], pt[1], global_cx, global_cy, -angle_rad) for pt in polygon]
            xs = [pt[0] for pt in rot_pts]
            ys = [pt[1] for pt in rot_pts]
            block["normalized_geometry"] = {
                "min_x": min(xs), "max_x": max(xs),
                "min_y": min(ys), "max_y": max(ys),
                "center_x": sum(xs)/4.0, "center_y": sum(ys)/4.0
            }
            
    return blocks

def _cluster_into_rows(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Phase 2: Naive Y-overlap clustering and X-sorting."""
    if not blocks:
        return []
        
    # Sort blocks by center_y initially to process top-to-bottom
    sorted_blocks = sorted(blocks, key=lambda b: b["normalized_geometry"]["center_y"])
    
    rows = []
    
    for block in sorted_blocks:
        geom = block["normalized_geometry"]
        b_min_y, b_max_y = geom["min_y"], geom["max_y"]
        b_height = b_max_y - b_min_y
        
        placed = False
        for row in rows:
            avg_cy = sum(b["normalized_geometry"]["center_y"] for b in row["blocks"]) / len(row["blocks"])
            avg_h = sum((b["normalized_geometry"]["max_y"] - b["normalized_geometry"]["min_y"]) for b in row["blocks"]) / len(row["blocks"])
            
            r_min_y = avg_cy - (avg_h / 2.0)
            r_max_y = avg_cy + (avg_h / 2.0)
            r_height = r_max_y - r_min_y
            
            overlap = min(r_max_y, b_max_y) - max(r_min_y, b_min_y)
            if overlap > 0:
                min_height = min(b_height, r_height)
                # If overlap is > 40% of the smaller height
                if min_height > 0 and (overlap / min_height) > 0.4:
                    row["blocks"].append(block)
                    placed = True
                    break
        
        if not placed:
            rows.append({"blocks": [block]})
            
    # Sort blocks within each row left-to-right (by min_x)
    for idx, row in enumerate(rows):
        row["row_index"] = idx
        row["blocks"] = sorted(row["blocks"], key=lambda b: b["normalized_geometry"]["min_x"])
        
    return rows

def _classify_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Phase 4: Contextual Row Classification"""
    for row in rows:
        text = " ".join([b.get("text", "") for b in row["blocks"]]).upper()
        
        has_price = bool(re.search(r'\b\d+\.\d{2}\b', text))
        has_date = bool(re.search(r'\b\d{2}[-/]\d{2,4}\b', text))
        has_hsn = bool(re.search(r'\b\d{4,8}\b', text))
        has_med_keyword = bool(re.search(r'\b(TABS?|CAPS?|INJ|MG|ML|TABLETS?|CAPSULES?|SYRUPS?|OINTS?|\d+\'S)\b', text))
        
        if "TOTAL" in text or "AMOUNT" in text or "TAX" in text or "GST" in text:
            row["classification"] = "Totals"
        elif has_med_keyword or (has_price and (has_hsn or has_date)):
            row["classification"] = "Medicine Table Row"
        elif "INVOICE" in text or "DATE" in text or "PARTY" in text:
            row["classification"] = "Header"
        else:
            row["classification"] = "Unknown"
            
    return rows

def _project_columns_and_merge(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Phase 5: Global Column Projection and Multi-Line Spillover Merging"""
    if not rows: return rows
    
    # 1. Global X-Axis Column Boundaries
    all_blocks = []
    for row in rows:
        all_blocks.extend(row["blocks"])
        
    if not all_blocks: return rows
    
    heights = [(b["normalized_geometry"]["max_y"] - b["normalized_geometry"]["min_y"]) for b in all_blocks]
    median_height = float(np.median(heights)) if heights else 0.0
    gap_threshold = 1.5 * median_height if median_height > 0 else 50.0

    centers = [b["normalized_geometry"]["center_x"] for b in all_blocks]
    centers.sort()
    
    # Find gaps > gap_threshold to define sparse column clusters
    clusters = []
    current_cluster = [centers[0]]
    for x in centers[1:]:
        if x - current_cluster[-1] > gap_threshold:
            clusters.append(current_cluster)
            current_cluster = [x]
        else:
            current_cluster.append(x)
    if current_cluster:
        clusters.append(current_cluster)
        
    col_centroids = [sum(c)/len(c) for c in clusters]
    
    def get_col_id(x: float) -> str:
        idx = min(range(len(col_centroids)), key=lambda i: abs(col_centroids[i] - x))
        return f"col_{idx}"
        
    # Map blocks to columns
    for row in rows:
        row["columns"] = {}
        for b in row["blocks"]:
            col_id = get_col_id(b["normalized_geometry"]["center_x"])
            existing = row["columns"].get(col_id, "")
            row["columns"][col_id] = (existing + " " + b.get("text", "")).strip()

    # 2. Multi-line Row Merging
    merged_rows = []
    for row in rows:
        if row["classification"] == "Unknown" and merged_rows:
            prev_row = merged_rows[-1]
            if prev_row["classification"] == "Medicine Table Row":
                text = " ".join([b.get("text", "") for b in row["blocks"]])
                has_price = bool(re.search(r'\b\d+\.\d{2}\b', text))
                
                # If orphaned row lacks pricing, merge it up to previous medicine row
                if not has_price:
                    prev_row["blocks"].extend(row["blocks"])
                    for col_id, val in row.get("columns", {}).items():
                        existing = prev_row["columns"].get(col_id, "")
                        prev_row["columns"][col_id] = (existing + " " + val).strip()
                    logger.info(f"Merged multi-line orphan into Row {prev_row.get('row_index')}")
                    continue
                    
        merged_rows.append(row)
        
    return merged_rows

def reconstruct_layout(blocks: List[Dict[str, Any]], debug: bool = False) -> Dict[str, Any]:
    """
    Phase 1: Entry point for document-layout reasoning engine.
    Currently applies basic geometry calculation.
    """
    logger.info(f"Starting spatial reconstruction on {len(blocks)} blocks (Debug={debug})")
    
    # Step 1: Compute geometry
    enhanced_blocks = [_compute_base_geometry(b) for b in blocks]
    
    # Step 3: Skew Normalization
    enhanced_blocks = _apply_skew_normalization(enhanced_blocks)
    
    # Step 2: Naive Row Clustering
    reconstructed_rows = _cluster_into_rows(enhanced_blocks)
    logger.info(f"Clustered {len(enhanced_blocks)} blocks into {len(reconstructed_rows)} rows.")
    
    # Step 4: Semantic Row Classification
    reconstructed_rows = _classify_rows(reconstructed_rows)
    
    # Step 5: Column Projection & Multi-line Merging
    reconstructed_rows = _project_columns_and_merge(reconstructed_rows)
    
    # Extract structural metadata
    detected_table_rows = [r for r in reconstructed_rows if r.get("classification") == "Medicine Table Row"]
    
    # Step 3/5 (Visualizer)
    if debug and enhanced_blocks:
        max_x = max([b["original_geometry"]["max_x"] for b in enhanced_blocks] + [1000])
        max_y = max([b["original_geometry"]["max_y"] for b in enhanced_blocks] + [1000])
        draw_debug_visualization(enhanced_blocks, reconstructed_rows, max_x + 100, max_y + 100, "datasets/debug/latest_reconstruction.png")
    
    # Return structure expected by the API
    return {
        "reconstructed_rows": reconstructed_rows,
        "detected_table_rows": detected_table_rows,
        "columns_extracted": True
    }
