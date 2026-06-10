# NOTE: This module is part of the legacy extraction path.
# It should remain available as fallback during Azure Document Intelligence migration.
# Do not delete until Azure shadow comparison proves replacement quality.

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
from services.layout_pipeline.column_anchor_detector import detect_column_anchors
from services.layout_pipeline.invoice_diagnostics import attach_invoice_diagnostics
from services.layout_pipeline.reconstruction_diagnostics import (
    _box_to_dict,
    _build_topology_debug,
    _graph_telemetry_block,
    _summarize_column_projection_debug,
    _token_flags,
)
from services.layout_pipeline.reconstruction_metrics import (
    build_row_handoff_summary,
    build_tsr_candidate_decision_summary,
    _compute_tsr_confidence,
    _invoice_footer_tax_source_counts,
)

from services.topology.column_stabilizer import ColumnStabilizer
from services.financial_reconciler import FinancialReconciler, reconcile_invoice_financials
from services.table_classifier import TableClassifier, route_tables
from services.table_candidate_sanity import select_valid_table_candidate

from services.tsr.heuristic_tsr import HeuristicTSREngine
from services.tsr.future_ppstructure import PPStructure_TSREngine
from services.layout_pipeline.wide_table_detector import detect_wide_table, WideTableEvidence
from services.layout_pipeline.header_anchor import detect_header_row, expand_table_columns_from_header
from services.layout_pipeline.footer_kv_extractor import extract_footer_kv
from services.layout_pipeline.graph_fallback import build_graph_fallback_table_region


def _enforce_ordering_invariants(table_regions):
    """
    Enforce universal physical ordering: columns sorted by min_x ascending
    (leftmost = col_0), rows sorted by min_y ascending (topmost = row_0).
    Cell references are remapped to match the new IDs.
    """
    for tr in table_regions:
        # Sort columns left-to-right by physical min_x
        tr.columns.sort(key=lambda c: c.geometry.min_x if c.geometry else 0)
        col_id_remap = {}
        for i, col in enumerate(tr.columns):
            old_id = col.col_id
            new_id = f"col_{i}"
            col_id_remap[old_id] = new_id
            col.col_id = new_id

        # Sort rows top-to-bottom by physical min_y
        tr.rows.sort(key=lambda r: r.geometry.min_y if r.geometry else 0)
        row_id_remap = {}
        for i, row in enumerate(tr.rows):
            old_id = row.row_id
            new_id = f"row_{i}"
            row_id_remap[old_id] = new_id
            row.row_id = new_id

        # Update cell references to match remapped IDs
        for cell in tr.cells:
            cell.col_id = col_id_remap.get(cell.col_id, cell.col_id)
            cell.row_id = row_id_remap.get(cell.row_id, cell.row_id)

    logger.info(
        f"[ORDERING] Enforced ordering invariants on {len(table_regions)} table(s)"
    )




def _dominance_score_confidence(score: float) -> float:
    return max(0.0, min(0.99, (float(score) + 200.0) / 700.0))


def _image_bounds(image: Any, blocks: List[Dict[str, Any]]) -> tuple[float | None, float | None]:
    if image is not None and getattr(image, "size", None):
        try:
            return float(image.size[0]), float(image.size[1])
        except Exception:
            pass
    xs = []
    ys = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        geom = block.get("normalized_geometry") or block.get("geometry")
        if isinstance(geom, dict):
            for key in ("min_x", "max_x"):
                if geom.get(key) is not None:
                    xs.append(float(geom[key]))
            for key in ("min_y", "max_y"):
                if geom.get(key) is not None:
                    ys.append(float(geom[key]))
        polygon = block.get("polygon") if isinstance(block, dict) else None
        if isinstance(polygon, list):
            for point in polygon:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
    return (max(xs) if xs else None, max(ys) if ys else None)


