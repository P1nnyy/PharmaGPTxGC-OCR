"""
Lightweight document graph diagnostics and candidate row/column extractor.

This is not a learned GCN, but it makes the same production invariant explicit:
OCR blocks are nodes, and spatial neighbors are first-class topology signals.
Extended to support deterministic geometry graph candidate reconstruction.
"""

import re
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




def _generate_graph_candidate_rows(items: List[Tuple[OCRBlock, GeometryBox]]) -> List[Dict[str, Any]]:
    """Helper to group tokens into row candidates and classify their types using local heuristics."""
    if not items:
        return []

    heights = [max(1.0, geom.max_y - geom.min_y) for _, geom in items]
    median_height = sorted(heights)[len(heights) // 2] if heights else 10.0
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

    candidate_rows = []
    for idx, cluster in enumerate(clusters):
        ordered = sorted(cluster, key=lambda entry: entry[1].min_x)

        min_x = min(entry[1].min_x for entry in ordered)
        max_x = max(entry[1].max_x for entry in ordered)
        min_y = min(entry[1].min_y for entry in ordered)
        max_y = max(entry[1].max_y for entry in ordered)
        center_y = sum(entry[1].center_y for entry in ordered) / len(ordered)

        token_ids = [block.id for block, _ in ordered]
        text = " ".join((block.text or "").strip() for block, _ in ordered)
        text_upper = text.upper()

        # Classify candidate role using Indian pharma context priors
        footer_keywords = [
            "TOTAL", "SUBTOTAL", "SUB TOTAL", "CGST", "SGST", "IGST", "ROUND OFF", "DISCOUNT",
            "AMOUNT IN WORDS", "NET AMT", "NET AMOUNT", "NET PAYABLE", "BILL AMOUNT", "TOTAL PAYABLE",
            "CR/DR NOTE", "CD%", "TD%", "CASH DISCOUNT", "TRADE DISCOUNT"
        ]
        header_keywords = [
            "PRODUCT", "ITEM", "DESCRIPTION", "BATCH", "EXP", "HSN", "QTY", "MRP", "RATE", "AMOUNT",
            "SL.NO", "S.NO", "SR.NO", "PACK", "MFG", "DISC%", "SLAB"
        ]
        metadata_keywords = [
            "INVOICE NO", "INVOICE DATE", "BILL NO", "BILL DATE", "DATE:", "GSTIN", "DL NO",
            "PHONE", "MOBILE", "PATIENT", "DOCTOR", "NAME:", "ADDRESS:", "DRUG LICENSE"
        ]

        is_footer = any(kw in text_upper for kw in footer_keywords)
        is_header = any(kw in text_upper for kw in header_keywords)
        is_metadata = any(kw in text_upper for kw in metadata_keywords)

        has_alpha = any(c.isalpha() for c in text)
        has_digit = any(c.isdigit() for c in text)
        num_tokens = sum(1 for block, _ in ordered if any(c.isdigit() for c in (block.text or "")))

        # Item row candidate: multi-token structure with mixed alphanumeric data
        is_item = has_alpha and has_digit and num_tokens >= 1 and len(ordered) >= 3 and not is_footer and not is_header and not is_metadata

        if is_footer:
            row_type_hint = "footer_candidate"
        elif is_header:
            row_type_hint = "header_candidate"
        elif is_item:
            row_type_hint = "item_candidate"
        elif is_metadata:
            row_type_hint = "metadata_candidate"
        else:
            row_type_hint = "unknown"

        confidence = 1.0
        if len(ordered) == 1:
            confidence *= 0.3
        elif len(ordered) == 2:
            confidence *= 0.6

        if row_type_hint == "item_candidate":
            if len(ordered) < 4:
                confidence *= 0.8
            # Boost if has clear pharmaceutical expiry patterns
            has_expiry_pattern = any(bool(re.search(r'\d{2}/\d{2}', block.text or "")) for block, _ in ordered)
            if has_expiry_pattern:
                confidence = min(1.0, confidence * 1.2)

        if not text.strip():
            confidence = 0.0

        candidate_rows.append({
            "row_id": f"graph_row_{idx}",
            "token_ids": token_ids,
            "text": text,
            "min_x": round(min_x, 3),
            "max_x": round(max_x, 3),
            "min_y": round(min_y, 3),
            "max_y": round(max_y, 3),
            "center_y": round(center_y, 3),
            "token_count": len(ordered),
            "row_type_hint": row_type_hint,
            "confidence": round(confidence, 3),
        })

    return candidate_rows


def _generate_graph_candidate_columns(items: List[Tuple[OCRBlock, GeometryBox]], candidate_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cluster horizontal token bands from item + header rows into candidate columns."""
    row_type_map = {r["row_id"]: r["row_type_hint"] for r in candidate_rows}
    row_token_set = {}
    for r in candidate_rows:
        for t_id in r["token_ids"]:
            row_token_set[t_id] = r["row_id"]

    active_tokens = []
    for block, geom in items:
        row_id = row_token_set.get(block.id)
        if not row_id:
            continue
        row_type = row_type_map.get(row_id)
        if row_type in ["item_candidate", "header_candidate"]:
            active_tokens.append({
                "token_id": block.id,
                "text": block.text,
                "min_x": geom.min_x,
                "max_x": geom.max_x,
                "center_x": geom.center_x,
                "row_id": row_id,
                "row_type": row_type,
            })

    if not active_tokens:
        return []

    widths = [t["max_x"] - t["min_x"] for t in active_tokens]
    median_width = sorted(widths)[len(widths) // 2] if widths else 45.0
    col_threshold = max(20.0, median_width * 0.70)

    sorted_tokens = sorted(active_tokens, key=lambda t: t["center_x"])
    col_clusters: List[List[Dict[str, Any]]] = []

    for t in sorted_tokens:
        for cluster in col_clusters:
            avg_center_x = sum(item["center_x"] for item in cluster) / len(cluster)
            if abs(t["center_x"] - avg_center_x) <= col_threshold:
                cluster.append(t)
                break
        else:
            col_clusters.append([t])

    candidate_cols = []
    item_row_ids = [r["row_id"] for r in candidate_rows if r["row_type_hint"] == "item_candidate"]
    num_item_rows = len(item_row_ids)

    for idx, cluster in enumerate(col_clusters):
        min_x = min(t["min_x"] for t in cluster)
        max_x = max(t["max_x"] for t in cluster)
        center_x = sum(t["center_x"] for t in cluster) / len(cluster)

        supporting_token_ids = [t["token_id"] for t in cluster]
        supporting_row_ids = list(set(t["row_id"] for t in cluster))

        semantic_hint = "unknown"
        for t in cluster:
            if t["row_type"] == "header_candidate":
                t_text = (t["text"] or "").upper().strip()
                if any(kw in t_text for kw in ["PRODUCT", "ITEM", "DESCRIPTION", "NAME", "MEDICINE"]):
                    semantic_hint = "product"
                    break
                elif any(kw in t_text for kw in ["BATCH", "B.NO", "BTH", "B NO"]):
                    semantic_hint = "batch"
                    break
                elif any(kw in t_text for kw in ["EXP", "EXPIRY", "E.DT", "EXP.DATE"]):
                    semantic_hint = "expiry"
                    break
                elif any(kw in t_text for kw in ["HSN", "SAC"]):
                    semantic_hint = "hsn"
                    break
                elif any(kw in t_text for kw in ["FREE", "SCH", "SCHEME"]):
                    semantic_hint = "free_qty"
                    break
                elif any(kw in t_text for kw in ["QTY", "QUANTITY", "QNTY", "NOS"]):
                    semantic_hint = "qty"
                    break
                elif any(kw in t_text for kw in ["MRP", "M.R.P"]):
                    semantic_hint = "mrp"
                    break
                elif any(kw in t_text for kw in ["RATE", "UNIT", "PRICE"]):
                    semantic_hint = "rate"
                    break
                elif any(kw in t_text for kw in ["GST", "SGST", "CGST", "IGST", "TAX"]):
                    semantic_hint = "gst"
                    break
                elif any(kw in t_text for kw in ["AMT", "AMOUNT", "NET", "VALUE"]):
                    semantic_hint = "amount"
                    break

        if semantic_hint == "unknown":
            for t in cluster:
                t_text = (t["text"] or "").strip()
                if re.match(r'^\d{2}/\d{2}$', t_text) or re.match(r'^\d{2}-\d{2}$', t_text):
                    semantic_hint = "expiry"
                    break
                elif re.match(r'^\d{4,10}$', t_text) and len(t_text) >= 6:
                    semantic_hint = "hsn"
                    break

        supporting_item_rows = [rid for rid in supporting_row_ids if rid in item_row_ids]
        if num_item_rows > 0:
            confidence = len(supporting_item_rows) / num_item_rows
        else:
            confidence = 0.5

        has_header_support = any(t["row_type"] == "header_candidate" for t in cluster)
        if has_header_support:
            confidence = min(1.0, confidence * 1.25)

        candidate_cols.append({
            "col_id": f"graph_col_{idx}",
            "min_x": round(min_x, 3),
            "max_x": round(max_x, 3),
            "center_x": round(center_x, 3),
            "supporting_token_ids": supporting_token_ids,
            "supporting_row_ids": supporting_row_ids,
            "semantic_hint": semantic_hint,
            "confidence": round(confidence, 3),
        })

    return candidate_cols


def build_document_graph(blocks: List[OCRBlock]) -> Dict[str, Any]:
    """Generates structural spatial representation and graph-based candidate rows/columns."""
    items = [(block, _geom(block)) for block in blocks if block.id and _geom(block)]
    items = [(block, geom) for block, geom in items if geom is not None]
    edges = _nearest_directional_edges(items)
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

    # Generate graph candidate rows and columns
    graph_candidate_rows = _generate_graph_candidate_rows(items)
    graph_candidate_columns = _generate_graph_candidate_columns(items, graph_candidate_rows)

    # Derive row_clusters from graph_candidate_rows (preserves identical output keys)
    row_clusters = [
        {
            "cluster_id": r["row_id"],
            "token_ids": r["token_ids"],
            "token_count": r["token_count"],
            "sample_text": r["text"][:180],
        }
        for r in graph_candidate_rows
    ]

    # Compute graph table region enclosing item and header candidate rows
    table_rows = [r for r in graph_candidate_rows if r["row_type_hint"] in ["item_candidate", "header_candidate"]]
    if table_rows:
        t_min_x = min(r["min_x"] for r in table_rows)
        t_max_x = max(r["max_x"] for r in table_rows)
        t_min_y = min(r["min_y"] for r in table_rows)
        t_max_y = max(r["max_y"] for r in table_rows)
        row_count = len(table_rows)
        column_count = len(graph_candidate_columns)
        avg_row_conf = sum(r["confidence"] for r in table_rows) / row_count if row_count > 0 else 0.0
        avg_col_conf = sum(c["confidence"] for c in graph_candidate_columns) / column_count if column_count > 0 else 0.0
        candidate_quality = round((avg_row_conf + avg_col_conf) / 2.0, 3)

        graph_table_region = {
            "min_x": round(t_min_x, 3),
            "max_x": round(t_max_x, 3),
            "min_y": round(t_min_y, 3),
            "max_y": round(t_max_y, 3),
            "row_count": row_count,
            "column_count": column_count,
            "candidate_quality": candidate_quality,
        }
    else:
        graph_table_region = {
            "min_x": 0.0,
            "max_x": 1000.0,
            "min_y": 0.0,
            "max_y": 1000.0,
            "row_count": 0,
            "column_count": 0,
            "candidate_quality": 0.0,
        }

    # Compute aggregate graph confidence
    num_item_rows = sum(1 for r in graph_candidate_rows if r["row_type_hint"] == "item_candidate")
    item_factor = min(1.0, num_item_rows / 8.0)

    col_factor = sum(c["confidence"] for c in graph_candidate_columns) / len(graph_candidate_columns) if graph_candidate_columns else 0.0

    node_count = len(items)
    isolated_ratio = len(isolated) / node_count if node_count > 0 else 0.0
    isolated_factor = max(0.0, 1.0 - isolated_ratio)

    has_header = any(r["row_type_hint"] == "header_candidate" for r in graph_candidate_rows)
    has_footer = any(r["row_type_hint"] == "footer_candidate" for r in graph_candidate_rows)
    evidence_bonus = (0.1 if has_header else 0.0) + (0.1 if has_footer else 0.0)

    column_band_stability = round(col_factor, 3)

    graph_confidence = round(
        min(1.0, (item_factor * 0.3) + (col_factor * 0.3) + (isolated_factor * 0.2) + evidence_bonus + 0.1), 3
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "row_clusters": row_clusters,
        "graph_candidate_rows": graph_candidate_rows,
        "graph_candidate_columns": graph_candidate_columns,
        "graph_table_region": graph_table_region,
        "graph_confidence": graph_confidence,
        "metrics": {
            "node_count": len(nodes),
            "edge_count": sum(
                1 for edge_map in edges.values() for value in edge_map.values() if value
            ),
            "row_cluster_count": len(row_clusters),
            "max_row_cluster_size": max((cluster["token_count"] for cluster in row_clusters), default=0),
            "isolated_node_count": len(isolated),
            # new telemetry metrics
            "graph_candidate_row_count": len(graph_candidate_rows),
            "graph_candidate_column_count": len(graph_candidate_columns),
            "graph_confidence": graph_confidence,
            "column_band_stability": column_band_stability,
            "isolated_node_ratio": round(isolated_ratio, 3),
        },
    }
