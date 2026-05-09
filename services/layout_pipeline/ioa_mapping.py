from typing import List
from models.layout_models import OCRBlock, TableRegion, GeometryBox

def _compute_ioa(block_geom: GeometryBox, cell_geom: GeometryBox) -> float:
    # Intersection
    dx = min(block_geom.max_x, cell_geom.max_x) - max(block_geom.min_x, cell_geom.min_x)
    dy = min(block_geom.max_y, cell_geom.max_y) - max(block_geom.min_y, cell_geom.min_y)
    
    if dx > 0 and dy > 0:
        intersection_area = dx * dy
        block_area = (block_geom.max_x - block_geom.min_x) * (block_geom.max_y - block_geom.min_y)
        if block_area > 0:
            return intersection_area / block_area
    return 0.0

def map_tokens_to_cells(blocks: List[OCRBlock], regions: List[TableRegion]) -> None:
    """
    Adapter Layer: Maps OCR token geometry into TSR structure topology.
    Uses Intersection over Area (IoA).
    """
    for region in regions:
        # Clear previous mappings if any
        for cell in region.cells:
            cell.mapped_block_ids = []
            cell.text = ""
            
        for block in blocks:
            if not block.normalized_geometry or not block.id:
                continue
                
            best_cell = None
            best_ioa = 0.0
            
            for cell in region.cells:
                if not cell.geometry:
                    continue
                    
                ioa = _compute_ioa(block.normalized_geometry, cell.geometry)
                if ioa > best_ioa:
                    best_ioa = ioa
                    best_cell = cell
                    
            if best_cell and best_ioa > 0.3: # Threshold for assignment
                best_cell.mapped_block_ids.append(block.id)
                
        # Populate text for each cell based on mapped blocks (sorted by x-coordinate)
        for cell in region.cells:
            if not cell.mapped_block_ids:
                continue
            
            cell_blocks = [b for b in blocks if b.id in cell.mapped_block_ids]
            cell_blocks.sort(key=lambda b: b.normalized_geometry.min_x if b.normalized_geometry else 0)
            
            cell.text = " ".join([b.text for b in cell_blocks])