def filter_graph_rows(raw_graph_rows: list, tsr_metadata: dict) -> list:
    """
    Filters graph candidate rows, blocking footer/tax rows from preservation override
    and tracking them in diagnostics/telemetry.
    """
    import re
    from core.logger import logger

    graph_rows = []
    graph_rows_raw_count = len(raw_graph_rows)
    graph_rows_dropped_reasons = {}

    # Telemetry & Override counters
    graph_rows_preserved_by_header_evidence = 0
    graph_rows_preserved_by_product_evidence = 0
    graph_rows_dropped_detail_sample = []
    graph_preservation_blocked_footer_tax_count = 0
    graph_preservation_blocked_examples = []

    # Compile patterns and filters for overrides
    header_tokens_pattern = re.compile(
        r"\b(PRODUCT|ITEM|DESCRIPTION|BATCH|EXP|EXPIRY|HSN|QTY|MRP|RATE|AMOUNT)\b"
    )
    footer_tax_labels_pattern = re.compile(
        r"\b(CGST|SGST|IGST|GST|taxable|tax\s+amt|total|grand\s+total|net\s+amount|round\s+off|amount\s+in\s+words|less\s+td|add\s+sgst|add\s+cgst|non-taxable|taxable\s+amt)\b",
        re.IGNORECASE
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

        if hint in ("footer_candidate", "metadata_candidate", "tax_candidate", "tax_summary_candidate", "footer_summary_row", "tax_summary_row"):
            normally_dropped = True
            drop_reason = f"row_type_hint_{hint}"
        elif hint not in ("item_candidate", "header_candidate"):
            normally_dropped = True
            drop_reason = f"row_type_hint_{hint}"

        if normally_dropped:
            # Preservation Overrides
            is_blocked_footer_tax = (
                hint in ("footer_candidate", "tax_summary_candidate", "footer_summary_row", "tax_summary_row", "metadata_candidate") or
                footer_tax_labels_pattern.search(text) is not None
            )
            is_real_item_header = has_strong_header_tokens and (
                "PRODUCT" in text_upper or
                "ITEM" in text_upper or
                "DESCRIPTION" in text_upper or
                "MEDICINE" in text_upper or
                "DRUG" in text_upper or
                "PARTICULARS" in text_upper
            )

            # Rule 1: Header Preservation Override
            if has_strong_header_tokens:
                if is_blocked_footer_tax and not is_real_item_header:
                    graph_preservation_blocked_footer_tax_count += 1
                    if len(graph_preservation_blocked_examples) < 10:
                        graph_preservation_blocked_examples.append({
                            "row_id": row_id,
                            "text": text[:100],
                            "hint": hint,
                            "rule_blocked": "Header Rule"
                        })
                    logger.info(f"[PRESERVATION BLOCKED] Blocked row_id={row_id} from Header Rule due to footer/tax flag. Hint={hint}. Text={text[:60]}")
                else:
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
                if is_blocked_footer_tax:
                    graph_preservation_blocked_footer_tax_count += 1
                    if len(graph_preservation_blocked_examples) < 10:
                        graph_preservation_blocked_examples.append({
                            "row_id": row_id,
                            "text": text[:100],
                            "hint": hint,
                            "rule_blocked": "Product Context Rule"
                        })
                    logger.info(f"[PRESERVATION BLOCKED] Blocked row_id={row_id} from Product Context Rule due to footer/tax flag. Hint={hint}. Text={text[:60]}")
                else:
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
        f"Preserved Products: {graph_rows_preserved_by_product_evidence} | "
        f"Blocked Footer/Tax Preservations: {graph_preservation_blocked_footer_tax_count}"
    )

    # Telemetry
    tsr_metadata["graph_rows_raw_count"] = graph_rows_raw_count
    tsr_metadata["graph_rows_filtered_count"] = graph_rows_filtered_count
    tsr_metadata["graph_rows_dropped_count"] = graph_rows_dropped_count
    tsr_metadata["graph_rows_dropped_reasons"] = graph_rows_dropped_reasons
    tsr_metadata["graph_rows_preserved_by_header_evidence"] = graph_rows_preserved_by_header_evidence
    tsr_metadata["graph_rows_preserved_by_product_evidence"] = graph_rows_preserved_by_product_evidence
    tsr_metadata["graph_rows_dropped_detail_sample"] = graph_rows_dropped_detail_sample
    tsr_metadata["graph_preservation_blocked_footer_tax_count"] = graph_preservation_blocked_footer_tax_count
    tsr_metadata["graph_preservation_blocked_examples"] = graph_preservation_blocked_examples

    return graph_rows


