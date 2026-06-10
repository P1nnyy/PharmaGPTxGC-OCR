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


def _extract_cells(table: Any) -> List[Any]:
    """
    Extracts cell list from table checking various common schemas (cells, preview_cells, grid, selected_table_grid).
    """
    cells = _read_attr(table, "cells", None)
    if isinstance(cells, (list, tuple, set)) and len(cells) > 0:
        return list(cells)
    
    preview_cells = _read_attr(table, "preview_cells", None)
    if isinstance(preview_cells, (list, tuple, set)) and len(preview_cells) > 0:
        return list(preview_cells)
        
    grid = _read_attr(table, "grid", None)
    if isinstance(grid, (list, tuple)) and len(grid) > 0:
        extracted = []
        for r_idx, row in enumerate(grid):
            if isinstance(row, (list, tuple)):
                for c_idx, val in enumerate(row):
                    extracted.append({"text": val, "row_index": r_idx, "col_index": c_idx})
        if extracted:
            return extracted
            
    selected_grid = _read_attr(table, "selected_table_grid", None)
    if selected_grid is not None:
        if isinstance(selected_grid, (list, tuple)) and len(selected_grid) > 0:
            extracted = []
            for r_idx, row in enumerate(selected_grid):
                if isinstance(row, (list, tuple)):
                    for c_idx, val in enumerate(row):
                        extracted.append({"text": val, "row_index": r_idx, "col_index": c_idx})
            if extracted:
                return extracted
        if isinstance(selected_grid, str):
            extracted = []
            lines = [l for l in selected_grid.splitlines() if l.strip()]
            for r_idx, line in enumerate(lines):
                parts = line.split(",")
                for c_idx, val in enumerate(parts):
                    extracted.append({"text": val.strip(), "row_index": r_idx, "col_index": c_idx})
            if extracted:
                return extracted
                
    return []


def _extract_row_count(table: Any, metrics: Dict[str, Any]) -> int:
    """
    Extracts row count by checking metrics, row length, shape attributes, grid layouts, and CSV grids.
    """
    # 1. Check metrics
    for key in ("row_count", "rows"):
        val = metrics.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass

    # 2. Check table attributes
    rc = _read_attr(table, "row_count", None)
    if rc is not None:
        try:
            return int(rc)
        except (TypeError, ValueError):
            pass

    # Check shape attribute
    shape = _read_attr(table, "shape", None)
    if shape is not None:
        if isinstance(shape, dict):
            for k in ("rows", "row_count", "row", "r"):
                if shape.get(k) is not None:
                    try:
                        return int(shape[k])
                    except (TypeError, ValueError):
                        pass
        elif isinstance(shape, (list, tuple)) and len(shape) >= 2:
            try:
                return int(shape[0])
            except (TypeError, ValueError):
                pass

    # Check rows list/attribute
    rows = _read_attr(table, "rows", None)
    if rows is not None:
        if isinstance(rows, (list, tuple, set)):
            return len(rows)
        try:
            return int(rows)
        except (TypeError, ValueError):
            pass

    # Check reconstructed_rows
    recon_rows = _read_attr(table, "reconstructed_rows", None)
    if isinstance(recon_rows, (list, tuple)):
        return len(recon_rows)

    # Check grid
    grid = _read_attr(table, "grid", None)
    if isinstance(grid, (list, tuple)):
        return len(grid)

    # Check selected_table_grid
    selected_grid = _read_attr(table, "selected_table_grid", None)
    if selected_grid is not None:
        if isinstance(selected_grid, (list, tuple)):
            return len(selected_grid)
        if isinstance(selected_grid, str):
            lines = [l for l in selected_grid.splitlines() if l.strip()]
            if lines:
                return len(lines)

    return 0


def _extract_column_count(table: Any, metrics: Dict[str, Any]) -> int:
    """
    Extracts column count by checking metrics, columns length, shape attributes, grid layouts, and CSV grids.
    """
    # 1. Check metrics
    for key in ("column_count", "col_count", "columns", "cols"):
        val = metrics.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass

    # 2. Check table attributes
    for key in ("column_count", "cols", "col_count"):
        cc = _read_attr(table, key, None)
        if cc is not None:
            try:
                return int(cc)
            except (TypeError, ValueError):
                pass

    # Check shape attribute
    shape = _read_attr(table, "shape", None)
    if shape is not None:
        if isinstance(shape, dict):
            for k in ("columns", "column_count", "cols", "col_count", "col", "c"):
                if shape.get(k) is not None:
                    try:
                        return int(shape[k])
                    except (TypeError, ValueError):
                        pass
        elif isinstance(shape, (list, tuple)) and len(shape) >= 2:
            try:
                return int(shape[1])
            except (TypeError, ValueError):
                pass

    # Check columns list/attribute
    columns = _read_attr(table, "columns", None)
    if columns is not None:
        if isinstance(columns, (list, tuple, set)):
            return len(columns)
        try:
            return int(columns)
        except (TypeError, ValueError):
            pass

    # Check grid
    grid = _read_attr(table, "grid", None)
    if isinstance(grid, (list, tuple)) and len(grid) > 0:
        first_row = grid[0]
        if isinstance(first_row, (list, tuple)):
            return len(first_row)

    # Check selected_table_grid
    selected_grid = _read_attr(table, "selected_table_grid", None)
    if selected_grid is not None:
        if isinstance(selected_grid, (list, tuple)) and len(selected_grid) > 0:
            first_row = selected_grid[0]
            if isinstance(first_row, (list, tuple)):
                return len(first_row)
        if isinstance(selected_grid, str):
            lines = [l for l in selected_grid.splitlines() if l.strip()]
            if lines:
                parts = lines[0].split(",")
                return len(parts)

    return 0


