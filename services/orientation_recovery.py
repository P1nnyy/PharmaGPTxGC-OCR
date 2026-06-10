# NOTE: This module is part of the legacy extraction path.
# It should remain available as fallback during Azure Document Intelligence migration.
# Do not delete until Azure shadow comparison proves replacement quality.

import re
import math
from typing import Dict, Any, Tuple, List
from PIL import Image
from core.logger import logger
from services.validators.rotation_detector import rotate_image_clockwise
from services import ocr_engine, spatial_reconstruction
from services.diagnostics_writer import validate_coordinate_space

def is_primary_table_usable(metadata: Dict[str, Any]) -> bool:
    """
    Checks if the primary reconstruction has a usable selected table.
    Ensures that we do not trigger orientation recovery if we already have a high-quality table.
    """
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    
    # 1. Check if selected table is available in either top-level or metrics section
    selected_available = metadata.get("selected_table_available")
    if selected_available is None:
        selected_available = metrics.get("selected_table_available")
    if not selected_available:
        return False
        
    # 2. Check selected table ID existence
    selected_id = metadata.get("selected_table_id") or metrics.get("selected_main_table_id")
    if not selected_id:
        return False
        
    # 3. Check for non-empty selected grid or reconstructed rows
    reconstructed_rows = metadata.get("reconstructed_rows") or metrics.get("reconstructed_rows")
    selected_grid = metadata.get("selected_table_grid") or metrics.get("selected_table_grid")
    
    # Check reconstructed_rows length if it's a list
    if isinstance(reconstructed_rows, list) and len(reconstructed_rows) == 0:
        if not selected_grid:
            return False
            
    # Check selected_grid empty checks
    if selected_grid is not None:
        if isinstance(selected_grid, list) and len(selected_grid) == 0:
            return False
        if isinstance(selected_grid, str) and not selected_grid.strip():
            return False

    # 4. Check for coordinate space violation or bounds violations
    coord_report = validate_coordinate_space(metadata)
    if coord_report.get("has_violation"):
        return False

    # 5. Check candidate-specific sanity metrics from table_sanity
    table_sanity = metrics.get("table_sanity") or metadata.get("table_sanity") or {}
    per_candidate = table_sanity.get("per_candidate") or []
    for cand in per_candidate:
        if str(cand.get("table_id")) == str(selected_id):
            rejection_reasons = cand.get("rejection_reasons") or []
            
            # If the selected candidate is explicitly marked invalid for geometry or catastrophic score
            if any(r in rejection_reasons for r in ("coordinate_space_violation", "table_bbox_out_of_bounds", "cell_bbox_out_of_bounds", "catastrophic_tsr_score")):
                return False
                
            # If the selected candidate has item_rows == 0 and all columns unknown
            item_rows = cand.get("item_rows")
            all_unknown = cand.get("all_unknown_columns")
            if item_rows == 0 and all_unknown is True:
                return False
                
            # Check for catastrophic sanity score
            ts_score = cand.get("table_sanity_score")
            if ts_score is not None and ts_score <= -50.0:
                return False

    return True

