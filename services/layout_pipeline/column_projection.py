"""
Column Projection Logic for PharmaGPT.
Enhanced with adaptive projection smoothing, dense pharma region detection,
and robust column consolidation.
"""

import numpy as np
import structlog
from typing import List, Tuple, Dict, Any
from models.layout_models import OCRBlock

# Hard constraints for robust topology reconstruction
MAX_REASONABLE_COLUMNS = 22
MIN_COLUMN_WIDTH_PX = 18
MIN_COLUMN_GAP_PX = 12

# Set up logger explicitly requested
log = structlog.get_logger()

LAST_PROJECTION_DEBUG: Dict[str, Any] = {}


def get_last_projection_debug() -> Dict[str, Any]:
    return dict(LAST_PROJECTION_DEBUG)


def _is_numeric_or_date_span(span: Tuple[int, int], blocks: List[OCRBlock]) -> bool:
    """Assess whether a defined x-span aligns mainly with numeric or date-like tokens."""
    min_x, max_x = span
    in_span = []
    for b in blocks:
        if not b.normalized_geometry:
            continue
        # Check if block center lies inside the horizontal column boundaries
        cx = b.normalized_geometry.center_x
        if min_x <= cx <= max_x:
            in_span.append(b)
            
    if not in_span:
        return False
        
    import re
    # Patterns representing typical compact fields in pharmaceutical invoice tables
    decimal_pat = re.compile(r'^\s*[\d,]+\.\d{2}\s*$')
    date_pat = re.compile(r'^\s*\d{2}/\d{2,4}\s*$')
    small_int_pat = re.compile(r'^\s*\d{1,8}\s*$')
    combo_pat = re.compile(r'\b\d+(?:[xX×*+]\d+)*\b')
    
    matching_count = 0
    for b in in_span:
        txt = b.text.strip()
        if decimal_pat.match(txt) or date_pat.match(txt) or small_int_pat.match(txt) or combo_pat.search(txt):
            matching_count += 1
            
    ratio = matching_count / len(in_span)
    return ratio > 0.6


def _is_dense_pharma_region(blocks: List[OCRBlock]) -> bool:
    """
    Deterministic check to identify dense pharmaceutical tables.
    Uses geometry and text features of the OCR blocks to classify density.
    """
    valid_blocks = [b for b in blocks if b.normalized_geometry]
    if not valid_blocks:
        return False

    # 1. Cluster blocks into rows to check layout structure
    try:
        from services.layout_pipeline.row_clustering import cluster_into_rows
        rows = cluster_into_rows(valid_blocks)
    except Exception as e:
        log.warn("dense_pharma_check_row_clustering_failed", error=str(e))
        return False

    if not rows:
        return False

    # Count blocks per row
    blocks_per_row = [len(r.blocks) for r in rows if r.blocks]
    if not blocks_per_row:
        return False
    avg_blocks_per_row = sum(blocks_per_row) / len(blocks_per_row)

    # 2. Compute inter-block horizontal gaps within each row
    gaps = []
    for r in rows:
        sorted_b = sorted(r.blocks, key=lambda b: b.normalized_geometry.min_x)
        for i in range(len(sorted_b) - 1):
            gap = sorted_b[i+1].normalized_geometry.min_x - sorted_b[i].normalized_geometry.max_x
            gaps.append(gap)

    # Calculate median spacing gap to assess compaction
    median_gap = float(np.median(gaps)) if gaps else 100.0

    # 3. Check for pharma-like compact numeric/date/gst patterns in the texts
    import re
    # decimal value: e.g. 118.00, 84.16, 1.84
    decimal_pat = re.compile(r'^\s*[\d,]+\.\d{2}\s*$')
    # date value: e.g. 05/27, 07/27, 12/2026
    date_pat = re.compile(r'^\s*\d{2}/\d{2,4}\s*$')
    # small quantity or gst percentage or code: e.g. 5, 90, 0, 12, 18, 28, 30049099
    small_int_pat = re.compile(r'^\s*\d{1,8}\s*$')
    # pack combos or other numeric combos: e.g. 10 S, 10x1x10
    combo_pat = re.compile(r'\b\d+(?:[xX×*+]\d+)*\b')

    matching_count = 0
    for b in valid_blocks:
        txt = b.text.strip()
        if not txt:
            continue
        if decimal_pat.match(txt) or date_pat.match(txt) or small_int_pat.match(txt) or combo_pat.search(txt):
            matching_count += 1

    matching_ratio = matching_count / len(valid_blocks) if valid_blocks else 0.0

    # Strict Criteria for dense pharma table:
    # - Average blocks per row >= 5.0 (many columns/cells expected)
    # - Median gap <= 30.0 px (compact spacing)
    # - High density of numeric/date/gst tokens (>= 35%)
    is_dense = (avg_blocks_per_row >= 5.0) and (median_gap <= 30.0) and (matching_ratio >= 0.35)

    log.debug("dense_pharma_region_assessment",
              avg_blocks_per_row=avg_blocks_per_row,
              median_gap=median_gap,
              matching_ratio=matching_ratio,
              is_dense=is_dense)
    return is_dense


