from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


PHARMA_HEADER_RE = re.compile(
    r"\b(ITEM|PRODUCT|DESCRIPTION|PARTICULAR|HSN|BATCH|B\.?NO|QTY|QUANTITY|RATE|EXP|EXPIRY|MRP|GST|AMOUNT)\b",
    re.IGNORECASE,
)
CATASTROPHIC_TSR_SCORE = -50.0
GEOMETRY_TOLERANCE = 2.0


def table_bbox(table: Any) -> Optional[List[float]]:
    geom = _read_attr(table, "geometry", None) or _read_attr(table, "normalized_geometry", None)
    bbox = _bbox_from_geometry(geom)
    if bbox:
        return bbox

    cell_bboxes = [
        bbox
        for bbox in (cell_bbox(cell) for cell in (_read_attr(table, "cells", []) or []))
        if bbox
    ]
    if not cell_bboxes:
        return None
    return [
        min(b[0] for b in cell_bboxes),
        min(b[1] for b in cell_bboxes),
        max(b[2] for b in cell_bboxes),
        max(b[3] for b in cell_bboxes),
    ]


def cell_bbox(cell: Any) -> Optional[List[float]]:
    return (
        _bbox_from_explicit(_read_attr(cell, "bbox", None))
        or _bbox_from_explicit(_read_attr(cell, "absolute_bbox", None))
        or _bbox_from_geometry(_read_attr(cell, "geometry", None))
        or _bbox_from_geometry(_read_attr(cell, "normalized_geometry", None))
    )


def evaluate_table_candidate_sanity(
    table: Any,
    *,
    processed_width: Optional[float] = None,
    processed_height: Optional[float] = None,
    candidate_score: Optional[float] = None,
    candidate_metrics: Optional[Dict[str, Any]] = None,
    ocr_block_count: Optional[int] = None,
    tolerance: float = GEOMETRY_TOLERANCE,
) -> Dict[str, Any]:
    metrics = candidate_metrics if isinstance(candidate_metrics, dict) else {}
    rejection_reasons: List[str] = []
    warnings: List[str] = []

    table_id = str(_read_attr(table, "table_id", "") or "unknown")
    rows = list(_read_attr(table, "rows", []) or [])
    columns = list(_read_attr(table, "columns", []) or [])
    cells = list(_read_attr(table, "cells", []) or [])
    row_count = len(rows)
    column_count = len(columns)
    cell_count = len(cells)
    item_rows = _item_row_count(rows, metrics)
    semantic_gaps = _semantic_gaps(table, metrics)
    all_unknown_columns = _all_unknown_columns(table, metrics)
    pharma_header_hits = _pharma_header_hits(table)
    score = _safe_float(candidate_score)
    if score is None:
        score = _safe_float(_read_attr(table, "score", None))
    if score is None:
        score = _safe_float(_read_attr(table, "representability_score", None))

    bbox = table_bbox(table)
    geometry_reasons = _geometry_rejection_reasons(
        bbox,
        processed_width=processed_width,
        processed_height=processed_height,
        tolerance=tolerance,
        prefix="table_bbox",
    )
    rejection_reasons.extend(geometry_reasons)

    bad_cell_count = 0
    checked_cell_count = 0
    for cell in cells:
        bbox_reasons = _geometry_rejection_reasons(
            cell_bbox(cell),
            processed_width=processed_width,
            processed_height=processed_height,
            tolerance=tolerance,
            prefix="cell_bbox",
        )
        if bbox_reasons:
            bad_cell_count += 1
        checked_cell_count += 1
    if bad_cell_count:
        rejection_reasons.append("cell_bbox_out_of_bounds")
        if bad_cell_count >= max(1, math.ceil(checked_cell_count * 0.10)):
            rejection_reasons.append("coordinate_space_violation")

    if row_count <= 0 or column_count <= 0 or cell_count <= 0:
        rejection_reasons.append("empty_or_dead_region")
    if row_count < 2:
        warnings.append("row_count_too_small")
    if column_count < 3:
        warnings.append("column_count_too_small")
    if column_count > 30:
        warnings.append("column_count_unusually_large")

    if item_rows == 0:
        if all_unknown_columns:
            rejection_reasons.append("zero_item_rows_all_unknown_columns")
        elif semantic_gaps >= 4:
            rejection_reasons.append("zero_item_rows_high_semantic_gaps")
        else:
            warnings.append("zero_item_rows")

    if score is not None and score <= CATASTROPHIC_TSR_SCORE:
        rejection_reasons.append("catastrophic_tsr_score")

    if ocr_block_count == 0:
        rejection_reasons.append("no_ocr_blocks")

    sane_score = 0.0
    sane_score += min(row_count, 20) * 2.0
    sane_score += min(column_count, 15) * 3.0
    sane_score += min(item_rows, 20) * 8.0
    sane_score += min(pharma_header_hits, 8) * 5.0
    sane_score -= semantic_gaps * 4.0
    sane_score -= bad_cell_count * 2.0
    if score is not None:
        sane_score += max(-40.0, min(40.0, float(score) / 5.0))
    sane_score = round(sane_score, 3)

    rejection_reasons = _dedupe(rejection_reasons)
    valid = not rejection_reasons
    return {
        "table_id": table_id,
        "valid": valid,
        "table_sanity_score": sane_score,
        "rejection_reasons": rejection_reasons,
        "warnings": _dedupe(warnings),
        "bbox": bbox,
        "processed_bounds": [0, 0, processed_width, processed_height]
        if processed_width and processed_height
        else None,
        "row_count": row_count,
        "column_count": column_count,
        "cell_count": cell_count,
        "item_rows": item_rows,
        "semantic_gaps": semantic_gaps,
        "all_unknown_columns": all_unknown_columns,
        "pharma_header_hits": pharma_header_hits,
        "cell_bbox_out_of_bounds_count": bad_cell_count,
        "checked_cell_count": checked_cell_count,
        "candidate_score": score,
    }