def should_attempt_orientation_recovery(metadata: Dict[str, Any], quality_gate: Dict[str, Any] | None = None) -> bool:
    """
    Check if the metadata or quality gate metrics indicate that orientation recovery should be triggered.
    Prevents infinite recursion by checking orientation_recovery_attempted.
    Uses is_primary_table_usable to keep usable primary reconstructions.
    """
    # Prevent infinite loop recursion
    if metadata.get("orientation_recovery_attempted") or metadata.get("processed_image", {}).get("orientation_recovery_attempted"):
        return False
        
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    qg = quality_gate or metadata.get("quality_gate") or {}
    
    # Check if primary table is already usable. If so, skip recovery!
    if is_primary_table_usable(metadata):
        logger.info("[ORIENTATION RECOVERY SKIP] Skipping recovery because primary table is usable.")
        metadata["orientation_recovery_attempted"] = False
        metadata["orientation_recovery_skip_reason"] = "primary_table_usable"
        
        # Ensure selected_reason is primary_table_preserved in sanity dicts
        for target in (metadata, metrics):
            table_sanity = target.get("table_sanity")
            if isinstance(table_sanity, dict):
                table_sanity["selected_reason"] = "primary_table_preserved"
        return False

    # We do NOT trigger from orientation_ambiguous == True alone.
    # We only trigger when there is a hard failure signal.
    has_hard_failure = False
    
    # 1. selected_candidate_id missing or selected_table_available is False
    selected_id = metadata.get("selected_table_id") or metrics.get("selected_main_table_id")
    selected_available = metadata.get("selected_table_available")
    if selected_available is None:
        selected_available = metrics.get("selected_table_available")
        
    if not selected_id or selected_available is False:
        logger.info("[ORIENTATION RECOVERY TRIGGER] selected_table_available is False or selected_id is missing")
        has_hard_failure = True
        
    # 2. fast_fail_reason == no_valid_table_candidate or quality gate lists it
    qg_reasons = qg.get("reasons") or []
    if metadata.get("fast_fail_reason") == "no_valid_table_candidate" or metrics.get("no_valid_table_candidate") is True or "no_valid_table_candidate" in qg_reasons:
        logger.info("[ORIENTATION RECOVERY TRIGGER] no_valid_table_candidate detected")
        has_hard_failure = True

    # 3. Selected table grid or reconstructed rows are empty
    reconstructed_rows = metadata.get("reconstructed_rows") or metrics.get("reconstructed_rows")
    selected_grid = metadata.get("selected_table_grid") or metrics.get("selected_table_grid")
    grid_is_empty = False
    if isinstance(reconstructed_rows, list) and len(reconstructed_rows) == 0:
        if not selected_grid:
            grid_is_empty = True
    if selected_grid is not None:
        if isinstance(selected_grid, list) and len(selected_grid) == 0:
            grid_is_empty = True
        elif isinstance(selected_grid, str) and not selected_grid.strip():
            grid_is_empty = True
    if grid_is_empty:
        logger.info("[ORIENTATION RECOVERY TRIGGER] selected table grid/reconstructed rows is empty")
        has_hard_failure = True

    # 4. Coordinate space violation detected
    coord_report = validate_coordinate_space(metadata)
    if coord_report.get("has_violation"):
        logger.info("[ORIENTATION RECOVERY TRIGGER] coordinate space violation detected")
        has_hard_failure = True

    # 5. Geometry out-of-bounds reasons or catastrophic score in candidates
    table_sanity = metrics.get("table_sanity") or metadata.get("table_sanity") or {}
    per_candidate = table_sanity.get("per_candidate") or []
    for cand in per_candidate:
        reasons = cand.get("rejection_reasons") or []
        if any(r in reasons for r in ("coordinate_space_violation", "table_bbox_out_of_bounds", "cell_bbox_out_of_bounds")):
            logger.info("[ORIENTATION RECOVERY TRIGGER] candidate table %s has geometry violation", cand.get("table_id"))
            has_hard_failure = True
            
        if "catastrophic_tsr_score" in reasons:
            logger.info("[ORIENTATION RECOVERY TRIGGER] candidate table %s has catastrophic_tsr_score", cand.get("table_id"))
            has_hard_failure = True
            
        c_score = cand.get("candidate_score")
        if c_score is not None and c_score <= -50.0:
            logger.info("[ORIENTATION RECOVERY TRIGGER] candidate table %s has candidate_score <= -50.0", cand.get("table_id"))
            has_hard_failure = True
            
        ts_score = cand.get("table_sanity_score")
        if ts_score is not None and ts_score <= -50.0:
            logger.info("[ORIENTATION RECOVERY TRIGGER] candidate table %s has table_sanity_score <= -50.0", cand.get("table_id"))
            has_hard_failure = True

        # If selected candidate has item_rows == 0 and all unknown columns
        if str(cand.get("table_id")) == str(selected_id):
            if cand.get("item_rows") == 0 and cand.get("all_unknown_columns") is True:
                logger.info("[ORIENTATION RECOVERY TRIGGER] selected candidate has item_rows=0 and all_unknown_columns")
                has_hard_failure = True

    return has_hard_failure

