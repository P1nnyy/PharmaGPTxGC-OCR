import re
from typing import Any, Dict, List, Optional, Set, Tuple

from models.layout_models import OCRBlock, TableRegion, ColumnRegion, TableCell, GeometryBox


def _geom(block: OCRBlock):
    return block.normalized_geometry or block.original_geometry


def _ratios(text: str) -> Tuple[float, float]:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0, 0.0
    alpha = sum(1 for c in chars if c.isalpha())
    digit = sum(1 for c in chars if c.isdigit())
    return alpha / len(chars), digit / len(chars)


def extract_token_features(block: OCRBlock) -> Optional[Dict[str, Any]]:
    geom = _geom(block)
    if not geom:
        return None

    text = (block.text or "").strip()
    compact = re.sub(r"\s+", "", text.upper())
    alpha_ratio, digit_ratio = _ratios(text)

    is_decimal_money_like = bool(re.fullmatch(r"[₹$]?\d[\d,]*\.\d{1,3}%?", compact))
    is_integer_like = bool(re.fullmatch(r"\d+", compact))
    is_qty_like = bool(
        re.fullmatch(r"\d+(?:[+*xX]\d+)?", compact)
        or re.fullmatch(r"\d+(?:\.\d+)?", compact)
    ) and len(compact) <= 5
    is_expiry_like = bool(re.fullmatch(r"\d{1,2}[/-]\d{2,4}", compact))
    is_hsn_like = bool(re.fullmatch(r"\d{6,8}", compact))
    is_batch_like = (
        bool(re.fullmatch(r"[A-Z0-9-]{5,16}", compact))
        and bool(re.search(r"[A-Z]", compact))
        and bool(re.search(r"\d", compact))
        and not is_expiry_like
    )

    return {
        "token_id": block.id,
        "text": text,
        "geometry": geom,
        "center_x": float(geom.center_x),
        "min_x": float(geom.min_x),
        "max_x": float(geom.max_x),
        "width": float(geom.max_x - geom.min_x),
        "right_edge": float(geom.max_x),
        "is_decimal_money_like": is_decimal_money_like,
        "is_integer_like": is_integer_like,
        "is_qty_like": is_qty_like,
        "is_expiry_like": is_expiry_like,
        "is_hsn_like": is_hsn_like,
        "is_batch_like": is_batch_like,
        "alpha_ratio": round(alpha_ratio, 4),
        "digit_ratio": round(digit_ratio, 4),
    }


def _feature_vote(feature: Dict[str, Any]) -> Optional[str]:
    if feature["is_expiry_like"]:
        return "expiry"
    if feature["is_batch_like"]:
        return "batch"
    if feature["is_hsn_like"]:
        return "hsn"
    if feature["is_decimal_money_like"]:
        return "money"
    if feature["is_qty_like"] or feature["is_integer_like"]:
        return "qty"
    if feature["alpha_ratio"] > 0.55:
        return "text"
    return None


def _anchor_x(feature: Dict[str, Any], vote: str) -> float:
    if vote in {"money", "qty"}:
        return feature["right_edge"]
    return feature["center_x"]


def _cluster_candidates(candidates: List[Dict[str, Any]], threshold: float) -> List[List[Dict[str, Any]]]:
    clusters: List[List[Dict[str, Any]]] = []
    for candidate in sorted(candidates, key=lambda c: c["anchor_x"]):
        if not clusters:
            clusters.append([candidate])
            continue

        last = clusters[-1]
        center = sum(c["anchor_x"] for c in last) / len(last)
        if abs(candidate["anchor_x"] - center) < threshold:
            last.append(candidate)
        else:
            clusters.append([candidate])
    return clusters


def _band_from_cluster(cluster: List[Dict[str, Any]], col_id: str) -> Dict[str, Any]:
    min_x = min(c["feature"]["min_x"] for c in cluster)
    max_x = max(c["feature"]["max_x"] for c in cluster)
    center_x = sum(c["anchor_x"] for c in cluster) / len(cluster)
    votes = {"expiry": 0, "batch": 0, "hsn": 0, "money": 0, "qty": 0, "text": 0}
    row_ids: Set[str] = set()
    for candidate in cluster:
        votes[candidate["vote"]] += 1
        row_ids.add(candidate["row_id"])
    return {
        "col_id": col_id,
        "min_x": float(min_x),
        "max_x": float(max_x),
        "center_x": float(center_x),
        "support_count": len(row_ids),
        "token_count": len(cluster),
        "feature_votes": votes,
    }


