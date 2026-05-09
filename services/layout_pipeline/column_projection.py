import numpy as np
from typing import List, Tuple
from models.layout_models import OCRBlock

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
        
    heights = []
    for b in blocks:
        if b.normalized_geometry:
            heights.append(b.normalized_geometry.max_y - b.normalized_geometry.min_y)
            
    median_height = float(np.median(heights)) if heights else 0.0
    gap_threshold = 1.5 * median_height if median_height > 0 else 50.0

    anchors = [get_anchor_x(b) for b in blocks if get_anchor_x(b) > 0]
    anchors.sort()
    
    if not anchors:
        return []
        
    # Find gaps > gap_threshold to define sparse column clusters
    clusters = []
    current_cluster = [anchors[0]]
    for x in anchors[1:]:
        if x - current_cluster[-1] > gap_threshold:
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