def score_orientation_candidate(angle: int, metadata: Dict[str, Any], ocr_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes a downstream readability score for an orientation candidate based on TSR table structures,
    pharma headers, clean row counts, and numeric OCR validity.
    """
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    table_sanity = metrics.get("table_sanity") or metadata.get("table_sanity") or {}
    per_candidate = table_sanity.get("per_candidate") or []
    
    selected_available = bool(metadata.get("selected_table_available", metrics.get("selected_table_available", False)))
    selected_id = metadata.get("selected_table_id") or metrics.get("selected_main_table_id")
    
    selected_candidate = None
    if selected_available and selected_id:
        for cand in per_candidate:
            if str(cand.get("table_id")) == str(selected_id):
                selected_candidate = cand
                break
                
    if not selected_candidate and per_candidate:
        selected_candidate = max(per_candidate, key=lambda c: c.get("table_sanity_score", 0.0), default=None)
        
    score = 0.0
    valid = False
    row_count = 0
    column_count = 0
    item_rows = 0
    pharma_header_hits = 0
    all_unknown_columns = True
    cell_bbox_out_of_bounds_count = 0
    rejection_reasons = []
    geometry_repaired = False
    salvageable = False
    repairable_rejections = []
    
    if selected_candidate:
        valid = bool(selected_candidate.get("valid", False))
        row_count = int(selected_candidate.get("row_count", 0))
        column_count = int(selected_candidate.get("column_count", 0))
        item_rows = int(selected_candidate.get("item_rows", 0))
        pharma_header_hits = int(selected_candidate.get("pharma_header_hits", 0))
        all_unknown_columns = bool(selected_candidate.get("all_unknown_columns", True))
        cell_bbox_out_of_bounds_count = int(selected_candidate.get("cell_bbox_out_of_bounds_count", 0))
        rejection_reasons = list(selected_candidate.get("rejection_reasons") or [])
        
        geometry_repaired = bool(selected_candidate.get("geometry_repaired", False))
        salvageable = bool(selected_candidate.get("salvageable", False))
        repairable_rejections = list(selected_candidate.get("repairable_rejections") or [])
        
        # Add baseline TSR sanity score
        score += float(selected_candidate.get("table_sanity_score", 0.0))
        
        # Add bonus for successful candidate selection
        if selected_available:
            score += 50.0
        if valid:
            score += 30.0
            
        # Item rows bonus
        if item_rows > 0:
            score += 20.0 + min(item_rows, 15) * 2.0
            
        # Column and row layout counts
        if row_count >= 2:
            score += 10.0
        if column_count >= 8:
            score += 15.0 # Wide table bonus
            
        # Pharma header keyword hits
        if pharma_header_hits > 0:
            score += pharma_header_hits * 5.0
            
        # Penalize geometry/bounds issues
        if "coordinate_space_violation" in rejection_reasons:
            score -= 50.0
        if any(r in rejection_reasons for r in ("table_bbox_out_of_bounds", "cell_bbox_out_of_bounds")):
            score -= 30.0
            
        # Evaluate unknown columns ratio
        col_semantics = metrics.get("final_column_semantics") or metrics.get("semantic_columns") or {}
        if isinstance(col_semantics, dict) and selected_id in col_semantics:
            col_semantics = col_semantics[selected_id]
            
        total_cols = len([k for k in col_semantics.keys() if not k.startswith("_")])
        if total_cols > 0:
            unknown_cols = sum(1 for v in col_semantics.values() if (v.get("type") if isinstance(v, dict) else v) == "unknown")
            unknown_ratio = unknown_cols / total_cols
            if all_unknown_columns:
                score -= 40.0
            else:
                score += (1.0 - unknown_ratio) * 25.0
        else:
            if all_unknown_columns:
                score -= 40.0
                
        # Expiry date detection bonus
        has_expiry_match = False
        EXPIRY_DATE_RE = re.compile(r"\b\d{2}[-/]\d{2,4}\b")
        if isinstance(col_semantics, dict):
            for col_id, col_data in col_semantics.items():
                if col_id.startswith("_"):
                    continue
                pred_type = col_data.get("type") if isinstance(col_data, dict) else col_data
                if pred_type in ("exp", "expiry", "expiry_date"):
                    samples = col_data.get("sample_values") if isinstance(col_data, dict) else []
                    if samples:
                        for sample in samples:
                            if sample and EXPIRY_DATE_RE.search(str(sample)):
                                has_expiry_match = True
                                break
        if has_expiry_match:
            score += 15.0
            
        # Check for numeric-heavy garbage substitutions (e.g. letters in qty/rate)
        num_cols = ["qty", "rate", "mrp", "amount", "gst"]
        present_num_cols = []
        garbage_cols = 0
        if isinstance(col_semantics, dict):
            for col_id, col_data in col_semantics.items():
                if col_id.startswith("_"):
                    continue
                pred_type = col_data.get("type") if isinstance(col_data, dict) else col_data
                if pred_type in num_cols:
                    present_num_cols.append(pred_type)
                    samples = col_data.get("sample_values") if isinstance(col_data, dict) else []
                    if samples:
                        alpha_count = 0
                        digit_count = 0
                        for val in samples:
                            # clean common symbols, whitespace
                            val_str = re.sub(r"[\s₹Rs\.%,/\-]", "", str(val))
                            alpha_count += len(re.findall(r"[a-zA-Z]", val_str))
                            digit_count += len(re.findall(r"[0-9]", val_str))
                        if alpha_count > 0:
                            total_chars = alpha_count + digit_count
                            if total_chars > 0 and (alpha_count / total_chars) > 0.2:
                                garbage_cols += 1
                                
        score += len(set(present_num_cols)) * 4.0
        score -= garbage_cols * 20.0
    else:
        score = -100.0
        rejection_reasons = ["no_valid_table_candidate"]
        
    if not selected_available:
        score -= 50.0
        
    return {
        "score": round(score, 3),
        "selected_table_available": selected_available,
        "valid": valid,
        "row_count": row_count,
        "column_count": column_count,
        "item_rows": item_rows,
        "pharma_header_hits": pharma_header_hits,
        "all_unknown_columns": all_unknown_columns,
        "rejection_reasons": rejection_reasons,
        "geometry_repaired": geometry_repaired,
        "salvageable": salvageable,
        "repairable_rejections": repairable_rejections,
    }

def run_orientation_recovery(
    original_image: Image.Image,
    normal_payload: Dict[str, Any],
    reconstruct_mode: str,
    benchmark_mode: bool,
    processed_image_path: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Executes controlled rotation testing of alternate orientations (90, 180, 270 deg)
    and chooses the layout producing the best readability score.
    """
    primary_angle = int(normal_payload["metadata"].get("processed_image", {}).get("rotation_angle", 0) or 0)
    logger.info("[ORIENTATION RECOVERY] Starting recovery loop. Original processed angle: %s", primary_angle)
    
    primary_score_details = score_orientation_candidate(primary_angle, normal_payload["metadata"], normal_payload["ocr_result"])
    logger.info("[ORIENTATION RECOVERY] Primary orientation angle %s score: %s", primary_angle, primary_score_details["score"])
    
    all_candidates = [
        {
            "angle": primary_angle,
            "ocr_result": normal_payload["ocr_result"],
            "metadata": normal_payload["metadata"],
            "score_details": primary_score_details,
        }
    ]
    
    alternate_angles = [a for a in [0, 90, 180, 270] if a != primary_angle]
    alternates = []
    
    for angle in alternate_angles:
        logger.info("[ORIENTATION RECOVERY] Probing alternate angle: %s", angle)
        # Rotate the original image clockwise by the target angle
        rotated_img = rotate_image_clockwise(original_image.copy(), angle)
        
        # Run OCR engine with bypass_rotation_detection=True
        candidate_ocr = ocr_engine.process_image(
            rotated_img,
            bypass_rotation_detection=True,
            processed_image_path=None,
            include_processed_image_data_url=False
        )
        
        # Run spatial reconstruction
        candidate_reconstruction = spatial_reconstruction.reconstruct_layout(
            candidate_ocr["blocks"],
            debug=(not benchmark_mode),
            reconstruct_mode=reconstruct_mode,
            image=rotated_img,
            benchmark_mode=benchmark_mode
        )
        
        candidate_metadata = {
            **candidate_ocr["metadata"],
            "blocks": candidate_ocr["blocks"],
            **candidate_reconstruction
        }
        
        candidate_score_details = score_orientation_candidate(angle, candidate_metadata, candidate_ocr)
        logger.info("[ORIENTATION RECOVERY] Probed angle %s score details: %s", angle, candidate_score_details)
        
        candidates_data = {
            "angle": angle,
            "ocr_result": candidate_ocr,
            "metadata": candidate_metadata,
            "score_details": candidate_score_details,
        }
        alternates.append(candidates_data)
        all_candidates.append(candidates_data)
        
    # Sort all_candidates by angle for consistent metadata
    all_candidates.sort(key=lambda x: x["angle"])
    
    # Select best candidate
    valid_alternates = [c for c in alternates if c["score_details"]["selected_table_available"]]
    primary_is_valid = primary_score_details["selected_table_available"]
    
    chosen_candidate = None
    improvement_achieved = False
    
    if not primary_is_valid:
        if valid_alternates:
            valid_alternates.sort(key=lambda x: x["score_details"]["score"], reverse=True)
            chosen_candidate = valid_alternates[0]
            improvement_achieved = True
            if chosen_candidate["score_details"]["geometry_repaired"]:
                chosen_reason = "selected_salvageable_orientation"
            else:
                chosen_reason = f"alternate_angle_{chosen_candidate['angle']}_is_valid_and_beats_invalid_primary"
        else:
            chosen_reason = "retained_original_angle_due_to_no_valid_alternative"
    else:
        if valid_alternates:
            valid_alternates.sort(key=lambda x: x["score_details"]["score"], reverse=True)
            best_alternate = valid_alternates[0]
            if best_alternate["score_details"]["score"] > primary_score_details["score"] + 15.0:
                chosen_candidate = best_alternate
                improvement_achieved = True
                if chosen_candidate["score_details"]["geometry_repaired"]:
                    chosen_reason = "selected_salvageable_orientation"
                else:
                    chosen_reason = f"alternate_angle_{chosen_candidate['angle']}_significantly_beats_valid_primary"
            else:
                chosen_reason = "retained_original_angle_due_to_insufficient_alternate_margin"
        else:
            chosen_reason = "retained_original_angle_due_to_no_valid_alternative"
            
    if chosen_candidate:
        chosen_angle = chosen_candidate["angle"]
        logger.warning(
            "[ORIENTATION RECOVERY] Success! Choosing improved orientation: %s (reason: %s)",
            chosen_angle,
            chosen_reason
        )
        
        # Re-run OCR and reconstruction to finalize paths, save images, etc.
        final_rotated_image = rotate_image_clockwise(original_image.copy(), chosen_angle)
        
        final_ocr = ocr_engine.process_image(
            final_rotated_image,
            bypass_rotation_detection=True,
            processed_image_path=processed_image_path,
            include_processed_image_data_url=True
        )
        
        final_reconstruction = spatial_reconstruction.reconstruct_layout(
            final_ocr["blocks"],
            debug=(not benchmark_mode),
            reconstruct_mode=reconstruct_mode,
            image=final_rotated_image,
            benchmark_mode=benchmark_mode
        )
        
        final_metadata = {
            **final_ocr["metadata"],
            "blocks": final_ocr["blocks"],
            **final_reconstruction
        }
        
        # Override processed image rotation properties in final_metadata
        final_metadata["rotation_angle"] = chosen_angle
        final_metadata["rotation_applied"] = bool(chosen_angle != 0)
        final_metadata["rotation_source"] = "orientation_recovery"
        final_metadata["rotation_method"] = "orientation_recovery"
        
        if "processed_image" in final_metadata:
            final_metadata["processed_image"]["rotation_angle"] = chosen_angle
            final_metadata["processed_image"]["rotation_applied"] = bool(chosen_angle != 0)
            final_metadata["processed_image"]["rotation_source"] = "orientation_recovery"
            final_metadata["processed_image"]["rotation_method"] = "orientation_recovery"
            
        final_ocr_result = final_ocr
        
        # Distinguish selected reason
        metrics = final_metadata.get("metrics") or {}
        table_sanity = metrics.get("table_sanity") or final_metadata.get("table_sanity") or {}
        if isinstance(table_sanity, dict):
            table_sanity["selected_reason"] = "recovered_orientation_selected"
            if "table_sanity" in final_metadata:
                final_metadata["table_sanity"] = table_sanity
            if "table_sanity" in metrics:
                metrics["table_sanity"] = table_sanity
    else:
        chosen_angle = primary_angle
        logger.info("[ORIENTATION RECOVERY] No better orientation found. Retaining original angle: %s", primary_angle)
        final_metadata = normal_payload["metadata"]
        final_ocr_result = normal_payload["ocr_result"]
        
        # Distinguish selected reason when primary retained
        metrics = final_metadata.get("metrics") or {}
        table_sanity = metrics.get("table_sanity") or final_metadata.get("table_sanity") or {}
        if isinstance(table_sanity, dict):
            if final_metadata.get("selected_table_available", metrics.get("selected_table_available")):
                table_sanity["selected_reason"] = "primary_table_preserved"
            else:
                table_sanity["selected_reason"] = "no_valid_candidate"
            if "table_sanity" in final_metadata:
                final_metadata["table_sanity"] = table_sanity
            if "table_sanity" in metrics:
                metrics["table_sanity"] = table_sanity
        
    # Append orientation recovery diagnostics
    chosen_score_details = chosen_candidate["score_details"] if chosen_candidate else primary_score_details
    recovery_diagnostics = {
        "orientation_recovery_attempted": True,
        "orientation_recovery_reason": "primary_failed_sanity_or_ambiguous",
        "original_angle": primary_angle,
        "chosen_angle": chosen_angle,
        "chosen_reason": chosen_reason,
        "geometry_repaired": bool(chosen_score_details.get("geometry_repaired", False)),
        "repairable_rejections": list(chosen_score_details.get("repairable_rejections") or []),
        "per_angle_scores": {str(c["angle"]): c["score_details"]["score"] for c in all_candidates},
        "per_angle_selected_table_available": {str(c["angle"]): c["score_details"]["selected_table_available"] for c in all_candidates},
        "per_angle_item_rows": {str(c["angle"]): c["score_details"]["item_rows"] for c in all_candidates},
        "per_angle_column_count": {str(c["angle"]): c["score_details"]["column_count"] for c in all_candidates},
        "per_angle_header_hits": {str(c["angle"]): c["score_details"]["pharma_header_hits"] for c in all_candidates},
        "per_angle_rejection_reasons": {str(c["angle"]): c["score_details"]["rejection_reasons"] for c in all_candidates},
        "per_angle_salvageable": {str(c["angle"]): c["score_details"]["salvageable"] for c in all_candidates},
        "whether_recovery_improved_the_result": improvement_achieved,
    }
    
    final_metadata.update(recovery_diagnostics)
    if "processed_image" in final_metadata:
        final_metadata["processed_image"].update(recovery_diagnostics)
        
    return final_ocr_result, final_metadata
