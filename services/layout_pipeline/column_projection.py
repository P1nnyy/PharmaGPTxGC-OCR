import numpy as np
from typing import List, Tuple
from models.layout_models import OCRBlock
from core.logger import logger

def get_anchor_x(block: OCRBlock) -> float:
    """
    Determine the X-axis anchor point for projection.
    Numeric tokens use right-edge anchoring for decimal alignment,
    while text tokens use center anchoring.
    """
    if block.is_numeric:
        return block.right_edge
    if block.normalized_geometry:
        return block.normalized_geometry.center_x
    return 0.0

def project_column_boundaries(blocks: List[OCRBlock]) -> List[Tuple[float, float]]:
    """
    Phase 5.1: Global X-Axis Column Boundaries
    Returns a list of (min_x, max_x) for each detected column.
    """
    if not blocks:
        return []
        
    char_widths = []
    for b in blocks:
        if b.normalized_geometry and len(b.text) > 0:
            char_width = (b.normalized_geometry.max_x - b.normalized_geometry.min_x) / len(b.text)
            char_widths.append(char_width)
            
    median_char_width = float(np.median(char_widths)) if char_widths else 10.0
    MAX_COLUMN_GAP_PX = median_char_width * 1.5

    anchors = [get_anchor_x(b) for b in blocks if get_anchor_x(b) > 0]
    anchors.sort()
    
    if not anchors:
        return []
        
    # Find gaps > MAX_COLUMN_GAP_PX to define sparse column clusters
    clusters = []
    current_cluster = [anchors[0]]
    for x in anchors[1:]:
        gap_x = x - current_cluster[-1]
        if gap_x > MAX_COLUMN_GAP_PX:
            logger.info(f"Forced sparse split at gap_x={gap_x:.1f}px (threshold: {MAX_COLUMN_GAP_PX:.1f}px)")
            clusters.append(current_cluster)
            current_cluster = [x]
        else:
            current_cluster.append(x)
            
    if current_cluster:
        clusters.append(current_cluster)
        
    col_centroids = [sum(c)/len(c) for c in clusters]
    
    # Calculate boundaries halfway between centroids
    boundaries = []
    for i, centroid in enumerate(col_centroids):
        # min_x
        if i == 0:
            min_x = 0.0
        else:
            min_x = (col_centroids[i-1] + centroid) / 2.0
            
        # max_x
        if i == len(col_centroids) - 1:
            max_x = float('inf') # Rightmost column extends to infinity
        else:
            max_x = (centroid + col_centroids[i+1]) / 2.0
            
        boundaries.append((min_x, max_x))

    return boundaries
