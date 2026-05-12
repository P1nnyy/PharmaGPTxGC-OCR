"""
Deterministic Multiline Row Merging Utility.
Implements Hierarchical Row Graphs using purely geometric and structural signals.
Fuses visual row fragments into unified Semantic Medicine Entities.
"""

import re
import structlog
from typing import List, Tuple, Dict, Any, Optional
from models.layout_models import TableRegion, RowRegion, TableCell, GeometryBox, OCRBlock

log = structlog.get_logger()

class RowIntegrityMetrics:
    """Evaluates spatial/content stability of a single visual row band."""
    def __init__(self, row: RowRegion, cells: List[TableCell], blocks_map: Dict[str, OCRBlock]):
        self.row_id = row.row_id
        self.min_x = row.geometry.min_x if row.geometry else 0.0
        self.max_x = row.geometry.max_x if row.geometry else 0.0
        self.min_y = row.geometry.min_y if row.geometry else 0.0
        self.max_y = row.geometry.max_y if row.geometry else 0.0
        
        # Gather all raw blocks mapped to this row's cells
        self.blocks = []
        for c in cells:
            for b_id in c.mapped_block_ids:
                if b_id in blocks_map:
                    self.blocks.append(blocks_map[b_id])
        
        # Sort blocks by geometry to get accurate left anchor
        self.blocks.sort(key=lambda b: b.normalized_geometry.min_x if b.normalized_geometry else 0)
        
        self.text_content = " ".join([b.text for b in self.blocks]).upper()
        self.has_text = len(self.blocks) > 0
        
        # Geometric Left Anchor (Crucial for indentation detection)
        self.left_anchor = 0.0
        if self.blocks and self.blocks[0].normalized_geometry:
            self.left_anchor = self.blocks[0].normalized_geometry.min_x
            
        # Numeric Density (Low density implies continuation text rather than new item)
        self.num_count = sum(1 for b in self.blocks if b.is_numeric)
        self.total_tok = len(self.blocks)
        self.numeric_density = self.num_count / max(1, self.total_tok)
        
        # Check if explicit numeric structures exist which strongly block merging
        # (e.g. Row contains a price like "45.00")
        self.contains_pricing = any(re.search(r'\d+\.\d{2}', b.text) for b in self.blocks)
        
        # Strong Numeric Signal: Multiple numeric tokens or a price.
        self.is_structurally_strong = self.num_count >= 2 or self.contains_pricing


