from typing import List, Dict, Any
from core.logger import logger
from core.config import settings

from services.layout_pipeline.geometry import process_blocks
from services.layout_pipeline.skew import apply_skew_normalization
from services.layout_pipeline.ioa_mapping import map_tokens_to_cells
from services.layout_pipeline.semantic_column_classifier import SemanticColumnClassifier
from services.layout_pipeline.stability_engine import TopologyStabilityEngine
from services.layout_pipeline.row_validator import RowValidator
from services.layout_pipeline.multiline_merging import merge_multiline_table_rows, update_row_stability_scores
from services.layout_pipeline.confidence import ConfidenceCompositor
from services.layout_pipeline.row_roles import classify_row_roles
from services.layout_pipeline.column_anchor_detector import detect_column_anchors, repair_undersegmented_table_with_anchors
from services.layout_pipeline.column_band_rescue import build_column_band_rescue_candidate
from services.topology.column_stabilizer import ColumnStabilizer
from services.financial_reconciler import FinancialReconciler, reconcile_invoice_financials
from services.table_classifier import TableClassifier, route_tables, TableType

from services.tsr.heuristic_tsr import HeuristicTSREngine
from services.tsr.future_tatr import TATR_TSREngine
from services.tsr.future_ppstructure import PPStructure_TSREngine

def get_engine(mode: str):
    if mode == "tatr":
        return TATR_TSREngine()
    elif mode == "ppstructure":
        return PPStructure_TSREngine()
    else:
        return HeuristicTSREngine()

def _compute_tsr_confidence(table_regions) -> float:
    """
    Evaluate aggregate TSR output quality to decide if PPStructure topology is trustworthy.
    Returns 0.0-1.0 confidence score.

    Signals checked:
    - At least one table detected
    - Tables have reasonable cell counts
    - topology_confidence values from the engine are acceptable
    """
    if not table_regions:
        return 0.0

    confidences = [tr.topology_confidence for tr in table_regions]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    # Check for degenerate tables (tables with zero cells)
    total_cells = sum(len(tr.cells) for tr in table_regions)
    if total_cells == 0:
        return 0.0

    # A single table with very few cells on a full invoice is suspicious
    if len(table_regions) == 1 and total_cells < 3:
        avg_confidence *= 0.5

    return round(avg_confidence, 3)


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

def _dominance_score_confidence(score: float) -> float:
    return max(0.0, min(0.99, (float(score) + 200.0) / 700.0))

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
    import re
    clean = (text or "").strip()
    compact = re.sub(r"\s+", "", clean.upper())
    return {
        "is_decimal": bool(re.fullmatch(r"[₹$]?\d[\d,]*\.\d+%?", compact)),
        "is_date_like": bool(re.fullmatch(r"\d{1,2}[/-]\d{2,4}", compact)),
        "is_batch_like": bool(re.search(r"[A-Z]\d|\d[A-Z]", compact)),
        "is_hsn_like": bool(re.fullmatch(r"\d{6,8}", compact)),
    }

def _build_topology_debug(ocr_blocks, table_regions, main_tables=None, semantic_results=None) -> Dict[str, Any]:
    """
    Non-mutating topology inspection artifact for debugging token→row→cell→column failures.
    """
    import re
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
        "main_tables": debug_tables,
    }