def project_column_boundaries(blocks: List[OCRBlock]) -> List[Tuple[float, float]]:
    """
    Orchestrates hard column stabilization.
    Maps token geometries into smoothed intensity histograms to detect robust boundaries.
    """
    global LAST_PROJECTION_DEBUG

    if not blocks:
        LAST_PROJECTION_DEBUG = {
            "raw_projected_column_count": 0,
            "stabilized_column_count": 0,
            "final_column_count": 0,
            "hard_limit_merge_count": 0,
        }
        log.debug("column_projection_empty_input")
        return []

    # 1. Define workspace dimensions
    valid_blocks = [b for b in blocks if b.normalized_geometry]
    if not valid_blocks:
        LAST_PROJECTION_DEBUG = {
            "raw_projected_column_count": 0,
            "stabilized_column_count": 0,
            "final_column_count": 0,
            "hard_limit_merge_count": 0,
        }
        return []
        
    max_x = int(max(b.normalized_geometry.max_x for b in valid_blocks)) + 50
    
    # 2. Construct occupancy histogram
    hist = np.zeros(max_x, dtype=float)
    for b in valid_blocks:
        g = b.normalized_geometry
        start = max(0, int(g.min_x))
        end = min(max_x, int(g.max_x))
        if end > start:
            hist[start:end] += 1.0

    raw_peaks = np.where(hist > 0)[0]
    
    # Check if region is a dense pharma region
    is_dense = _is_dense_pharma_region(blocks)
    
    # 3. Adaptive projection smoothing to filter tiny whitespace valleys/jitter
    # Use smaller kernel size (2) for dense pharma regions to keep columns resolved
    kernel_size = 2 if is_dense else 15
    kernel = np.ones(kernel_size) / kernel_size
    smoothed = np.convolve(hist, kernel, mode='same')
    
    # Filter based on significance threshold
    threshold = 0.1
    mask = smoothed > threshold
    
    # 4. Detect raw continuous ranges from smoothed data
    changes = np.diff(mask.astype(int))
    starts = np.where(changes == 1)[0] + 1
    ends = np.where(changes == -1)[0] + 1
    
    if mask[0]:
        starts = np.insert(starts, 0, 0)
    if mask[-1]:
        ends = np.append(ends, len(mask) - 1)
        
    raw_columns = list(zip(starts, ends))
    smoothed_peak_ranges = raw_columns
    
    # 5. Refine & Consolidate Columns step-by-step
    merge_gap_limit = 4.0 if is_dense else float(MIN_COLUMN_GAP_PX)
    stabilized_columns = _consolidate_and_filter_columns(raw_columns, blocks, merge_gap_limit, is_dense)
    
    # 6. Hard constraint loop: Collapse recovery if explosion occurred
    final_columns = _enforce_hard_limits(stabilized_columns, blocks, is_dense)
    hard_limit_merge_count = max(0, len(stabilized_columns) - len(final_columns))
    
    # Calculate midpoints between final selected spans to fulfill partition interface
    derived_boundaries = []
    for i in range(len(final_columns)):
        # Left limit
        if i == 0:
            b_left = 0.0
        else:
            # Midpoint between prev max and current min
            b_left = (final_columns[i-1][1] + final_columns[i][0]) / 2.0
            
        # Right limit
        if i == len(final_columns) - 1:
            b_right = float('inf')
        else:
            # Midpoint between current max and next min
            b_right = (final_columns[i][1] + final_columns[i+1][0]) / 2.0
            
        derived_boundaries.append((b_left, b_right))

    LAST_PROJECTION_DEBUG = {
        "raw_projected_column_count": len(raw_columns),
        "stabilized_column_count": len(stabilized_columns),
        "final_column_count": len(final_columns),
        "hard_limit_merge_count": hard_limit_merge_count,
        "is_dense_pharma_region": is_dense,
    }

    log.debug("column_projection_finalized",
              raw_peaks_count=len(raw_peaks),
              raw_projected_column_count=LAST_PROJECTION_DEBUG["raw_projected_column_count"],
              smoothed_peaks_ranges_count=len(smoothed_peak_ranges),
              stabilized_column_count=LAST_PROJECTION_DEBUG["stabilized_column_count"],
              final_column_count=LAST_PROJECTION_DEBUG["final_column_count"],
              final_stabilized_count=len(derived_boundaries),
              hard_limit_merge_count=LAST_PROJECTION_DEBUG["hard_limit_merge_count"],
              columns_data=[{"min": float(c[0]), "max": float(c[1])} for c in final_columns]
    )
    
    return derived_boundaries