def merge_multiline_table_rows(region: TableRegion, all_blocks: List[OCRBlock]) -> Tuple[TableRegion, List[Dict[str, Any]]]:
    """
    Applies deterministic multiline row logic to fuse fragmented visual rows.
    Operates in-place but returns the modified region and an audit history for debug rendering.
    
    Args:
        region: TableRegion populated with rows and mapped cell tokens.
        all_blocks: List of raw OCRBlocks for building row integrity metadata.
        
    Returns:
        (Updated region, audit_log of operations)
    """
    if not region.rows or not region.cells:
        return region, []
        
    blocks_map = {b.id: b for b in all_blocks if b.id}
    
    # Sort visual rows top to bottom
    sorted_rows = sorted(region.rows, key=lambda r: r.geometry.min_y if r.geometry else 0)
    
    # Precompute metrics for every row to avoid recomputation in loop
    row_cells_map = {}
    for c in region.cells:
        row_cells_map.setdefault(c.row_id, []).append(c)
        
    metrics = {}
    for row in sorted_rows:
        metrics[row.row_id] = RowIntegrityMetrics(row, row_cells_map.get(row.row_id, []), blocks_map)
        
    # Track operations: semantic_parent_id -> list of visual_row_ids merged into it
    final_hierarchy: Dict[str, List[str]] = {r.row_id: [r.row_id] for r in sorted_rows}
    merge_audit = [] # Record detail for visualizer
    
    # Merge decision loop
    rows_to_drop = set()
    
    i = 1
    while i < len(sorted_rows):
        curr = sorted_rows[i]
        prev = sorted_rows[i-1]
        
        # If previous was dropped, find the actual active semantic parent
        anchor_prev_idx = i - 1
        while anchor_prev_idx >= 0 and sorted_rows[anchor_prev_idx].row_id in rows_to_drop:
            anchor_prev_idx -= 1
            
        if anchor_prev_idx < 0:
            i += 1
            continue
            
        active_parent = sorted_rows[anchor_prev_idx]
        
        m_curr = metrics[curr.row_id]
        m_prev = metrics[active_parent.row_id]
        
        # ── DETERMINISTIC GEOMETRIC CONDITIONS ──
        
        # 1. Vertical Gap constraint
        v_gap = m_curr.min_y - m_prev.max_y
        
        # 2. Left Alignment Anchor Overlap
        # Medicine continuation rows align with or indent slightly from original name
        left_delta = abs(m_curr.left_anchor - m_prev.left_anchor)
        is_indented = m_curr.left_anchor > (m_prev.left_anchor - 10) and m_curr.left_anchor < (m_prev.left_anchor + 100)
        
        # 3. Content structure safety
        # Block merge if current row has strong independent numeric structure (likely next product)
        is_continuation_candidate = not m_curr.is_structurally_strong
        
        # Thresholds
        MAX_CONTINUATION_GAP = 22.0 # Small vertical gap usually indicates spillover
        MAX_ALIGN_DELTA = 15.0      # Strict left overlap
        
        should_merge = False
        reject_reason = ""
        
        if v_gap > MAX_CONTINUATION_GAP:
            reject_reason = "gap_too_large"
        elif not is_indented and left_delta > MAX_ALIGN_DELTA:
            reject_reason = "alignment_drift"
        elif m_curr.is_structurally_strong:
            reject_reason = "independent_numeric_struct"
        elif not m_curr.has_text:
            # Blank visual row bands can be absorbed silently
            should_merge = True
        else:
            # ALL SIGNALS PASS
            should_merge = True
            
        # Decision logging
        decision = {
            "prev_id": active_parent.row_id,
            "curr_id": curr.row_id,
            "v_gap": round(v_gap, 1),
            "left_delta": round(left_delta, 1),
            "should_merge": should_merge,
            "reason": reject_reason or "cohesive_geometry"
        }
        merge_audit.append(decision)
        
        if should_merge:
            log.info("multiline_row_fused", parent=active_parent.row_id, child=curr.row_id, gap=v_gap)
            rows_to_drop.add(curr.row_id)
            final_hierarchy[active_parent.row_id].append(curr.row_id)
            
            # Execute Semantic Merge (Transfer logic)
            # A. Update geometry of parent to encapsulate child
            if active_parent.geometry and curr.geometry:
                active_parent.geometry.max_y = max(active_parent.geometry.max_y, curr.geometry.max_y)
                active_parent.geometry.min_x = min(active_parent.geometry.min_x, curr.geometry.min_x)
                active_parent.geometry.max_x = max(active_parent.geometry.max_x, curr.geometry.max_x)
                # Recompute center
                active_parent.geometry.center_y = (active_parent.geometry.min_y + active_parent.geometry.max_y) / 2.0
            
            # B. Physically re-assign child row cells into parent row scope
            # Collect child cells and map to parent row_id
            child_cells = row_cells_map.get(curr.row_id, [])
            for cc in child_cells:
                cc.row_id = active_parent.row_id
                cc.assignment_strategy = "multiline_merged"
            
            # Merge cell contents where column matches exist in parent
            # We'll clean up duplicate cells later
            row_cells_map[active_parent.row_id].extend(child_cells)
            # Zero out the dropped row's list
            row_cells_map[curr.row_id] = []
            
            # Re-evaluate active metrics for parent to include newly merged content bounds
            updated_metrics = RowIntegrityMetrics(active_parent, row_cells_map[active_parent.row_id], blocks_map)
            metrics[active_parent.row_id] = updated_metrics
            
        i += 1
        
    # FINALIZATION: Filter and normalize objects in region
    
    # 1. Drop consumed rows
    region.rows = [r for r in region.rows if r.row_id not in rows_to_drop]
    
    # 2. Deduplicate Cells created by horizontal merging.
    # If col 0 had text in both row 1 and row 2, combine them into single semantic cell.
    combined_cells = {}
    for cell in region.cells:
        # Active row target (in case re-mapped)
        r_id = cell.row_id 
        c_id = cell.col_id
        key = (r_id, c_id)
        
        if key not in combined_cells:
            combined_cells[key] = cell
        else:
            master = combined_cells[key]
            # Combine assignments
            master.mapped_block_ids = list(set(master.mapped_block_ids + cell.mapped_block_ids))
            # Spatial combine geometry
            if master.geometry and cell.geometry:
                master.geometry.min_y = min(master.geometry.min_y, cell.geometry.min_y)
                master.geometry.max_y = max(master.geometry.max_y, cell.geometry.max_y)
                master.geometry.center_y = (master.geometry.min_y + master.geometry.max_y) / 2.0
                
            # Text regeneration can happen later, but let's concat for transparency
            if cell.text and cell.text not in master.text:
                 master.text = f"{master.text}\n{cell.text}".strip()
    
    region.cells = list(combined_cells.values())
    
    log.debug("multiline_merging_complete", original_count=len(sorted_rows), reduced_count=len(region.rows), dropped=len(rows_to_drop))
    
    return region, merge_audit

def update_row_stability_scores(region: TableRegion, all_blocks: List[OCRBlock]) -> TableRegion:
    """
    Task 3: Row Ownership Stability Scoring.
    Annotates each semantic row with an explicit confidence score 0.0-1.0 
    based on structural continuity.
    """
    blocks_map = {b.id: b for b in all_blocks if b.id}
    row_cells_map = {}
    for c in region.cells:
        row_cells_map.setdefault(c.row_id, []).append(c)
        
    for row in region.rows:
        m = RowIntegrityMetrics(row, row_cells_map.get(row.row_id, []), blocks_map)
        
        # Scoring rubric
        score = 1.0
        
        # Penality 1: Contains NO text? Invalid structure
        if not m.has_text:
            score *= 0.3
            
        # Penalty 2: Heavy numeric presence with NO pricing token? Highly volatile
        if m.numeric_density > 0.7 and not m.contains_pricing:
            score *= 0.8
            
        # Bonus: Clean product line item (Balanced mix of text and numeric anchoring)
        if m.contains_pricing and m.numeric_density > 0.1 and m.numeric_density < 0.6:
            score = min(1.0, score * 1.2)
            
        row.stability = round(score, 2)
        
    return region
    
def merge_multiline_rows(rows: List[Any]) -> Tuple[List[Any], int]:
    """
    LEGACY SHIM: Used by heuristic_tsr. 
    Redirects to simplistic fallback logic while new system overrides primary path.
    """
    merged_rows: List[Any] = []
    merge_count = 0
    
    for row in rows:
        if getattr(row, 'classification', "") == "Unknown" and merged_rows:
            prev_row = merged_rows[-1]
            if getattr(prev_row, 'classification', "") == "Medicine Table Row":
                text = " ".join([b.text for b in row.blocks]).upper()
                # Rough price check
                has_price = bool(re.search(r'\d+\.\d{2}', text))
                if not has_price:
                    prev_row.blocks.extend(row.blocks)
                    merge_count += 1
                    continue
        merged_rows.append(row)
    return merged_rows, merge_count
