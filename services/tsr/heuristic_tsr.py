"""
Heuristic Table Structure Recognition (TSR) Engine for Invoice processing.

Segments document blocks into table regions, infers row and column boundaries,
and maps text elements into cells. Includes multi-orientation layout validation,
applying coordinate transposes to find the best layout angle and then mapping
geometries back.
"""

import re
from PIL import Image
from typing import List, Dict, Tuple, Any, Optional
from models.layout_models import (
    OCRBlock, TableRegion, RowRegion, ColumnRegion, TableCell, GeometryBox, RegionType
)
from services.tsr.base_tsr import BaseTSREngine
from core.logger import logger

# Import internal layout primitives
from services.layout_pipeline.row_clustering import cluster_into_rows
from services.layout_pipeline.row_classification import classify_rows
from services.layout_pipeline.column_projection import get_last_projection_debug, project_column_boundaries
from services.layout_pipeline.multiline_merging import merge_multiline_rows
from services.layout_pipeline.wide_table_detector import detect_wide_table, split_fused_block


def rotate_blocks(blocks: List[OCRBlock], angle: int) -> List[OCRBlock]:
    """Rotates OCR block normalized coordinates clock-wise to evaluate structural cohesion."""
    if angle == 0 or angle % 360 == 0:
        return [b.model_copy() for b in blocks]
        
    # Gather bounding box ranges to compute rotation envelope
    xs, ys = [], []
    for b in blocks:
        if b.normalized_geometry:
            xs.extend([b.normalized_geometry.min_x, b.normalized_geometry.max_x])
            ys.extend([b.normalized_geometry.min_y, b.normalized_geometry.max_y])
            
    max_x = max(xs) if xs else 1000.0
    max_y = max(ys) if ys else 1000.0
    
    rotated = []
    for b in blocks:
        if not b.normalized_geometry:
            rotated.append(b.model_copy())
            continue
            
        geom = b.normalized_geometry
        
        # Apply standard clock-wise bounding box transposes
        if angle == 90:
            new_min_x = max_y - geom.max_y
            new_max_x = max_y - geom.min_y
            new_min_y = geom.min_x
            new_max_y = geom.max_x
        elif angle == 180:
            new_min_x = max_x - geom.max_x
            new_max_x = max_x - geom.min_x
            new_min_y = max_y - geom.max_y
            new_max_y = max_y - geom.min_y
        elif angle == 270:
            new_min_x = geom.min_y
            new_max_x = geom.max_y
            new_min_y = max_x - geom.max_x
            new_max_y = max_x - geom.min_x
        else:
            new_min_x, new_max_x = geom.min_x, geom.max_x
            new_min_y, new_max_y = geom.min_y, geom.max_y
            
        new_geom = GeometryBox(
            min_x=new_min_x, max_x=new_max_x,
            min_y=new_min_y, max_y=new_max_y,
            center_x=(new_min_x + new_max_x) / 2.0,
            center_y=(new_min_y + new_max_y) / 2.0
        )
        
        b_copy = b.model_copy()
        b_copy.normalized_geometry = new_geom
        rotated.append(b_copy)
        
    return rotated


def invert_geometry(geom: GeometryBox, angle: int, max_x: float, max_y: float) -> GeometryBox:
    """Applies inverse rotation (360 - angle) to map geometries back to original coordinates."""
    if angle == 0 or angle % 360 == 0:
        return geom
        
    inv_angle = 360 - angle
    
    if inv_angle == 90:
        # Note: the rotated envelope has swapped max_x and max_y dimensions, 
        # so max_y represents the horizontal width limit of the forward space
        new_min_x = max_y - geom.max_y
        new_max_x = max_y - geom.min_y
        new_min_y = geom.min_x
        new_max_y = geom.max_x
    elif inv_angle == 180:
        new_min_x = max_x - geom.max_x
        new_max_x = max_x - geom.min_x
        new_min_y = max_y - geom.max_y
        new_max_y = max_y - geom.min_y
    elif inv_angle == 270:
        new_min_x = geom.min_y
        new_max_x = geom.max_y
        new_min_y = max_x - geom.max_x
        new_max_y = max_x - geom.min_x
    else:
        new_min_x, new_max_x = geom.min_x, geom.max_x
        new_min_y, new_max_y = geom.min_y, geom.max_y
        
    return GeometryBox(
        min_x=new_min_x, max_x=new_max_x,
        min_y=new_min_y, max_y=new_max_y,
        center_x=(new_min_x + new_max_x) / 2.0,
        center_y=(new_min_y + new_max_y) / 2.0
    )