def _consolidate_and_filter_columns(columns: List[Tuple[int, int]], blocks: List[OCRBlock], merge_gap_limit: float = 12.0, is_dense: bool = False) -> List[Tuple[int, int]]:
    """
    Performs primary clean and merge routine based on distance and width parameters.
    """
    if not columns:
        return []
        
    # Sort from left to right
    columns = sorted(columns, key=lambda x: x[0])
    
    consolidated = []
    curr_col = columns[0]
    
    rejected_log = []
    
    for i in range(1, len(columns)):
        nxt_col = columns[i]
        gap = nxt_col[0] - curr_col[1]
        
        effective_gap_limit = merge_gap_limit
        if is_dense:
            # In dense (wide-table) mode, if BOTH adjacent spans are
            # numeric/date-like, they are separate real columns (qty, rate,
            # MRP, disc, GST, amount).  Block the merge entirely.
            if _is_numeric_or_date_span(curr_col, blocks) and _is_numeric_or_date_span(nxt_col, blocks):
                # Hard block — never merge two adjacent numeric columns
                # in a wide table regardless of gap size.
                consolidated.append(curr_col)
                curr_col = nxt_col
                continue
            else:
                effective_gap_limit = 6.0
        
        # Merge Condition 1: Gap below minimal boundary limit
        if gap < effective_gap_limit:
            # Merge adjacent column ranges
            curr_col = (min(curr_col[0], nxt_col[0]), max(curr_col[1], nxt_col[1]))
            continue
            
        # Specific Condition: Check if both contain sparse numeric structures and are relatively close
        # GATED: only fires in non-dense mode to avoid destroying wide-table columns.
        if not is_dense and gap < 40.0:
             if _is_primarily_numeric(curr_col, blocks) and _is_primarily_numeric(nxt_col, blocks):
                  curr_col = (min(curr_col[0], nxt_col[0]), max(curr_col[1], nxt_col[1]))
                  log.debug("numeric_column_merged", left_span=curr_col, gap=gap)
                  continue
                  
        consolidated.append(curr_col)
        curr_col = nxt_col
        
    consolidated.append(curr_col)
    
    # Width enforcement: Reject extremely narrow columns
    # In dense pharma mode, narrow integer quantities or single-digit codes should be allowed to survive
    effective_min_width = 8.0 if is_dense else float(MIN_COLUMN_WIDTH_PX)
    final_pass = []
    for col in consolidated:
        width = col[1] - col[0]
        if width >= effective_min_width:
            final_pass.append(col)
        else:
            rejected_log.append({"col": col, "width": width, "reason": "below_min_width"})
            
    if rejected_log:
        log.debug("columns_rejected_by_width", rejections=rejected_log)
            
    return final_pass


def _enforce_hard_limits(columns: List[Tuple[int, int]], blocks: List[OCRBlock], is_dense: bool = False) -> List[Tuple[int, int]]:
    """
    Trigger active column-collapse recovery when counts explode.
    Merges columns by identifying the closest neighbors iteratively until beneath limit.
    """
    working_cols = sorted(columns, key=lambda x: x[0])
    
    iteration_limit = 100
    iters = 0
    
    effective_min_width = 8.0 if is_dense else float(MIN_COLUMN_WIDTH_PX)
    
    while len(working_cols) > MAX_REASONABLE_COLUMNS and iters < iteration_limit:
        iters += 1
        min_gap = float('inf')
        best_idx = -1
        
        for i in range(len(working_cols) - 1):
            gap = working_cols[i+1][0] - working_cols[i][1]
            cost = gap
            if (working_cols[i][1] - working_cols[i][0]) < (effective_min_width * 1.5):
                cost *= 0.8
                
            if cost < min_gap:
                min_gap = cost
                best_idx = i
                
        if best_idx != -1:
            c1 = working_cols[best_idx]
            c2 = working_cols[best_idx + 1]
            log.info("emergency_column_collapse", c1=c1, c2=c2, gap=min_gap, remaining=len(working_cols))
            
            merged = (min(c1[0], c2[0]), max(c1[1], c2[1]))
            working_cols = working_cols[:best_idx] + [merged] + working_cols[best_idx+2:]
        else:
            break
            
    return working_cols


def _is_primarily_numeric(span: Tuple[int, int], blocks: List[OCRBlock]) -> bool:
    """Assess whether a defined x-span aligns mainly with numeric tokens."""
    min_x, max_x = span
    in_span = []
    for b in blocks:
        if not b.normalized_geometry: continue
        cx = b.normalized_geometry.center_x
        if min_x <= cx <= max_x:
            in_span.append(b)
            
    if not in_span:
        return False
        
    numeric_count = sum(1 for b in in_span if b.is_numeric)
    ratio = numeric_count / len(in_span)
    return ratio > 0.6
