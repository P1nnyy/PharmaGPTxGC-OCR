from typing import List
from models.layout_models import ReconstructedRow, TableRegion, GeometryBox

def detect_table_regions(rows: List[ReconstructedRow]) -> List[TableRegion]:
    """
    Identifies table boundaries from the reconstructed rows.
    In heuristic mode, this simply groups 'Medicine Table Row' items into a single region.
    Future: Will integrate Table Transformer (TATR) outputs.
    """
    table_rows = [r for r in rows if r.classification == "Medicine Table Row"]
    
    if not table_rows:
        return []
        
    # Heuristic: Create a single TableRegion containing all medicine rows
    region = TableRegion(
        table_id="heuristic_table_0",
        rows=table_rows
    )
    
    # Calculate bounding box for the entire table region
    min_xs, max_xs, min_ys, max_ys = [], [], [], []
    for r in table_rows:
        for b in r.blocks:
            if b.normalized_geometry:
                min_xs.append(b.normalized_geometry.min_x)
                max_xs.append(b.normalized_geometry.max_x)
                min_ys.append(b.normalized_geometry.min_y)
                max_ys.append(b.normalized_geometry.max_y)
                
    if min_xs:
        min_x = min(min_xs)
        max_x = max(max_xs)
        min_y = min(min_ys)
        max_y = max(max_ys)
        region.geometry = GeometryBox(
            min_x=min_x, max_x=max_x,
            min_y=min_y, max_y=max_y,
            center_x=(min_x + max_x) / 2.0,
            center_y=(min_y + max_y) / 2.0
        )
        
    return [region]
