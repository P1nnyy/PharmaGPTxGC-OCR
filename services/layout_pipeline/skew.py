import math
import numpy as np
from typing import List
from core.logger import logger
from models.layout_models import OCRBlock, GeometryBox

def estimate_skew_angle(blocks: List[OCRBlock]) -> float:
    angles = []
    for block in blocks:
        polygon = block.polygon
        if len(polygon) == 4:
            # use top edge
            dy = polygon[1][1] - polygon[0][1]
            dx = polygon[1][0] - polygon[0][0]
            if dx != 0:
                angles.append(math.atan2(dy, dx))
    return float(np.median(angles)) if angles else 0.0

def rotate_point(x: float, y: float, cx: float, cy: float, angle_rad: float) -> tuple[float, float]:
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    nx = cx + (x - cx) * cos_a - (y - cy) * sin_a
    ny = cy + (x - cx) * sin_a + (y - cy) * cos_a
    return nx, ny

def apply_skew_normalization(blocks: List[OCRBlock]) -> List[OCRBlock]:
    angle_rad = estimate_skew_angle(blocks)
    logger.info(f"Dominant skew angle estimated: {math.degrees(angle_rad):.2f} degrees")
    
    if abs(angle_rad) < 0.01:
        return blocks
        
    # Find global center
    all_cx = [b.original_geometry.center_x for b in blocks if b.original_geometry]
    all_cy = [b.original_geometry.center_y for b in blocks if b.original_geometry]
    if not all_cx:
        return blocks
    
    global_cx = sum(all_cx) / len(all_cx)
    global_cy = sum(all_cy) / len(all_cy)
    
    for block in blocks:
        if not block.original_geometry:
            continue
            
        polygon = block.polygon
        if len(polygon) == 4:
            rot_pts = [rotate_point(pt[0], pt[1], global_cx, global_cy, -angle_rad) for pt in polygon]
            xs = [pt[0] for pt in rot_pts]
            ys = [pt[1] for pt in rot_pts]
            
            block.normalized_geometry = GeometryBox(
                min_x=min(xs),
                max_x=max(xs),
                min_y=min(ys),
                max_y=max(ys),
                center_x=sum(xs)/4.0,
                center_y=sum(ys)/4.0
            )
            
    return blocks
