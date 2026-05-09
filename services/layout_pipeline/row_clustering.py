from typing import List
from models.layout_models import OCRBlock, ReconstructedRow

def cluster_into_rows(blocks: List[OCRBlock]) -> List[ReconstructedRow]:
    """Phase 2: Naive Y-overlap clustering and X-sorting."""
    if not blocks:
        return []
        
    # Sort blocks by center_y initially to process top-to-bottom
    sorted_blocks = sorted(blocks, key=lambda b: b.normalized_geometry.center_y if b.normalized_geometry else 0)
    
    rows: List[ReconstructedRow] = []
    
    for block in sorted_blocks:
        if not block.normalized_geometry:
            continue
            
        geom = block.normalized_geometry
        b_min_y, b_max_y = geom.min_y, geom.max_y
        b_height = b_max_y - b_min_y
        
        placed = False
        for row in rows:
            if not row.blocks:
                continue
                
            avg_cy = sum(b.normalized_geometry.center_y for b in row.blocks if b.normalized_geometry) / len(row.blocks)
            avg_h = sum((b.normalized_geometry.max_y - b.normalized_geometry.min_y) for b in row.blocks if b.normalized_geometry) / len(row.blocks)
            
            r_min_y = avg_cy - (avg_h / 2.0)
            r_max_y = avg_cy + (avg_h / 2.0)
            r_height = r_max_y - r_min_y
            
            overlap = min(r_max_y, b_max_y) - max(r_min_y, b_min_y)
            if overlap > 0:
                min_height = min(b_height, r_height)
                # If overlap is > 40% of the smaller height
                if min_height > 0 and (overlap / min_height) > 0.4:
                    row.blocks.append(block)
                    placed = True
                    break
        
        if not placed:
            new_row = ReconstructedRow(blocks=[block])
            rows.append(new_row)
            
    # Sort blocks within each row left-to-right (by min_x)
    for idx, row in enumerate(rows):
        row.row_index = idx
        row.blocks = sorted(row.blocks, key=lambda b: b.normalized_geometry.min_x if b.normalized_geometry else 0)
        
    return rows
