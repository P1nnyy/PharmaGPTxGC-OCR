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
    """Applies an affine 2x3 or 3x3 matrix to a single 2D point."""
    px = (matrix[0, 0] * pt[0] + matrix[0, 1] * pt[1] + matrix[0, 2])
    py = (matrix[1, 0] * pt[0] + matrix[1, 1] * pt[1] + matrix[1, 2])
    return (px, py)

def build_geom_from_bbox(bbox: List[float], inv_matrix: np.ndarray = None) -> GeometryBox:
    """Creates GeometryBox, applying inverse transform to four corners if provided."""
    min_x, min_y, max_x, max_y = bbox[0], bbox[1], bbox[2], bbox[3]
    if inv_matrix is None:
        return GeometryBox(
            min_x=float(min_x), min_y=float(min_y), max_x=float(max_x), max_y=float(max_y),
            center_x=float((min_x + max_x) / 2), center_y=float((min_y + max_y) / 2)
        )
    
    # Extract 4 corners from the bbox
    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    # Back-transform all 4 corners into original image coordinate system
    trans_pts = [transform_point(p, inv_matrix) for p in corners]
    
    xs = [p[0] for p in trans_pts]
    ys = [p[1] for p in trans_pts]
    
    f_min_x, f_max_x = min(xs), max(xs)
    f_min_y, f_max_y = min(ys), max(ys)
    
    return GeometryBox(
        min_x=float(f_min_x), min_y=float(f_min_y), max_x=float(f_max_x), max_y=float(f_max_y),
        center_x=float((f_min_x + f_max_x) / 2), center_y=float((f_min_y + f_max_y) / 2)
    )

