from services.tsr.base_tsr import BaseTSREngine
from PIL import Image
from typing import List, Dict, Tuple, Any
from models.layout_models import (
    OCRBlock, TableRegion, RowRegion, ColumnRegion, TableCell, GeometryBox, RegionType
)

# Import internal layout primitives
from services.layout_pipeline.row_clustering import cluster_into_rows
from services.layout_pipeline.row_classification import classify_rows
from services.layout_pipeline.column_projection import get_last_projection_debug, project_column_boundaries
from services.layout_pipeline.multiline_merging import merge_multiline_rows

class HeuristicTSREngine(BaseTSREngine):
    def detect_tables(self, blocks: List[OCRBlock], image: Image.Image = None) -> Tuple[List[TableRegion], Dict[str, Any]]:
        """
        Uses deterministic geometry heuristics to infer structural topology.
        Segments the document into multiple TableRegions with local column projection.
        """
        if not blocks:
            return [], {}
            
        # 1. Compose Base Primitives
        reconstructed_rows = cluster_into_rows(blocks)
        reconstructed_rows = classify_rows(reconstructed_rows)
        reconstructed_rows, _ = merge_multiline_rows(reconstructed_rows)
        
        # 2. Segment rows into contiguous semantic regions
        segmented_regions = []
        if reconstructed_rows:
            current_segment = [reconstructed_rows[0]]
            current_class = reconstructed_rows[0].classification
            
            for row in reconstructed_rows[1:]:
                if row.classification == current_class:
                    current_segment.append(row)
                else:
                    segmented_regions.append((current_class, current_segment))
                    current_segment = [row]
                    current_class = row.classification
            
            if current_segment:
                segmented_regions.append((current_class, current_segment))
                
        # 3. Process Each Segment as an independent TableRegion
        table_regions = []
        column_projection_debug = {}
        global_row_counter = 0
        
        for region_idx, (classification, region_rows) in enumerate(segmented_regions):
            region_blocks = []
            for r in region_rows:
                region_blocks.extend(r.blocks)
                
            if not region_blocks:
                continue
                
            # Local Column boundaries
            col_bounds = project_column_boundaries(region_blocks)
            table_id = f"heuristic_region_{region_idx}"
            column_projection_debug[table_id] = {
                **get_last_projection_debug(),
                "table_id": table_id,
            }
            col_regions = []
            for i, (min_x, max_x) in enumerate(col_bounds):
                col_id = f"col_{i}"
                col_regions.append(ColumnRegion(
                    col_id=col_id,
                    geometry=GeometryBox(
                        min_x=min_x, max_x=max_x if max_x != float('inf') else min_x + 500,
                        min_y=0, max_y=10000, # Unbounded vertically conceptually
                        center_x=(min_x + (max_x if max_x != float('inf') else min_x + 500)) / 2,
                        center_y=5000
                    ),
                    confidence=1.0
                ))
                
            # Build Row and Cell topologies for this region
            table_rows = []
            table_cells = []
            
            reg_min_x, reg_max_x = float('inf'), float('-inf')
            reg_min_y, reg_max_y = float('inf'), float('-inf')
            
            for r in region_rows:
                row_id = f"row_{global_row_counter}"
                global_row_counter += 1
                
                r_min_x = min([b.normalized_geometry.min_x for b in r.blocks if b.normalized_geometry] + [float('inf')])
                r_max_x = max([b.normalized_geometry.max_x for b in r.blocks if b.normalized_geometry] + [float('-inf')])
                r_min_y = min([b.normalized_geometry.min_y for b in r.blocks if b.normalized_geometry] + [float('inf')])
                r_max_y = max([b.normalized_geometry.max_y for b in r.blocks if b.normalized_geometry] + [float('-inf')])
                
                if r_min_x == float('inf'):
                    continue
                    
                reg_min_x, reg_max_x = min(reg_min_x, r_min_x), max(reg_max_x, r_max_x)
                reg_min_y, reg_max_y = min(reg_min_y, r_min_y), max(reg_max_y, r_max_y)
                    
                row_geom = GeometryBox(
                    min_x=r_min_x, max_x=r_max_x,
                    min_y=r_min_y, max_y=r_max_y,
                    center_x=(r_min_x + r_max_x) / 2.0,
                    center_y=(r_min_y + r_max_y) / 2.0
                )
                table_rows.append(RowRegion(row_id=row_id, geometry=row_geom, confidence=1.0))
                
                # Cells (Intersection of row and column)
                for c_idx, col in enumerate(col_regions):
                    c_min_x = col_bounds[c_idx][0]
                    c_max_x = col_bounds[c_idx][1]
                    
                    cell_geom = GeometryBox(
                        min_x=max(r_min_x, c_min_x),
                        max_x=min(r_max_x, c_max_x) if c_max_x != float('inf') else r_max_x + 200,
                        min_y=r_min_y,
                        max_y=r_max_y,
                        center_x=(max(r_min_x, c_min_x) + (min(r_max_x, c_max_x) if c_max_x != float('inf') else r_max_x + 200)) / 2,
                        center_y=(r_min_y + r_max_y) / 2
                    )
                    
                    table_cells.append(TableCell(
                        row_id=row_id,
                        col_id=col.col_id,
                        geometry=cell_geom,
                        confidence=1.0
                    ))
                    
            reg_geom = None
            if reg_min_x != float('inf'):
                reg_geom = GeometryBox(
                    min_x=reg_min_x, max_x=reg_max_x,
                    min_y=reg_min_y, max_y=reg_max_y,
                    center_x=(reg_min_x + reg_max_x) / 2,
                    center_y=(reg_min_y + reg_max_y) / 2
                )
                
            region_type = RegionType.UNKNOWN
            if classification == "Header":
                region_type = RegionType.HEADER
            elif classification == "Medicine Table Row":
                region_type = RegionType.MEDICINE_TABLE
            elif classification == "Totals":
                region_type = RegionType.TOTALS
                
            region = TableRegion(
                table_id=table_id,
                region_type=region_type,
                geometry=reg_geom,
                rows=table_rows,
                columns=col_regions,
                cells=table_cells,
                confidence=1.0,
                source_engine="heuristic"
            )
            table_regions.append(region)
            
        return table_regions, {"column_projection_debug": column_projection_debug}