def _make_geom(min_x: float, min_y: float, max_x: float, max_y: float) -> GeometryBox:
    return GeometryBox(
        min_x=float(min_x),
        min_y=float(min_y),
        max_x=float(max_x),
        max_y=float(max_y),
        center_x=float((min_x + max_x) / 2.0),
        center_y=float((min_y + max_y) / 2.0),
    )


def _union_geom(features: List[Dict[str, Any]]) -> GeometryBox:
    return _make_geom(
        min(f["min_x"] for f in features),
        min(f["geometry"].min_y for f in features),
        max(f["max_x"] for f in features),
        max(f["geometry"].max_y for f in features),
    )


def _avg_populated_cell_text_len(table_region: TableRegion) -> float:
    texts = [c.text.strip() for c in table_region.cells if c.text and c.text.strip()]
    if not texts:
        return 0.0
    return sum(len(t) for t in texts) / len(texts)


def _row_cells(table_region: TableRegion) -> Dict[str, List[TableCell]]:
    rows: Dict[str, List[TableCell]] = {}
    for cell in table_region.cells:
        rows.setdefault(cell.row_id, []).append(cell)
    return rows


def _undersegmentation_reason(table_region: TableRegion) -> Optional[str]:
    before_column_count = len(table_region.columns)
    avg_text_len = _avg_populated_cell_text_len(table_region)
    cells_by_row = _row_cells(table_region)
    item_rows = [r for r in table_region.rows if getattr(r, "row_role", "unknown_row") == "item_row"]
    one_cell_item_rows = 0
    for row in item_rows:
        populated = [c for c in cells_by_row.get(row.row_id, []) if c.text and c.text.strip()]
        if len(populated) <= 1:
            one_cell_item_rows += 1

    item_single_cell_ratio = one_cell_item_rows / len(item_rows) if item_rows else 0.0
    if before_column_count <= 2 and avg_text_len >= 60.0:
        return "main_table_columns_le_2_and_high_avg_cell_text_len"
    if before_column_count <= 2 and item_single_cell_ratio >= 0.5:
        return "main_table_columns_le_2_and_item_rows_cell_count_1"
    return None


def _semantic_repair_trigger(
    semantic_context: Optional[Dict[str, Any]],
    missing_semantic_columns: Optional[List[str]],
) -> bool:
    missing = {str(col).lower() for col in (missing_semantic_columns or [])}
    if missing.intersection({"quantity", "rate", "amount"}):
        return True

    if not semantic_context:
        return False

    inferred = semantic_context.get("_inference_summary", {})
    final_semantics = inferred.get("final_column_semantics", {})
    if not final_semantics:
        final_semantics = {
            col_id: data.get("type")
            for col_id, data in semantic_context.items()
            if isinstance(data, dict) and not str(col_id).startswith("_")
        }

    all_types = [str(value).lower() for value in final_semantics.values() if str(value).strip()]
    known_types = {value for value in all_types if value != "unknown"}
    if known_types == {"product", "amount"}:
        return True
    if known_types == {"product"} and "unknown" in all_types:
        return True
    if known_types == {"amount"}:
        return True
    return False


def detect_column_anchors(
    table_region: TableRegion,
    ocr_blocks: List[OCRBlock],
    clustering_threshold: float = 24.0,
    min_row_support: int = 2,
) -> Dict[str, Any]:
    """
    Infer stable vertical anchor bands from OCR token geometry without mutating topology.
    """
    blocks_by_id = {b.id: b for b in ocr_blocks if b.id}
    row_roles = {r.row_id: getattr(r, "row_role", "unknown_row") for r in table_region.rows}
    item_row_ids = {row_id for row_id, role in row_roles.items() if role == "item_row"}
    usable_row_ids = item_row_ids or {
        row_id for row_id, role in row_roles.items()
        if role not in {"footer_summary_row", "tax_summary_row", "metadata_row"}
    }

    candidates = []
    token_count_used = 0
    seen_tokens: Set[str] = set()

    for cell in table_region.cells:
        if cell.row_id not in usable_row_ids:
            continue
        for token_id in cell.mapped_block_ids:
            if token_id in seen_tokens:
                continue
            seen_tokens.add(token_id)
            block = blocks_by_id.get(token_id)
            if not block:
                continue
            feature = extract_token_features(block)
            if not feature:
                continue
            token_count_used += 1
            vote = _feature_vote(feature)
            if vote not in {"expiry", "batch", "hsn", "money", "qty", "text"}:
                continue
            # Text anchors are useful for the left product column, but require stronger alpha shape.
            if vote == "text" and feature["alpha_ratio"] < 0.65:
                continue
            candidates.append({
                "token_id": token_id,
                "row_id": cell.row_id,
                "vote": vote,
                "anchor_x": _anchor_x(feature, vote),
                "feature": feature,
            })

    anchors = []
    rejected_anchors = []
    for cluster in _cluster_candidates(candidates, clustering_threshold):
        band = _band_from_cluster(cluster, f"anchor_col_{len(anchors)}")
        if band["support_count"] >= min_row_support:
            anchors.append(band)
        else:
            rejected_anchors.append({
                **band,
                "reason": "insufficient_row_support",
            })

    # Re-number after rejection so returned ids are stable and dense.
    for idx, anchor in enumerate(anchors):
        anchor["col_id"] = f"anchor_col_{idx}"

    return {
        "candidate_anchor_count": len(candidates),
        "final_anchor_count": len(anchors),
        "anchors": anchors,
        "rejected_anchors": rejected_anchors,
        "clustering_threshold": clustering_threshold,
        "token_count_used": token_count_used,
        "item_row_ids_used": sorted(item_row_ids),
    }


