import os
import re
import json
import math
from typing import List, Dict, Any, Tuple, Optional
from models.layout_models import OCRBlock, TableRegion, GeometryBox, TableCell
from core.logger import logger
from services.qty_parser import is_compound_quantity, parse_quantity

def is_numeric_like(text: str) -> bool:
    """
    Explicit detector for financial/quantity data shapes.
    Handles currencies, decimals, percentages, comma groups.
    """
    if not text:
        return False
    # Remove whitespace and currency fluff
    clean = text.replace(' ', '').replace('₹', '').replace('RS', '').replace('$', '')
    
    # 1. Check standard decimal numbers (e.g. 1,234.56 or 12.34)
    if re.search(r'\d+[\d,]*\.\d+', clean):
        return True
        
    # 2. Check percentage figures
    if '%' in clean and re.search(r'\d+', clean):
        return True
        
    # 3. Check standalone integers if they don't have text soup
    only_digits = re.sub(r'[^\d]', '', clean)
    if only_digits and len(only_digits) == len(clean.replace(',','').replace('.','')):
        return True
        
    return False

def _compute_weighted_candidate_score(block: OCRBlock, cell: TableCell, ioa: float, is_num: bool = False) -> float:
    """
    Creates composite weighted fit score merging IoA Overlap + Edge Alignment + Vertical Depth.
    
    NUMERIC tokens use RIGHT-EDGE alignment — critical for decimal-aligned invoice columns
    (amount, GST, totals). Center-based scoring causes systematic rightward drift.
    TEXT tokens use CENTER alignment as prose blocks do not have inherent edge preference.
    """
    b_geom = block.normalized_geometry
    c_geom = cell.geometry
    c_w = max(5.0, c_geom.max_x - c_geom.min_x)
    
    if is_num:
        # RIGHT-EDGE scoring: rewards tokens whose right boundary matches the cell's right wall.
        # This is the natural alignment axis for financial figures in invoice tables.
        right_edge_dist = abs(b_geom.max_x - c_geom.max_x)
        # Normalize by cell width so distance is expressed in fractions of column width
        horiz_score = max(0.0, 1.0 - (right_edge_dist / c_w))
    else:
        # CENTER scoring: prose text is centered in its logical cell box.
        b_cx = b_geom.center_x
        c_cx = c_geom.center_x
        horiz_norm_dist = abs(b_cx - c_cx) / c_w
        horiz_score = max(0.0, 1.0 - horiz_norm_dist)
    
    # Vertical Alignment Score (identical for both numeric and text)
    b_cy = b_geom.center_y
    c_cy = c_geom.center_y
    c_h = max(5.0, c_geom.max_y - c_geom.min_y)
    vert_norm_dist = abs(b_cy - c_cy) / c_h
    vert_score = max(0.0, 1.0 - vert_norm_dist)
    
    # WEIGHTED MIX:
    # Primary: Overlap Volume (55%) — structural containment signal
    # Secondary: Edge/Center Alignment (35%) — column anchoring signal
    # Tertiary: Vertical lane fit (10%)
    weighted = (ioa * 0.55) + (horiz_score * 0.35) + (vert_score * 0.10)
    
    return round(weighted, 4)

def _compute_ioa(block_geom: GeometryBox, cell_geom: GeometryBox, pad: float = 2.0) -> float:
    """Intersection over Block Area calculation with minor bounding box bleed support."""
    c_min_x, c_max_x = cell_geom.min_x - pad, cell_geom.max_x + pad
    c_min_y, c_max_y = cell_geom.min_y - pad, cell_geom.max_y + pad
    
    dx = min(block_geom.max_x, c_max_x) - max(block_geom.min_x, c_min_x)
    dy = min(block_geom.max_y, c_max_y) - max(block_geom.min_y, c_min_y)
    
    if dx > 0 and dy > 0:
        intersection = dx * dy
        b_area = (block_geom.max_x - block_geom.min_x) * (block_geom.max_y - block_geom.min_y)
        return float(intersection / b_area) if b_area > 0 else 0.0
    return 0.0

