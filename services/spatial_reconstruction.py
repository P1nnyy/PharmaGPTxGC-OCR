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
from services.layout_pipeline.document_graph import build_document_graph
from services.layout_pipeline.graph_fallback import build_graph_fallback_table_region
from services.layout_pipeline.reconstruction_diagnostics import (
    _box_to_dict,
    _build_topology_debug,
    _graph_telemetry_block,
    _summarize_column_projection_debug,
    _token_flags,
)
from services.layout_pipeline.vendor_priors import build_vendor_template_prior
from services.topology.column_stabilizer import ColumnStabilizer
from services.financial_reconciler import FinancialReconciler, reconcile_invoice_financials
from services.table_classifier import TableClassifier, route_tables

from services.tsr.heuristic_tsr import HeuristicTSREngine
from services.tsr.future_ppstructure import PPStructure_TSREngine

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


def _invoice_footer_tax_source_counts(invoice_reconciliation: Dict[str, Any]) -> Dict[str, int]:
    footer_labels = {
        "parsed_subtotal",
        "discount",
        "roundoff",
        "cr_dr_note",
        "parsed_grand_total",
    }
    tax_labels = {"sgst", "cgst", "igst"}
    footer_rows = set()
    tax_rows = set()

    for source_map in (
        invoice_reconciliation.get("sources") or {},
        invoice_reconciliation.get("ignored_sources") or {},
    ):
        for label, source_or_sources in source_map.items():
            sources = source_or_sources if isinstance(source_or_sources, list) else [source_or_sources]
            for source in sources:
                if not isinstance(source, dict):
                    continue
                row_key = (source.get("table_id"), source.get("row_id"))
                if not row_key[0] or not row_key[1]:
                    continue
                if label in tax_labels:
                    tax_rows.add(row_key)
                elif label in footer_labels:
                    footer_rows.add(row_key)

    return {
        "footer_rows_count": len(footer_rows),
        "tax_rows_count": len(tax_rows),
    }


