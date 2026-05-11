import os
import cv2
import numpy as np
import statistics
from PIL import Image
from typing import List, Tuple, Dict, Any
from models.layout_models import OCRBlock, TableRegion, RowRegion, ColumnRegion, TableCell, GeometryBox, RegionType
from services.tsr.base_tsr import BaseTSREngine
from core.logger import logger
from services.topology.topology_cleanup import TopologyCleaner

def compute_stable_bands(intervals: List[Tuple[float, float]], overlap_thresh: float = 0.35) -> List[Tuple[float, float]]:
    """
    Derives non-overlapping unified 1D bands by merging highly overlapping coordinate intervals.
    Prevents multi-line cells from generating duplicate cluster ids.
    """
    if not intervals:
        return []
    # Sort intervals by their center location to group adjacently
    sorted_intervals = sorted(intervals, key=lambda x: (x[0] + x[1]) / 2.0)
    
    bands = []
    curr_band = sorted_intervals[0]
    
    for nxt in sorted_intervals[1:]:
        # Calculate Intersection over Min-Length ratio
        ov_min = max(curr_band[0], nxt[0])
        ov_max = min(curr_band[1], nxt[1])
        intersect = max(0.0, float(ov_max - ov_min))
        min_len = min(curr_band[1] - curr_band[0], nxt[1] - nxt[0])
        
        if min_len > 0 and (intersect / min_len) > overlap_thresh:
            # Form a unified envelope
            curr_band = (min(curr_band[0], nxt[0]), max(curr_band[1], nxt[1]))
        else:
            bands.append(curr_band)
            curr_band = nxt
            
    bands.append(curr_band)
    return sorted(bands, key=lambda x: x[0])

def get_best_matching_band(val_min: float, val_max: float, bands: List[Tuple[float, float]]) -> int:
    """Matches a target span to the band offering maximum length overlap."""
    best_idx = 0
    max_intersect = -1.0
    
    for i, band in enumerate(bands):
        ov_min = max(val_min, band[0])
        ov_max = min(val_max, band[1])
        intersect = max(0.0, float(ov_max - ov_min))
        
        if intersect > max_intersect:
            max_intersect = intersect
            best_idx = i
            
    # Fallback to strict distance metric if the box lives completely outside predicted bands
    if max_intersect <= 0.0:
        target_c = (val_min + val_max) / 2.0
        best_idx = min(range(len(bands)), key=lambda i: abs(((bands[i][0] + bands[i][1]) / 2.0) - target_c))
        
    return best_idx

def transform_point(pt: Tuple[float, float], matrix: np.ndarray) -> Tuple[float, float]:
    px = (matrix[0, 0] * pt[0] + matrix[0, 1] * pt[1] + matrix[0, 2])
    py = (matrix[1, 0] * pt[0] + matrix[1, 1] * pt[1] + matrix[1, 2])
    return (px, py)

def build_geom_from_bbox(bbox: List[float], inv_matrix: np.ndarray = None) -> GeometryBox:
    min_x, min_y, max_x, max_y = bbox[0], bbox[1], bbox[2], bbox[3]
    if inv_matrix is None:
        return GeometryBox(
            min_x=float(min_x), min_y=float(min_y), max_x=float(max_x), max_y=float(max_y),
            center_x=float((min_x + max_x) / 2), center_y=float((min_y + max_y) / 2)
        )
    
    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    trans_pts = [transform_point(p, inv_matrix) for p in corners]
    xs = [p[0] for p in trans_pts]
    ys = [p[1] for p in trans_pts]
    f_min_x, f_max_x = min(xs), max(xs)
    f_min_y, f_max_y = min(ys), max(ys)
    
    return GeometryBox(
        min_x=float(f_min_x), min_y=float(f_min_y), max_x=float(f_max_x), max_y=float(f_max_y),
        center_x=float((f_min_x + f_max_x) / 2), center_y=float((f_min_y + f_max_y) / 2)
    )