def reconstruct_layout(blocks: List[Dict[str, Any]], debug: bool = False, reconstruct_mode: str = "ppstructure", image: Any = None, benchmark_mode: bool = False, allow_salvage: bool = False) -> Dict[str, Any]:
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

    # Pre-reconstruction wide table block splitting
    from services.layout_pipeline.wide_table_detector import detect_wide_table, split_fused_blocks
    raw_wide_table_evidence = detect_wide_table(ocr_blocks, [])
    if raw_wide_table_evidence.is_wide:
        logger.info("[WIDE TABLE] Pre-reconstruction wide table detected. Splitting fused blocks...")
        ocr_blocks = split_fused_blocks(ocr_blocks)

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
    document_graph = {
        "graph_candidate_rows": [],
        "graph_candidate_columns": [],
        "graph_table_region": {},
        "graph_confidence": 0.0,
        "metrics": {},
    }

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
    tsr_candidate_decision = None
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
        return attach_invoice_diagnostics({
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
                "tsr_candidate_decision": build_tsr_candidate_decision_summary(
                    selected_topology_source=selected_topology_source,
                    selected_candidate_reason="zero_tables",
                    tsr_status_metric=tsr_status_metric,
                    tsr_metadata=tsr_metadata,
                ),
                **tsr_metadata,
                "tsr_status": tsr_status_metric
            }
        }, invoice_id="unknown")

    tsr_metadata["topology_source"] = topology_source

    # Step 3.5: Wide-Table Evidence Detection (topology-gated)
    wide_table_evidence = detect_wide_table(ocr_blocks, table_regions)
    tsr_metadata["wide_table_mode"] = wide_table_evidence.is_wide
    tsr_metadata["wide_table_confidence"] = wide_table_evidence.confidence
    tsr_metadata["wide_table_signals"] = wide_table_evidence.signals
    tsr_metadata["wide_table_estimated_column_count"] = wide_table_evidence.estimated_column_count
    if wide_table_evidence.is_wide:
        before_split_count = len(ocr_blocks)
        ocr_blocks = split_fused_blocks(ocr_blocks)
        tsr_metadata["wide_table_split_blocks_before_mapping"] = {
            "before": before_split_count,
            "after": len(ocr_blocks),
            "created": max(0, len(ocr_blocks) - before_split_count),
        }

    # Step 3.6: Header-derived expansion for collapsed wide-table topology.
    header_expansion_diagnostics = {}
    if wide_table_evidence.is_wide:
        for tr in table_regions:
            if len(tr.columns) >= 10:
                continue
            header_expansion_diagnostics[tr.table_id] = expand_table_columns_from_header(
                tr,
                ocr_blocks,
                min_columns=10,
            )
        if header_expansion_diagnostics:
            tsr_metadata["wide_table_header_expansion"] = header_expansion_diagnostics
            failed = [
                table_id
                for table_id, diag in header_expansion_diagnostics.items()
                if not diag.get("expanded")
            ]
            if failed:
                tsr_metadata["wide_table_column_expansion_failed"] = True
                tsr_metadata["wide_table_column_expansion_failure_tables"] = failed

    # Step 4: PRE-ASSIGNMENT Geometry Stabilization (geometry-only, no text dependency)
    stabilizer = ColumnStabilizer()
    repair_metrics_total = {"phantom_column_count": 0, "repaired_columns": 0, "semantic_column_drift": 0, "numeric_merge_blocked_count": 0}
    for tr in table_regions:
        rep = stabilizer.stabilize_region(tr, wide_table_evidence=wide_table_evidence)
        for k, v in rep.items():
            repair_metrics_total[k] = repair_metrics_total.get(k, 0) + v

    # Step 5: Cell Mapping (IoA) — runs AFTER geometry stabilization
    map_tokens_to_cells(ocr_blocks, table_regions, debug=(debug and not benchmark_mode))

    # Step 5.0.1: Enforce Universal Ordering Invariants
    # Columns sorted by min_x (leftmost = col_0), rows by min_y (topmost = row_0).
    _enforce_ordering_invariants(table_regions)

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

    graph_rows = filter_graph_rows(raw_graph_rows, tsr_metadata)

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
            
        # Classify row roles first to ensure column semantics classification can identify item rows
        role_metrics = classify_row_roles(tr)

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
        
        status = temp_invoice_recon.get("status", "FAIL")
        math_score = 0.0
        if len(missing_req_cols) > 0:
            math_score = 0.0
        elif status == "PASS":
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

        # Row Role Metrics
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
        
        # Check for required semantic columns checklist and populate on tr
        required_list = ['product', 'quantity', 'rate', 'amount', 'batch', 'expiry']
        present_fields = []
        missing_fields = []
        for rf in required_list:
            if rf == 'product':
                is_present = 'product' in final_vals or 'drug_name' in final_vals
            elif rf == 'quantity':
                is_present = any(q in final_vals for q in ('quantity', 'qty', 'free_quantity'))
            else:
                is_present = rf in final_vals
                
            if is_present:
                present_fields.append(rf)
            else:
                missing_fields.append(rf)
                
        tr.required_fields_present = present_fields
        tr.required_fields_missing = missing_fields
        
        # Calculate representability_score
        rep_score = len(present_fields) / len(required_list)
        if wide_table_evidence.is_wide and len(tr.columns) < 10:
            rep_score *= 0.5
        num_unknown = sum(1 for v in final_semantics.values() if v == 'unknown')
        if len(tr.columns) > 0 and (num_unknown / len(tr.columns)) > 0.5:
            rep_score *= 0.6
            
        tr.representability_score = round(max(0.0, min(1.0, rep_score)), 3)

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
        try:
            graph_candidate = build_graph_fallback_table_region(
                graph_rows=graph_rows,
                graph_cols=graph_cols,
                graph_confidence=document_graph.get("graph_confidence", 0.5)
            )
        except Exception as e:
            logger.warning(
                f"[GRAPH FALLBACK ERROR] Failed to build graph fallback table region: {str(e)}",
                exc_info=True
            )
            graph_candidate = None

        if graph_candidate:
            graph_score, graph_metrics = evaluate_candidate_table(graph_candidate, is_graph=True)

    graph_selection_blocked_reason = None
    processed_width, processed_height = _image_bounds(image, ocr_blocks)
    candidate_inputs = [
        ("heuristic_anchor", heuristic_candidate, heuristic_score, heuristic_metrics),
    ]
    if graph_candidate is not None:
        candidate_inputs.append(("document_graph_candidate", graph_candidate, graph_score, graph_metrics))
    seen_candidate_ids = {
        getattr(candidate, "table_id", None)
        for _, candidate, _, _ in candidate_inputs
        if candidate is not None
    }
    routing_scores_by_id = {
        str(item.get("table_id")): item
        for item in table_routing_diagnostics.get("main_table_candidate_scores", [])
        if isinstance(item, dict) and item.get("table_id")
    }
    for candidate in table_regions:
        table_id = getattr(candidate, "table_id", None)
        if table_id in seen_candidate_ids:
            continue
        routing_score = routing_scores_by_id.get(str(table_id), {})
        candidate_inputs.append(
            (
                "routed_table_candidate",
                candidate,
                routing_score.get("score"),
                {
                    "item_rows_count": (routing_score.get("role_counts") or {}).get("item_rows_count"),
                    "semantic_columns": getattr(candidate, "semantic_column_cache", None),
                },
            )
        )

    table_sanity_selection = select_valid_table_candidate(
        candidate_inputs,
        processed_width=processed_width,
        processed_height=processed_height,
        ocr_block_count=len(ocr_blocks),
        allow_salvage=allow_salvage,
    )
    tsr_metadata["table_sanity"] = table_sanity_selection
    tsr_metadata["selected_table_available"] = table_sanity_selection["selected_table_available"]
    tsr_metadata["selected_main_table_id"] = table_sanity_selection["selected_candidate_id"]
    tsr_metadata["rejected_table_candidates"] = table_sanity_selection["rejected_candidates"]

    if not table_sanity_selection["selected_table_available"]:
        logger.warning("[TABLE SANITY] No valid table candidate survived structural checks.")
        selected_topology_source = "none"
        selected_candidate_reason = "no_valid_candidate"
        tsr_candidate_decision = build_tsr_candidate_decision_summary(
            heuristic_candidate=heuristic_candidate,
            heuristic_metrics=heuristic_metrics,
            heuristic_score=heuristic_score,
            graph_candidate=graph_candidate,
            graph_metrics=graph_metrics,
            graph_score=graph_score,
            graph_selection_blocked_reason=graph_selection_blocked_reason,
            selected_topology_source=selected_topology_source,
            selected_candidate_reason=selected_candidate_reason,
            tsr_status_metric=tsr_status_metric,
            tsr_metadata=tsr_metadata,
        )
        tsr_candidate_decision["selected_table_available"] = False
        tsr_candidate_decision["rejected_candidates"] = table_sanity_selection["rejected_candidates"]
        topology_debug = _build_topology_debug(ocr_blocks, table_regions, [], {}, document_graph=document_graph)
        return attach_invoice_diagnostics({
            "reconstructed_rows": [],
            "detected_table_rows": [],
            "columns_extracted": False,
            "structured_tables": [tr.model_dump(mode='json') for tr in table_regions],
            "semantic_markdown": "",
            "fast_fail": True,
            "fast_fail_reason": "no_valid_table_candidate",
            "topology_source": topology_source,
            "selected_topology_source": selected_topology_source,
            "selected_table_available": False,
            "selected_table_id": None,
            "graph_candidate_rows": document_graph.get("graph_candidate_rows", []),
            "graph_candidate_columns": document_graph.get("graph_candidate_columns", []),
            "graph_table_region": document_graph.get("graph_table_region", {}),
            "graph_confidence": document_graph.get("graph_confidence", 0.0),
            "metrics": {
                "raw_token_count": len(ocr_blocks),
                "table_count": len(table_regions),
                "topology_debug": topology_debug,
                "selected_table_available": False,
                "no_valid_table_candidate": True,
                "table_sanity": table_sanity_selection,
                "candidate_decision": tsr_candidate_decision,
                "tsr_candidate_decision": tsr_candidate_decision,
                **table_routing_diagnostics,
                **tsr_metadata,
                "tsr_status": tsr_status_metric,
            }
        }, invoice_id="unknown")

    if table_sanity_selection["selected_candidate_id"] != getattr(table_bundle.main_table, "table_id", None):
        selected_id = table_sanity_selection["selected_candidate_id"]
        replacement = graph_candidate if getattr(graph_candidate, "table_id", None) == selected_id else None
        if replacement is None:
            replacement = next((tr for tr in table_regions if tr.table_id == selected_id), None)
        if replacement is not None:
            table_bundle.main_table = replacement
            selected_topology_source = table_sanity_selection["selected_source"] or "heuristic_anchor"
            selected_candidate_reason = table_sanity_selection["selected_reason"]
            logger.warning("[TABLE SANITY] Replaced selected main table with valid candidate %s", selected_id)

    # Deterministic Blocking Rules
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
    selected_topology_source = table_sanity_selection.get("selected_source") or "heuristic_anchor"
    selected_candidate_reason = table_sanity_selection.get("selected_reason") or "default_heuristic"

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
    tsr_candidate_decision = build_tsr_candidate_decision_summary(
        heuristic_candidate=heuristic_candidate,
        heuristic_metrics=heuristic_metrics,
        heuristic_score=heuristic_score,
        graph_candidate=graph_candidate,
        graph_metrics=graph_metrics,
        graph_score=graph_score,
        graph_selection_blocked_reason=graph_selection_blocked_reason,
        selected_topology_source=selected_topology_source,
        selected_candidate_reason=selected_candidate_reason,
        tsr_status_metric=tsr_status_metric,
        tsr_metadata=tsr_metadata,
    )

    # Promote graph candidate if selected
    if selected_topology_source == "document_graph_candidate":
        table_bundle.main_table = graph_candidate
        if graph_candidate not in table_regions:
            table_regions.append(graph_candidate)
        topology_source = "document_graph_candidate"

    # Emergency Fallback Safety Net (Fallback Engine)
    should_fallback = False
    trigger_reason = None

    should_fallback = False
    trigger_reason = None

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

    column_band_rescue_candidate = None
    column_band_rescue_metrics = {
        "column_band_rescue_selected": False,
        "column_band_rescue_confidence": 0.0,
        "column_band_rescued_rows_count": 0,
        "column_band_rescue_item_subtotal_preview": 0.0,
        "column_band_rescue_rejected_reason": "disabled_in_production",
    }

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

    semantic_results = {}
    classifier = SemanticColumnClassifier()
    
    # Run semantic input sanitizer diagnostics before classification
    from services.layout_pipeline.semantic_input_sanitizer import sanitize_rows_for_semantic_inference
    sanitizer_diagnostics = {
        "input_row_count": 0,
        "item_row_count": 0,
        "excluded_footer_tax_count": 0,
        "excluded_examples": []
    }
    for tr in analysis_targets:
        tr_roles = {r.row_id: getattr(r, "row_role", "unknown_row") for r in tr.rows}
        san_res = sanitize_rows_for_semantic_inference(tr.rows, cells=tr.cells, row_roles=tr_roles)
        metrics = san_res["metrics"]
        sanitizer_diagnostics["input_row_count"] += metrics["input_row_count"]
        sanitizer_diagnostics["item_row_count"] += metrics["item_row_count"]
        sanitizer_diagnostics["excluded_footer_tax_count"] += metrics["excluded_count"]
        sanitizer_diagnostics["excluded_examples"].extend(metrics["excluded_examples"])

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

    product_phase_shift_metrics = {
        "product_numeric_phase_shift_detected": False,
        "product_phase_shift_repair_count": 0,
        "product_phase_shift_source": "not_evaluated",
        "product_phase_shift_affected_rows": [],
    }

    # Build normalized item rows before financial reconciliation so row math can
    # use guarded selected-graph quantity repairs without re-running reconciliation.
    from services.table_segmenter import TableSegmenter, build_item_row_alignment_diagnostics
    segmenter = TableSegmenter(table_regions, ocr_blocks)
    selected_main_table = table_bundle.main_table if table_bundle else None
    selected_main_table_semantics = (
        final_column_semantics.get(selected_main_table.table_id, {})
        if selected_main_table is not None
        else {}
    )
    selected_main_table_resolution = {}
    if selected_main_table is not None:
        selected_main_table_resolution = semantic_results.get(selected_main_table.table_id, {}).get("_inference_summary", {}).get("semantic_role_resolution", {})
    segmenter_results = segmenter.process(
        selected_topology_source=selected_topology_source,
        selected_main_table=selected_main_table,
        column_semantics=selected_main_table_semantics,
    )
    seg_debug = segmenter_results["debug"]
    item_row_source_selection = (
        segmenter_results.get("item_row_source_selection")
        or seg_debug.get("item_row_source_selection", {})
    )

    # Step 8: Financial Reconciliation (subtotal/grand total verification)
    # Note: We reconcile the MAIN table specifically
    target_reconcile = [table_bundle.main_table]

    reconciler = FinancialReconciler(
        semantic_column_cache=semantic_results,
        item_rows_clean=segmenter_results.get("item_rows_clean"),
    )
    reconciliation_results = reconciler.reconcile_all(target_reconcile)
    main_table_id = table_bundle.main_table.table_id
    footer_reconcile_tables = [
        tr for tr in table_regions
        if tr.table_id != main_table_id
    ]
    invoice_reconciliation_result = reconcile_invoice_financials(
        reconciliation_results.get(main_table_id, {}),
        table_regions,
        graph_candidate_rows=document_graph.get("graph_candidate_rows"),
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
        # Consolidated credit/debit note adjustment
        "cr_dr_note": invoice_reconciliation_result.get("cr_dr_note"),
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
        # Rich label-value pairing diagnostics tree for Indian pharma footer reconciliation
        "footer_label_value_diagnostics": invoice_reconciliation_result.get("footer_label_value_diagnostics"),

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
    vendor_template_prior = {}
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
        return attach_invoice_diagnostics({
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
                "tsr_candidate_decision": tsr_candidate_decision,
                **tsr_metadata,
                "tsr_status": tsr_status_metric
            }
        }, invoice_id="unknown")

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

    row_handoff_summary = build_row_handoff_summary(
        selected_topology_source=selected_topology_source,
        topology_source=topology_source,
        selected_main_table=selected_main_table,
        item_rows_clean=segmenter_results.get("item_rows_clean"),
        clean_item_row_validation_errors=seg_debug.get("clean_item_row_validation_errors", []),
        reconciliation_result=main_rec,
        graph_metrics=graph_metrics,
        heuristic_metrics=heuristic_metrics,
    )
    item_row_alignment_diagnostics = build_item_row_alignment_diagnostics(
        selected_topology_source=selected_topology_source,
        selected_main_table=selected_main_table,
        item_rows_clean=segmenter_results.get("item_rows_clean"),
        column_semantics=selected_main_table_semantics,
    )
    
    # invoice_totals construction
    invoice_level = reconciliation_results.get("invoice_level") or {}
    invoice_totals = {
        "subtotal": invoice_level.get("footer_subtotal") or invoice_level.get("item_derived_subtotal") or 0.0,
        "discount": invoice_level.get("discount_total") or 0.0,
        "cgst": invoice_level.get("cgst_total") or 0.0,
        "sgst": invoice_level.get("sgst_total") or 0.0,
        "igst": invoice_level.get("igst_total") or 0.0,
        "gst_total": invoice_level.get("gst_total") or 0.0,
        "roundoff": abs(invoice_level.get("roundoff") or 0.0),
        "cr_dr_note": invoice_level.get("cr_dr_note") or 0.0,
        "grand_total": invoice_level.get("parsed_grand_total") or invoice_level.get("expected_grand_total") or 0.0
    }
    
    # metadata section
    metadata_section = {
        "invoice_id": invoice_level.get("item_table_region_id") or "unknown",
        "tsr_engine": tsr_metadata.get("tsr_engine") or "unknown",
        "topology_source": topology_source,
        "selected_topology_source": selected_topology_source,
        "selected_table_available": bool(tsr_metadata.get("selected_table_available", True)),
        "selected_table_id": tsr_metadata.get("selected_main_table_id"),
        "invoice_confidence": confidence_hierarchy.get("invoice_confidence", 0.0),
        "total_tokens": raw_token_count,
        "reconstructed_line_count": recon_line_count,
        "image_properties": tsr_metadata.get("image_properties") or {}
    }

    final_result = {
        "metadata": metadata_section,
        "tax_summary": segmenter_results["tax_summary"],
        "item_rows_clean": segmenter_results["item_rows_clean"],
        "scheme_rows": segmenter_results["scheme_rows"],
        "credit_note_rows": segmenter_results["credit_note_rows"],
        "invoice_totals": invoice_totals,
        "semantic_input_sanitizer": sanitizer_diagnostics,
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
        "selected_table_available": bool(tsr_metadata.get("selected_table_available", True)),
        "selected_table_id": tsr_metadata.get("selected_main_table_id"),
        "invoice_confidence": confidence_hierarchy["invoice_confidence"],
        "graph_candidate_rows": document_graph.get("graph_candidate_rows", []),
        "graph_candidate_columns": document_graph.get("graph_candidate_columns", []),
        "graph_table_region": document_graph.get("graph_table_region", {}),
        "graph_confidence": document_graph.get("graph_confidence", 0.0),
        "metrics": {
            "semantic_column_results": semantic_results,
            "raw_token_count": raw_token_count,
            "token_coverage": token_coverage_report.to_dict() if token_coverage_report else {},
            "token_coverage_debug": token_coverage_report.to_dict() if token_coverage_report else {},
            "reconstructed_line_count": recon_line_count,
            "numeric_merge_suspicions": int(numeric_merge_suspicions),
            "avg_tokens_per_line": float(round(avg_tok, 2)),
            "table_count": len(table_regions),
            "selected_table_available": bool(tsr_metadata.get("selected_table_available", True)),
            "selected_main_table_id": tsr_metadata.get("selected_main_table_id"),
            "table_sanity": tsr_metadata.get("table_sanity", {}),
            "row_count": total_rows,
            "col_count": total_cols,
            "orphan_token_count": orphan_tokens,
            "ioa_success_rate": ioa_success_rate,
            "empty_cell_ratio": empty_cell_ratio,
            "topology_stability": stability_metrics,
            "topology_debug": topology_debug,
            "semantic_debug": semantic_debug,
            "semantic_role_resolution": selected_main_table_resolution,
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
            "wide_table_diagnostics": {
                "wide_table_mode": wide_table_evidence.is_wide,
                "wide_table_confidence": wide_table_evidence.confidence,
                "wide_table_signals": wide_table_evidence.signals,
                "estimated_column_count": wide_table_evidence.estimated_column_count,
                "numeric_merge_blocked_count": repair_metrics_total.get("numeric_merge_blocked_count", 0),
                "header_expansion": header_expansion_diagnostics,
                "column_expansion_failed": bool(tsr_metadata.get("wide_table_column_expansion_failed")),
                "column_expansion_failure_tables": tsr_metadata.get("wide_table_column_expansion_failure_tables", []),
                "split_blocks_before_mapping": tsr_metadata.get("wide_table_split_blocks_before_mapping", {}),
            },
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
            "tsr_candidate_decision": tsr_candidate_decision,
            "item_row_source_selection": item_row_source_selection,
            "qty_inference_summary": seg_debug.get("qty_inference_summary", {}),
            "header_trapped_item_recovery": seg_debug.get("header_trapped_item_recovery", {}),
            "row_handoff_summary": row_handoff_summary,
            "item_row_alignment_diagnostics": item_row_alignment_diagnostics,
            **tsr_metadata,
            "tsr_status": tsr_status_metric
        }
    }
    return attach_invoice_diagnostics(final_result, invoice_id=metadata_section.get("invoice_id") or "unknown")
