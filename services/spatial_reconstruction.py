from typing import List, Dict, Any
from core.logger import logger
from utils.debug_visualizer import draw_debug_visualization

from services.layout_pipeline.geometry import process_blocks
from services.layout_pipeline.skew import apply_skew_normalization
from services.layout_pipeline.ioa_mapping import map_tokens_to_cells
from services.layout_pipeline.semantic_column_classifier import SemanticColumnClassifier
from services.layout_pipeline.stability_engine import TopologyStabilityEngine
from services.layout_pipeline.row_validator import RowValidator
from services.layout_pipeline.multiline_merging import merge_multiline_table_rows, update_row_stability_scores
from services.layout_pipeline.confidence import ConfidenceCompositor
from services.layout_pipeline.row_roles import classify_row_roles
from services.topology.column_stabilizer import ColumnStabilizer
from services.financial_reconciler import FinancialReconciler
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
    topology_source = "ppstructure"  # Track which engine produced the canonical topology
    heuristic_fallback_used = False
    ppstructure_regions_attempted = 0
    ppstructure_cells_attempted = 0

    if reconstruct_mode == "compare":
        logger.info("Running in compare mode. Executing multiple engines.")
        heuristic_engine = HeuristicTSREngine()
        pp_engine = PPStructure_TSREngine()

        heuristic_regions, _ = heuristic_engine.detect_tables(ocr_blocks)
        pp_regions, tsr_metadata = pp_engine.detect_tables(ocr_blocks, image=image)
        ppstructure_regions_attempted = len(pp_regions)
        ppstructure_cells_attempted = sum(len(tr.cells) for tr in pp_regions)

        logger.info(f"[COMPARE] Heuristic detected {len(heuristic_regions)} tables.")
        logger.info(f"[COMPARE] PP-Structure detected {len(pp_regions)} tables.")
        table_regions = pp_regions
    elif reconstruct_mode == "heuristic":
        # Explicit heuristic mode (debug only)
        engine = HeuristicTSREngine()
        table_regions, tsr_metadata = engine.detect_tables(ocr_blocks)
        topology_source = "heuristic"
        heuristic_fallback_used = False
        for tr in table_regions:
            tr.topology_confidence = 0.5  # Degraded confidence for heuristic-derived topology
    else:
        # PRIMARY PATH: PPStructure with confidence-gated fallback
        pp_engine = PPStructure_TSREngine()
        table_regions, tsr_metadata = pp_engine.detect_tables(ocr_blocks, image=image)
        ppstructure_regions_attempted = len(table_regions)
        ppstructure_cells_attempted = sum(len(tr.cells) for tr in table_regions)

        # --- CONFIDENCE GATE ---
        # Evaluate TSR output quality. If PPStructure fails or produces unreliable topology,
        # fall back to heuristic engine rather than proceeding with garbage structure.
        tsr_confidence = _compute_tsr_confidence(table_regions)

        if tsr_confidence < 0.4:
            logger.warning(
                f"[CONFIDENCE GATE] TSR confidence {tsr_confidence:.2f} below threshold (0.40). "
                f"Falling back to heuristic topology."
            )
            heuristic_engine = HeuristicTSREngine()
            table_regions, _ = heuristic_engine.detect_tables(ocr_blocks)
            topology_source = "heuristic_fallback"
            heuristic_fallback_used = True
            for tr in table_regions:
                tr.topology_confidence = 0.5  # Degraded confidence tag

    canonical_cell_count = sum(len(tr.cells) for tr in table_regions)
    tsr_contribution_percent = 100.0 if topology_source == "ppstructure" and canonical_cell_count else 0.0
    tsr_metadata.update({
        "ppstructure_regions_attempted": ppstructure_regions_attempted,
        "ppstructure_cells_attempted": ppstructure_cells_attempted,
        "canonical_region_count": len(table_regions),
        "canonical_cell_count": canonical_cell_count,
        "tsr_contribution_percent": tsr_contribution_percent,
        "heuristic_fallback_used": heuristic_fallback_used,
        "heuristic_fallback_count": 1 if heuristic_fallback_used else 0,
    })

    # --- FAST-FAIL: No topology at all (both engines failed) ---
    if not table_regions:
        logger.warning("[FAST FAIL] Zero table regions from both PPStructure and heuristic fallback.")
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
                **tsr_metadata
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
    map_tokens_to_cells(ocr_blocks, table_regions)

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
    table_bundle = route_tables(table_regions, classifications)

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

    semantic_results = {}
    classifier = SemanticColumnClassifier()
    semantic_rejection_total = 0
    semantic_outlier_total = 0
    hard_deleted_cells_total = 0
    columns_inferred_from_item_rows_only = True
    for tr in analysis_targets:
        semantic_results[tr.table_id] = classifier.enrich_region_metadata(tr)
        rejection_summary = semantic_results[tr.table_id].get("_rejection_summary", {})
        inference_summary = semantic_results[tr.table_id].get("_inference_summary", {})
        semantic_rejection_total += rejection_summary.get("semantic_rejection_count", 0)
        semantic_outlier_total += rejection_summary.get("semantic_outlier_count", 0)
        hard_deleted_cells_total += rejection_summary.get("hard_deleted_cells_count", 0)
        columns_inferred_from_item_rows_only = (
            columns_inferred_from_item_rows_only
            and inference_summary.get("columns_inferred_from_item_rows_only", False)
        )

    stability_engine = TopologyStabilityEngine()
    stability_metrics = stability_engine.compute_stability(analysis_targets)

    logger.info(f"Topology Confidence Check: Overall Score={stability_metrics.get('overall', 0)}")

    # Step 7: Row-Level Validation (semantic + financial per-row)
    row_validator = RowValidator(semantic_column_cache=semantic_results)
    row_validation_results = row_validator.validate_all(analysis_targets)

    # Step 8: Financial Reconciliation (subtotal/grand total verification)
    # Note: We reconcile the MAIN table specifically
    target_reconcile = [table_bundle.main_table]

    reconciler = FinancialReconciler(semantic_column_cache=semantic_results)
    reconciliation_results = reconciler.reconcile_all(target_reconcile)

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
                "instrumentation": {
                    "tsr_contribution_percent": tsr_contribution_percent,
                    "heuristic_fallback_used": heuristic_fallback_used,
                    "heuristic_fallback_count": 1 if heuristic_fallback_used else 0,
                    "semantic_rejection_count": semantic_rejection_total,
                    "semantic_outlier_count": semantic_outlier_total,
                    "hard_deleted_cells_count": hard_deleted_cells_total,
                    "columns_inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
                    "item_rows_count": row_role_metrics["item_rows_count"],
                    "footer_rows_count": row_role_metrics["footer_rows_count"],
                    "tax_rows_count": row_role_metrics["tax_rows_count"],
                    "row_role_metrics": row_role_metrics,
                    "confidence_variance": confidence_hierarchy.get("confidence_variance", {}),
                },
                "fast_fail": True,
                **tsr_metadata
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
            "column_semantic_cache": semantic_results,
            "semantic_rejection_count": semantic_rejection_total,
            "semantic_outlier_count": semantic_outlier_total,
            "hard_deleted_cells_count": hard_deleted_cells_total,
            "columns_inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
            "item_rows_count": row_role_metrics["item_rows_count"],
            "footer_rows_count": row_role_metrics["footer_rows_count"],
            "tax_rows_count": row_role_metrics["tax_rows_count"],
            "row_role_metrics": row_role_metrics,
            "topology_repairs": repair_metrics_total,
            "row_validation": row_validation_results,
            "financial_reconciliation": reconciliation_results,
            "confidence_hierarchy": confidence_hierarchy,
            "instrumentation": {
                "tsr_contribution_percent": tsr_contribution_percent,
                "heuristic_fallback_used": heuristic_fallback_used,
                "heuristic_fallback_count": 1 if heuristic_fallback_used else 0,
                "semantic_rejection_count": semantic_rejection_total,
                "semantic_outlier_count": semantic_outlier_total,
                "hard_deleted_cells_count": hard_deleted_cells_total,
                "columns_inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
                "item_rows_count": row_role_metrics["item_rows_count"],
                "footer_rows_count": row_role_metrics["footer_rows_count"],
                "tax_rows_count": row_role_metrics["tax_rows_count"],
                "row_role_metrics": row_role_metrics,
                "confidence_variance": confidence_hierarchy.get("confidence_variance", {}),
            },
            "fast_fail": False,
            **tsr_metadata
        }
    }
