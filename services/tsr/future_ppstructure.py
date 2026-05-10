import os
import cv2
import numpy as np
import statistics
from PIL import Image
from typing import List, Tuple, Dict, Any
from models.layout_models import OCRBlock, TableRegion, RowRegion, ColumnRegion, TableCell, GeometryBox, RegionType
from services.tsr.base_tsr import BaseTSREngine
from core.logger import logger

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
                for cb in cell_bboxes:
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
                
                if not cell_bboxes:
                    final_regions.append(region)
                    table_counter += 1
                    continue
                    
                y_c = [(b[1] + b[3]) / 2 for b in cell_bboxes]
                y_s = sorted(list(set(y_c)))
                row_clusters = []
                for y in y_s:
                    if not row_clusters or y - row_clusters[-1][-1] > 10:
                        row_clusters.append([y])
                    else:
                        row_clusters[-1].append(y)
                row_y = [sum(c)/len(c) for c in row_clusters]
                
                x_c = [(b[0] + b[2]) / 2 for b in cell_bboxes]
                x_s = sorted(list(set(x_c)))
                col_clusters = []
                for x in x_s:
                    if not col_clusters or x - col_clusters[-1][-1] > 10:
                        col_clusters.append([x])
                    else:
                        col_clusters[-1].append(x)
                col_x = [sum(c)/len(c) for c in col_clusters]
                
                for i in range(len(row_y)):
                    region.rows.append(RowRegion(row_id=f"row_{i}"))
                for j in range(len(col_x)):
                    region.columns.append(ColumnRegion(col_id=f"col_{j}"))
                    
                for cb in cell_bboxes:
                    cy = (cb[1] + cb[3]) / 2
                    cx = (cb[0] + cb[2]) / 2
                    row_idx = min(range(len(row_y)), key=lambda i: abs(row_y[i] - cy))
                    col_idx = min(range(len(col_x)), key=lambda j: abs(col_x[j] - cx))
                    
                    c_geom_orig = build_geom_from_bbox(cb, M_inv)
                    c_geom_norm = build_geom_from_bbox(cb, None)
                    
                    region.cells.append(TableCell(
                        row_id=f"row_{row_idx}",
                        col_id=f"col_{col_idx}",
                        geometry=c_geom_orig,
                        original_geometry=c_geom_orig,
                        normalized_geometry=c_geom_norm
                    ))
                    
                final_regions.append(region)
                table_counter += 1
                
        cv2.imwrite(os.path.join(debug_dir, "tsr_ppstructure_overlay.png"), overlay_img)
        
        meta = {
            "selected_orientation": f"rotate_{winner['angle']}",
            "orientation_score": float(winner["score"]),
            "orientation_candidates_tested": len(candidate_orientations),
            "final_inference_dims": list(winner["image"].shape[:2])
        }
        
        return final_regions, meta
