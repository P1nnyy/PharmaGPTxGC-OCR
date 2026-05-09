import os
import cv2
import numpy as np
from typing import List
from core.logger import logger
from models.layout_models import OCRBlock, TableRegion
from services.layout_pipeline.column_projection import get_anchor_x

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
                pt1 = (int(geom.min_x), int(geom.min_y))
                pt2 = (int(geom.max_x), int(geom.max_y))
                cv2.rectangle(canvas, pt1, pt2, COLOR_NORMALIZED_BBOX, 1)
                
                cv2.putText(canvas, block.text[:10], (int(geom.min_x) + 2, int(geom.min_y) + 12), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
                
                # Draw numeric anchors
                if block.is_numeric:
                    anchor_x = int(get_anchor_x(block))
                    anchor_y = int(geom.center_y)
                    cv2.circle(canvas, (anchor_x, anchor_y), 3, COLOR_ANCHOR, -1)
                    
        # 2. Draw TSR Grids
        for region in regions:
            if region.geometry:
                rg = region.geometry
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
                    
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # 5. Check cv2.imwrite success
        success = cv2.imwrite(output_path, canvas)
        if not success:
            raise RuntimeError(f"cv2.imwrite failed to save image to {output_path}")
            
        # 6. Add final logger
        logger.info(f"Saved visualization to {output_path}")
        
    except Exception as e:
        # 1. REMOVE silent exception swallowing, use logger.exception and re-raise
        logger.exception(f"Failed to generate debug visualization: {e}")
        raise