def _useful_anchor_columns(anchor_debug: Dict[str, Any]) -> List[Dict[str, Any]]:
    useful = []
    for anchor in anchor_debug.get("anchors", []):
        votes = anchor.get("feature_votes", {})
        non_text_votes = sum(votes.get(k, 0) for k in ("expiry", "batch", "hsn", "money", "qty"))
        if non_text_votes > 0:
            useful.append(anchor)
    return sorted(useful, key=lambda a: a["center_x"])


def _assign_feature_to_column(
    feature: Dict[str, Any],
    anchors: List[Dict[str, Any]],
    product_col_id: str,
) -> str:
    if not anchors:
        return product_col_id

    first_anchor = anchors[0]
    text = feature["text"].upper()
    alpha_heavy = feature["alpha_ratio"] >= 0.45
    pack_like = bool(re.search(r"\d+\*?\d*'?S\b|\d+\s*(ML|MG|GM|G)\b", text))

    if feature["center_x"] < first_anchor["min_x"]:
        return product_col_id
    if (alpha_heavy or pack_like) and feature["center_x"] < first_anchor["center_x"]:
        return product_col_id

    vote = _feature_vote(feature)
    ref_x = feature["right_edge"] if vote in {"money", "qty"} else feature["center_x"]
    return min(anchors, key=lambda a: abs(ref_x - a["center_x"]))["col_id"]


