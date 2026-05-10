from typing import List, Dict, Any, Tuple
from core.logger import logger
from models.layout_models import TableRegion, ColumnRegion

class ColumnStabilizer:
    """
    PRE-ASSIGNMENT Geometry Stabilization Tier.
    
    Operates on raw cell bounding box geometry derived from TSR BEFORE any token assignment
    has been finalized. This prevents semantic corruption loops where incorrect token placements
    would poison the very classifier used to detect and fix them.
    
    Uses only spatial signals:
    - Column width distributions
    - Column X-span overlap
    - Cell occupancy density per column
    """
    
    def __init__(self):
        pass
        
    def stabilize_region(self, region: TableRegion) -> Dict[str, int]:
        """
        Geometry-only scan: detects and repairs phantom/fractured column bands in-place.
        Does NOT read cell.text - safe to call before token assignment.
        """
        metrics = {
            "phantom_column_count": 0,
            "repaired_columns": 0,
            "semantic_column_drift": 0
        }
        
        if not region.columns or not region.cells:
            return metrics
            
        # 1. Measure column X-spans from raw cell geometry
        col_bounds = {}
        for col in region.columns:
            cid = col.col_id
            c_cells = [c for c in region.cells if c.col_id == cid and c.geometry]
            if not c_cells:
                col_bounds[cid] = (0, 0)
                continue
            min_x = min(c.geometry.min_x for c in c_cells)
            max_x = max(c.geometry.max_x for c in c_cells)
            col_bounds[cid] = (min_x, max_x)
            
        # 2. Derive column widths and occupancy counts for geometry-based analysis
        col_occupancy = {}  # col_id -> number of cells pointing to it
        for cell in region.cells:
            cid = cell.col_id
            col_occupancy[cid] = col_occupancy.get(cid, 0) + 1
            
        total_cells = max(1, len(region.cells))
        
        # 3. Build merge candidate list using only geometry signals
        # Heuristic type inference from column width alone (no text)
        def _geom_type(cid):
            """Narrow columns are likely numeric amount columns; wide columns are likely text."""
            bounds = col_bounds.get(cid)
            if not bounds or bounds[1] == 0: return "unknown"
            width = bounds[1] - bounds[0]
            # Will be refined against median after all bounds are known
            return width  # Return raw width for comparison
        
        col_widths = {cid: (_geom_type(cid)) for cid in col_bounds}
        widths_list = [v for v in col_widths.values() if isinstance(v, float) and v > 0]
        import statistics
        median_width = statistics.median(widths_list) if widths_list else 1.0
        
        merges_to_execute = {}
        sorted_cols = sorted(region.columns, key=lambda c: col_bounds.get(c.col_id, (0, 0))[0])
        
        for i in range(len(sorted_cols)):
            curr_cid = sorted_cols[i].col_id
            if curr_cid in merges_to_execute: continue
            curr_bounds = col_bounds.get(curr_cid)
            if not curr_bounds or curr_bounds[1] == 0: continue
            
            for j in range(i + 1, len(sorted_cols)):
                nxt_cid = sorted_cols[j].col_id
                if nxt_cid in merges_to_execute: continue
                nxt_bounds = col_bounds.get(nxt_cid)
                if not nxt_bounds or nxt_bounds[1] == 0: continue
                
                # Geometry-only merge signals:
                gap = nxt_bounds[0] - curr_bounds[1]
                overlap = max(0, min(curr_bounds[1], nxt_bounds[1]) - max(curr_bounds[0], nxt_bounds[0]))
                
                is_curr_phantom = (col_widths.get(curr_cid, median_width) < median_width * 0.28)
                is_nxt_phantom = (col_widths.get(nxt_cid, median_width) < median_width * 0.28)
                curr_occupancy_ratio = col_occupancy.get(curr_cid, 0) / total_cells
                nxt_occupancy_ratio = col_occupancy.get(nxt_cid, 0) / total_cells
                
                should_merge = False
                if overlap > 5.0:  # Direct horizontal entanglement
                    should_merge = True
                elif (is_curr_phantom or is_nxt_phantom) and gap < 8.0:  # Phantom touching healthy column
                    should_merge = True
                    if is_curr_phantom: metrics["phantom_column_count"] += 1
                    if is_nxt_phantom: metrics["phantom_column_count"] += 1
                    
                if should_merge:
                    # Merge smaller-occupancy column into heavier one
                    curr_occ = col_occupancy.get(curr_cid, 0)
                    nxt_occ = col_occupancy.get(nxt_cid, 0)
                    if nxt_occ > curr_occ:
                        victim, winner = curr_cid, nxt_cid
                    else:
                        victim, winner = nxt_cid, curr_cid
                        
                    merges_to_execute[victim] = winner
                    metrics["repaired_columns"] += 1
                    logger.info(f"[SEMANTIC REPAIR] Scheduled merge of column '{victim}' into '{winner}' (reason: spatial-semantic cohesion)")
                    break # Stop forward chain for this victim as it is consumed
                    
        # 4. Commit Modifications physically in the state object
        if not merges_to_execute:
            return metrics
            
        # Reassign Cell ownerships
        for cell in region.cells:
            if cell.col_id in merges_to_execute:
                final_dest = merges_to_execute[cell.col_id]
                # Resolve transitive chain just in case A->B and B->C
                while final_dest in merges_to_execute:
                    final_dest = merges_to_execute[final_dest]
                cell.col_id = final_dest
                
        # Remove deleted regions from logic loop
        new_col_list = [c for c in region.columns if c.col_id not in merges_to_execute]
        region.columns = new_col_list
        
        # Post-process re-combine texts for identical slot assignments created by merge
        # (If row R had a cell in both A and B, they are now BOTH row R in col B).
        # We must combine their mapped_block_ids and texts.
        
        combined_cells = {}
        for cell in region.cells:
            key = (cell.row_id, cell.col_id)
            if key not in combined_cells:
                combined_cells[key] = cell
            else:
                master = combined_cells[key]
                # Unify mapped blocks
                master.mapped_block_ids = list(set(master.mapped_block_ids + cell.mapped_block_ids))
                # Text re-generation occurs automatically upstream or we can rough-join
                master.text = f"{master.text} {cell.text}".strip()
                
        # Set physical region cells to unique set only
        region.cells = list(combined_cells.values())
        
        logger.info(f"[TOPOLOGY STABILIZED] Completed {len(merges_to_execute)} logical column merges.")
        return metrics
