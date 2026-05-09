import os
from PIL import Image, ImageDraw, ImageFont
from typing import List
from core.logger import logger
from models.layout_models import OCRBlock, TableRegion
from services.layout_pipeline.column_projection import get_anchor_x

def draw_debug_visualization(blocks: List[OCRBlock], regions: List[TableRegion], image_width: float, image_height: float, output_path: str):
    """
    Renders a debug image visualizing the spatial reconstruction.
    """
    try:
        img = Image.new('RGB', (int(image_width), int(image_height)), color='white')
        draw = ImageDraw.Draw(img)
        
        # Colors
        COLOR_RAW_POLYGON = (200, 200, 200)
        COLOR_NORMALIZED_BBOX = (150, 150, 255)
        COLOR_ANCHOR = (255, 0, 0)
        COLOR_TABLE = (0, 0, 0)
        COLOR_CELL = (0, 200, 0)
        COLOR_ROW = (200, 100, 0)
        
        # 1. Draw raw polygons and bounding boxes
        for block in blocks:
            poly = block.polygon
            if len(poly) == 4:
                pts = [(p[0], p[1]) for p in poly]
                pts.append(pts[0])
                draw.line(pts, fill=COLOR_RAW_POLYGON, width=1)
                
            if block.normalized_geometry:
                geom = block.normalized_geometry
                draw.rectangle([geom.min_x, geom.min_y, geom.max_x, geom.max_y], outline=COLOR_NORMALIZED_BBOX, width=1)
                draw.text((geom.min_x + 2, geom.min_y + 2), block.text[:10], fill=(0,0,0))
                
                # Draw numeric anchors
                if block.is_numeric:
                    anchor_x = get_anchor_x(block)
                    anchor_y = geom.center_y
                    draw.ellipse([anchor_x-2, anchor_y-2, anchor_x+2, anchor_y+2], fill=COLOR_ANCHOR)
                    
        # 2. Draw TSR Grids
        for region in regions:
            # Draw table boundary
            if region.geometry:
                rg = region.geometry
                draw.rectangle([rg.min_x, rg.min_y, rg.max_x, rg.max_y], outline=COLOR_TABLE, width=3)
                draw.text((rg.min_x, max(0, rg.min_y - 15)), f"Region: {region.region_type.value} | Engine: {region.source_engine}", fill=COLOR_TABLE)
                
            # Draw row boundaries
            for row in region.rows:
                if row.geometry:
                    rg = row.geometry
                    draw.rectangle([rg.min_x, rg.min_y, rg.max_x, rg.max_y], outline=COLOR_ROW, width=2)
                    
            # Draw cell boundaries
            for cell in region.cells:
                if cell.geometry:
                    cg = cell.geometry
                    draw.rectangle([cg.min_x, cg.min_y, cg.max_x, cg.max_y], outline=COLOR_CELL, width=1)
                    
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path)
        logger.info(f"Debug visualization saved to {output_path}")
        
    except Exception as e:
        logger.error(f"Failed to generate debug visualization: {e}")