def repair_undersegmented_table_with_anchors(
    table_region: TableRegion,
    ocr_blocks: List[OCRBlock],
    anchor_debug: Optional[Dict[str, Any]] = None,
    semantic_context: Optional[Dict[str, Any]] = None,
    missing_semantic_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Split one-cell medicine rows into geometry-anchored cells. Mutates only on success.
    """
    before_column_count = len(table_region.columns)
    before_avg_len = _avg_populated_cell_text_len(table_region)
    reason = _undersegmentation_reason(table_region)
    anchor_debug = anchor_debug or detect_column_anchors(table_region, ocr_blocks)
    candidate_anchor_count = anchor_debug.get("candidate_anchor_count", 0)
    final_anchor_count = anchor_debug.get("final_anchor_count", 0)
    missing_semantic_trigger = _semantic_repair_trigger(semantic_context, missing_semantic_columns)
    if (
        not reason
        and before_column_count <= 2
        and final_anchor_count >= 4
        and missing_semantic_trigger
    ):
        reason = "low_column_count_with_strong_anchors_and_missing_semantics"

    base_metrics = {
        "enabled": False,
        "repair_attempted": False,
        "reason": reason or "not_under_segmented",
        "undersegmentation_trigger_reason": reason,
        "missing_semantic_columns_trigger": sorted({str(col).lower() for col in (missing_semantic_columns or [])}),
        "candidate_anchor_count": candidate_anchor_count,
        "final_anchor_count": final_anchor_count,
        "before_column_count": before_column_count,
        "after_column_count": before_column_count,
        "before_avg_cell_text_len": round(before_avg_len, 2),
        "after_avg_cell_text_len": round(before_avg_len, 2),
        "repaired_row_count": 0,
        "product_col_detected": False,
        "anchor_columns_used": [],
    }
    if not reason:
        return base_metrics

    base_metrics["repair_attempted"] = True
    anchors = _useful_anchor_columns(anchor_debug)
    if len(anchors) + 1 < 3:
        return {
            **base_metrics,
            "reason": "anchor_repair_produced_fewer_than_3_useful_columns",
            "anchor_columns_used": anchors,
        }

    blocks_by_id = {b.id: b for b in ocr_blocks if b.id}
    product_col_id = "anchor_product"
    table_geom = table_region.geometry
    all_row_geoms = [r.geometry for r in table_region.rows if r.geometry]
    min_y = table_geom.min_y if table_geom else min([g.min_y for g in all_row_geoms] + [0.0])
    max_y = table_geom.max_y if table_geom else max([g.max_y for g in all_row_geoms] + [1000.0])
    min_x = table_geom.min_x if table_geom else 0.0
    max_x = table_geom.max_x if table_geom else max([a["max_x"] for a in anchors] + [1000.0])

    product_max_x = max(min_x, anchors[0]["min_x"] - 2.0)
    new_columns = [
        ColumnRegion(
            col_id=product_col_id,
            geometry=_make_geom(min_x, min_y, product_max_x, max_y),
            normalized_geometry=_make_geom(min_x, min_y, product_max_x, max_y),
            confidence=1.0,
        )
    ]
    for idx, anchor in enumerate(anchors):
        col_id = f"anchor_col_{idx}"
        anchor["col_id"] = col_id
        geom = _make_geom(anchor["min_x"], min_y, anchor["max_x"], max_y)
        new_columns.append(ColumnRegion(
            col_id=col_id,
            geometry=geom,
            normalized_geometry=geom.model_copy(),
            confidence=1.0,
        ))

    cells_by_row = _row_cells(table_region)
    new_cells: List[TableCell] = []
    repaired_row_count = 0

    for row in table_region.rows:
        token_features = []
        seen: Set[str] = set()
        for cell in cells_by_row.get(row.row_id, []):
            for token_id in cell.mapped_block_ids:
                if token_id in seen:
                    continue
                seen.add(token_id)
                block = blocks_by_id.get(token_id)
                if not block:
                    continue
                feature = extract_token_features(block)
                if feature:
                    token_features.append(feature)

        assignments: Dict[str, List[Dict[str, Any]]] = {}
        for feature in token_features:
            col_id = _assign_feature_to_column(feature, anchors, product_col_id)
            assignments.setdefault(col_id, []).append(feature)

        populated_cols = 0
        for col in new_columns:
            features = assignments.get(col.col_id, [])
            if not features:
                continue
            features.sort(key=lambda f: (f["geometry"].min_y, f["min_x"]))
            text = " ".join(f["text"] for f in features if f["text"]).strip()
            geom = _union_geom(features)
            new_cells.append(TableCell(
                row_id=row.row_id,
                col_id=col.col_id,
                geometry=geom,
                original_geometry=geom.model_copy(),
                normalized_geometry=geom.model_copy(),
                confidence=1.0,
                mapped_block_ids=[f["token_id"] for f in features if f["token_id"]],
                text=text,
                original_text=text,
                semantic_outlier=False,
                assignment_confidence=1.0,
                assignment_strategy="anchor_repair",
            ))
            populated_cols += 1

        if getattr(row, "row_role", "unknown_row") == "item_row" and populated_cols > 1:
            repaired_row_count += 1

    item_row_ids = {row.row_id for row in table_region.rows if getattr(row, "row_role", "unknown_row") == "item_row"}
    meaningful_columns = {
        cell.col_id
        for cell in new_cells
        if (cell.text or "").strip()
        and (not item_row_ids or cell.row_id in item_row_ids)
    }

    if len(meaningful_columns) < 4:
        return {
            **base_metrics,
            "reason": "anchor_repair_failed_insufficient_output_columns",
            "after_column_count": len(meaningful_columns),
            "anchor_columns_used": anchors,
        }

    if repaired_row_count == 0:
        return {
            **base_metrics,
            "reason": "anchor_repair_no_item_rows_split",
            "anchor_columns_used": anchors,
        }

    table_region.columns = new_columns
    table_region.cells = new_cells

    after_avg_len = _avg_populated_cell_text_len(table_region)
    return {
        "enabled": True,
        "repair_attempted": True,
        "reason": reason,
        "undersegmentation_trigger_reason": reason,
        "missing_semantic_columns_trigger": sorted({str(col).lower() for col in (missing_semantic_columns or [])}),
        "candidate_anchor_count": candidate_anchor_count,
        "final_anchor_count": final_anchor_count,
        "before_column_count": before_column_count,
        "after_column_count": len(new_columns),
        "before_avg_cell_text_len": round(before_avg_len, 2),
        "after_avg_cell_text_len": round(after_avg_len, 2),
        "repaired_row_count": repaired_row_count,
        "product_col_detected": True,
        "anchor_columns_used": anchors,
    }