class PPStructure_TSREngine(BaseTSREngine):
    def __init__(self):
        self._engine = None
        
    def _get_engine(self):
        if self._engine is None:
            logger.info("Lazy loading PP-StructureV3...")
            from paddleocr import PPStructure
            # use_gpu=False applied temporarily to bypass CUDA issues
            self._engine = PPStructure(
                show_log=False,
                image_orientation=False,
                use_gpu=False
            )
        return self._engine

    def detect_tables(self, blocks: List[OCRBlock], image: Image.Image = None) -> Tuple[List[TableRegion], Dict[str, Any]]:
        if image is None:
            logger.warning("PPStructure requires an image, but None was provided.")
            return [], {"error": "No image supplied"}
            
        # Save debug artifacts dir
        debug_dir = "datasets/debug"
        os.makedirs(debug_dir, exist_ok=True)
        
        # 1. Pre-Analysis: Check dominant text direction using median box aspect ratio
        widths = []
        heights = []
        for b in blocks:
            if b.normalized_geometry:
                w = b.normalized_geometry.max_x - b.normalized_geometry.min_x
                h = b.normalized_geometry.max_y - b.normalized_geometry.min_y
                if w > 0 and h > 0:
                    widths.append(w)
                    heights.append(h)
        
        is_rotated = False
        orientation_confidence = 0.0
        if widths:
            ratios = [h / w for h, w in zip(heights, widths)]
            median_ratio = statistics.median(ratios)
            orientation_confidence = float(min(median_ratio / 1.3, 1.0))
            if median_ratio > 1.3: # Average English word spans sideways
                is_rotated = True
                logger.info(f"Detected rotated image flow (median height/width: {median_ratio:.2f}). Applying normalization.")
        
        # Prep raw image
        img_np = np.array(image.convert("RGB"))
        img_cv = img_np[:, :, ::-1] # Convert to BGR
        
        # Save original image debug copy
        cv2.imwrite(os.path.join(debug_dir, "tsr_input_original.png"), img_cv)
        
        h, w = img_cv.shape[:2]
        M_cumulative = np.eye(3)
        
        # 2. Step A: Rotate 90 Deg Clockwise if vertical
        applied_rotation = 0
        if is_rotated:
            center = (w // 2, h // 2)
            # In OpenCV, negative is clockwise
            M_rot_2x3 = cv2.getRotationMatrix2D(center, -90, 1.0)
            
            # Adjust translation so the image bounds fully fit inside the new rectangle
            cos = np.abs(M_rot_2x3[0, 0])
            sin = np.abs(M_rot_2x3[0, 1])
            nW = int((h * sin) + (w * cos))
            nH = int((h * cos) + (w * sin))
            M_rot_2x3[0, 2] += (nW / 2) - center[0]
            M_rot_2x3[1, 2] += (nH / 2) - center[1]
            
            img_cv = cv2.warpAffine(img_cv, M_rot_2x3, (nW, nH), borderValue=(255, 255, 255))
            
            M_rot_3x3 = np.vstack([M_rot_2x3, [0, 0, 1]])
            M_cumulative = M_rot_3x3 @ M_cumulative
            applied_rotation = 90
            h, w = img_cv.shape[:2]
            
        # 3. Step B: Lightweight contour-based deskew on the intermediate image
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        # Threshold to find dense ink pixels
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        
        deskew_angle = 0.0
        if len(coords) > 10:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                deskew_angle = -(90 + angle)
            else:
                deskew_angle = -angle
                
        # Only apply deskew if the angle is visible but not extreme noise
        if abs(deskew_angle) > 0.3 and abs(deskew_angle) < 15.0:
            logger.info(f"Applying deskew adjustment: {deskew_angle:.2f} degrees.")
            center = (w // 2, h // 2)
            M_skew_2x3 = cv2.getRotationMatrix2D(center, deskew_angle, 1.0)
            img_cv = cv2.warpAffine(img_cv, M_skew_2x3, (w, h), borderValue=(255, 255, 255))
            
            M_skew_3x3 = np.vstack([M_skew_2x3, [0, 0, 1]])
            M_cumulative = M_skew_3x3 @ M_cumulative
        else:
            deskew_angle = 0.0
            
        # Save final preprocessed image sent into PP-Structure
        cv2.imwrite(os.path.join(debug_dir, "tsr_input_normalized.png"), img_cv)
        
        # Calculate Inverse matrix for geometric un-winding
        try:
            M_inv = np.linalg.inv(M_cumulative)
        except np.linalg.LinAlgError:
            logger.error("Failed to invert affine matrix. Proceeding without coordinate correction.")
            M_inv = np.eye(3)
            
        # 4. Core Inference
        engine = self._get_engine()
        logger.info(f"Running PP-Structure inference on image: {img_cv.shape}")
        results = engine(img_cv)
        
        # Render PP-Structure's raw overlay on the normalized image for side-by-side comparison
        raw_overlay = img_cv.copy()
        
        table_regions = []
        table_counter = 0
        
        for res in results:
            if res.get('type') == 'table':
                res_data = res.get('res', {})
                bbox = res.get('bbox') # Normalized space box
                cell_bboxes = res_data.get('cell_bbox', []) # List of boxes in normalized space
                
                # Draw table overlay on the debug normalized image
                if bbox:
                    cv2.rectangle(raw_overlay, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), (0, 255, 0), 3)
                for cb in cell_bboxes:
                    cv2.rectangle(raw_overlay, (int(cb[0]), int(cb[1])), (int(cb[2]), int(cb[3])), (255, 0, 0), 1)

                # A. Build full transformed geometries
                table_geom_orig = build_geom_from_bbox(bbox, M_inv)
                table_geom_norm = build_geom_from_bbox(bbox, None)
                
                region = TableRegion(
                    table_id=f"table_{table_counter}",
                    region_type=RegionType.TABLE,
                    geometry=table_geom_orig,
                    original_geometry=table_geom_orig,
                    normalized_geometry=table_geom_norm,
                    source_engine="ppstructure"
                )
                
                # Geometry clustering to resolve grid IDs from the normalized-space boxes
                if not cell_bboxes:
                    table_regions.append(region)
                    table_counter += 1
                    continue
                    
                y_centers = [(b[1] + b[3]) / 2 for b in cell_bboxes]
                y_sorted = sorted(list(set(y_centers)))
                row_clusters = []
                for y in y_sorted:
                    if not row_clusters or y - row_clusters[-1][-1] > 10:
                        row_clusters.append([y])
                    else:
                        row_clusters[-1].append(y)
                row_y_centers = [sum(c)/len(c) for c in row_clusters]
                
                x_centers = [(b[0] + b[2]) / 2 for b in cell_bboxes]
                x_sorted = sorted(list(set(x_centers)))
                col_clusters = []
                for x in x_sorted:
                    if not col_clusters or x - col_clusters[-1][-1] > 10:
                        col_clusters.append([x])
                    else:
                        col_clusters[-1].append(x)
                col_x_centers = [sum(c)/len(c) for c in col_clusters]
                
                # Add topology entries
                for i, ry in enumerate(row_y_centers):
                    region.rows.append(RowRegion(row_id=f"row_{i}"))
                for j, cx in enumerate(col_x_centers):
                    region.columns.append(ColumnRegion(col_id=f"col_{j}"))
                
                # Process every individual cell
                for cb in cell_bboxes:
                    cy = (cb[1] + cb[3]) / 2
                    cx = (cb[0] + cb[2]) / 2
                    row_idx = min(range(len(row_y_centers)), key=lambda i: abs(row_y_centers[i] - cy))
                    col_idx = min(range(len(col_x_centers)), key=lambda j: abs(col_x_centers[j] - cx))
                    
                    c_geom_orig = build_geom_from_bbox(cb, M_inv)
                    c_geom_norm = build_geom_from_bbox(cb, None)
                    
                    region.cells.append(TableCell(
                        row_id=f"row_{row_idx}",
                        col_id=f"col_{col_idx}",
                        geometry=c_geom_orig, # Primary geom matches OCR
                        original_geometry=c_geom_orig,
                        normalized_geometry=c_geom_norm
                    ))
                
                table_regions.append(region)
                table_counter += 1
                
        # Write overlay debug render
        cv2.imwrite(os.path.join(debug_dir, "tsr_ppstructure_overlay.png"), raw_overlay)
        
        meta = {
            "orientation_corrected": is_rotated,
            "rotation_applied": applied_rotation,
            "deskew_angle": float(deskew_angle),
            "orientation_confidence": float(orientation_confidence),
            "inference_dims": list(img_cv.shape[:2])
        }
        
        return table_regions, meta
