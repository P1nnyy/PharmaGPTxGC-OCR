"""
Lightweight document graph diagnostics.

This is not a learned GCN, but it makes the same production invariant explicit:
OCR blocks are nodes, and spatial neighbors are first-class topology signals.
"""

from typing import Any, Dict, List, Optional, Tuple

from models.layout_models import OCRBlock, GeometryBox


def _geom(block: OCRBlock) -> Optional[GeometryBox]:
    return block.normalized_geometry or block.original_geometry


def _box_dict(geom: Optional[GeometryBox]) -> Dict[str, Any]:
    if not geom:
        return {}
    return {
        "x1": round(float(geom.min_x), 3),
        "y1": round(float(geom.min_y), 3),
        "x2": round(float(geom.max_x), 3),
        "y2": round(float(geom.max_y), 3),
        "center_x": round(float(geom.center_x), 3),
        "center_y": round(float(geom.center_y), 3),
    }


def _overlap_ratio(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
    overlap = max(0.0, min(a_max, b_max) - max(a_min, b_min))
    denom = max(1.0, min(a_max - a_min, b_max - b_min))
    return overlap / denom


def _relative_distance(a: GeometryBox, b: GeometryBox) -> float:
    page_scale = max(1.0, max(a.max_x, b.max_x) - min(a.min_x, b.min_x), max(a.max_y, b.max_y) - min(a.min_y, b.min_y))
    return (((a.center_x - b.center_x) ** 2 + (a.center_y - b.center_y) ** 2) ** 0.5) / page_scale


def _nearest_directional_edges(items: List[Tuple[OCRBlock, GeometryBox]]) -> Dict[str, Dict[str, Any]]:
    edges: Dict[str, Dict[str, Any]] = {}
    for block, geom in items:
        directional: Dict[str, Any] = {}
        candidates = {
            "left": [],
            "right": [],
            "top": [],
            "bottom": [],
        }
        for other, other_geom in items:
            if other.id == block.id:
                continue
            y_overlap = _overlap_ratio(geom.min_y, geom.max_y, other_geom.min_y, other_geom.max_y)
            x_overlap = _overlap_ratio(geom.min_x, geom.max_x, other_geom.min_x, other_geom.max_x)
            if other_geom.center_x < geom.center_x and y_overlap >= 0.25:
                candidates["left"].append((geom.center_x - other_geom.center_x, other, other_geom))
            if other_geom.center_x > geom.center_x and y_overlap >= 0.25:
                candidates["right"].append((other_geom.center_x - geom.center_x, other, other_geom))
            if other_geom.center_y < geom.center_y and x_overlap >= 0.20:
                candidates["top"].append((geom.center_y - other_geom.center_y, other, other_geom))
            if other_geom.center_y > geom.center_y and x_overlap >= 0.20:
                candidates["bottom"].append((other_geom.center_y - geom.center_y, other, other_geom))

        for direction, direction_candidates in candidates.items():
            if not direction_candidates:
                directional[direction] = None
                continue
            _, nearest_block, nearest_geom = sorted(direction_candidates, key=lambda item: item[0])[0]
            directional[direction] = {
                "token_id": nearest_block.id,
                "relative_distance": round(_relative_distance(geom, nearest_geom), 4),
            }
        edges[block.id] = directional
    return edges


def _row_clusters(items: List[Tuple[OCRBlock, GeometryBox]]) -> List[Dict[str, Any]]:
    if not items:
        return []
    heights = [max(1.0, geom.max_y - geom.min_y) for _, geom in items]
    median_height = sorted(heights)[len(heights) // 2]
    threshold = max(8.0, median_height * 0.65)
    clusters: List[List[Tuple[OCRBlock, GeometryBox]]] = []

    for item in sorted(items, key=lambda entry: entry[1].center_y):
        _, geom = item
        for cluster in clusters:
            center_y = sum(entry[1].center_y for entry in cluster) / len(cluster)
            if abs(geom.center_y - center_y) <= threshold:
                cluster.append(item)
                break
        else:
            clusters.append([item])

    output = []
    for idx, cluster in enumerate(clusters):
        ordered = sorted(cluster, key=lambda entry: entry[1].min_x)
        output.append({
            "cluster_id": f"graph_row_{idx}",
            "token_ids": [block.id for block, _ in ordered],
            "token_count": len(ordered),
            "sample_text": " ".join((block.text or "").strip() for block, _ in ordered)[:180],
        })
    return output


def build_document_graph(blocks: List[OCRBlock]) -> Dict[str, Any]:
    items = [(block, _geom(block)) for block in blocks if block.id and _geom(block)]
    items = [(block, geom) for block, geom in items if geom is not None]
    edges = _nearest_directional_edges(items)
    row_clusters = _row_clusters(items)
    isolated = [
        block.id
        for block, _ in items
        if not any(edges.get(block.id, {}).get(direction) for direction in ("left", "right", "top", "bottom"))
    ]

    nodes = [
        {
            "token_id": block.id,
            "text": block.text,
            **_box_dict(geom),
        }
        for block, geom in items
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "row_clusters": row_clusters,
        "metrics": {
            "node_count": len(nodes),
            "edge_count": sum(
                1 for edge_map in edges.values() for value in edge_map.values() if value
            ),
            "row_cluster_count": len(row_clusters),
            "max_row_cluster_size": max((cluster["token_count"] for cluster in row_clusters), default=0),
            "isolated_node_count": len(isolated),
        },
    }
