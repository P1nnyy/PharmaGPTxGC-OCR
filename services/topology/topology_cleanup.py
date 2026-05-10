import statistics
from typing import List, Tuple
from core.logger import logger

class TopologyCleaner:
    """
    Presents geometry consolidation logic designed to execute ON the raw bounding boxes
    BEFORE standard band-canonicalization fires. Rejects phantom boxes and heals fragmented spans.
    """

    def __init__(self):
        pass

    def clean_cell_boxes(self, bboxes: List[List[float]]) -> List[List[float]]:
        """
        Main orchestrator for spatial noise reduction.
        """
        if not bboxes:
            return []
            
        original_count = len(bboxes)
        
        # 1. Statistical Context Discovery
        widths = [b[2] - b[0] for b in bboxes]
        heights = [b[3] - b[1] for b in bboxes]
        
        if not widths or not heights:
            return bboxes
            
        med_w = statistics.median(widths)
        med_h = statistics.median(heights)
        
        logger.info(f"[TOPOLOGY CLEANUP] Statistical Base: Median Width={med_w:.1f}, Median Height={med_h:.1f}")
        
        # 2. Execution Layer 1: Filter Micro-Orphans
        working_set = []
        for b in bboxes:
            bw = b[2] - b[0]
            bh = b[3] - b[1]
            # Threshold definitions based strictly on relative context
            if bw < (med_w * 0.15) and bh < (med_h * 0.15):
                # Extremely small box likely representing speck noise
                continue
            working_set.append(b)
            
        # 3. Execution Layer 2: Adjacent Fragment Merge
        # Iterative pass to unify items side-by-side (horizontal adjacency)
        working_set = self._merge_adjacent_fragments(working_set, med_w, med_h)
        
        final_count = len(working_set)
        if final_count != original_count:
            logger.info(f"[TOPOLOGY CLEANUP] Finalized box consolidation: {original_count} -> {final_count}")
            
        return working_set

    def _merge_adjacent_fragments(self, bboxes: List[List[float]], med_w: float, med_h: float) -> List[List[float]]:
        """
        Finds neighboring bounding boxes that share deep vertical alignment and short horizontal gaps.
        Explicitly targets fragmented medicine names and numerical code splits.
        """
        # Sort primarily by Y-center, then secondary by X-center
        sorted_boxes = sorted(bboxes, key=lambda b: ((b[1] + b[3]) / 2.0, b[0]))
        
        merged_list = []
        skip_indices = set()
        
        for i in range(len(sorted_boxes)):
            if i in skip_indices:
                continue
                
            curr = sorted_boxes[i]
            # Attempt finding matches forward in sorted chain
            for j in range(i + 1, len(sorted_boxes)):
                if j in skip_indices:
                    continue
                    
                nxt = sorted_boxes[j]
                
                # Vertical overlap test (Requires >70% according to spec)
                ov_min = max(curr[1], nxt[1])
                ov_max = min(curr[3], nxt[3])
                intersection = max(0.0, ov_max - ov_min)
                min_h = min(curr[3] - curr[1], nxt[3] - nxt[1])
                
                v_aligned = (min_h > 0) and ((intersection / min_h) > 0.70)
                
                if v_aligned:
                    # Calculate horizontal separation
                    # Determine who sits left/right
                    left, right = (curr, nxt) if curr[0] <= nxt[0] else (nxt, curr)
                    gap = right[0] - left[2]
                    
                    # Merge conditions: Small gap (Relative to median width)
                    is_close = gap < (med_w * 0.18)
                    
                    # Specifically merge if one item is extremely narrow (Phantom Column case)
                    left_w = left[2] - left[0]
                    right_w = right[2] - right[0]
                    is_phantom = (left_w < med_w * 0.28) or (right_w < med_w * 0.28)
                    
                    if is_close or (is_phantom and gap < med_w * 0.25):
                        # Trigger Merge action!
                        new_box = [
                            min(curr[0], nxt[0]),
                            min(curr[1], nxt[1]),
                            max(curr[2], nxt[2]),
                            max(curr[3], nxt[3])
                        ]
                        logger.info(f"[TOPOLOGY CLEANUP] Merged adjacent fragments: width reduction achieved.")
                        curr = new_box # Use merged version for subsequent iterations
                        skip_indices.add(j)
                    else:
                        # They are aligned vertically but separated horizontally. Stop chain.
                        break
                else:
                    # Vertical sort is linear; if Y center gap expands significantly, break chain early
                    center_gap = abs(((curr[1]+curr[3])/2.0) - ((nxt[1]+nxt[3])/2.0))
                    if center_gap > med_h * 0.8:
                        break
            
            merged_list.append(curr)
            
        return merged_list