def _extract_cell_count(table: Any, row_count: int, column_count: int) -> int:
    """
    Extracts cell count by checking list lengths or grid layouts, defaulting to row_count * col_count.
    """
    # Check cells
    cells = _read_attr(table, "cells", None)
    if isinstance(cells, (list, tuple, set)):
        return len(cells)
    
    # Check preview_cells
    preview_cells = _read_attr(table, "preview_cells", None)
    if isinstance(preview_cells, (list, tuple, set)):
        return len(preview_cells)
        
    # Check grid
    grid = _read_attr(table, "grid", None)
    if isinstance(grid, (list, tuple)):
        count = sum(len(r) for r in grid if isinstance(r, (list, tuple)))
        if count > 0:
            return count

    # Check selected_table_grid
    selected_grid = _read_attr(table, "selected_table_grid", None)
    if selected_grid is not None:
        if isinstance(selected_grid, (list, tuple)):
            count = sum(len(r) for r in selected_grid if isinstance(r, (list, tuple)))
            if count > 0:
                return count
        if isinstance(selected_grid, str):
            lines = [l for l in selected_grid.splitlines() if l.strip()]
            count = sum(len(l.split(",")) for l in lines)
            if count > 0:
                return count

    if row_count > 0 and column_count > 0:
        return row_count * column_count
    return 0


def _extract_item_rows(table: Any, rows: List[Any], row_count: int, metrics: Dict[str, Any]) -> int:
    """
    Extracts clean item row count by checking metrics flags, role counts, or ratio parameters.
    """
    for key in ("item_rows_count", "item_rows", "item_row_count"):
        val = metrics.get(key)
        if val is not None:
            if isinstance(val, (list, tuple, set)):
                return len(val)
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
                
    for key in ("item_rows_count", "item_rows", "item_row_count", "item_rows_clean"):
        val = _read_attr(table, key, None)
        if val is not None:
            if isinstance(val, (list, tuple, set)):
                return len(val)
            try:
                return int(val)
            except (TypeError, ValueError):
                pass

    if rows:
        count = sum(1 for r in rows if str(_read_attr(r, "row_role", "")).lower() == "item_row")
        if count > 0:
            return count

    ratio = metrics.get("item_row_ratio")
    if ratio is not None:
        try:
            return int(round(float(ratio) * row_count))
        except (TypeError, ValueError):
            pass
            
    return 0


