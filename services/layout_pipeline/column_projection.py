"""
Column Projection Logic for PharmaGPT.
Enhanced with projection smoothing, hard reconstruction constraints, 
and robust collapse recovery.
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
    
    # 2. Construct raw occupancy histogram (intensity grid)
    hist = np.zeros(max_x, dtype=float)
    for b in valid_blocks:
        g = b.normalized_geometry
        # Weigh histogram by occurrence. Use 1.0 per token span.
        start = max(0, int(g.min_x))
        end = min(max_x, int(g.max_x))
        if end > start:
            hist[start:end] += 1.0

    raw_peaks = np.where(hist > 0)[0]
    
    # 3. Apply moving average smoothing to filter tiny whitespace valleys/jitter
    # Kernel width determines baseline noise forgiveness (e.g. 15px blur)
    kernel_size = 15
    kernel = np.ones(kernel_size) / kernel_size
    smoothed = np.convolve(hist, kernel, mode='same')
    
    # Filter based on significance threshold (e.g. ignore extremely sparse single pixel echoes)
    threshold = 0.1
    mask = smoothed > threshold
    
    # 4. Detect raw continuous ranges from smoothed data
    changes = np.diff(mask.astype(int))
    starts = np.where(changes == 1)[0] + 1
    ends = np.where(changes == -1)[0] + 1
    
    # Edge case catch
    if mask[0]:
        starts = np.insert(starts, 0, 0)
    if mask[-1]:
        ends = np.append(ends, len(mask) - 1)
        
    raw_columns = list(zip(starts, ends))
    smoothed_peak_ranges = raw_columns
    
    # 5. Refine & Consolidate Columns step-by-step
    stabilized_columns = _consolidate_and_filter_columns(raw_columns, blocks)
    
    # 6. Hard constraint loop: Collapse recovery if explosion occurred
    final_columns = _enforce_hard_limits(stabilized_columns, blocks)
    hard_limit_merge_count = max(0, len(stabilized_columns) - len(final_columns))
    
    # Convert list of (min, max) into final boundary pairs
    # Ensuring explicit mapping from boundary to boundary
    formatted_boundaries = []
    for i, (col_min, col_max) in enumerate(final_columns):
        # If last column, set right edge to float('inf') per convention
        # Wait, heuristic TSR handles infinity right extension. 
        # Let's produce precise spans.
        
        # The upstream logic expects midpoints as division walls?
        # Let's provide clean spans and derive midpoints explicitly for separation.
        pass

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
    }

    # Mandatory detailed debug logging using structlog only
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


def _consolidate_and_filter_columns(columns: List[Tuple[int, int]], blocks: List[OCRBlock]) -> List[Tuple[int, int]]:
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
        
        # Merge Condition 1: Gap below minimal boundary limit (25px)
        if gap < MIN_COLUMN_GAP_PX:
            # Merge
            curr_col = (min(curr_col[0], nxt_col[0]), max(curr_col[1], nxt_col[1]))
            continue
            
        # Specific Condition: Check if both contain sparse numeric structures and are relatively close
        # (Even if slightly larger than 25px but still narrow gap < 40)
        if gap < 40.0:
             if _is_primarily_numeric(curr_col, blocks) and _is_primarily_numeric(nxt_col, blocks):
                  # Adjacent sparse numeric columns likely fragmented artifacts (e.g. Discount & Amount fractured)
                  curr_col = (min(curr_col[0], nxt_col[0]), max(curr_col[1], nxt_col[1]))
                  log.debug("numeric_column_merged", left_span=curr_col, gap=gap)
                  continue
                  
        consolidated.append(curr_col)
        curr_col = nxt_col
        
    consolidated.append(curr_col)
    
    # Width enforcement: Reject extremely narrow columns which survived smoothing
    final_pass = []
    for col in consolidated:
        width = col[1] - col[0]
        if width >= MIN_COLUMN_WIDTH_PX:
            final_pass.append(col)
        else:
            rejected_log.append({"col": col, "width": width, "reason": "below_min_width"})
            
    if rejected_log:
        log.debug("columns_rejected_by_width", rejections=rejected_log)
            
    return final_pass


def _enforce_hard_limits(columns: List[Tuple[int, int]], blocks: List[OCRBlock]) -> List[Tuple[int, int]]:
    """
    Trigger active column-collapse recovery when counts explode.
    Merges columns by identifying the closest neighbors iteratively until beneath limit.
    """
    working_cols = sorted(columns, key=lambda x: x[0])
    
    iteration_limit = 100 # Prevent infiniloops
    iters = 0
    
    while len(working_cols) > MAX_REASONABLE_COLUMNS and iters < iteration_limit:
        iters += 1
        # Find pair with minimum inter-column gap
        min_gap = float('inf')
        best_idx = -1
        
        for i in range(len(working_cols) - 1):
            gap = working_cols[i+1][0] - working_cols[i][1]
            # Weight the decision to prefer merging columns which are narrow or both numeric
            cost = gap
            if (working_cols[i][1] - working_cols[i][0]) < (MIN_COLUMN_WIDTH_PX * 1.5):
                cost *= 0.8 # Discount merging narrow columns
                
            if cost < min_gap:
                min_gap = cost
                best_idx = i
                
        if best_idx != -1:
            c1 = working_cols[best_idx]
            c2 = working_cols[best_idx + 1]
            log.info("emergency_column_collapse", c1=c1, c2=c2, gap=min_gap, remaining=len(working_cols))
            
            # Create merged span
            merged = (min(c1[0], c2[0]), max(c1[1], c2[1]))
            # Rebuild list
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
        # Check if block center is contained within this projected column
        cx = b.normalized_geometry.center_x
        if min_x <= cx <= max_x:
            in_span.append(b)
            
    if not in_span:
        return False
        
    numeric_count = sum(1 for b in in_span if b.is_numeric)
    ratio = numeric_count / len(in_span)
    return ratio > 0.6