def _compute_y_overlap(block_geom: GeometryBox, row_geom: GeometryBox) -> float:
    """Compute normalized vertical overlap between a token and a row band."""
    overlap = min(block_geom.max_y, row_geom.max_y) - max(block_geom.min_y, row_geom.min_y)
    if overlap <= 0:
        return 0.0
    block_height = max(1.0, block_geom.max_y - block_geom.min_y)
    return overlap / block_height

def map_tokens_to_cells(blocks: List[OCRBlock], regions: List[TableRegion]) -> None:
    """
    V4 Assignment Engine: Soft Row-Scoped Allocator.
    
    Three-tier assignment strategy:
    - Tier 1 (row_scoped): Token assigned within its primary row band. Full confidence.
    - Tier 2 (neighbor_row): Token assigned in adjacent row (±1). 0.85x confidence penalty.
    - Tier 3 (global_fallback): Unrestricted cell search. 0.5x confidence penalty.
    
    Preserves right-edge scoring for numerics, IoA thresholds, and ambiguity rejection.
    """
    # System Metric Trackers
    metrics = {
        "numeric_assignment_conflicts": 0,
        "ambiguous_numeric_tokens": 0,
        "orphan_numeric_tokens": 0,
        "total_numeric_mapped": 0,
        "numeric_column_jumps": 0,
        # Benchmark telemetry
        "right_edge_alignment_variance": 0.0,
        "numeric_column_entropy": 0.0,
        "semantic_collision_count": 0,
        "assignment_rejection_rate": 0.0,
        "phantom_repair_count": 0,
        # Row-scoped tier tracking
        "tier1_assignments": 0,
        "tier2_assignments": 0,
        "tier3_assignments": 0,
    }
    _right_edge_deltas = []
    _total_tokens_attempted = 0

    # Build row-indexed cell lookup and collect all rows with geometry
    all_cells = []
    cells_by_row = {}  # row_id -> [cells]
    all_rows = []       # RowRegion objects with geometry
    row_order = []      # Ordered list of row_ids for neighbor lookup
    
    for r in regions:
        for row in r.rows:
            if row.geometry:
                all_rows.append(row)
                row_order.append(row.row_id)
        for c in r.cells:
            c.mapped_block_ids = []
            c.text = ""
            c.assignment_strategy = "unassigned"
            c.assignment_confidence = 1.0
            if c.geometry:
                all_cells.append(c)
                if c.row_id not in cells_by_row:
                    cells_by_row[c.row_id] = []
                cells_by_row[c.row_id].append(c)
                
    if not all_cells:
        logger.warning("Mapping aborted: 0 cells detected in downstream topological structure.")
        return

    def _get_neighbor_row_ids(row_id: str) -> List[str]:
        """Return IDs of the rows immediately above and below the given row."""
        if row_id not in row_order:
            return []
        idx = row_order.index(row_id)
        neighbors = []
        if idx > 0:
            neighbors.append(row_order[idx - 1])
        if idx < len(row_order) - 1:
            neighbors.append(row_order[idx + 1])
        return neighbors

    def _score_against_cells(block, cell_list, is_num, min_gate_ioa):
        """Score a block against a list of candidate cells. Returns sorted (score, ioa, cell) list."""
        scored = []
        pad_size = 1.5 if is_num else 3.0
        for cell in cell_list:
            raw_ioa = _compute_ioa(block.normalized_geometry, cell.geometry, pad=pad_size)
            if raw_ioa >= min_gate_ioa:
                fit = _compute_weighted_candidate_score(block, cell, raw_ioa, is_num=is_num)
                scored.append((fit, raw_ioa, cell))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _check_ambiguity(scored_candidates) -> bool:
        """Return True if top two candidates are dangerously close in score."""
        if len(scored_candidates) > 1:
            delta = scored_candidates[0][0] - scored_candidates[1][0]
            if delta < 0.12:
                return True
        return False

    assignment_audit = []
    
    for block in blocks:
        if not block.normalized_geometry or not block.id:
            continue
        _total_tokens_attempted += 1
        
        text = (block.text or "").strip()
        is_num = is_numeric_like(text)
        min_gate_ioa = 0.55 if is_num else 0.30
        
        assigned = False
        assignment_strategy = "unassigned"
        confidence_multiplier = 1.0
        
        # ── TIER 1: Primary Row Assignment ──
        # Find the row whose band has the highest Y-overlap with this token.
        if all_rows:
            row_scores = [(row, _compute_y_overlap(block.normalized_geometry, row.geometry))
                          for row in all_rows]
            row_scores.sort(key=lambda x: x[1], reverse=True)
            best_row, best_y_overlap = row_scores[0]
            
            if best_y_overlap > 0.3:
                row_cells = cells_by_row.get(best_row.row_id, [])
                if row_cells:
                    scored = _score_against_cells(block, row_cells, is_num, min_gate_ioa)
                    if scored and not _check_ambiguity(scored):
                        top_score, top_ioa, top_cell = scored[0]
                        top_cell.mapped_block_ids.append(block.id)
                        top_cell.assignment_strategy = "row_scoped"
                        top_cell.assignment_confidence = min(top_cell.assignment_confidence, top_score)
                        assignment_strategy = "row_scoped"
                        confidence_multiplier = 1.0
                        assigned = True
                        metrics["tier1_assignments"] += 1
        
        # ── TIER 2: Neighboring Row Tolerance (±1 row) ──
        if not assigned and all_rows:
            best_row_id = row_scores[0][0].row_id if row_scores[0][1] > 0.1 else None
            if best_row_id:
                neighbor_ids = _get_neighbor_row_ids(best_row_id)
                neighbor_cells = []
                for nid in neighbor_ids:
                    neighbor_cells.extend(cells_by_row.get(nid, []))
                if neighbor_cells:
                    scored = _score_against_cells(block, neighbor_cells, is_num, min_gate_ioa)
                    if scored and not _check_ambiguity(scored):
                        top_score, top_ioa, top_cell = scored[0]
                        top_cell.mapped_block_ids.append(block.id)
                        top_cell.assignment_strategy = "neighbor_row"
                        top_cell.assignment_confidence = min(top_cell.assignment_confidence, top_score * 0.85)
                        assignment_strategy = "neighbor_row"
                        confidence_multiplier = 0.85
                        assigned = True
                        metrics["tier2_assignments"] += 1
        
        # ── TIER 3: Global Fallback ──
        if not assigned:
            scored = _score_against_cells(block, all_cells, is_num, min_gate_ioa)
            if scored and not _check_ambiguity(scored):
                top_score, top_ioa, top_cell = scored[0]
                top_cell.mapped_block_ids.append(block.id)
                top_cell.assignment_strategy = "global_fallback"
                top_cell.assignment_confidence = min(top_cell.assignment_confidence, top_score * 0.5)
                assignment_strategy = "global_fallback"
                confidence_multiplier = 0.5
                assigned = True
                metrics["tier3_assignments"] += 1
        
        # ── Record Result ──
        if assigned:
            if is_num:
                metrics["total_numeric_mapped"] += 1
                _right_edge_deltas.append(abs(block.normalized_geometry.max_x - top_cell.geometry.max_x))
            assignment_audit.append({
                "id": block.id, "text": text, "is_num": is_num,
                "target": f"{top_cell.row_id}:{top_cell.col_id}",
                "score": round(top_score * confidence_multiplier, 4),
                "strategy": assignment_strategy,
                "status": "MAPPED"
            })
        else:
            if is_num:
                metrics["orphan_numeric_tokens"] += 1
            assignment_audit.append({
                "id": block.id, "text": text,
                "status": "ORPHAN",
                "reason": "no_valid_candidate" if not all_rows else "ambiguous_or_below_threshold"
            })

    # 6. Cell Population and Semantic-Aware Collision Detection
    for cell in all_cells:
        if not cell.mapped_block_ids: continue
        
        c_blocks = [b for b in blocks if b.id in cell.mapped_block_ids]
        # Standard reading order (discretized Y then linear X)
        c_blocks.sort(key=lambda b: (round((b.normalized_geometry.min_y or 0) / 6), b.normalized_geometry.min_x or 0))
        cell.text = " ".join([b.text for b in c_blocks if b.text])
        
        # Semantic-aware collision detection.
        # Only flag SUSPICIOUS multi-number cells — valid pairs like CGST+SGST or Qty+Free must pass.
        nums = [b for b in c_blocks if is_numeric_like(b.text or "")]
        if len(nums) > 1:
            # Collect the float values to test for suspicion heuristics
            vals = []
            for n in nums:
                cleaned = re.sub(r'[^\d.]', '', (n.text or ""))
                try: vals.append(float(cleaned))
                except: pass
            
            # SUSPICIOUS cases only:
            # 1. Values are near-identical (duplicate amount candidates)
            # 2. The merged text contains concatenated decimal chains (e.g. 12.3456.78)
            # 3. All values are large amounts (> 100), suggesting totals merging
            is_suspicious = False
            if len(vals) >= 2:
                merged_text = cell.text
                has_decimal_chain = bool(re.search(r'\d+\.\d+\.\d+', merged_text))
                all_large = all(v > 100.0 for v in vals)
                near_duplicate = (len(vals) == 2 and abs(vals[0] - vals[1]) < 0.5)
                if has_decimal_chain or (all_large and near_duplicate):
                    is_suspicious = True
            
            # EXPLICIT EXEMPTION: Suppress false positive for structured Scheme/Pack quantities
            if is_suspicious:
                # Quick surface check first
                if is_compound_quantity(cell.text):
                    is_suspicious = False
                    logger.debug(f"[IOA] Compound qty collision suppressed: {cell.text}")
                else:
                    # Deeper structural parse — catches edge cases is_compound_quantity misses
                    try:
                        pq = parse_quantity(cell.text)
                        if pq.is_scheme or pq.pack_size is not None:
                            is_suspicious = False
                            logger.debug(f"[IOA] Compound qty collision suppressed: {cell.text}")
                    except Exception:
                        pass  # parse failure — leave is_suspicious as-is
                    
            if is_suspicious:
                metrics["numeric_assignment_conflicts"] += 1
                metrics["semantic_collision_count"] += 1
                logger.debug(f"[SEMANTIC COLLISION] Suspicious multi-number cell: {cell.row_id}:{cell.col_id} → '{cell.text}'")
            
    # 7. Benchmark Telemetry Finalization
    total_rejected = metrics["orphan_numeric_tokens"] + metrics["ambiguous_numeric_tokens"]
    metrics["assignment_rejection_rate"] = round(
        total_rejected / _total_tokens_attempted if _total_tokens_attempted > 0 else 0.0, 4
    )
    if _right_edge_deltas:
        import statistics
        metrics["right_edge_alignment_variance"] = round(statistics.variance(_right_edge_deltas) if len(_right_edge_deltas) > 1 else 0.0, 4)
    
    # 8. Telemetry Persistence
    try:
        debug_dir = "datasets/debug"
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "ioa_hardened_metrics.json"), "w", encoding="utf-8") as f:
            json.dump({
                "engine_metrics": metrics,
                "log": assignment_audit
            }, f, indent=2)
        logger.info(
            f"V4 Row-Scoped Allocator: mapped={metrics['total_numeric_mapped']} nums, "
            f"orphans={metrics['orphan_numeric_tokens']}, "
            f"tier1={metrics['tier1_assignments']}, tier2={metrics['tier2_assignments']}, tier3={metrics['tier3_assignments']}, "
            f"rejection_rate={metrics['assignment_rejection_rate']:.2%}, "
            f"right_edge_variance={metrics['right_edge_alignment_variance']:.2f}px"
        )
    except Exception as e:
        logger.error(f"Allocator telemetry write failure: {e}")