def _repair_product_numeric_phase_shift(
    main_table,
    table_regions,
    ocr_blocks,
    final_semantics: Dict[str, str],
) -> Dict[str, Any]:
    """Conservatively shift product ownership up one visual row for heuristic tables."""
    metrics = {
        "product_numeric_phase_shift_detected": False,
        "product_phase_shift_repair_count": 0,
        "product_phase_shift_source": "not_attempted",
        "product_phase_shift_affected_rows": [],
    }
    if not main_table or not str(main_table.table_id).startswith("heuristic_region"):
        metrics["product_phase_shift_source"] = "not_heuristic_table"
        return metrics

    product_col_id = next((col_id for col_id, semantic in final_semantics.items() if semantic == "product"), None)
    numeric_col_ids = {
        col_id
        for col_id, semantic in final_semantics.items()
        if semantic in {"quantity", "free_quantity", "mrp", "rate", "amount"}
    }
    if not product_col_id or not numeric_col_ids:
        metrics["product_phase_shift_source"] = "missing_product_or_numeric_semantics"
        return metrics

    block_by_id = {block.id: block for block in ocr_blocks if getattr(block, "id", None)}

    def _center_y(block) -> float:
        geom = getattr(block, "normalized_geometry", None) or getattr(block, "original_geometry", None)
        return float(getattr(geom, "center_y", 0.0) or 0.0)

    def _center_x(block) -> float:
        geom = getattr(block, "normalized_geometry", None) or getattr(block, "original_geometry", None)
        return float(getattr(geom, "center_x", 0.0) or 0.0)

    def _is_product_like(text: str) -> bool:
        import re

        upper = (text or "").upper().strip()
        if not upper or not re.search(r"[A-Z]", upper):
            return False
        blocked = {
            "PRODUCT",
            "PRODUCT NAME",
            "PACK",
            "BATCH",
            "HSN",
            "MRP",
            "RATE",
            "AMOUNT",
            "QTY",
            "SGST",
            "CGST",
            "GST",
            "DIS",
        }
        if upper in blocked:
            return False
        if any(word in upper for word in ("TOTAL", "SUB TOTAL", "GRAND", "ROUND", "DISCOUNT", "BANK", "GSTIN")):
            return False
        return True

    row_by_id = {row.row_id: row for row in main_table.rows}
    cells_by_row: Dict[str, Dict[str, Any]] = {}
    for cell in main_table.cells:
        cells_by_row.setdefault(cell.row_id, {})[cell.col_id] = cell

    def _row_center(row) -> float:
        return float(getattr(row.geometry, "center_y", 0.0) or 0.0)

    def _cell_blocks(cell) -> List[Any]:
        return [block_by_id[block_id] for block_id in cell.mapped_block_ids if block_id in block_by_id]

    eligible_rows = []
    for row in sorted(main_table.rows, key=_row_center):
        if getattr(row, "row_role", "") != "item_row":
            continue
        row_cells = cells_by_row.get(row.row_id, {})
        has_numeric = any((row_cells.get(col_id) and row_cells[col_id].mapped_block_ids) for col_id in numeric_col_ids)
        if has_numeric:
            eligible_rows.append(row)
    if len(eligible_rows) < 3:
        metrics["product_phase_shift_source"] = "insufficient_item_rows"
        return metrics

    row_centers = [_row_center(row) for row in eligible_rows]
    intervals = [
        row_centers[idx + 1] - row_centers[idx]
        for idx in range(len(row_centers) - 1)
        if row_centers[idx + 1] > row_centers[idx]
    ]
    if not intervals:
        metrics["product_phase_shift_source"] = "missing_row_intervals"
        return metrics
    intervals_sorted = sorted(intervals)
    row_interval = intervals_sorted[len(intervals_sorted) // 2]

    product_col = next((col for col in main_table.columns if col.col_id == product_col_id), None)
    if not product_col or not product_col.geometry:
        metrics["product_phase_shift_source"] = "missing_product_column_geometry"
        return metrics
    x_min = max(float(product_col.geometry.min_x) + 35.0, float(product_col.geometry.min_x))
    x_max = float(product_col.geometry.max_x) + 55.0
    first_row = eligible_rows[0]
    first_center = _row_center(first_row)
    external_candidates = []
    current_table_token_ids = {block_id for cell in main_table.cells for block_id in cell.mapped_block_ids}
    for region in table_regions:
        if region.table_id == main_table.table_id:
            continue
        for cell in region.cells:
            candidate_blocks = []
            for block in _cell_blocks(cell):
                if block.id in current_table_token_ids:
                    continue
                if not (x_min <= _center_x(block) <= x_max):
                    continue
                if not (first_center - (1.5 * row_interval) <= _center_y(block) < first_center):
                    continue
                if _is_product_like(block.text):
                    candidate_blocks.append(block)
            if candidate_blocks:
                candidate_blocks.sort(key=lambda b: (_center_y(b), _center_x(b)))
                external_candidates.append(
                    {
                        "source_table_id": region.table_id,
                        "source_row_id": cell.row_id,
                        "source_col_id": cell.col_id,
                        "block_ids": [block.id for block in candidate_blocks],
                        "text": " ".join(block.text for block in candidate_blocks if block.text).strip(),
                        "center_y": max(_center_y(block) for block in candidate_blocks),
                    }
                )
    if not external_candidates:
        metrics["product_phase_shift_source"] = "no_preceding_product_candidate"
        return metrics
    external_candidates.sort(key=lambda item: item["center_y"], reverse=True)
    preceding_product = external_candidates[0]

    product_cells = []
    for row in eligible_rows:
        product_cell = cells_by_row.get(row.row_id, {}).get(product_col_id)
        if product_cell is not None:
            product_cells.append(product_cell)
        else:
            product_cells.append(None)

    current_products = []
    for cell in product_cells:
        if cell is None:
            continue
        product_blocks = [
            block
            for block in _cell_blocks(cell)
            if x_min <= _center_x(block) <= x_max and _is_product_like(block.text)
        ]
        if not product_blocks:
            continue
        product_blocks.sort(key=lambda b: (_center_y(b), _center_x(b)))
        current_products.append(
            {
                "block_ids": [block.id for block in product_blocks],
                "text": " ".join(block.text for block in product_blocks if block.text).strip(),
                "source_table_id": main_table.table_id,
                "source_row_id": cell.row_id,
                "source_col_id": cell.col_id,
            }
        )
    if len(current_products) < 2:
        metrics["product_phase_shift_source"] = "insufficient_product_cells"
        return metrics

    replacement_sequence = [preceding_product] + current_products
    repair_limit = min(len(eligible_rows), len(replacement_sequence))
    if repair_limit < 3:
        metrics["product_phase_shift_source"] = "insufficient_repair_sequence"
        return metrics

    metrics["product_numeric_phase_shift_detected"] = True
    metrics["product_phase_shift_source"] = (
        f"{preceding_product['source_table_id']}:{preceding_product['source_row_id']}:{preceding_product['source_col_id']}"
    )
    affected_rows = []
    for idx in range(repair_limit):
        row = eligible_rows[idx]
        product_cell = cells_by_row.get(row.row_id, {}).get(product_col_id)
        if product_cell is None:
            continue
        replacement = replacement_sequence[idx]
        before = {
            "text": product_cell.text,
            "mapped_block_ids": list(product_cell.mapped_block_ids),
        }
        if before["mapped_block_ids"] == replacement["block_ids"]:
            continue
        product_cell.original_text = product_cell.original_text or product_cell.text
        product_cell.mapped_block_ids = list(replacement["block_ids"])
        product_cell.text = replacement["text"]
        product_cell.assignment_strategy = "product_phase_shift_repair"
        row.provenance["product_phase_shift_repair"] = {
            "before": before,
            "after": {
                "text": product_cell.text,
                "mapped_block_ids": list(product_cell.mapped_block_ids),
                "source_table_id": replacement.get("source_table_id"),
                "source_row_id": replacement.get("source_row_id"),
                "source_col_id": replacement.get("source_col_id"),
            },
        }
        affected_rows.append(
            {
                "row_id": row.row_id,
                "before_text": before["text"],
                "after_text": product_cell.text,
                "before_block_ids": before["mapped_block_ids"],
                "after_block_ids": list(product_cell.mapped_block_ids),
            }
        )

    metrics["product_phase_shift_repair_count"] = len(affected_rows)
    metrics["product_phase_shift_affected_rows"] = affected_rows
    if not affected_rows:
        metrics["product_numeric_phase_shift_detected"] = False
        metrics["product_phase_shift_source"] = "no_cell_changes_needed"
    return metrics


def _dominance_score_confidence(score: float) -> float:
    return max(0.0, min(0.99, (float(score) + 200.0) / 700.0))

def reconstruct_layout(blocks: List[Dict[str, Any]], debug: bool = False, reconstruct_mode: str = "ppstructure", image: Any = None, benchmark_mode: bool = False) -> Dict[str, Any]:
    """
    Entry point for document-layout reasoning engine.
    Orchestrates OCR geometry preservation, TSR grid detection, and Cell Mapping.

    benchmark_mode: When True, disables expensive debug artifacts, enables fast-fail
    on hopeless invoices, and minimizes intermediate dumps to maximize VM throughput.
    """
    logger.info(f"Starting spatial reconstruction on {len(blocks)} blocks (Mode={reconstruct_mode}, Debug={debug}, Benchmark={benchmark_mode})")

    graph_fallback_used = False
    graph_rejection_reason = "reconstruction_confidence_high"

    # Fallback telemetry initialization
    graph_fallback_cell_count = 0
    graph_fallback_non_empty_cell_count = 0
    graph_fallback_mapped_token_count = 0
    graph_fallback_empty_cell_ratio = 0.0
    graph_fallback_item_row_count = 0

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
    document_graph = build_document_graph(ocr_blocks)

    # Step 3: TSR Table Region Detection with Confidence-Gated Fallback
    table_regions = []
    tsr_metadata = {
        "graph_fallback_product_repair_count": 0,
        "graph_fallback_amount_repair_count": 0,
        "graph_fallback_numeric_reassignment_count": 0,
        "graph_fallback_suspicious_qty_count": 0,
    }
    ppstructure_enabled = bool(
        settings.ENABLE_PPSTRUCTURE
        or str(settings.TSR_PRIMARY_ENGINE).lower() == "ppstructure"
    )
    ppstructure_threshold = float(settings.PPSTRUCTURE_CONFIDENCE_THRESHOLD)
    topology_source = "ppstructure" if ppstructure_enabled else "heuristic_anchor"
    selected_topology_source = "heuristic_anchor"
    heuristic_fallback_used = False
    ppstructure_regions_attempted = 0
    ppstructure_cells_attempted = 0
    tsr_status_metric = {
        "ppstructure_enabled": ppstructure_enabled,
        "ppstructure_skipped_reason": None,
        "fallback_used": False,
        "ppstructure_success": False,
        "ppstructure_zero_output": False,
        "tsr_contribution_percent": 0.0,
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
            tsr_status_metric["ppstructure_zero_output"] = True

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
    tsr_status_metric.update({
        "topology_source": topology_source,
        "ppstructure_regions_attempted": ppstructure_regions_attempted,
        "ppstructure_cells_attempted": ppstructure_cells_attempted,
        "ppstructure_success": bool(topology_source == "ppstructure" and ppstructure_regions_attempted > 0 and ppstructure_cells_attempted > 0),
        "tsr_contribution_percent": tsr_contribution_percent,
    })
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
        topology_debug = _build_topology_debug(ocr_blocks, [], [], {}, document_graph=document_graph)
        return {
            "reconstructed_rows": [],
            "detected_table_rows": [],
            "columns_extracted": False,
            "structured_tables": [],
            "semantic_markdown": "",
            "fast_fail": True,
            "fast_fail_reason": "zero_tables",
            "topology_source": topology_source,
            "selected_topology_source": selected_topology_source,
            "graph_candidate_rows": document_graph.get("graph_candidate_rows", []),
            "graph_candidate_columns": document_graph.get("graph_candidate_columns", []),
            "graph_table_region": document_graph.get("graph_table_region", {}),
            "graph_confidence": document_graph.get("graph_confidence", 0.0),
            "metrics": {
                "raw_token_count": len(ocr_blocks),
                "table_count": 0,
                "topology_debug": topology_debug,
                "column_anchor_debug": {},
                **_graph_telemetry_block(
                    document_graph=document_graph,
                    graph_fallback_used=graph_fallback_used,
                    graph_rejection_reason=graph_rejection_reason,
                    graph_fallback_cell_count=graph_fallback_cell_count,
                    graph_fallback_non_empty_cell_count=graph_fallback_non_empty_cell_count,
                    graph_fallback_mapped_token_count=graph_fallback_mapped_token_count,
                    graph_fallback_empty_cell_ratio=graph_fallback_empty_cell_ratio,
                    graph_fallback_item_row_count=graph_fallback_item_row_count,
                ),
                "instrumentation": {
                    "tsr_contribution_percent": tsr_contribution_percent,
                    "heuristic_fallback_used": heuristic_fallback_used,
                    "heuristic_fallback_count": 1 if heuristic_fallback_used else 0,
                    "semantic_rejection_count": 0,
                    "confidence_variance": {
                        "table_confidence_variance": 0.0,
                        "row_confidence_variance": 0.0
                    },
                    "document_graph_metrics": document_graph.get("metrics", {}),
                    **_graph_telemetry_block(
                        document_graph=document_graph,
                        graph_fallback_used=graph_fallback_used,
                        graph_rejection_reason=graph_rejection_reason,
                        graph_fallback_cell_count=graph_fallback_cell_count,
                        graph_fallback_non_empty_cell_count=graph_fallback_non_empty_cell_count,
                        graph_fallback_mapped_token_count=graph_fallback_mapped_token_count,
                        graph_fallback_empty_cell_ratio=graph_fallback_empty_cell_ratio,
                        graph_fallback_item_row_count=graph_fallback_item_row_count,
                    ),
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

    # Step 5.1: Token Coverage Validation (diagnostic only)
    from services.layout_pipeline.token_validator import TokenMappingValidator
    token_coverage_report = None
    try:
        validator = TokenMappingValidator(threshold=float(settings.TOKEN_COVERAGE_THRESHOLD))
        token_coverage_report = validator.validate(ocr_blocks, table_regions)

        if debug and not benchmark_mode:
            try:
                debug_dir = os.path.join(settings.DATASETS_DIR, "debug")
                os.makedirs(debug_dir, exist_ok=True)
                with open(os.path.join(debug_dir, "token_coverage_report.json"), "w", encoding="utf-8") as f:
                    f.write(token_coverage_report.to_json())
            except Exception as e:
                logger.error(f"Failed to export token coverage report: {e}")
    except Exception as e:
        logger.error(f"[TOKEN COVERAGE] diagnostic generation failed: {e}")

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

    # --- GRAPH FALLBACK & RANKED TOPOLOGY ENGINE ---
    # Retrieve graph candidate rows/cols
    raw_graph_rows = document_graph.get("graph_candidate_rows", [])
    graph_cols = document_graph.get("graph_candidate_columns", [])

    import re
    graph_rows = []
    graph_rows_raw_count = len(raw_graph_rows)
    graph_rows_dropped_reasons = {}

    # Telemetry & Override counters
    graph_rows_preserved_by_header_evidence = 0
    graph_rows_preserved_by_product_evidence = 0
    graph_rows_dropped_detail_sample = []

    # Compile patterns and filters for overrides
    header_tokens_pattern = re.compile(
        r"\b(PRODUCT|ITEM|DESCRIPTION|BATCH|EXP|EXPIRY|HSN|QTY|MRP|RATE|AMOUNT)\b"
    )
    common_stops = {
        "THE", "FOR", "AND", "GST", "TAX", "NET", "AMT", "SUB", "PCS", "QTY", "EXP", "LOT",
        "IFSC", "BANK", "DATE", "INVOICE", "BILL", "TOTAL", "GRAND", "PAGE", "ONLY",
        "RUPEES", "WORDS", "SIGN", "PROP", "JURIS", "TERMS", "GOODS", "SOLD", "DELAY", "INTER"
    }

    for r in raw_graph_rows:
        row_id = r.get("row_id", "")
        text = r.get("text", "")
        text_upper = text.upper()
        hint = r.get("row_type_hint", "unknown")

        has_strong_header_tokens = header_tokens_pattern.search(text_upper) is not None

        # Precedence 1: Check obvious noise drops
        # A. Amount in words
        is_amount_in_words = (
            "AMOUNT IN WORDS" in text_upper or
            "AMT IN WORDS" in text_upper or
            "RUPEES ONLY" in text_upper or
            "RUPEES" in text_upper or
            "WORDS ONLY" in text_upper or
            "RUPEES IN WORDS" in text_upper or
            re.search(r"RUPEES\s+[A-Za-z\s]+ONLY", text_upper) is not None
        )
        if is_amount_in_words:
            reason = "amount_in_words"
            graph_rows_dropped_reasons[reason] = graph_rows_dropped_reasons.get(reason, 0) + 1
            graph_rows_dropped_detail_sample.append({
                "row_id": row_id,
                "row_type_hint": hint,
                "text_preview": text[:100],
                "drop_reason": reason
            })
            logger.info(f"[GRAPH ROW DROPPED] row_id={row_id} | hint={hint} | reason={reason} | text={text[:60]}")
            continue

        # B. Terms and conditions
        is_terms_conditions = (
            "TERMS & CONDITIONS" in text_upper or
            "TERMS AND CONDITIONS" in text_upper or
            "SUBJECT TO" in text_upper or
            "JURISDICTION" in text_upper or
            "GOODS ONCE SOLD" in text_upper or
            "INTEREST @" in text_upper or
            "DELAYED PAYMENT" in text_upper
        )
        if is_terms_conditions:
            reason = "terms_conditions"
            graph_rows_dropped_reasons[reason] = graph_rows_dropped_reasons.get(reason, 0) + 1
            graph_rows_dropped_detail_sample.append({
                "row_id": row_id,
                "row_type_hint": hint,
                "text_preview": text[:100],
                "drop_reason": reason
            })
            logger.info(f"[GRAPH ROW DROPPED] row_id={row_id} | hint={hint} | reason={reason} | text={text[:60]}")
            continue

        # C. Bank details and signature blocks
        is_bank_signature = (
            "SIGNATURE" in text_upper or
            "AUTHORISED SIGN" in text_upper or
            "AUTH. SIGN" in text_upper or
            "BANK DETAIL" in text_upper or
            "IFSC CODE" in text_upper or
            "A/C NO" in text_upper or
            "ACCOUNT NO" in text_upper or
            "FOR AUTHORISED" in text_upper or
            "PROP." in text_upper or
            "PARTNER" in text_upper
        )
        if is_bank_signature:
            reason = "bank_signature"
            graph_rows_dropped_reasons[reason] = graph_rows_dropped_reasons.get(reason, 0) + 1
            graph_rows_dropped_detail_sample.append({
                "row_id": row_id,
                "row_type_hint": hint,
                "text_preview": text[:100],
                "drop_reason": reason
            })
            logger.info(f"[GRAPH ROW DROPPED] row_id={row_id} | hint={hint} | reason={reason} | text={text[:60]}")
            continue

        # D. Pure GST/Tax footer rows (ensure we don't accidentally drop actual headers containing tax info)
        is_tax_footer = (
            "GST SUMMARY" in text_upper or
            "TAX SUMMARY" in text_upper or
            "TAXABLE VALUE" in text_upper or
            "TAXABLE VAL" in text_upper or
            ("CGST" in text_upper and "SGST" in text_upper and "TAXABLE" in text_upper) or
            ("CGST RATE" in text_upper and not has_strong_header_tokens) or
            ("SGST RATE" in text_upper and not has_strong_header_tokens) or
            ("IGST RATE" in text_upper and not has_strong_header_tokens)
        )
        if is_tax_footer:
            reason = "gst_summary_tax_footer"
            graph_rows_dropped_reasons[reason] = graph_rows_dropped_reasons.get(reason, 0) + 1
            graph_rows_dropped_detail_sample.append({
                "row_id": row_id,
                "row_type_hint": hint,
                "text_preview": text[:100],
                "drop_reason": reason
            })
            logger.info(f"[GRAPH ROW DROPPED] row_id={row_id} | hint={hint} | reason={reason} | text={text[:60]}")
            continue

        # Precedence 2: Filter by row classification hint, applying preservation rules to overrides
        normally_dropped = False
        drop_reason = ""

        if hint in ("footer_candidate", "metadata_candidate", "tax_candidate"):
            normally_dropped = True
            drop_reason = f"row_type_hint_{hint}"
        elif hint not in ("item_candidate", "header_candidate"):
            normally_dropped = True
            drop_reason = f"row_type_hint_{hint}"

        if normally_dropped:
            # Preservation Overrides
            
            # Rule 1: Header Preservation Override
            if has_strong_header_tokens:
                graph_rows_preserved_by_header_evidence += 1
                logger.info(f"[PRESERVATION OVERRIDE] Preserved row_id={row_id} via Header Rule. Hint={hint}. Text={text[:60]}")
                graph_rows.append(r)
                continue

            # Rule 2: Product-Context Preservation Override
            has_med_term = (
                re.search(r"\b(TAB|CAP|INJ|SUSP|SYR|TABLET|CAPSULE|MG|ML|GM|STRIP)\b", text_upper) is not None or
                any(w not in common_stops for w in re.findall(r"\b[A-Z]{3,}\b", text_upper))
            )
            has_batch = (
                re.search(r"\bB\.?\s*NO\b", text_upper) is not None or
                "BATCH" in text_upper or
                "LOT" in text_upper or
                re.search(r"\bB/N\b", text_upper) is not None or
                re.search(r"\bB\.N\b", text_upper) is not None
            )
            has_expiry = (
                re.search(r"\b\d{2}[/-]\d{2,4}\b", text_upper) is not None or
                "EXP" in text_upper or
                "EXPIRY" in text_upper
            )
            has_amount_dec = re.search(r"\b\d+\.\d{2}\b", text_upper) is not None
            
            has_evidence = has_batch or has_expiry or has_amount_dec

            if has_med_term and has_evidence:
                graph_rows_preserved_by_product_evidence += 1
                logger.info(f"[PRESERVATION OVERRIDE] Preserved row_id={row_id} via Product Context Rule. Hint={hint}. Text={text[:60]}")
                graph_rows.append(r)
                continue

            # Dropped completely
            graph_rows_dropped_reasons[drop_reason] = graph_rows_dropped_reasons.get(drop_reason, 0) + 1
            graph_rows_dropped_detail_sample.append({
                "row_id": row_id,
                "row_type_hint": hint,
                "text_preview": text[:100],
                "drop_reason": drop_reason
            })
            logger.info(f"[GRAPH ROW DROPPED] row_id={row_id} | hint={hint} | reason={drop_reason} | text={text[:60]}")
            continue

        graph_rows.append(r)

    graph_rows_filtered_count = len(graph_rows)
    graph_rows_dropped_count = graph_rows_raw_count - graph_rows_filtered_count

    logger.info(
        f"[GRAPH FILTERING] Raw Count: {graph_rows_raw_count} | "
        f"Filtered Count: {graph_rows_filtered_count} | "
        f"Dropped Count: {graph_rows_dropped_count} | "
        f"Dropped Reasons: {graph_rows_dropped_reasons} | "
        f"Preserved Headers: {graph_rows_preserved_by_header_evidence} | "
        f"Preserved Products: {graph_rows_preserved_by_product_evidence}"
    )

    # Telemetry
    tsr_metadata["graph_rows_raw_count"] = graph_rows_raw_count
    tsr_metadata["graph_rows_filtered_count"] = graph_rows_filtered_count
    tsr_metadata["graph_rows_dropped_count"] = graph_rows_dropped_count
    tsr_metadata["graph_rows_dropped_reasons"] = graph_rows_dropped_reasons
    tsr_metadata["graph_rows_preserved_by_header_evidence"] = graph_rows_preserved_by_header_evidence
    tsr_metadata["graph_rows_preserved_by_product_evidence"] = graph_rows_preserved_by_product_evidence
    tsr_metadata["graph_rows_dropped_detail_sample"] = graph_rows_dropped_detail_sample

    # Helper function to evaluate and score table candidates
    def evaluate_candidate_table(tr, is_graph=False):
        if not tr:
            return 0.0, {
                "row_count": 0,
                "column_stability": 0.0,
                "mapped_token_count": 0,
                "non_empty_cell_ratio": 0.0,
                "has_amount_col": 0.0,
                "math_score": 0.0,
                "status": "FAIL",
                "missing_req_cols": ["amount", "quantity", "rate", "product"],
                "quality_penalty": 0.0,
                "semantic_mismatches": 0,
                "structural_failures": 0,
                "financial_failures": 0,
                "item_row_ratio": 0.0,
                "non_item_ratio": 0.0,
                "row_math_pass_count": 0,
                "row_math_fail_count": 0,
                "row_math_failure_rate": 0.0
            }
        
        row_count = len(tr.rows)
        if row_count == 0:
            return 0.0, {
                "row_count": 0,
                "column_stability": 0.0,
                "mapped_token_count": 0,
                "non_empty_cell_ratio": 0.0,
                "has_amount_col": 0.0,
                "math_score": 0.0,
                "status": "FAIL",
                "missing_req_cols": ["amount", "quantity", "rate", "product"],
                "quality_penalty": 0.0,
                "semantic_mismatches": 0,
                "structural_failures": 0,
                "financial_failures": 0,
                "item_row_ratio": 0.0,
                "non_item_ratio": 0.0,
                "row_math_pass_count": 0,
                "row_math_fail_count": 0,
                "row_math_failure_rate": 0.0
            }

        # For graph candidate, we perform mapping, multiline merging, and stability scores first
        if is_graph:
            from services.layout_pipeline.graph_fallback import assign_tokens_to_graph_cells
            rep_counts = assign_tokens_to_graph_cells(tr, ocr_blocks, graph_rows, graph_cols)
            for k in ["graph_fallback_product_repair_count", "graph_fallback_amount_repair_count", "graph_fallback_numeric_reassignment_count", "graph_fallback_suspicious_qty_count"]:
                if k not in tsr_metadata:
                    tsr_metadata[k] = 0
            tsr_metadata["graph_fallback_product_repair_count"] += rep_counts.get("product_repair_count", 0)
            tsr_metadata["graph_fallback_amount_repair_count"] += rep_counts.get("amount_repair_count", 0)
            tsr_metadata["graph_fallback_numeric_reassignment_count"] += rep_counts.get("numeric_reassignment_count", 0)
            tsr_metadata["graph_fallback_suspicious_qty_count"] += rep_counts.get("suspicious_qty_count", 0)
            tr, _ = merge_multiline_table_rows(tr, ocr_blocks)
            tr = update_row_stability_scores(tr, ocr_blocks)
            
        # 1. Row Count & 2. Column stability (average row stability)
        avg_row_stability = sum(getattr(r, "stability", 1.0) for r in tr.rows) / row_count
        
        # 3. Mapped token count & 4. Non-empty cell ratio
        mapped_tokens = set()
        total_cells = len(tr.cells)
        empty_cells = 0
        for cell in tr.cells:
            if cell.mapped_block_ids:
                mapped_tokens.update(cell.mapped_block_ids)
            else:
                empty_cells += 1
        mapped_token_count = len(mapped_tokens)
        non_empty_cell_ratio = (total_cells - empty_cells) / total_cells if total_cells > 0 else 0.0

        # 5. Semantic amount column detection
        temp_classifier = SemanticColumnClassifier()
        temp_semantic_res = temp_classifier.enrich_region_metadata(tr)
        inference_summary = temp_semantic_res.get("_inference_summary", {})
        final_semantics = inference_summary.get("final_column_semantics", {})
        has_amount_col = 1.0 if 'amount' in final_semantics.values() else 0.0

        # 6. Invoice math score (using temp FinancialReconciler)
        temp_reconciler = FinancialReconciler(semantic_column_cache={tr.table_id: temp_semantic_res})
        temp_reconciliation_results = temp_reconciler.reconcile_all([tr])
        
        footer_reconcile_tables = [
            other_tr for other_tr in table_regions
            if other_tr.table_id != tr.table_id
        ]
        temp_invoice_recon = reconcile_invoice_financials(
            temp_reconciliation_results.get(tr.table_id, {}),
            footer_reconcile_tables,
        )
        
        status = temp_invoice_recon.get("status", "FAIL")
        math_score = 0.0
        if status == "PASS":
            math_score = 100.0
        elif status == "WARN":
            math_score = 75.0
        else:
            math_score = temp_invoice_recon.get("integrity_score", 0.0)

        # 7. Row Validation & Quality Metrics
        temp_validator = RowValidator(semantic_column_cache={tr.table_id: temp_semantic_res})
        val_results = temp_validator.validate_table(tr)
        
        semantic_mismatches = val_results.get("semantic_mismatches", 0)
        structural_failures = val_results.get("structural_failures", 0)
        financial_failures = val_results.get("financial_failures", 0)

        # Row math metrics
        row_math_pass_count = val_results.get("financial_passes", 0)
        row_math_fail_count = val_results.get("financial_failures", 0)
        total_row_math = row_math_pass_count + row_math_fail_count
        row_math_failure_rate = (row_math_fail_count / total_row_math) if total_row_math > 0 else 0.0

        # Check for required semantic columns: rate, amount, quantity, product
        final_vals = {str(v).lower() for v in final_semantics.values()}
        missing_req_cols = []
        if 'amount' not in final_vals:
            missing_req_cols.append('amount')
        if not any(k in final_vals for k in ('quantity', 'qty', 'free_quantity')):
            missing_req_cols.append('quantity')
        if 'rate' not in final_vals:
            missing_req_cols.append('rate')
        if not any(k in final_vals for k in ('product', 'drug_name')):
            missing_req_cols.append('product')

        # Row Role Metrics
        role_metrics = classify_row_roles(tr)
        item_rows = role_metrics.get("item_rows_count", 0)
        non_item_rows = (
            role_metrics.get("footer_rows_count", 0) +
            role_metrics.get("tax_rows_count", 0) +
            role_metrics.get("metadata_rows_count", 0) +
            role_metrics.get("unknown_rows_count", 0)
        )
        item_row_ratio = item_rows / row_count if row_count > 0 else 0.0
        non_item_ratio = non_item_rows / row_count if row_count > 0 else 0.0

        # Calculate Quality Penalty
        quality_penalty = 0.0
        
        # - reconciliation status FAIL or math score < 75
        if status == "FAIL" or math_score < 75.0:
            quality_penalty += 30.0
            
        # - missing required semantic columns, especially rate/amount/quantity/product
        quality_penalty += len(missing_req_cols) * 15.0
        
        # - high semantic_mismatches
        quality_penalty += semantic_mismatches * 3.0
        
        # - high structural_fail count
        quality_penalty += structural_failures * 5.0
        
        # - high financial_fail count
        quality_penalty += financial_failures * 5.0
        
        # - high footer/tax/metadata/unknown row ratio
        if non_item_ratio > 0.50:
            quality_penalty += 15.0
            
        # - low item_row ratio
        if item_row_ratio < 0.40:
            quality_penalty += 20.0
            
        # - very low non_empty_cell_ratio (< 0.20)
        if non_empty_cell_ratio < 0.20:
            quality_penalty += 25.0

        # Unified ranking score formula (with reduced density metrics influence)
        rank_score = (
            math_score +
            (30.0 if has_amount_col else 0.0) +
            (row_count * 0.5) +  # Reduced row count influence from 1.5 to 0.5
            (mapped_token_count * 0.05) +  # Reduced mapped token count influence from 0.2 to 0.05
            (non_empty_cell_ratio * 20.0) +
            (avg_row_stability * 10.0) -
            quality_penalty
        )
        
        metrics = {
            "row_count": row_count,
            "column_stability": round(avg_row_stability, 4),
            "mapped_token_count": mapped_token_count,
            "non_empty_cell_ratio": round(non_empty_cell_ratio, 4),
            "has_amount_col": has_amount_col,
            "math_score": math_score,
            "status": status,
            "missing_req_cols": missing_req_cols,
            "quality_penalty": quality_penalty,
            "semantic_mismatches": semantic_mismatches,
            "structural_failures": structural_failures,
            "financial_failures": financial_failures,
            "item_row_ratio": round(item_row_ratio, 4),
            "non_item_ratio": round(non_item_ratio, 4),
            "row_math_pass_count": row_math_pass_count,
            "row_math_fail_count": row_math_fail_count,
            "row_math_failure_rate": round(row_math_failure_rate, 4)
        }
        return rank_score, metrics

    # Score heuristic candidate
    heuristic_candidate = table_bundle.main_table
    heuristic_score, heuristic_metrics = evaluate_candidate_table(heuristic_candidate, is_graph=False)
    
    # Score graph candidate
    graph_candidate = None
    graph_score = 0.0
    graph_metrics = {
        "row_count": 0,
        "column_stability": 0.0,
        "mapped_token_count": 0,
        "non_empty_cell_ratio": 0.0,
        "has_amount_col": 0.0,
        "math_score": 0.0,
        "status": "FAIL",
        "missing_req_cols": ["amount", "quantity", "rate", "product"],
        "quality_penalty": 0.0,
        "semantic_mismatches": 0,
        "structural_failures": 0,
        "financial_failures": 0,
        "item_row_ratio": 0.0,
        "non_item_ratio": 0.0,
        "row_math_pass_count": 0,
        "row_math_fail_count": 0,
        "row_math_failure_rate": 0.0
    }
    
    if graph_rows and graph_cols:
        graph_candidate = build_graph_fallback_table_region(
            graph_rows=graph_rows,
            graph_cols=graph_cols,
            graph_confidence=document_graph.get("graph_confidence", 0.5)
        )
        graph_score, graph_metrics = evaluate_candidate_table(graph_candidate, is_graph=True)

    # Deterministic Blocking Rules
    graph_selection_blocked_reason = None
    heuristic_collapsed_or_unusable = (
        not heuristic_candidate
        or len(heuristic_candidate.rows) < 3
        or len(heuristic_candidate.columns) < 3
    )
    
    graph_reconciliation_fail = (graph_metrics.get("status") == "FAIL")
    heuristic_reconciliation_pass_or_warn = (heuristic_metrics.get("status") in ("PASS", "WARN"))
    graph_missing_req_cols = len(graph_metrics.get("missing_req_cols", [])) > 0
    
    if graph_candidate and len(graph_candidate.rows) > 0:
        # Rule 3: cannot beat heuristic if graph reconciliation is FAIL and heuristic is PASS/WARN
        if graph_reconciliation_fail and heuristic_reconciliation_pass_or_warn:
            graph_selection_blocked_reason = "reconciliation_fail_vs_pass_or_warn"
        # Rule 4: cannot be selected if required semantic columns are missing unless heuristic is collapsed/unusable
        elif graph_missing_req_cols and not heuristic_collapsed_or_unusable:
            graph_selection_blocked_reason = "missing_semantic_columns_vs_heuristic"
        
        # Row Math Regression Guard
        if not graph_selection_blocked_reason:
            heur_recon_pass = (heuristic_metrics.get("status") == "PASS")
            graph_recon_pass_warn = (graph_metrics.get("status") in ("PASS", "WARN"))
            heur_math_fail = heuristic_metrics.get("row_math_fail_count", 0)
            graph_math_fail = graph_metrics.get("row_math_fail_count", 0)
            
            if heur_recon_pass and graph_recon_pass_warn and (graph_math_fail > heur_math_fail + 1):
                graph_selection_blocked_reason = "graph_row_math_regression"
                
        # Missing Critical Semantics Guard
        if not graph_selection_blocked_reason:
            graph_missing_amount_rate = any(col in graph_metrics.get("missing_req_cols", []) for col in ("amount", "rate"))
            heur_has_amount_rate = not any(col in heuristic_metrics.get("missing_req_cols", []) for col in ("amount", "rate"))
            
            if graph_missing_amount_rate and heur_has_amount_rate and not heuristic_collapsed_or_unusable:
                graph_selection_blocked_reason = "graph_missing_critical_semantics"

    # Topology Decision Logic
    selected_topology_source = "heuristic_anchor"
    selected_candidate_reason = "default_heuristic"
    margin = 15.0
    
    if not heuristic_candidate or len(heuristic_candidate.rows) == 0:
        if graph_candidate and len(graph_candidate.rows) > 0:
            selected_topology_source = "document_graph_candidate"
            selected_candidate_reason = "heuristic_empty_graph_available"
    elif graph_candidate and len(graph_candidate.rows) > 0:
        if graph_selection_blocked_reason:
            selected_topology_source = "heuristic_anchor"
            selected_candidate_reason = f"heuristic_preferred_due_to_block_{graph_selection_blocked_reason}"
        elif graph_score > heuristic_score + margin:
            selected_topology_source = "document_graph_candidate"
            selected_candidate_reason = f"graph_score_beats_heuristic_with_margin_{graph_score - heuristic_score:.2f}"
        else:
            selected_topology_source = "heuristic_anchor"
            selected_candidate_reason = f"heuristic_score_higher_or_within_margin (diff: {heuristic_score - graph_score:.2f})"

    logger.info(
        f"[TOPOLOGY RANKING] Heuristic Score: {heuristic_score:.2f} ({heuristic_metrics}) | "
        f"Graph Score: {graph_score:.2f} ({graph_metrics}) | "
        f"Selected Topology Source: {selected_topology_source} | "
        f"Reason: {selected_candidate_reason} | Blocked: {graph_selection_blocked_reason}"
    )

    # Telemetry logging
    tsr_metadata["graph_selection_blocked_reason"] = graph_selection_blocked_reason
    tsr_metadata["graph_quality_penalty"] = graph_metrics.get("quality_penalty", 0.0)
    tsr_metadata["heuristic_quality_penalty"] = heuristic_metrics.get("quality_penalty", 0.0)
    tsr_metadata["selected_candidate_reason"] = selected_candidate_reason
    tsr_metadata["heuristic_row_math_fail_count"] = heuristic_metrics.get("row_math_fail_count", 0)
    tsr_metadata["graph_row_math_fail_count"] = graph_metrics.get("row_math_fail_count", 0)

    # Promote graph candidate if selected
    if selected_topology_source == "document_graph_candidate":
        table_bundle.main_table = graph_candidate
        if graph_candidate not in table_regions:
            table_regions.append(graph_candidate)
        topology_source = "document_graph_candidate"

    # Emergency Fallback Safety Net (Fallback Engine)
    should_fallback = False
    trigger_reason = None

    if not table_bundle.main_table:
        should_fallback = True
        trigger_reason = "missing_main_table"
    else:
        main_tr = table_bundle.main_table
        num_rows = len(main_tr.rows)
        num_cols = len(main_tr.columns)

        # Triggers for collapsed rows or poor column support
        if num_rows < 3 and len(ocr_blocks) >= 15:
            should_fallback = True
            trigger_reason = f"collapsed_rows_{num_rows}"
        elif num_cols < 3:
            should_fallback = True
            trigger_reason = f"poor_column_support_{num_cols}"
        elif getattr(main_tr, "topology_confidence", 1.0) < 0.40:
            should_fallback = True
            trigger_reason = f"low_topology_confidence_{main_tr.topology_confidence:.2f}"

    if should_fallback:
        if selected_topology_source == "document_graph_candidate":
            logger.info("[GRAPH FALLBACK] Already selected document_graph_candidate; skipping redundant emergency fallback.")
        else:
            if graph_rows and graph_cols:
                logger.warning(f"[GRAPH FALLBACK] Activating emergency document graph fallback due to: {trigger_reason}")
                fallback_tr = build_graph_fallback_table_region(
                    graph_rows=graph_rows,
                    graph_cols=graph_cols,
                    graph_confidence=document_graph.get("graph_confidence", 0.5)
                )
                from services.layout_pipeline.graph_fallback import assign_tokens_to_graph_cells
                rep_counts = assign_tokens_to_graph_cells(fallback_tr, ocr_blocks, graph_rows, graph_cols)
                for k in ["graph_fallback_product_repair_count", "graph_fallback_amount_repair_count", "graph_fallback_numeric_reassignment_count", "graph_fallback_suspicious_qty_count"]:
                    if k not in tsr_metadata:
                        tsr_metadata[k] = 0
                tsr_metadata["graph_fallback_product_repair_count"] += rep_counts.get("product_repair_count", 0)
                tsr_metadata["graph_fallback_amount_repair_count"] += rep_counts.get("amount_repair_count", 0)
                tsr_metadata["graph_fallback_numeric_reassignment_count"] += rep_counts.get("numeric_reassignment_count", 0)
                tsr_metadata["graph_fallback_suspicious_qty_count"] += rep_counts.get("suspicious_qty_count", 0)
                fallback_tr, audit = merge_multiline_table_rows(fallback_tr, ocr_blocks)
                fallback_tr = update_row_stability_scores(fallback_tr, ocr_blocks)

                table_bundle.main_table = fallback_tr
                if fallback_tr not in table_regions:
                    table_regions.append(fallback_tr)

                topology_source = "document_graph_fallback"
                selected_topology_source = "document_graph_fallback"
                graph_fallback_used = True
                graph_rejection_reason = "fallback_activated"
                fallback_tr.topology_confidence = document_graph.get("graph_confidence", 0.5)
            else:
                graph_rejection_reason = "graph_extraction_empty"
                logger.warning(f"[GRAPH FALLBACK] Fallback triggered ({trigger_reason}) but document graph candidates were empty.")

    # Populate actual selected topology sources in metadata
    tsr_metadata["topology_source"] = topology_source
    tsr_metadata["selected_topology_source"] = selected_topology_source

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

    product_phase_shift_metrics = {
        "product_numeric_phase_shift_detected": False,
        "product_phase_shift_repair_count": 0,
        "product_phase_shift_source": "not_evaluated",
        "product_phase_shift_affected_rows": [],
    }
    for tr in analysis_targets:
        product_phase_shift_metrics = _repair_product_numeric_phase_shift(
            tr,
            table_regions,
            ocr_blocks,
            final_column_semantics.get(tr.table_id, {}),
        )
        if product_phase_shift_metrics.get("product_phase_shift_repair_count", 0) > 0:
            logger.info(
                "[PRODUCT PHASE SHIFT] repaired rows=%s source=%s",
                product_phase_shift_metrics.get("product_phase_shift_repair_count"),
                product_phase_shift_metrics.get("product_phase_shift_source"),
            )
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

    # Map the unified invoice-level reconciliation result to its canonical structure
    # to fulfill both explicit user-requested fields and downstream metadata schemas.
    main_rec = reconciliation_results.get(main_table_id, {})
    invoice_level = {
        # Unique identifier of the primary medicine table region
        "item_table_region_id": main_table_id,
        # List of IDs of the table regions identified as footer/tax/summary structures
        "footer_source_region_ids": [t.table_id for t in footer_reconcile_tables],
        # Math subtotal computed directly from row-by-row item additions
        "item_derived_subtotal": invoice_reconciliation_result.get("item_derived_subtotal"),
        # Subtotal literally parsed from footer text boxes/cells
        "footer_subtotal": invoice_reconciliation_result.get("parsed_subtotal"),
        # Consolidated trade/cash/scheme discount total parsed from footer
        "discount_total": invoice_reconciliation_result.get("discount"),
        # State GST total amount parsed from footer rows
        "sgst_total": invoice_reconciliation_result.get("sgst"),
        # Central GST total amount parsed from footer rows
        "cgst_total": invoice_reconciliation_result.get("cgst"),
        # Integrated GST total amount parsed from footer rows
        "igst_total": invoice_reconciliation_result.get("igst"),
        # Total GST tax sum (SGST + CGST + IGST)
        "gst_total": invoice_reconciliation_result.get("parsed_gst"),
        # Exact roundoff adjustment applied, preserving standard mathematical sign
        "roundoff": invoice_reconciliation_result.get("roundoff_effect"),
        # Mathematically derived grand total: subtotal - discount + taxes + roundoff
        "expected_grand_total": invoice_reconciliation_result.get("expected_grand_total"),
        # Grand total literally parsed from footer text boxes
        "parsed_grand_total": invoice_reconciliation_result.get("parsed_grand_total"),
        # Verification flag indicating if parsed and derived subtotals match within tolerance
        "subtotal_match": invoice_reconciliation_result.get("subtotal_match"),
        # Verification flag indicating if parsed and expected grand totals match within tolerance
        "grand_total_match": invoice_reconciliation_result.get("grand_total_match"),
        # Reconciliation status (PASS, WARN, FAIL)
        "status": invoice_reconciliation_result.get("status"),
        # List of validation warning codes or flags encountered during the run
        "warnings": invoice_reconciliation_result.get("warnings"),
        # Nested dictionary mapping labels/keys to the exact text sources and bounding boxes
        "source rows/cells used": invoice_reconciliation_result.get("sources"),

        # Compatibility shims to allow validation/reporting engines to treat invoice_level
        # seamlessly as a standard table-level reconciliation output where required.
        "parsed_subtotal": invoice_reconciliation_result.get("parsed_subtotal"),
        "derived_subtotal": invoice_reconciliation_result.get("item_derived_subtotal"),
        "grand_total_discrepancy": invoice_reconciliation_result.get("grand_total_discrepancy"),
        "integrity_score": 100.0 if invoice_reconciliation_result.get("status") in ["PASS", "WARN"] else 50.0,
        "confidence": 1.0 if invoice_reconciliation_result.get("status") in ["PASS", "WARN"] else 0.5,
        "total_rows": main_rec.get("total_rows"),
        "rows_math_passed": main_rec.get("rows_math_passed"),
        "rows_math_failed": main_rec.get("rows_math_failed"),
    }
    # Store invoice_level in the main reconciliation results dictionary
    reconciliation_results["invoice_level"] = invoice_level

    # Document-wide role metrics aggregated across all table regions
    document_role_metrics = {
        "footer_rows_count": row_role_metrics["footer_rows_count"],
        "tax_rows_count": row_role_metrics["tax_rows_count"],
        "by_table": dict(row_role_metrics.get("by_table", {})),
    }
    for tr in footer_reconcile_tables:
        table_role_metrics = classify_row_roles(tr)
        document_role_metrics["by_table"][tr.table_id] = table_role_metrics
        document_role_metrics["footer_rows_count"] += table_role_metrics.get("footer_rows_count", 0)
        document_role_metrics["tax_rows_count"] += table_role_metrics.get("tax_rows_count", 0)

    invoice_source_role_counts = _invoice_footer_tax_source_counts(invoice_reconciliation_result)
    document_footer_rows_count = max(
        document_role_metrics["footer_rows_count"],
        invoice_source_role_counts["footer_rows_count"],
    )
    document_tax_rows_count = max(
        document_role_metrics["tax_rows_count"],
        invoice_source_role_counts["tax_rows_count"],
    )
    vendor_template_prior = build_vendor_template_prior(ocr_blocks, table_bundle.main_table, table_regions)
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
        document_graph=document_graph,
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
            "graph_candidate_rows": document_graph.get("graph_candidate_rows", []),
            "graph_candidate_columns": document_graph.get("graph_candidate_columns", []),
            "graph_table_region": document_graph.get("graph_table_region", {}),
            "graph_confidence": document_graph.get("graph_confidence", 0.0),
            "metrics": {
                "raw_token_count": len(ocr_blocks),
                "table_count": len(table_regions),
                "topology_stability": stability_metrics,
                "topology_debug": topology_debug,
                "semantic_debug": semantic_debug,
                **table_routing_diagnostics,
                "column_anchor_debug": column_anchor_debug,
                "anchor_repair": anchor_repair,
                **_graph_telemetry_block(
                    document_graph=document_graph,
                    graph_fallback_used=graph_fallback_used,
                    graph_rejection_reason=graph_rejection_reason,
                    graph_fallback_cell_count=graph_fallback_cell_count,
                    graph_fallback_non_empty_cell_count=graph_fallback_non_empty_cell_count,
                    graph_fallback_mapped_token_count=graph_fallback_mapped_token_count,
                    graph_fallback_empty_cell_ratio=graph_fallback_empty_cell_ratio,
                    graph_fallback_item_row_count=graph_fallback_item_row_count,
                ),
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
                    "document_graph_metrics": document_graph.get("metrics", {}),
                    **_graph_telemetry_block(
                        document_graph=document_graph,
                        graph_fallback_used=graph_fallback_used,
                        graph_rejection_reason=graph_rejection_reason,
                        graph_fallback_cell_count=graph_fallback_cell_count,
                        graph_fallback_non_empty_cell_count=graph_fallback_non_empty_cell_count,
                        graph_fallback_mapped_token_count=graph_fallback_mapped_token_count,
                        graph_fallback_empty_cell_ratio=graph_fallback_empty_cell_ratio,
                        graph_fallback_item_row_count=graph_fallback_item_row_count,
                    ),
                },
                "document_graph_metrics": document_graph.get("metrics", {}),
                "vendor_template_prior": vendor_template_prior,
                "fast_fail": True,
                **tsr_metadata,
                "tsr_status": tsr_status_metric
            }
        }

    # --- Graph Fallback Effectiveness Telemetry ---
    if graph_fallback_used and table_bundle.main_table:
        fallback_tr = table_bundle.main_table
        graph_fallback_cell_count = len(fallback_tr.cells)
        fallback_mapped_tokens = set()
        fallback_empty_cells = 0
        for cell in fallback_tr.cells:
            if cell.mapped_block_ids:
                fallback_mapped_tokens.update(cell.mapped_block_ids)
            else:
                fallback_empty_cells += 1
        graph_fallback_non_empty_cell_count = graph_fallback_cell_count - fallback_empty_cells
        graph_fallback_mapped_token_count = len(fallback_mapped_tokens)
        graph_fallback_empty_cell_ratio = round(fallback_empty_cells / graph_fallback_cell_count, 4) if graph_fallback_cell_count > 0 else 0.0
        
        # Calculate item row count dynamically
        graph_fallback_item_row_count = sum(
            1 for row in fallback_tr.rows
            if getattr(row, "row_role", "unknown_row") == "item_row"
        )

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

    # Run the table region segmentation and anchor-based reconstruction
    from services.table_segmenter import TableSegmenter
    segmenter = TableSegmenter(table_regions, ocr_blocks)
    segmenter_results = segmenter.process()
    
    seg_debug = segmenter_results["debug"]
    
    # invoice_totals construction
    invoice_level = reconciliation_results.get("invoice_level") or {}
    invoice_totals = {
        "subtotal": invoice_level.get("footer_subtotal") or invoice_level.get("item_derived_subtotal") or 0.0,
        "discount": invoice_level.get("discount_total") or 0.0,
        "cgst": invoice_level.get("cgst_total") or 0.0,
        "sgst": invoice_level.get("sgst_total") or 0.0,
        "igst": invoice_level.get("igst_total") or 0.0,
        "gst_total": invoice_level.get("gst_total") or 0.0,
        "roundoff": invoice_level.get("roundoff") or 0.0,
        "grand_total": invoice_level.get("parsed_grand_total") or invoice_level.get("expected_grand_total") or 0.0
    }
    
    # metadata section
    metadata_section = {
        "invoice_id": invoice_level.get("item_table_region_id") or "unknown",
        "tsr_engine": tsr_metadata.get("tsr_engine") or "unknown",
        "topology_source": topology_source,
        "selected_topology_source": selected_topology_source,
        "invoice_confidence": confidence_hierarchy.get("invoice_confidence", 0.0),
        "total_tokens": raw_token_count,
        "reconstructed_line_count": recon_line_count,
        "image_properties": tsr_metadata.get("image_properties") or {}
    }

    return {
        "metadata": metadata_section,
        "tax_summary": segmenter_results["tax_summary"],
        "item_rows_clean": segmenter_results["item_rows_clean"],
        "scheme_rows": segmenter_results["scheme_rows"],
        "credit_note_rows": segmenter_results["credit_note_rows"],
        "invoice_totals": invoice_totals,
        "table_region_debug": seg_debug["table_region_debug"],
        "detected_region_boundaries": seg_debug["detected_region_boundaries"],
        "rejected_item_rows_with_reason": seg_debug["rejected_item_rows_with_reason"],
        "item_row_anchor_debug": seg_debug["item_row_anchor_debug"],
        "inferred_item_column_bands": seg_debug.get("inferred_item_column_bands", {}),
        "raw_pcode_anchor_candidates": seg_debug.get("raw_pcode_anchor_candidates", []),
        "accepted_pcode_anchors": seg_debug.get("accepted_pcode_anchors", []),
        "rejected_pcode_anchors": seg_debug.get("rejected_pcode_anchors", []),
        "item_row_y_ranges": seg_debug.get("item_row_y_ranges", []),
        "tokens_assigned_by_row_and_column": seg_debug.get("tokens_assigned_by_row_and_column", []),
        "tokens_rejected_by_column_rule": seg_debug.get("tokens_rejected_by_column_rule", []),
        "clean_item_row_validation_errors": seg_debug.get("clean_item_row_validation_errors", []),
        "reconstructed_rows": legacy_reconstructed_rows,
        "detected_table_rows": legacy_table_rows,
        "columns_extracted": True,
        "structured_tables": structured_tables,
        "detected_table_rows": legacy_table_rows,
        "columns_extracted": True,
        "structured_tables": structured_tables,
        "auxiliary_tables": auxiliary_tables,
        "semantic_markdown": semantic_markdown,
        "fast_fail": False,
        "topology_source": topology_source,
        "selected_topology_source": selected_topology_source,
        "invoice_confidence": confidence_hierarchy["invoice_confidence"],
        "graph_candidate_rows": document_graph.get("graph_candidate_rows", []),
        "graph_candidate_columns": document_graph.get("graph_candidate_columns", []),
        "graph_table_region": document_graph.get("graph_table_region", {}),
        "graph_confidence": document_graph.get("graph_confidence", 0.0),
        "metrics": {
            "raw_token_count": raw_token_count,
            "token_coverage": token_coverage_report.to_dict() if token_coverage_report else {},
            "token_coverage_debug": token_coverage_report.to_dict() if token_coverage_report else {},
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
            "footer_rows_count": document_footer_rows_count,
            "tax_rows_count": document_tax_rows_count,
            "row_role_metrics": {
                **row_role_metrics,
                "document_footer_rows_count": document_footer_rows_count,
                "document_tax_rows_count": document_tax_rows_count,
                "document_by_table": document_role_metrics["by_table"],
                "invoice_source_footer_rows_count": invoice_source_role_counts["footer_rows_count"],
                "invoice_source_tax_rows_count": invoice_source_role_counts["tax_rows_count"],
            },
            "topology_repairs": repair_metrics_total,
            **product_phase_shift_metrics,
            "row_validation": row_validation_results,
            "financial_reconciliation": reconciliation_results,
            "invoice_financial_reconciliation": invoice_reconciliation_result,
            "confidence_hierarchy": confidence_hierarchy,
            "document_graph_metrics": document_graph.get("metrics", {}),
            "vendor_template_prior": vendor_template_prior,
            **_graph_telemetry_block(
                document_graph=document_graph,
                graph_fallback_used=graph_fallback_used,
                graph_rejection_reason=graph_rejection_reason,
                graph_fallback_cell_count=graph_fallback_cell_count,
                graph_fallback_non_empty_cell_count=graph_fallback_non_empty_cell_count,
                graph_fallback_mapped_token_count=graph_fallback_mapped_token_count,
                graph_fallback_empty_cell_ratio=graph_fallback_empty_cell_ratio,
                graph_fallback_item_row_count=graph_fallback_item_row_count,
            ),
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
                "footer_rows_count": document_footer_rows_count,
                "tax_rows_count": document_tax_rows_count,
                "row_role_metrics": {
                    **row_role_metrics,
                    "document_footer_rows_count": document_footer_rows_count,
                    "document_tax_rows_count": document_tax_rows_count,
                    "document_by_table": document_role_metrics["by_table"],
                    "invoice_source_footer_rows_count": invoice_source_role_counts["footer_rows_count"],
                    "invoice_source_tax_rows_count": invoice_source_role_counts["tax_rows_count"],
                },
                **product_phase_shift_metrics,
                "confidence_variance": confidence_hierarchy.get("confidence_variance", {}),
                "document_graph_metrics": document_graph.get("metrics", {}),
                **_graph_telemetry_block(
                    document_graph=document_graph,
                    graph_fallback_used=graph_fallback_used,
                    graph_rejection_reason=graph_rejection_reason,
                    graph_fallback_cell_count=graph_fallback_cell_count,
                    graph_fallback_non_empty_cell_count=graph_fallback_non_empty_cell_count,
                    graph_fallback_mapped_token_count=graph_fallback_mapped_token_count,
                    graph_fallback_empty_cell_ratio=graph_fallback_empty_cell_ratio,
                    graph_fallback_item_row_count=graph_fallback_item_row_count,
                ),
            },
            "fast_fail": False,
            **tsr_metadata,
            "tsr_status": tsr_status_metric
        }
    }