def table_bbox(table: Any) -> Optional[List[float]]:
    # 1. Check direct bounding box values
    for key in ("bbox", "normalized_bbox"):
        b = _read_attr(table, key, None)
        bbox = _bbox_from_explicit(b)
        if bbox:
            return bbox

    # 2. Check geometry fields
    geom = _read_attr(table, "geometry", None) or _read_attr(table, "normalized_geometry", None)
    bbox = _bbox_from_geometry(geom)
    if bbox:
        return bbox

    # 3. Check cells geometry bounding boxes union fallback
    extracted_cells = _extract_cells(table)
    cell_bboxes = [
        bbox
        for bbox in (cell_bbox(cell) for cell in extracted_cells)
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


def _clip_cell_bbox(cell: Any, width: float, height: float) -> None:
    """
    Clips cell coordinates to the processed image boundaries to recover salvageable layouts.
    """
    for key in ("bbox", "absolute_bbox"):
        val = _read_attr(cell, key, None)
        if isinstance(val, (list, tuple)) and len(val) >= 4:
            clipped = [
                max(0.0, min(float(val[0]), width)),
                max(0.0, min(float(val[1]), height)),
                max(0.0, min(float(val[2]), width)),
                max(0.0, min(float(val[3]), height))
            ]
            if isinstance(cell, dict):
                cell[key] = clipped
            else:
                try:
                    setattr(cell, key, clipped)
                except Exception:
                    pass

    for key in ("geometry", "normalized_geometry"):
        geom = _read_attr(cell, key, None)
        if geom is not None:
            if isinstance(geom, dict):
                geom["min_x"] = max(0.0, min(float(geom.get("min_x", 0.0)), width))
                geom["min_y"] = max(0.0, min(float(geom.get("min_y", 0.0)), height))
                geom["max_x"] = max(0.0, min(float(geom.get("max_x", width)), width))
                geom["max_y"] = max(0.0, min(float(geom.get("max_y", height)), height))
            else:
                try:
                    geom.min_x = max(0.0, min(float(getattr(geom, "min_x", 0.0)), width))
                    geom.min_y = max(0.0, min(float(getattr(geom, "min_y", 0.0)), height))
                    geom.max_x = max(0.0, min(float(getattr(geom, "max_x", width)), width))
                    geom.max_y = max(0.0, min(float(getattr(geom, "max_y", height)), height))
                except Exception:
                    pass


def evaluate_table_candidate_sanity(
    table: Any,
    *,
    processed_width: Optional[float] = None,
    processed_height: Optional[float] = None,
    candidate_score: Optional[float] = None,
    candidate_metrics: Optional[Dict[str, Any]] = None,
    ocr_block_count: Optional[int] = None,
    tolerance: float = GEOMETRY_TOLERANCE,
    allow_salvage: bool = False,
) -> Dict[str, Any]:
    metrics = candidate_metrics if isinstance(candidate_metrics, dict) else {}
    rejection_reasons: List[str] = []
    warnings: List[str] = []

    table_id = str(_read_attr(table, "table_id", "") or "unknown")
    
    # Robust layout cell and layout element extraction
    extracted_cells = _extract_cells(table)
    rows = list(_read_attr(table, "rows", []) or [])
    columns = list(_read_attr(table, "columns", []) or [])
    
    # Schema-aware size evaluation
    row_count = _extract_row_count(table, metrics)
    column_count = _extract_column_count(table, metrics)
    cell_count = _extract_cell_count(table, row_count, column_count)
    item_rows = _extract_item_rows(table, rows, row_count, metrics)
    
    semantic_gaps = _semantic_gaps(table, metrics)
    all_unknown_columns = _all_unknown_columns(table, metrics)
    pharma_header_hits = _pharma_header_hits(table, extracted_cells)
    
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
    for cell in extracted_cells:
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

    # Check for salvageable candidates with repairable cell bounding box overflow
    geometry_repaired = False
    repairable_rejections = []
    is_salvageable = False
    rejection_set = set(rejection_reasons)

    # Salvage condition: must only have cell_bbox_out_of_bounds in rejection reasons
    # and satisfy item row count, header keywords hits, and non-empty size/resolution limits
    if not valid and rejection_set == {"cell_bbox_out_of_bounds"}:
        if (
            item_rows >= 2
            and pharma_header_hits >= 3
            and not all_unknown_columns
            and processed_width is not None
            and processed_height is not None
        ):
            is_salvageable = True

    if is_salvageable and allow_salvage:
        # Perform clipping of cell bounding box geometries
        for cell in extracted_cells:
            _clip_cell_bbox(cell, processed_width, processed_height)
        geometry_repaired = True
        repairable_rejections = ["cell_bbox_out_of_bounds"]
        rejection_reasons = []
        valid = True

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
        "geometry_repaired": geometry_repaired,
        "salvageable": is_salvageable,
        "repairable_rejections": repairable_rejections,
    }


def select_valid_table_candidate(
    candidates: Iterable[Tuple[str, Any, Optional[float], Optional[Dict[str, Any]]]],
    *,
    processed_width: Optional[float] = None,
    processed_height: Optional[float] = None,
    ocr_block_count: Optional[int] = None,
    allow_salvage: bool = False,
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
            allow_salvage=allow_salvage,
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


def _semantic_gaps(table: Any, metrics: Dict[str, Any]) -> int:
    missing = metrics.get("missing_req_cols")
    if isinstance(missing, (list, tuple, set)):
        return len(missing)
    required_missing = _read_attr(table, "required_fields_missing", None)
    if isinstance(required_missing, (list, tuple, set)):
        return len(required_missing)
    return 0


def _all_unknown_columns(table: Any, metrics: Dict[str, Any]) -> bool:
    table_id = str(_read_attr(table, "table_id", "") or "unknown")
    values = []
    
    sources = [
        metrics.get("final_column_semantics"),
        metrics.get("semantic_columns"),
        _read_attr(table, "semantic_column_cache", None),
        _read_attr(table, "column_semantics", None),
    ]
    
    for source in sources:
        if not isinstance(source, dict):
            continue
            
        if table_id in source and isinstance(source[table_id], dict):
            dict_to_check = source[table_id]
        else:
            dict_to_check = source
            
        for key, value in dict_to_check.items():
            if isinstance(value, dict) and any(k in ("type", "predicted_type", "header_text") for k in value.keys()):
                pass
            elif isinstance(value, dict):
                if str(key) != table_id:
                    continue
                for sub_k, sub_v in value.items():
                    if str(sub_k).startswith("_"):
                        continue
                    if isinstance(sub_v, dict):
                        sub_v = sub_v.get("type") or sub_v.get("predicted_type")
                    values.append(str(sub_v or "unknown").lower())
                continue
                
            if str(key).startswith("_"):
                continue
            if isinstance(value, dict):
                value = value.get("type") or value.get("predicted_type")
            values.append(str(value or "unknown").lower())
            
    if values:
        return all(value == "unknown" for value in values)
        
    required_present = _read_attr(table, "required_fields_present", None)
    return not bool(required_present)


def _pharma_header_hits(table: Any, extracted_cells: List[Any]) -> int:
    text = " ".join(
        str(_read_attr(cell, "text", "") or "")
        for cell in extracted_cells
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