def select_valid_table_candidate(
    candidates: Iterable[Tuple[str, Any, Optional[float], Optional[Dict[str, Any]]]],
    *,
    processed_width: Optional[float] = None,
    processed_height: Optional[float] = None,
    ocr_block_count: Optional[int] = None,
) -> Dict[str, Any]:
    evaluated = []
    for source, table, score, metrics in candidates:
        if table is None:
            continue
        sanity = evaluate_table_candidate_sanity(
            table,
            processed_width=processed_width,
            processed_height=processed_height,
            candidate_score=score,
            candidate_metrics=metrics,
            ocr_block_count=ocr_block_count,
        )
        sanity["source"] = source
        evaluated.append(sanity)

    valid = [entry for entry in evaluated if entry["valid"]]
    selected = max(
        valid,
        key=lambda item: (
            item["table_sanity_score"],
            item["item_rows"],
            item["column_count"],
            item["row_count"],
        ),
        default=None,
    )
    return {
        "selected_table_available": selected is not None,
        "selected_candidate_id": selected.get("table_id") if selected else None,
        "selected_source": selected.get("source") if selected else None,
        "selected_reason": (
            "valid_candidate_highest_table_sanity"
            if selected
            else "no_valid_candidate"
        ),
        "per_candidate": evaluated,
        "rejected_candidates": [
            {
                "table_id": entry["table_id"],
                "source": entry.get("source"),
                "rejection_reasons": entry["rejection_reasons"],
                "table_sanity_score": entry["table_sanity_score"],
            }
            for entry in evaluated
            if not entry["valid"]
        ],
    }


def _geometry_rejection_reasons(
    bbox: Optional[List[float]],
    *,
    processed_width: Optional[float],
    processed_height: Optional[float],
    tolerance: float,
    prefix: str,
) -> List[str]:
    if not bbox:
        return ["invalid_geometry"]
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        return ["invalid_geometry"]
    reasons = []
    if processed_width and processed_height and max(abs(v) for v in bbox) > 1.0:
        if x1 < -tolerance or y1 < -tolerance or x2 > processed_width + tolerance or y2 > processed_height + tolerance:
            reasons.append(f"{prefix}_out_of_bounds")
            reasons.append("coordinate_space_violation")
    return reasons


def _bbox_from_explicit(value: Any) -> Optional[List[float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        values = [_safe_float(item) for item in value[:4]]
        if all(item is not None for item in values):
            return [float(item) for item in values]
    return None


def _bbox_from_geometry(geom: Any) -> Optional[List[float]]:
    if geom is None:
        return None
    values = [
        _read_attr(geom, "min_x", None),
        _read_attr(geom, "min_y", None),
        _read_attr(geom, "max_x", None),
        _read_attr(geom, "max_y", None),
    ]
    values = [_safe_float(value) for value in values]
    if all(value is not None for value in values):
        return [float(value) for value in values]
    return None


def _read_attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _item_row_count(rows: List[Any], metrics: Dict[str, Any]) -> int:
    explicit = metrics.get("item_rows_count")
    if explicit is not None:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            pass
    count = 0
    for row in rows:
        if str(_read_attr(row, "row_role", "")).lower() == "item_row":
            count += 1
    if count:
        return count
    ratio = metrics.get("item_row_ratio")
    row_count = metrics.get("row_count") or len(rows)
    try:
        return int(round(float(ratio) * int(row_count))) if ratio is not None else 0
    except (TypeError, ValueError):
        return 0


def _semantic_gaps(table: Any, metrics: Dict[str, Any]) -> int:
    missing = metrics.get("missing_req_cols")
    if isinstance(missing, (list, tuple, set)):
        return len(missing)
    required_missing = _read_attr(table, "required_fields_missing", None)
    if isinstance(required_missing, (list, tuple, set)):
        return len(required_missing)
    return 0


def _all_unknown_columns(table: Any, metrics: Dict[str, Any]) -> bool:
    values = []
    for source in (
        metrics.get("final_column_semantics"),
        metrics.get("semantic_columns"),
        _read_attr(table, "semantic_column_cache", None),
        _read_attr(table, "column_semantics", None),
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if str(key).startswith("_"):
                continue
            if isinstance(value, dict):
                value = value.get("type") or value.get("predicted_type")
            values.append(str(value or "unknown").lower())
    if values:
        return all(value == "unknown" for value in values)
    required_present = _read_attr(table, "required_fields_present", None)
    return not bool(required_present)


def _pharma_header_hits(table: Any) -> int:
    text = " ".join(
        str(_read_attr(cell, "text", "") or "")
        for cell in (_read_attr(table, "cells", []) or [])
    )
    return len(set(match.group(1).upper() for match in PHARMA_HEADER_RE.finditer(text)))


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