def reconstruct_layout(blocks: List[Dict[str, Any]], debug: bool = False, reconstruct_mode: str = "ppstructure", image: Any = None, benchmark_mode: bool = False) -> Dict[str, Any]:
    """
    Entry point for document-layout reasoning engine.
    Orchestrates OCR geometry preservation, TSR grid detection, and Cell Mapping.

    benchmark_mode: When True, disables expensive debug artifacts, enables fast-fail
    on hopeless invoices, and minimizes intermediate dumps to maximize VM throughput.
    """
    logger.info(f"Starting spatial reconstruction on {len(blocks)} blocks (Mode={reconstruct_mode}, Debug={debug}, Benchmark={benchmark_mode})")

    # Ensure blocks have IDs for mapping provenance
    for i, b in enumerate(blocks):
        if "id" not in b:
            b["id"] = f"block_{i}"

    # Step 1: Compute geometry
    ocr_blocks = process_blocks(blocks)

    # --- Diagnostic: Raw OCR & Coordinate Ordering Dumps ---
    import os
    import json
    import re
    debug_dir = "datasets/debug"
    os.makedirs(debug_dir, exist_ok=True)

    # In benchmark mode, skip expensive intermediate debug dumps to save VM time
    if debug and not benchmark_mode:
        # 1. Dump absolutely raw API blocks
        with open(os.path.join(debug_dir, "raw_ocr.json"), "w", encoding="utf-8") as f:
            json.dump(blocks, f, indent=2)

        # 2. Dump plain reading order sorted text without layout heuristics
        def _coord_sort_key(b):
            geom = b.original_geometry or b.normalized_geometry
            if not geom:
                return (0, 0)
            return (round(geom.min_y / 10), geom.min_x)

        sorted_blocks = sorted(ocr_blocks, key=_coord_sort_key)
        coord_lines = []
        current_baseline = None
        line_tokens = []

        for b in sorted_blocks:
            geom = b.original_geometry or b.normalized_geometry
            baseline = round(geom.min_y / 10) if geom else 0
            if current_baseline is not None and abs(baseline - current_baseline) > 1:
                coord_lines.append(" ".join(line_tokens))
                line_tokens = []
            current_baseline = baseline
            line_tokens.append(b.text)
        if line_tokens:
            coord_lines.append(" ".join(line_tokens))

        with open(os.path.join(debug_dir, "raw_coordinate_order.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(coord_lines))

    # Step 2: Skew Normalization
    ocr_blocks = apply_skew_normalization(ocr_blocks)

    # Step 3: TSR Table Region Detection with Confidence-Gated Fallback
    table_regions = []
    tsr_metadata = {}
    ppstructure_enabled = bool(
        settings.ENABLE_PPSTRUCTURE
        or str(settings.TSR_PRIMARY_ENGINE).lower() == "ppstructure"
    )
    ppstructure_threshold = float(settings.PPSTRUCTURE_CONFIDENCE_THRESHOLD)
    topology_source = "ppstructure" if ppstructure_enabled else "heuristic_anchor"
    heuristic_fallback_used = False
    ppstructure_regions_attempted = 0
    ppstructure_cells_attempted = 0
    tsr_status_metric = {
        "ppstructure_enabled": ppstructure_enabled,
        "ppstructure_skipped_reason": None,
        "fallback_used": False,
    }

    if reconstruct_mode == "compare":
        logger.info("Running in compare mode. Executing multiple engines.")
        heuristic_engine = HeuristicTSREngine()
        heuristic_regions, heuristic_metadata = heuristic_engine.detect_tables(ocr_blocks)
        if ppstructure_enabled:
            pp_engine = PPStructure_TSREngine()
            pp_regions, tsr_metadata = pp_engine.detect_tables(ocr_blocks, image=image, debug=(debug and not benchmark_mode))
            ppstructure_regions_attempted = len(pp_regions)
            ppstructure_cells_attempted = sum(len(tr.cells) for tr in pp_regions)
            logger.info(f"[COMPARE] PP-Structure detected {len(pp_regions)} tables.")
            table_regions = pp_regions
        else:
            logger.info("[PPSTRUCTURE] Skipped compare-mode PPStructure pass: disabled_by_config")
            table_regions = heuristic_regions
            topology_source = "heuristic_anchor"
            heuristic_fallback_used = True
            tsr_metadata = {
                **heuristic_metadata,
                "tsr_engine": "heuristic_anchor",
                "tsr_disabled_reason": "disabled_by_config",
            }
            tsr_status_metric["ppstructure_skipped_reason"] = "disabled_by_config"
            tsr_status_metric["fallback_used"] = True
            for tr in table_regions:
                tr.topology_confidence = 0.5
        logger.info(f"[COMPARE] Heuristic detected {len(heuristic_regions)} tables.")
    elif reconstruct_mode == "heuristic" or not ppstructure_enabled:
        # Explicit heuristic mode (debug only)
        if not ppstructure_enabled:
            logger.info("[PPSTRUCTURE] Skipped PPStructure: disabled_by_config")
            tsr_status_metric["ppstructure_skipped_reason"] = "disabled_by_config"
            tsr_status_metric["fallback_used"] = True
            heuristic_fallback_used = True
        engine = HeuristicTSREngine()
        table_regions, tsr_metadata = engine.detect_tables(ocr_blocks)
        topology_source = "heuristic_anchor" if not ppstructure_enabled else "heuristic"
        for tr in table_regions:
            tr.topology_confidence = 0.5  # Degraded confidence for heuristic-derived topology
    else:
        # PRIMARY PATH: PPStructure with confidence-gated fallback
        pp_engine = PPStructure_TSREngine()
        table_regions, tsr_metadata = pp_engine.detect_tables(ocr_blocks, image=image, debug=(debug and not benchmark_mode))
        ppstructure_regions_attempted = len(table_regions)
        ppstructure_cells_attempted = sum(len(tr.cells) for tr in table_regions)

        # --- CONFIDENCE GATE ---
        # Evaluate TSR output quality. If PPStructure fails or produces unreliable topology,
        # fall back to heuristic engine rather than proceeding with garbage structure.
        tsr_confidence = _compute_tsr_confidence(table_regions)
        tsr_status_metric["ppstructure_confidence"] = tsr_confidence
        tsr_status_metric["confidence_threshold"] = ppstructure_threshold

        if ppstructure_regions_attempted == 0 and ppstructure_cells_attempted == 0:
            logger.warning("[PPSTRUCTURE] tables=0 cells=0; falling back to heuristic topology.")

        if tsr_confidence < ppstructure_threshold:
            logger.warning(
                f"[CONFIDENCE GATE] TSR confidence {tsr_confidence:.2f} below threshold ({ppstructure_threshold:.2f}). "
                f"Falling back to heuristic topology."
            )
            heuristic_engine = HeuristicTSREngine()
            table_regions, heuristic_metadata = heuristic_engine.detect_tables(ocr_blocks)
            tsr_metadata.update(heuristic_metadata)
            topology_source = "heuristic_fallback"
            heuristic_fallback_used = True
            tsr_status_metric["fallback_used"] = True
            for tr in table_regions:
                tr.topology_confidence = 0.5  # Degraded confidence tag

    canonical_cell_count = sum(len(tr.cells) for tr in table_regions)
    tsr_contribution_percent = 100.0 if topology_source == "ppstructure" and canonical_cell_count else 0.0
    tsr_metadata.update({
        **_summarize_column_projection_debug(tsr_metadata),
        "ppstructure_regions_attempted": ppstructure_regions_attempted,
        "ppstructure_cells_attempted": ppstructure_cells_attempted,
        "canonical_region_count": len(table_regions),
        "canonical_cell_count": canonical_cell_count,
        "tsr_contribution_percent": tsr_contribution_percent,
        "heuristic_fallback_used": heuristic_fallback_used,
        "heuristic_fallback_count": 1 if heuristic_fallback_used else 0,
        "ppstructure_enabled": ppstructure_enabled,
        "ppstructure_multi_orientation_enabled": bool(settings.ENABLE_PPSTRUCTURE_MULTI_ORIENTATION),
        "ppstructure_confidence_threshold": ppstructure_threshold,
    })

    # --- FAST-FAIL: No topology at all (both engines failed) ---
    if not table_regions:
        logger.warning("[FAST FAIL] Zero table regions from selected topology path.")
        topology_debug = _build_topology_debug(ocr_blocks, [], [], {})
        return {
            "reconstructed_rows": [],
            "detected_table_rows": [],
            "columns_extracted": False,
            "structured_tables": [],
            "semantic_markdown": "",
            "fast_fail": True,
            "fast_fail_reason": "zero_tables",
            "topology_source": topology_source,
            "metrics": {
                "raw_token_count": len(ocr_blocks),
                "table_count": 0,
                "topology_debug": topology_debug,
                "column_anchor_debug": {},
                "instrumentation": {
                    "tsr_contribution_percent": tsr_contribution_percent,
                    "heuristic_fallback_used": heuristic_fallback_used,
                    "heuristic_fallback_count": 1 if heuristic_fallback_used else 0,
                    "semantic_rejection_count": 0,
                    "confidence_variance": {
                        "table_confidence_variance": 0.0,
                        "row_confidence_variance": 0.0
                    },
                },
                "fast_fail": True,
                **tsr_metadata,
                "tsr_status": tsr_status_metric
            }
        }

    tsr_metadata["topology_source"] = topology_source

    # Step 4: PRE-ASSIGNMENT Geometry Stabilization (geometry-only, no text dependency)
    stabilizer = ColumnStabilizer()
    repair_metrics_total = {"phantom_column_count": 0, "repaired_columns": 0, "semantic_column_drift": 0}
    for tr in table_regions:
        rep = stabilizer.stabilize_region(tr)
        for k, v in rep.items():
            repair_metrics_total[k] += v

    # Step 5: Cell Mapping (IoA) — runs AFTER geometry stabilization
    map_tokens_to_cells(ocr_blocks, table_regions, debug=(debug and not benchmark_mode))

    # ── NEW: HIERARCHICAL ROW GRAPH STAGE ──
    # Before applying destruction, snapshot Visual Row definitions for debug rendering
    visual_rows_snapshot = []
    for tr in table_regions:
        for r in tr.rows:
             visual_rows_snapshot.append({
                 "row_id": r.row_id,
                 "geometry": r.geometry.model_copy() if r.geometry else None
             })

    merge_audit_full = []
    for tr in table_regions:
        tr, audit = merge_multiline_table_rows(tr, ocr_blocks)
        tr = update_row_stability_scores(tr, ocr_blocks)
        merge_audit_full.extend(audit)

    logger.info(f"[HIERARCHY] Consolidated multiline rows. Audited decisions: {len(merge_audit_full)}")

    # ── Step 5.5: TABLE CLASSIFICATION & ROUTING (Failure Mode 4) ──
    classifier_engine = TableClassifier()
    classifications = classifier_engine.classify_region_list(table_regions)
    table_routing_diagnostics = getattr(classifier_engine, "last_routing_diagnostics", {})
    table_bundle = route_tables(table_regions, classifications, diagnostics=table_routing_diagnostics)

    ignored_tables_count = len(table_regions) - (1 if table_bundle.main_table else 0)

    logger.info(
        f"Detected {len(table_regions)} tables. "
        f"Chosen main table: {table_bundle.main_table.table_id if table_bundle.main_table else 'None'}. "
        f"Ignored tables: {ignored_tables_count}"
    )

    if not table_bundle.main_table:
        raise ValueError("Failed to isolate a dominant main invoice table.")

    # Step 6: Semantic & Mathematical Stability Audits (ACTIVE SIGNAL GENERATION)
    # ONLY perform downstream extraction / stability processing on Dominant Main Table to avoid contamination!
    analysis_targets = [table_bundle.main_table]

    row_role_metrics = {
        "item_rows_count": 0,
        "header_rows_count": 0,
        "footer_rows_count": 0,
        "tax_rows_count": 0,
        "metadata_rows_count": 0,
        "unknown_rows_count": 0,
        "by_table": {},
    }
    for tr in analysis_targets:
        table_role_metrics = classify_row_roles(tr)
        row_role_metrics["by_table"][tr.table_id] = table_role_metrics
        for key in (
            "item_rows_count",
            "header_rows_count",
            "footer_rows_count",
            "tax_rows_count",
            "metadata_rows_count",
            "unknown_rows_count",
        ):
            row_role_metrics[key] += table_role_metrics.get(key, 0)

    column_band_rescue_candidate, column_band_rescue_metrics = build_column_band_rescue_candidate(
        ocr_blocks=ocr_blocks,
        table_regions=table_regions,
        selected_main_table=table_bundle.main_table,
        selected_main_item_rows_count=row_role_metrics["item_rows_count"],
        max_final_column_count=int(tsr_metadata.get("max_final_column_count", 0) or 0),
    )
    if column_band_rescue_candidate is not None:
        candidate_score_details = classifier_engine.score_region_for_main_table(column_band_rescue_candidate)
        current_score_details = classifier_engine.score_region_for_main_table(table_bundle.main_table)
        candidate_score = float(candidate_score_details.get("score", 0.0))
        current_score = float(current_score_details.get("score", 0.0))
        current_confidence = _dominance_score_confidence(current_score)
        candidate_confidence = float(column_band_rescue_metrics.get("column_band_rescue_confidence", 0.0) or 0.0)

        column_band_rescue_metrics["column_band_rescue_candidate_score"] = round(candidate_score, 3)
        column_band_rescue_metrics["column_band_rescue_current_main_score"] = round(current_score, 3)
        column_band_rescue_metrics["column_band_rescue_current_main_confidence"] = round(current_confidence, 3)

        if candidate_score > current_score and candidate_confidence > current_confidence:
            table_regions.append(column_band_rescue_candidate)
            classifications = classifier_engine.classify_region_list(table_regions)
            table_routing_diagnostics = getattr(classifier_engine, "last_routing_diagnostics", {})
            table_bundle = route_tables(table_regions, classifications, diagnostics=table_routing_diagnostics)
            if table_bundle.main_table and table_bundle.main_table.table_id == column_band_rescue_candidate.table_id:
                table_bundle.main_table.source_engine = "column_band_rescue"
                column_band_rescue_metrics["column_band_rescue_selected"] = True
                logger.info(
                    "[COLUMN BAND RESCUE] selected rows=%s subtotal_preview=%s confidence=%s",
                    column_band_rescue_metrics.get("column_band_rescued_rows_count"),
                    column_band_rescue_metrics.get("column_band_rescue_item_subtotal_preview"),
                    column_band_rescue_metrics.get("column_band_rescue_confidence"),
                )
            else:
                column_band_rescue_metrics["column_band_rescue_rejected_reason"] = "rescue_candidate_not_selected_by_routing"
        else:
            column_band_rescue_metrics["column_band_rescue_rejected_reason"] = "candidate_did_not_beat_current_main_confidence"

        analysis_targets = [table_bundle.main_table]
        row_role_metrics = {
            "item_rows_count": 0,
            "header_rows_count": 0,
            "footer_rows_count": 0,
            "tax_rows_count": 0,
            "metadata_rows_count": 0,
            "unknown_rows_count": 0,
            "by_table": {},
        }
        for tr in analysis_targets:
            table_role_metrics = classify_row_roles(tr)
            row_role_metrics["by_table"][tr.table_id] = table_role_metrics
            for key in (
                "item_rows_count",
                "header_rows_count",
                "footer_rows_count",
                "tax_rows_count",
                "metadata_rows_count",
                "unknown_rows_count",
            ):
                row_role_metrics[key] += table_role_metrics.get(key, 0)

    tsr_metadata.update(column_band_rescue_metrics)

    column_anchor_debug = {}
    anchor_repair = {
        "enabled": False,
        "repair_attempted": False,
        "reason": "not_evaluated",
        "undersegmentation_trigger_reason": None,
        "missing_semantic_columns_trigger": [],
        "candidate_anchor_count": 0,
        "final_anchor_count": 0,
        "before_column_count": len(table_bundle.main_table.columns),
        "after_column_count": len(table_bundle.main_table.columns),
        "before_avg_cell_text_len": 0.0,
        "after_avg_cell_text_len": 0.0,
        "repaired_row_count": 0,
        "product_col_detected": False,
        "anchor_columns_used": [],
    }
    for tr in analysis_targets:
        column_anchor_debug[tr.table_id] = detect_column_anchors(tr, ocr_blocks)
        anchor_repair = repair_undersegmented_table_with_anchors(
            tr,
            ocr_blocks,
            column_anchor_debug[tr.table_id],
        )
        if anchor_repair.get("enabled"):
            table_role_metrics = classify_row_roles(tr)
            row_role_metrics = {
                "item_rows_count": table_role_metrics.get("item_rows_count", 0),
                "header_rows_count": table_role_metrics.get("header_rows_count", 0),
                "footer_rows_count": table_role_metrics.get("footer_rows_count", 0),
                "tax_rows_count": table_role_metrics.get("tax_rows_count", 0),
                "metadata_rows_count": table_role_metrics.get("metadata_rows_count", 0),
                "unknown_rows_count": table_role_metrics.get("unknown_rows_count", 0),
                "by_table": {tr.table_id: table_role_metrics},
            }
            column_anchor_debug[tr.table_id] = detect_column_anchors(tr, ocr_blocks)

    semantic_results = {}
    classifier = SemanticColumnClassifier()
    semantic_rejection_total = 0
    semantic_outlier_total = 0
    hard_deleted_cells_total = 0
    quarantined_cell_total = 0
    columns_inferred_from_item_rows_only = True
    semantic_column_scores_by_col = {}
    final_column_semantics = {}
    amount_column_candidates = {}
    rejected_amount_candidates = {}
    product_column_candidates = {}
    expiry_column_candidates = {}
    batch_column_candidates = {}
    hsn_column_candidates = {}
    gst_column_candidates = {}
    quantity_column_candidates = {}
    rejected_quantity_candidates = {}
    for tr in analysis_targets:
        semantic_results[tr.table_id] = classifier.enrich_region_metadata(tr)
        rejection_summary = semantic_results[tr.table_id].get("_rejection_summary", {})
        inference_summary = semantic_results[tr.table_id].get("_inference_summary", {})
        semantic_rejection_total += rejection_summary.get("semantic_rejection_count", 0)
        semantic_outlier_total += rejection_summary.get("semantic_outlier_count", 0)
        hard_deleted_cells_total += rejection_summary.get("hard_deleted_cells_count", 0)
        quarantined_cell_total += rejection_summary.get("quarantined_cell_count", 0)
        columns_inferred_from_item_rows_only = (
            columns_inferred_from_item_rows_only
            and inference_summary.get("columns_inferred_from_item_rows_only", False)
        )
        semantic_column_scores_by_col[tr.table_id] = inference_summary.get("semantic_column_scores_by_col", {})
        final_column_semantics[tr.table_id] = inference_summary.get("final_column_semantics", {})
        amount_column_candidates[tr.table_id] = inference_summary.get("amount_column_candidates", [])
        rejected_amount_candidates[tr.table_id] = inference_summary.get("rejected_amount_candidates", [])
        product_column_candidates[tr.table_id] = inference_summary.get("product_column_candidates", [])
        expiry_column_candidates[tr.table_id] = inference_summary.get("expiry_column_candidates", [])
        batch_column_candidates[tr.table_id] = inference_summary.get("batch_column_candidates", [])
        hsn_column_candidates[tr.table_id] = inference_summary.get("hsn_column_candidates", [])
        gst_column_candidates[tr.table_id] = inference_summary.get("gst_column_candidates", [])
        quantity_column_candidates[tr.table_id] = inference_summary.get("quantity_column_candidates", [])
        rejected_quantity_candidates[tr.table_id] = inference_summary.get("rejected_quantity_candidates", [])

    stability_engine = TopologyStabilityEngine()
    stability_metrics = stability_engine.compute_stability(analysis_targets)

    logger.info(f"Topology Confidence Check: Overall Score={stability_metrics.get('overall', 0)}")

    # Step 7: Row-Level Validation (semantic + financial per-row)
    row_validator = RowValidator(semantic_column_cache=semantic_results)
    row_validation_results = row_validator.validate_all(analysis_targets)

    if not anchor_repair.get("enabled"):
        for tr in analysis_targets:
            validation = row_validation_results.get(tr.table_id, {})
            retry_metrics = repair_undersegmented_table_with_anchors(
                tr,
                ocr_blocks,
                column_anchor_debug.get(tr.table_id),
                semantic_context=semantic_results.get(tr.table_id),
                missing_semantic_columns=validation.get("missing_semantic_columns", []),
            )
            if retry_metrics.get("repair_attempted"):
                anchor_repair = retry_metrics
            if retry_metrics.get("enabled"):
                table_role_metrics = classify_row_roles(tr)
                row_role_metrics = {
                    "item_rows_count": table_role_metrics.get("item_rows_count", 0),
                    "header_rows_count": table_role_metrics.get("header_rows_count", 0),
                    "footer_rows_count": table_role_metrics.get("footer_rows_count", 0),
                    "tax_rows_count": table_role_metrics.get("tax_rows_count", 0),
                    "metadata_rows_count": table_role_metrics.get("metadata_rows_count", 0),
                    "unknown_rows_count": table_role_metrics.get("unknown_rows_count", 0),
                    "by_table": {tr.table_id: table_role_metrics},
                }
                column_anchor_debug[tr.table_id] = detect_column_anchors(tr, ocr_blocks)

                semantic_results = {}
                semantic_rejection_total = 0
                semantic_outlier_total = 0
                hard_deleted_cells_total = 0
                quarantined_cell_total = 0
                columns_inferred_from_item_rows_only = True
                semantic_column_scores_by_col = {}
                final_column_semantics = {}
                amount_column_candidates = {}
                rejected_amount_candidates = {}
                product_column_candidates = {}
                expiry_column_candidates = {}
                batch_column_candidates = {}
                hsn_column_candidates = {}
                gst_column_candidates = {}
                quantity_column_candidates = {}
                rejected_quantity_candidates = {}
                for semantic_target in analysis_targets:
                    semantic_results[semantic_target.table_id] = classifier.enrich_region_metadata(semantic_target)
                    rejection_summary = semantic_results[semantic_target.table_id].get("_rejection_summary", {})
                    inference_summary = semantic_results[semantic_target.table_id].get("_inference_summary", {})
                    semantic_rejection_total += rejection_summary.get("semantic_rejection_count", 0)
                    semantic_outlier_total += rejection_summary.get("semantic_outlier_count", 0)
                    hard_deleted_cells_total += rejection_summary.get("hard_deleted_cells_count", 0)
                    quarantined_cell_total += rejection_summary.get("quarantined_cell_count", 0)
                    columns_inferred_from_item_rows_only = (
                        columns_inferred_from_item_rows_only
                        and inference_summary.get("columns_inferred_from_item_rows_only", False)
                    )
                    semantic_column_scores_by_col[semantic_target.table_id] = inference_summary.get("semantic_column_scores_by_col", {})
                    final_column_semantics[semantic_target.table_id] = inference_summary.get("final_column_semantics", {})
                    amount_column_candidates[semantic_target.table_id] = inference_summary.get("amount_column_candidates", [])
                    rejected_amount_candidates[semantic_target.table_id] = inference_summary.get("rejected_amount_candidates", [])
                    product_column_candidates[semantic_target.table_id] = inference_summary.get("product_column_candidates", [])
                    expiry_column_candidates[semantic_target.table_id] = inference_summary.get("expiry_column_candidates", [])
                    batch_column_candidates[semantic_target.table_id] = inference_summary.get("batch_column_candidates", [])
                    hsn_column_candidates[semantic_target.table_id] = inference_summary.get("hsn_column_candidates", [])
                    gst_column_candidates[semantic_target.table_id] = inference_summary.get("gst_column_candidates", [])
                    quantity_column_candidates[semantic_target.table_id] = inference_summary.get("quantity_column_candidates", [])
                    rejected_quantity_candidates[semantic_target.table_id] = inference_summary.get("rejected_quantity_candidates", [])

                row_validator = RowValidator(semantic_column_cache=semantic_results)
                row_validation_results = row_validator.validate_all(analysis_targets)
                break

    # Step 8: Financial Reconciliation (subtotal/grand total verification)
    # Note: We reconcile the MAIN table specifically
    target_reconcile = [table_bundle.main_table]

    reconciler = FinancialReconciler(semantic_column_cache=semantic_results)
    reconciliation_results = reconciler.reconcile_all(target_reconcile)
    main_table_id = table_bundle.main_table.table_id
    footer_reconcile_tables = [
        tr for tr in table_regions
        if tr.table_id != main_table_id
    ]
    invoice_reconciliation_result = reconcile_invoice_financials(
        reconciliation_results.get(main_table_id, {}),
        footer_reconcile_tables,
    )
    logger.info(
        "[INVOICE RECONCILIATION] "
        f"status={invoice_reconciliation_result.get('status')} "
        f"item_subtotal={invoice_reconciliation_result.get('item_derived_subtotal')} "
        f"parsed_subtotal={invoice_reconciliation_result.get('parsed_subtotal')} "
        f"expected_grand_total={invoice_reconciliation_result.get('expected_grand_total')} "
        f"parsed_grand_total={invoice_reconciliation_result.get('parsed_grand_total')} "
        f"match={invoice_reconciliation_result.get('grand_total_match')}"
    )

    # Step 9: Hierarchical Confidence Composition (token→cell→row→table→invoice)
    compositor = ConfidenceCompositor()
    confidence_hierarchy = compositor.compute_full_hierarchy(
        analysis_targets,
        row_validation=row_validation_results,
        reconciliation=reconciliation_results
    )

    logger.info(f"Invoice Confidence: {confidence_hierarchy['invoice_confidence']}")
    logger.info(
        f"[Instrumentation] TSR contribution={tsr_contribution_percent:.1f}% "
        f"heuristic_fallback={heuristic_fallback_used} "
        f"semantic_rejections={semantic_rejection_total} "
        f"semantic_outliers={semantic_outlier_total} "
        f"confidence_variance={confidence_hierarchy.get('confidence_variance', {})}"
    )
    topology_debug = _build_topology_debug(
        ocr_blocks,
        table_regions,
        analysis_targets,
        semantic_results,
    )
    semantic_debug = {
        "semantic_column_scores_by_col": semantic_column_scores_by_col,
        "final_column_semantics": final_column_semantics,
        "amount_column_candidates": amount_column_candidates,
        "rejected_amount_candidates": rejected_amount_candidates,
        "product_column_candidates": product_column_candidates,
        "expiry_column_candidates": expiry_column_candidates,
        "batch_column_candidates": batch_column_candidates,
        "hsn_column_candidates": hsn_column_candidates,
        "gst_column_candidates": gst_column_candidates,
        "quantity_column_candidates": quantity_column_candidates,
        "rejected_quantity_candidates": rejected_quantity_candidates,
        "quarantined_cell_count": quarantined_cell_total,
    }

    # --- FAST-FAIL CHECKPOINT 2: Critically low topology confidence ---
    if benchmark_mode and stability_metrics.get('overall', 100) < 30:
        logger.warning(f"[FAST FAIL] Topology confidence catastrophically low: {stability_metrics.get('overall', 0)}")
        return {
            "reconstructed_rows": [],
            "detected_table_rows": [],
            "columns_extracted": False,
            "structured_tables": [tr.model_dump(mode='json') for tr in table_regions],
            "semantic_markdown": "",
            "fast_fail": True,
            "fast_fail_reason": "critical_instability",
            "topology_source": topology_source,
            "metrics": {
                "raw_token_count": len(ocr_blocks),
                "table_count": len(table_regions),
                "topology_stability": stability_metrics,
                "topology_debug": topology_debug,
                "semantic_debug": semantic_debug,
                **table_routing_diagnostics,
                "column_anchor_debug": column_anchor_debug,
                "anchor_repair": anchor_repair,
                "instrumentation": {
                    "tsr_contribution_percent": tsr_contribution_percent,
                    "heuristic_fallback_used": heuristic_fallback_used,
                    "heuristic_fallback_count": 1 if heuristic_fallback_used else 0,
                    "semantic_rejection_count": semantic_rejection_total,
                    "semantic_outlier_count": semantic_outlier_total,
                    "hard_deleted_cells_count": hard_deleted_cells_total,
                    "quarantined_cell_count": quarantined_cell_total,
                    "columns_inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
                    "item_rows_count": row_role_metrics["item_rows_count"],
                    "footer_rows_count": row_role_metrics["footer_rows_count"],
                    "tax_rows_count": row_role_metrics["tax_rows_count"],
                    "row_role_metrics": row_role_metrics,
                    "confidence_variance": confidence_hierarchy.get("confidence_variance", {}),
                },
                "fast_fail": True,
                **tsr_metadata,
                "tsr_status": tsr_status_metric
            }
        }

    # --- Metrics Logging ---
    total_cells = sum(len(r.cells) for r in table_regions)
    total_rows = sum(len(r.rows) for r in table_regions)
    total_cols = sum(len(r.columns) for r in table_regions)

    mapped_tokens = set()
    empty_cells = 0
    for r in table_regions:
        for c in r.cells:
            mapped_tokens.update(c.mapped_block_ids)
            if not c.mapped_block_ids:
                empty_cells += 1

    orphan_tokens = len(ocr_blocks) - len(mapped_tokens)
    ioa_success_rate = (len(mapped_tokens) / len(ocr_blocks) * 100) if ocr_blocks else 100.0
    empty_cell_ratio = (empty_cells / total_cells * 100) if total_cells else 0.0

    logger.info(f"[Metrics] Detected Table Regions: {len(table_regions)}")
    logger.info(f"[Metrics] Total Rows: {total_rows}")
    logger.info(f"[Metrics] Total Columns: {total_cols}")
    logger.info(f"[Metrics] Total Cells: {total_cells}")
    logger.info(f"[Metrics] Orphan Tokens: {orphan_tokens}")
    logger.info(f"[Metrics] Empty Cell Ratio: {empty_cell_ratio:.1f}%")
    logger.info(f"[Metrics] IoA Success Rate: {ioa_success_rate:.1f}%")

    # --- PPStructure Validation Warnings ---
    for i, tr in enumerate(table_regions):
        t_id = tr.table_id or f"table_{i}"
        if not tr.columns:
            logger.warning(f"[VALIDATION ALERT] Table '{t_id}' detected with ZERO columns!")

        seen_rows = set()
        for r in tr.rows:
            if r.row_id in seen_rows:
                logger.warning(f"[VALIDATION ALERT] Duplicate Row ID detected in table '{t_id}': {r.row_id}")
            seen_rows.add(r.row_id)

        seen_cols = set()
        for c in tr.columns:
            if c.col_id in seen_cols:
                logger.warning(f"[VALIDATION ALERT] Duplicate Column ID detected in table '{t_id}': {c.col_id}")
            seen_cols.add(c.col_id)

    if empty_cell_ratio > 60.0:
        logger.warning(f"[VALIDATION ALERT] High sparsity threshold triggered: {empty_cell_ratio:.1f}% empty cells!")

    # --- Debug Visualization (skipped in benchmark mode to save compute) ---
    if debug and ocr_blocks and not benchmark_mode:
        max_x = max([b.original_geometry.max_x for b in ocr_blocks if b.original_geometry] + [1000])
        max_y = max([b.original_geometry.max_y for b in ocr_blocks if b.original_geometry] + [1000])

        from utils.debug_visualizer import draw_debug_visualization_v2
        draw_debug_visualization_v2(
            ocr_blocks,
            table_regions,
            max_x + 100,
            max_y + 100,
            "datasets/debug/latest_reconstruction.png",
            visual_rows=visual_rows_snapshot,
            merge_audit=merge_audit_full
        )

    # --- Backward Compatibility Shim ---
    # This legacy row format is maintained for downstream serializer compatibility.
    # The canonical output is `structured_tables` (the cell graph).
    legacy_reconstructed_rows = []
    legacy_table_rows = []
    row_counter = 0

    for tr in table_regions:
        for row_region in tr.rows:
            # Find cells for this row
            row_cells = [c for c in tr.cells if c.row_id == row_region.row_id]

            blocks_in_row = []
            columns_dict = {}
            for cell in row_cells:
                for b_id in cell.mapped_block_ids:
                    orig_b = next((b for b in blocks if b["id"] == b_id), None)
                    if orig_b:
                        blocks_in_row.append(orig_b)
                if cell.text:
                    columns_dict[cell.col_id] = cell.text

            legacy_row = {
                "row_index": row_counter,
                "blocks": blocks_in_row,
                "classification": tr.region_type.value,
                "row_role": getattr(row_region, "row_role", "unknown_row"),
                "columns": columns_dict
            }
            legacy_reconstructed_rows.append(legacy_row)
            if tr.region_type.value in ["table", "medicine_table"]:
                legacy_table_rows.append(legacy_row)
            row_counter += 1

    # Structured Tables Output
    structured_tables = [tr.model_dump(mode='json') for tr in table_regions]

    # Re-order or subset markdown generation if we successfully isolated main items!
    markdown_target_rows = legacy_reconstructed_rows
    if table_bundle and table_bundle.main_table:
         # Priority sort: Force main table to top of markdown
         main_id = table_bundle.main_table.table_id
         # Or ideally serialize based on semantic bundles...
         pass

    # Generate Semantic Markdown serialization
    from services.semantic_serializer import serialize_to_markdown
    semantic_markdown = serialize_to_markdown(legacy_reconstructed_rows)

    # --- Reconstruction Comparison Artifact & Auditing ---
    numeric_merge_suspicions = 0
    if semantic_markdown:
        # Heuristic: Detect multiple decimal points attached directly with no space (e.g., 12.3456.78)
        words = semantic_markdown.split()
        for w in words:
            # Check if word contains consecutive numbers glued by multiple decimal symbols
            if w.count('.') >= 2 and re.search(r'\d+\.\d+\.\d+', w):
                numeric_merge_suspicions += 1

        if debug:
            with open(os.path.join(debug_dir, "reconstructed_output.md"), "w", encoding="utf-8") as f:
                f.write(semantic_markdown)

    raw_token_count = len(ocr_blocks)
    recon_line_count = len(legacy_reconstructed_rows)
    avg_tok = (raw_token_count / recon_line_count) if recon_line_count > 0 else 0.0

    # Build auxiliary tables metadata from routing bundle
    auxiliary_tables = {}
    if table_bundle:
        auxiliary_tables = {
            "gst_summary": [tr.model_dump(mode='json') for tr in table_bundle.gst_summary],
            "scheme_items": [tr.model_dump(mode='json') for tr in table_bundle.scheme_items],
            "credit_notes": [tr.model_dump(mode='json') for tr in table_bundle.credit_notes],
        }

    return {
        "reconstructed_rows": legacy_reconstructed_rows,
        "detected_table_rows": legacy_table_rows,
        "columns_extracted": True,
        "structured_tables": structured_tables,
        "auxiliary_tables": auxiliary_tables,
        "semantic_markdown": semantic_markdown,
        "fast_fail": False,
        "topology_source": topology_source,
        "invoice_confidence": confidence_hierarchy["invoice_confidence"],
        "metrics": {
            "raw_token_count": raw_token_count,
            "reconstructed_line_count": recon_line_count,
            "numeric_merge_suspicions": int(numeric_merge_suspicions),
            "avg_tokens_per_line": float(round(avg_tok, 2)),
            "table_count": len(table_regions),
            "row_count": total_rows,
            "col_count": total_cols,
            "orphan_token_count": orphan_tokens,
            "ioa_success_rate": ioa_success_rate,
            "empty_cell_ratio": empty_cell_ratio,
            "topology_stability": stability_metrics,
            "topology_debug": topology_debug,
            "semantic_debug": semantic_debug,
            **table_routing_diagnostics,
            "column_anchor_debug": column_anchor_debug,
            "anchor_repair": anchor_repair,
            "column_semantic_cache": semantic_results,
            "semantic_rejection_count": semantic_rejection_total,
            "semantic_outlier_count": semantic_outlier_total,
            "hard_deleted_cells_count": hard_deleted_cells_total,
            "quarantined_cell_count": quarantined_cell_total,
            "columns_inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
            "semantic_column_scores_by_col": semantic_column_scores_by_col,
            "final_column_semantics": final_column_semantics,
            "amount_column_candidates": amount_column_candidates,
            "rejected_amount_candidates": rejected_amount_candidates,
            "product_column_candidates": product_column_candidates,
            "expiry_column_candidates": expiry_column_candidates,
            "batch_column_candidates": batch_column_candidates,
            "hsn_column_candidates": hsn_column_candidates,
            "gst_column_candidates": gst_column_candidates,
            "quantity_column_candidates": quantity_column_candidates,
            "rejected_quantity_candidates": rejected_quantity_candidates,
            "item_rows_count": row_role_metrics["item_rows_count"],
            "footer_rows_count": row_role_metrics["footer_rows_count"],
            "tax_rows_count": row_role_metrics["tax_rows_count"],
            "row_role_metrics": row_role_metrics,
            "topology_repairs": repair_metrics_total,
            "row_validation": row_validation_results,
            "financial_reconciliation": reconciliation_results,
            "invoice_financial_reconciliation": invoice_reconciliation_result,
            "confidence_hierarchy": confidence_hierarchy,
            "instrumentation": {
                "tsr_contribution_percent": tsr_contribution_percent,
                "heuristic_fallback_used": heuristic_fallback_used,
                "heuristic_fallback_count": 1 if heuristic_fallback_used else 0,
                "semantic_rejection_count": semantic_rejection_total,
                "semantic_outlier_count": semantic_outlier_total,
                "hard_deleted_cells_count": hard_deleted_cells_total,
                "quarantined_cell_count": quarantined_cell_total,
                "columns_inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
                "item_rows_count": row_role_metrics["item_rows_count"],
                "footer_rows_count": row_role_metrics["footer_rows_count"],
                "tax_rows_count": row_role_metrics["tax_rows_count"],
                "row_role_metrics": row_role_metrics,
                "confidence_variance": confidence_hierarchy.get("confidence_variance", {}),
            },
            "fast_fail": False,
            **tsr_metadata,
            "tsr_status": tsr_status_metric
        }
    }
