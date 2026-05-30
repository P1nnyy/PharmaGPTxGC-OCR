import re
from typing import Any, Dict


def _summarize_column_projection_debug(tsr_metadata: Dict[str, Any]) -> Dict[str, Any]:
    column_projection_debug = tsr_metadata.get("column_projection_debug") or {}
    projection_values = list(column_projection_debug.values())
    return {
        "column_projection_debug": column_projection_debug,
        "max_final_column_count": max(
            [int(item.get("final_column_count", 0) or 0) for item in projection_values],
            default=0,
        ),
        "total_hard_limit_merge_count": sum(
            int(item.get("hard_limit_merge_count", 0) or 0) for item in projection_values
        ),
        "max_raw_projected_column_count": max(
            [int(item.get("raw_projected_column_count", 0) or 0) for item in projection_values],
            default=0,
        ),
    }


def _graph_telemetry_block(
    document_graph: Dict[str, Any],
    graph_fallback_used: bool,
    graph_rejection_reason: str,
    graph_fallback_cell_count: int = 0,
    graph_fallback_non_empty_cell_count: int = 0,
    graph_fallback_mapped_token_count: int = 0,
    graph_fallback_empty_cell_ratio: float = 0.0,
    graph_fallback_item_row_count: int = 0,
) -> Dict[str, Any]:
    """Build the canonical graph telemetry dict reused across return paths."""
    dg_metrics = document_graph.get("metrics", {})
    return {
        "graph_candidate_row_count": len(document_graph.get("graph_candidate_rows", [])),
        "graph_candidate_column_count": len(document_graph.get("graph_candidate_columns", [])),
        "graph_confidence": document_graph.get("graph_confidence", 0.0),
        "graph_fallback_used": graph_fallback_used,
        "graph_rejection_reason": graph_rejection_reason,
        "isolated_node_count": dg_metrics.get("isolated_node_count", 0),
        "max_row_cluster_size": dg_metrics.get("max_row_cluster_size", 0),
        "column_band_stability": dg_metrics.get("column_band_stability", 0.0),
        "graph_fallback_cell_count": graph_fallback_cell_count,
        "graph_fallback_non_empty_cell_count": graph_fallback_non_empty_cell_count,
        "graph_fallback_mapped_token_count": graph_fallback_mapped_token_count,
        "graph_fallback_empty_cell_ratio": graph_fallback_empty_cell_ratio,
        "graph_fallback_item_row_count": graph_fallback_item_row_count,
    }


def _box_to_dict(geom) -> Dict[str, Any]:
    if not geom:
        return {
            "x1": None, "y1": None, "x2": None, "y2": None,
            "center_x": None, "center_y": None,
            "width": None, "height": None,
        }
    return {
        "x1": float(geom.min_x),
        "y1": float(geom.min_y),
        "x2": float(geom.max_x),
        "y2": float(geom.max_y),
        "center_x": float(geom.center_x),
        "center_y": float(geom.center_y),
        "width": float(geom.max_x - geom.min_x),
        "height": float(geom.max_y - geom.min_y),
    }


def _token_flags(text: str) -> Dict[str, bool]:
    clean = (text or "").strip()
    compact = re.sub(r"\s+", "", clean.upper())
    return {
        "is_decimal": bool(re.fullmatch(r"[₹$]?\d[\d,]*\.\d+%?", compact)),
        "is_date_like": bool(re.fullmatch(r"\d{1,2}[/-]\d{2,4}", compact)),
        "is_batch_like": bool(re.search(r"[A-Z]\d|\d[A-Z]", compact)),
        "is_hsn_like": bool(re.fullmatch(r"\d{6,8}", compact)),
    }


def _build_topology_debug(ocr_blocks, table_regions, main_tables=None, semantic_results=None, document_graph=None) -> Dict[str, Any]:
    """
    Non-mutating topology inspection artifact for debugging token->row->cell->column failures.
    """
    main_tables = main_tables or []
    semantic_results = semantic_results or {}

    assignment_by_token = {}
    blocks_by_id = {b.id: b for b in ocr_blocks if b.id}

    for table in table_regions:
        for cell in table.cells:
            cell_id = f"{cell.row_id}:{cell.col_id}"
            for token_id in cell.mapped_block_ids:
                assignment_by_token.setdefault(token_id, {
                    "assigned_row_id": cell.row_id,
                    "assigned_cell_id": cell_id,
                    "assigned_col_id": cell.col_id,
                    "assigned_table_id": table.table_id,
                })

    raw_token_graph = []
    for block in ocr_blocks:
        geom = block.normalized_geometry or block.original_geometry
        box = _box_to_dict(geom)
        flags = _token_flags(block.text)
        assignment = assignment_by_token.get(block.id, {})
        raw_token_graph.append({
            "token_id": block.id,
            "text": block.text,
            **box,
            "is_numeric": bool(block.is_numeric),
            **flags,
            "assigned_row_id": assignment.get("assigned_row_id"),
            "assigned_cell_id": assignment.get("assigned_cell_id"),
            "assigned_col_id": assignment.get("assigned_col_id"),
        })

    main_table_ids = {t.table_id for t in main_tables}
    debug_tables = []
    for table in table_regions:
        if main_table_ids and table.table_id not in main_table_ids:
            continue

        cells_by_row = {}
        for cell in table.cells:
            cells_by_row.setdefault(cell.row_id, []).append(cell)

        rows_debug = []
        for row in table.rows:
            row_cells = cells_by_row.get(row.row_id, [])
            token_ids = []
            for cell in row_cells:
                token_ids.extend(cell.mapped_block_ids)
            row_tokens = []
            for token_id in token_ids:
                block = blocks_by_id.get(token_id)
                if not block:
                    continue
                geom = block.normalized_geometry or block.original_geometry
                row_tokens.append({
                    "token_id": token_id,
                    "text": block.text,
                    **_box_to_dict(geom),
                })
            row_tokens.sort(key=lambda t: (
                t["center_y"] if t["center_y"] is not None else 0,
                t["center_x"] if t["center_x"] is not None else 0,
            ))
            rows_debug.append({
                "row_id": row.row_id,
                "row_role": getattr(row, "row_role", "unknown_row"),
                "geometry": _box_to_dict(row.geometry),
                "token_count": len(row_tokens),
                "tokens": row_tokens,
            })

        debug_tables.append({
            "table_id": table.table_id,
            "row_count": len(table.rows),
            "column_count": len(table.columns),
            "rows": rows_debug,
            "current_reconstructed_cells": [
                {
                    "cell_id": f"{cell.row_id}:{cell.col_id}",
                    "row_id": cell.row_id,
                    "col_id": cell.col_id,
                    "text": cell.text,
                    "mapped_block_ids": list(cell.mapped_block_ids),
                    "geometry": _box_to_dict(cell.geometry),
                    "assignment_strategy": cell.assignment_strategy,
                    "assignment_confidence": cell.assignment_confidence,
                    "semantic_outlier": getattr(cell, "semantic_outlier", False),
                    "semantic_outlier_reason": getattr(cell, "semantic_outlier_reason", None),
                }
                for cell in table.cells
            ],
            "current_column_boundaries": [
                {
                    "col_id": col.col_id,
                    "geometry": _box_to_dict(col.geometry),
                }
                for col in table.columns
            ],
            "current_semantic_labels": {
                col_id: data.get("type")
                for col_id, data in semantic_results.get(table.table_id, {}).items()
                if isinstance(data, dict) and not col_id.startswith("_")
            },
        })

    return {
        "raw_token_graph": raw_token_graph,
        "document_graph": document_graph or {},
        "main_tables": debug_tables,
    }