class HeuristicTSREngine(BaseTSREngine):
    """Deterministic geometric primitive analyzer for table segment extraction."""

    def _detect_tables_single(self, blocks: List[OCRBlock]) -> Tuple[List[TableRegion], Dict[str, Any]]:
        """Core layout primitive segmentation on a static single coordinate space."""
        # 0. Check wide table evidence and run pre-reconstruction block splitting if active
        raw_wide_table_evidence = detect_wide_table(blocks, [])
        if raw_wide_table_evidence.is_wide:
            split_blocks = []
            for b in blocks:
                split_blocks.extend(split_fused_block(b))
            blocks = split_blocks

        # 1. Compose Base Primitives
        reconstructed_rows = cluster_into_rows(blocks)
        reconstructed_rows = classify_rows(reconstructed_rows)
        reconstructed_rows, _ = merge_multiline_rows(reconstructed_rows)
        
        # 2. Segment rows into contiguous semantic regions
        segmented_regions = []
        if reconstructed_rows:
            def get_segment_group(classification: str) -> str:
                # Group Column Header and Medicine Table Row into the same contiguous item table segment
                if classification in ("Column Header", "Medicine Table Row"):
                    return "Medicine Table Row"
                return classification

            current_segment = [reconstructed_rows[0]]
            current_group = get_segment_group(reconstructed_rows[0].classification)
            
            for row in reconstructed_rows[1:]:
                row_group = get_segment_group(row.classification)
                if row_group == current_group:
                    current_segment.append(row)
                else:
                    segmented_regions.append((current_group, current_segment))
                    current_segment = [row]
                    current_group = row_group
            
            if current_segment:
                segmented_regions.append((current_group, current_segment))
                
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
            
            # 3.5. Header Anchor Override (if wide table mode is active and columns collapsed)
            if raw_wide_table_evidence.is_wide and len(col_bounds) < 10:
                header_row = None
                for r in region_rows:
                    if r.classification == "Column Header":
                        header_row = r
                        break
                if not header_row and region_rows:
                    # Fallback header match pattern
                    header_label_pat = re.compile(
                        r"\b(PRODUCT|ITEM|DESCRIPTION|PARTICULARS|MEDICINE|DRUG|NAME|HSN|SAC|BATCH|B\.?\s*NO|LOT|QTY|QUANTITY|BILLED|FREE|SCHEME|SCH|RATE|PTR|PRICE|DISC|DISCOUNT|TD|CD|EXP|EXPIRY|MRP|GST|CGST|SGST|IGST|TAX|AMOUNT|AMT|VALUE|NET|PACK|COMPANY|MFR|MANUFACTURER|SR\.?\s*NO|S\.?\s*NO|SHO|SL|NO)\b",
                        re.I
                    )
                    first_r = region_rows[0]
                    header_hits = sum(1 for b in first_r.blocks if header_label_pat.search(b.text))
                    if header_hits >= 3:
                        header_row = first_r
                
                if header_row:
                    header_blocks = sorted(header_row.blocks, key=lambda b: b.normalized_geometry.min_x if b.normalized_geometry else 0)
                    anchor_spans = []
                    for b in header_blocks:
                        geom = b.normalized_geometry
                        if geom:
                            anchor_spans.append((geom.min_x, geom.max_x))
                    
                    anchor_spans.sort(key=lambda s: s[0])
                    if len(anchor_spans) >= 8:
                        derived_bounds = []
                        for i in range(len(anchor_spans)):
                            # Left limit
                            if i == 0:
                                b_left = 0.0
                            else:
                                b_left = (anchor_spans[i-1][1] + anchor_spans[i][0]) / 2.0
                            
                            # Right limit
                            if i == len(anchor_spans) - 1:
                                b_right = float('inf')
                            else:
                                b_right = (anchor_spans[i][1] + anchor_spans[i+1][0]) / 2.0
                            
                            derived_bounds.append((b_left, b_right))
                        
                        col_bounds = derived_bounds
                        logger.info(f"[HEURISTIC TSR] Overrode collapsed columns with {len(col_bounds)} header partition bands.")

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
                        min_y=0, max_y=10000,
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
                row_role = "header_row" if r.classification == "Column Header" else "unknown_row"
                table_rows.append(RowRegion(row_id=row_id, geometry=row_geom, confidence=1.0, row_role=row_role))
                
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
            if classification == "Header" or classification == "Column Header":
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
                source_engine="heuristic",
                topology_confidence=1.0
            )
            table_regions.append(region)
            
        return table_regions, {"column_projection_debug": column_projection_debug}

    def detect_tables(self, blocks: List[OCRBlock], image: Image.Image = None) -> Tuple[List[TableRegion], Dict[str, Any]]:
        """
        Detects tables in blocks using 4-rotation layout validation.
        Selects the rotation that displays the most cohesive invoice row and column alignment,
        then projects geometries back to original unrotated space.
        """
        if not blocks:
            return [], {}

        candidates = []
        
        # Get total page dimensions from blocks for rotation bounds
        xs, ys = [], []
        for b in blocks:
            if b.normalized_geometry:
                xs.extend([b.normalized_geometry.min_x, b.normalized_geometry.max_x])
                ys.extend([b.normalized_geometry.min_y, b.normalized_geometry.max_y])
        max_x = max(xs) if xs else 1000.0
        max_y = max(ys) if ys else 1000.0

        # Evaluate layout coherence across all 4 rotation hypotheses
        for angle in [0, 90, 180, 270]:
            rotated_blocks = rotate_blocks(blocks, angle)
            
            try:
                reconstructed_rows = cluster_into_rows(rotated_blocks)
                reconstructed_rows = classify_rows(reconstructed_rows)
                reconstructed_rows, _ = merge_multiline_rows(reconstructed_rows)
                
                num_rows = len(reconstructed_rows)
                num_med_rows = sum(1 for r in reconstructed_rows if r.classification == "Medicine Table Row")
                
                # Cohesion score rewards structured rows and medicine table classification blocks
                score = (num_med_rows * 100) + (num_rows * 5)
            except Exception as e:
                logger.error(f"[HEURISTIC TSR] Orientation evaluation error on angle {angle}: {e}")
                score = float("-inf")
                reconstructed_rows = []
                
            candidates.append({
                "angle": angle,
                "score": score,
                "blocks": rotated_blocks,
                "reconstructed_rows": reconstructed_rows
            })

        # Select the winning rotation orientation
        winner = max(candidates, key=lambda x: x["score"])
        winner_angle = winner["angle"]
        
        logger.info(
            f"[HEURISTIC TSR] Dynamic Orientation Decision: selected={winner_angle}°, "
            f"score={winner['score']:.2f}, default_0_score={candidates[0]['score']:.2f}"
        )
        
        # Run table primitive segmentation on the winning rotated blocks
        table_regions, metadata = self._detect_tables_single(winner["blocks"])
        metadata["selected_orientation"] = f"rotate_{winner_angle}"
        
        # If the image/blocks needed rotation, map all geometries back and degrade confidence
        if winner_angle != 0:
            logger.warning(
                f"🚨 Heuristic TSR detected rotation of {winner_angle}°! "
                f"Applying inverse mapping to coordinates and degrading confidence..."
            )
            for region in table_regions:
                # Invert TableRegion geometry bounds
                if region.geometry:
                    region.geometry = invert_geometry(region.geometry, winner_angle, max_x, max_y)
                if region.original_geometry:
                    region.original_geometry = invert_geometry(region.original_geometry, winner_angle, max_x, max_y)
                if region.normalized_geometry:
                    region.normalized_geometry = invert_geometry(region.normalized_geometry, winner_angle, max_x, max_y)
                    
                # Invert RowRegion geometry bounds
                for r in region.rows:
                    if r.geometry:
                        r.geometry = invert_geometry(r.geometry, winner_angle, max_x, max_y)
                    if r.normalized_geometry:
                        r.normalized_geometry = invert_geometry(r.normalized_geometry, winner_angle, max_x, max_y)
                        
                # Invert ColumnRegion geometry bounds
                for c in region.columns:
                    if c.geometry:
                        c.geometry = invert_geometry(c.geometry, winner_angle, max_x, max_y)
                    if c.normalized_geometry:
                        c.normalized_geometry = invert_geometry(c.normalized_geometry, winner_angle, max_x, max_y)
                        
                # Invert TableCell geometry bounds
                for cell in region.cells:
                    if cell.geometry:
                        cell.geometry = invert_geometry(cell.geometry, winner_angle, max_x, max_y)
                    if cell.original_geometry:
                        cell.original_geometry = invert_geometry(cell.original_geometry, winner_angle, max_x, max_y)
                    if cell.normalized_geometry:
                        cell.normalized_geometry = invert_geometry(cell.normalized_geometry, winner_angle, max_x, max_y)
                        
                # Degradation penalty if rotated: topology_confidence *= 0.9 (Acceptance Criteria)
                region.topology_confidence = round(region.topology_confidence * 0.9, 3)
                region.confidence = round(region.confidence * 0.9, 3)

        return table_regions, metadata