def get_full_affine_transform(img_cv: np.ndarray, rotate_code: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generates a deterministic OpenCV image transform and cumulative affine matrix.
    rotate_code: 0 (none), 90, 180, 270 clockwise.
    """
    h, w = img_cv.shape[:2]
    M = np.eye(3)
    
    # Base rotation
    if rotate_code != 0:
        center = (w // 2, h // 2)
        M_rot_2x3 = cv2.getRotationMatrix2D(center, -rotate_code, 1.0)
        
        # Re-bind the new window dimensions to prevent clipping corner contents
        cos = np.abs(M_rot_2x3[0, 0])
        sin = np.abs(M_rot_2x3[0, 1])
        nW = int((h * sin) + (w * cos))
        nH = int((h * cos) + (w * sin))
        M_rot_2x3[0, 2] += (nW / 2) - center[0]
        M_rot_2x3[1, 2] += (nH / 2) - center[1]
        
        warped = cv2.warpAffine(img_cv, M_rot_2x3, (nW, nH), borderValue=(255, 255, 255))
        M = np.vstack([M_rot_2x3, [0, 0, 1]]) @ M
        
        cur_h, cur_w = warped.shape[:2]
    else:
        warped = img_cv.copy()
        cur_h, cur_w = h, w
        
    # Apply deskew logic on pre-warped candidate to maximize its scoring chance
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    
    deskew_angle = 0.0
    if len(coords) > 10:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            deskew_angle = -(90 + angle)
        else:
            deskew_angle = -angle
            
    if abs(deskew_angle) > 0.3 and abs(deskew_angle) < 15.0:
        center = (cur_w // 2, cur_h // 2)
        M_skew_2x3 = cv2.getRotationMatrix2D(center, deskew_angle, 1.0)
        final_warped = cv2.warpAffine(warped, M_skew_2x3, (cur_w, cur_h), borderValue=(255, 255, 255))
        M = np.vstack([M_skew_2x3, [0, 0, 1]]) @ M
        return final_warped, M
        
    return warped, M

class PPStructure_TSREngine(BaseTSREngine):
    def __init__(self):
        self._engine = None
        
    def _get_engine(self):
        if self._engine is None:
            logger.info("Lazy loading PP-StructureV3 (CPU mode for architecture validation)...")
            from paddleocr import PPStructure
            self._engine = PPStructure(
                show_log=False,
                image_orientation=False,
                use_gpu=False
            )
        return self._engine

    def detect_tables(self, blocks: List[OCRBlock], image: Image.Image = None) -> Tuple[List[TableRegion], Dict[str, Any]]:
        if image is None:
            return [], {"error": "No image"}
            
        engine = self._get_engine()
        
        debug_dir = "datasets/debug"
        os.makedirs(debug_dir, exist_ok=True)
        
        img_np = np.array(image.convert("RGB"))
        img_cv = img_np[:, :, ::-1]
        
        candidate_orientations = [
            (0, "tsr_input_original.png"),
            (90, "tsr_input_rot90.png"),
            (180, "tsr_input_rot180.png"),
            (270, "tsr_input_rot270.png")
        ]
        
        candidates = []
        
        logger.info(f"Starting multi-orientation analysis ({len(candidate_orientations)} candidates)...")
        
        for angle, filename in candidate_orientations:
            norm_img, M_total = get_full_affine_transform(img_cv, angle)
            
            # Save candidate to debug folder
            cv2.imwrite(os.path.join(debug_dir, filename), norm_img)
            
            logger.info(f"Running PP-Structure inference on {angle}-degree candidate...")
            results = engine(norm_img)
            
            # Score computation
            table_count = 0
            total_cells = 0
            table_bboxes = []
            
            for res in results:
                if res.get('type') == 'table':
                    table_count += 1
                    res_data = res.get('res', {})
                    total_cells += len(res_data.get('cell_bbox', []))
                    if 'bbox' in res:
                        table_bboxes.append(res['bbox'])
            
            # Compute simple orphan token estimate for scoring
            # Transform all OCR block center points to candidate space
            orphan_estimate = 0
            for b in blocks:
                if b.normalized_geometry:
                    pt_orig = (b.normalized_geometry.center_x, b.normalized_geometry.center_y)
                    pt_cand = transform_point(pt_orig, M_total)
                    
                    # Check if point lies inside any table boundary
                    contained = False
                    for box in table_bboxes:
                        if box[0] <= pt_cand[0] <= box[2] and box[1] <= pt_cand[1] <= box[3]:
                            contained = True
                            break
                    if not contained:
                        orphan_estimate += 1
            
            # User recommended formula:
            score = (table_count * 100) + (total_cells * 5) - (orphan_estimate * 0.1) # weighted down slightly to ensure cell weight wins
            
            logger.info(f"[Candidate {angle}] tables={table_count}, cells={total_cells}, score={score:.2f}")
            candidates.append({
                "angle": angle,
                "score": score,
                "table_count": table_count,
                "total_cells": total_cells,
                "results": results,
                "image": norm_img,
                "matrix": M_total
            })
            
        # Select absolute winner
        winner = max(candidates, key=lambda x: x["score"])
        logger.info(f"Orientation Decision: WINNER={winner['angle']} with score {winner['score']:.2f}")
        
        # Save selected final output debug image
        cv2.imwrite(os.path.join(debug_dir, "tsr_selected_orientation.png"), winner['image'])
        
        try:
            M_inv = np.linalg.inv(winner['matrix'])
        except:
            M_inv = np.eye(3)
            
        # --- NEW Diagnostic Artifact Persistence ---
        import json
        def numpy_sanitizer(obj):
            if isinstance(obj, (np.ndarray, np.generic)):
                return obj.tolist()
            return str(obj)
            
        # 1. Dump original AI model output before coordinate realignment
        with open(os.path.join(debug_dir, "raw_ppstructure_response.json"), "w", encoding="utf-8") as f:
            json.dump(winner['results'], f, default=numpy_sanitizer, indent=2)
            
        # Overlay visual diagnostic copy
        overlay_img = winner['image'].copy()
        
        final_regions = []
        table_counter = 0
        
        for res in winner['results']:
            if res.get('type') == 'table':
                res_data = res.get('res', {})
                bbox = res.get('bbox')
                cell_bboxes = res_data.get('cell_bbox', [])
                
                if bbox:
                    cv2.rectangle(overlay_img, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), (0, 255, 0), 3)
                
                # --- TOPOLOGY CLEANUP STAGE INJECTED ---
                # Refines noise, merges phantom fragments BEFORE canonical banding.
                cleaner = TopologyCleaner()
                final_cell_bboxes = cleaner.clean_cell_boxes(cell_bboxes)
                
                for cb in final_cell_bboxes:
                    cv2.rectangle(overlay_img, (int(cb[0]), int(cb[1])), (int(cb[2]), int(cb[3])), (255, 0, 0), 1)
                
                t_geom_orig = build_geom_from_bbox(bbox, M_inv)
                t_geom_norm = build_geom_from_bbox(bbox, None)
                
                region = TableRegion(
                    table_id=f"table_{table_counter}",
                    region_type=RegionType.TABLE,
                    geometry=t_geom_orig,
                    original_geometry=t_geom_orig,
                    normalized_geometry=t_geom_norm,
                    source_engine="ppstructure"
                )
                
                if not final_cell_bboxes:
                    final_regions.append(region)
                    table_counter += 1
                    continue
                    
                # 1. Generate Interval Domains directly from source bounding box extents
                y_intervals = [(b[1], b[3]) for b in final_cell_bboxes]
                x_intervals = [(b[0], b[2]) for b in final_cell_bboxes]
                
                # 2. Derive Canonical Row and Column bands (Merging overlaps > 35%)
                row_bands = compute_stable_bands(y_intervals, overlap_thresh=0.35)
                col_bands = compute_stable_bands(x_intervals, overlap_thresh=0.35)
                
                logger.info(f"Topology Inference [Table {table_counter}]: Derived {len(row_bands)} Row Bands, {len(col_bands)} Col Bands.")
                
                # 3. Perform Slot-Occupancy Assignment ensuring unique cell placement
                slot_occupants = {} 
                collision_count = 0
                
                # Track logical usage explicitly to support pure Sparse-Occupancy modeling
                utilized_rows = set()
                utilized_cols = set()
                
                for cb in final_cell_bboxes:
                    row_idx = get_best_matching_band(cb[1], cb[3], row_bands)
                    col_idx = get_best_matching_band(cb[0], cb[2], col_bands)
                    slot_key = (row_idx, col_idx)
                    
                    # Calculate joint matching weight to break duplicate ties
                    y_ov = max(0.0, min(cb[3], row_bands[row_idx][1]) - max(cb[1], row_bands[row_idx][0]))
                    x_ov = max(0.0, min(cb[2], col_bands[col_idx][1]) - max(cb[0], col_bands[col_idx][0]))
                    fit_score = y_ov * x_ov # Area intersection weight
                    
                    c_geom_orig = build_geom_from_bbox(cb, M_inv)
                    c_geom_norm = build_geom_from_bbox(cb, None)
                    
                    cell_obj = TableCell(
                        row_id=f"row_{row_idx}",
                        col_id=f"col_{col_idx}",
                        geometry=c_geom_orig,
                        original_geometry=c_geom_orig,
                        normalized_geometry=c_geom_norm
                    )
                    
                    if slot_key in slot_occupants:
                        collision_count += 1
                        existing_score = slot_occupants[slot_key][0]
                        if fit_score > existing_score:
                            slot_occupants[slot_key] = (fit_score, cell_obj)
                    else:
                        slot_occupants[slot_key] = (fit_score, cell_obj)
                        
                    utilized_rows.add(row_idx)
                    utilized_cols.add(col_idx)
                
                # 4. Materialize Active Sparse Domains with GEOMETRY from computed bands
                # Row bands and column bands carry the canonical spatial truth — preserve it.
                for rid in sorted(list(utilized_rows)):
                    band = row_bands[rid]
                    row_geom = build_geom_from_bbox(
                        [col_bands[0][0], band[0], col_bands[-1][1], band[1]], None
                    )
                    region.rows.append(RowRegion(
                        row_id=f"row_{rid}",
                        geometry=row_geom,
                        normalized_geometry=row_geom
                    ))
                for cid in sorted(list(utilized_cols)):
                    band = col_bands[cid]
                    col_geom = build_geom_from_bbox(
                        [band[0], row_bands[0][0], band[1], row_bands[-1][1]], None
                    )
                    region.columns.append(ColumnRegion(
                        col_id=f"col_{cid}",
                        geometry=col_geom,
                        normalized_geometry=col_geom
                    ))
                    
                if collision_count > 0:
                    logger.warning(f"[VALIDATION ALERT] Dropped {collision_count} overlapping cell box collisions inside Table {table_counter}")
                    
                # Commit distinct, filtered cell set
                for _, final_cell in slot_occupants.values():
                    region.cells.append(final_cell)
                
                # Compute topology confidence from structural quality signals
                total_source_cells = len(final_cell_bboxes)
                placed_cells = len(slot_occupants)
                collision_ratio = collision_count / total_source_cells if total_source_cells > 0 else 0.0
                coverage = placed_cells / max(1, len(utilized_rows) * len(utilized_cols))
                # High collisions or low coverage = low confidence
                region.topology_confidence = round(max(0.1, min(1.0, coverage * (1.0 - collision_ratio))), 3)
                logger.info(f"Table {table_counter} topology_confidence={region.topology_confidence} (coverage={coverage:.2f}, collision_ratio={collision_ratio:.2f})")
                    
                final_regions.append(region)
                table_counter += 1
                
        cv2.imwrite(os.path.join(debug_dir, "tsr_ppstructure_overlay.png"), overlay_img)
        
        # 2. Dump structured geometry grid audit
        cell_grid_audit = []
        for tr in final_regions:
            t_data = {"table_id": tr.table_id, "cells": []}
            for cl in tr.cells:
                t_data["cells"].append({
                    "row": cl.row_id, "col": cl.col_id,
                    "normalized_bbox": [cl.normalized_geometry.min_x, cl.normalized_geometry.min_y, 
                                       cl.normalized_geometry.max_x, cl.normalized_geometry.max_y] if cl.normalized_geometry else []
                })
            cell_grid_audit.append(t_data)
            
        with open(os.path.join(debug_dir, "normalized_cell_grid.json"), "w", encoding="utf-8") as f:
            json.dump(cell_grid_audit, f, indent=2)
        
        meta = {
            "selected_orientation": f"rotate_{winner['angle']}",
            "orientation_score": float(winner["score"]),
            "orientation_candidates_tested": len(candidate_orientations),
            "final_inference_dims": list(winner["image"].shape[:2])
        }
        
        return final_regions, meta
