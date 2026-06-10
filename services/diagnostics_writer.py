from __future__ import annotations

import csv
import json
import math
import zipfile
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.logger import logger


DIAGNOSTIC_FILENAMES = (
    "full_response.json",
    "ocr_blocks_raw.json",
    "candidate_tables.json",
    "selected_table_grid.csv",
    "semantic_mapping.json",
    "quality_gate.json",
    "processed_image_metadata.json",
    "orientation_recovery.json",
)


def write_upload_diagnostics(
    *,
    diagnostics_run_id: str,
    response_payload: Dict[str, Any],
    ocr_blocks: List[Dict[str, Any]],
    ocr_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Persist backend-owned diagnostic artifacts for a completed upload.

    Failures are logged and returned as metadata so artifact generation cannot
    crash invoice processing.
    """
    safe_run_id = _safe_run_id(diagnostics_run_id)
    diagnostics_dir = Path("local_runs") / f"diagnostics_{safe_run_id}"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    metadata = response_payload.get("metadata") if isinstance(response_payload.get("metadata"), dict) else {}
    write_errors: List[Dict[str, str]] = []

    def write_json(name: str, value: Any) -> None:
        try:
            _write_json(diagnostics_dir / name, value)
        except Exception as exc:
            logger.error("[DIAGNOSTICS] Failed writing %s: %s", name, exc)
            write_errors.append({"file": name, "error": str(exc)})

    write_json("ocr_blocks_raw.json", ocr_blocks)
    write_json("candidate_tables.json", _build_candidate_tables(metadata))
    _write_selected_grid_safe(diagnostics_dir / "selected_table_grid.csv", metadata, write_errors)
    write_json("semantic_mapping.json", _build_semantic_mapping(metadata))
    write_json("quality_gate.json", _build_quality_gate(metadata))
    write_json("processed_image_metadata.json", _build_processed_image_metadata(ocr_metadata, metadata))
    write_json("orientation_recovery.json", _build_orientation_recovery(metadata))

    final_response = {
        **response_payload,
        "metadata": {
            **metadata,
            "diagnostics_run_id": safe_run_id,
            "diagnostics": {
                "run_id": safe_run_id,
                "directory": str(diagnostics_dir.resolve()),
                "write_errors": write_errors,
                "artifacts": [],
            },
            "artifacts": [],
        },
    }
    write_json("full_response.json", final_response)

    bundle_path = diagnostics_dir / "full_diagnostics_bundle.zip"
    try:
        _write_bundle(bundle_path, diagnostics_dir, DIAGNOSTIC_FILENAMES)
    except Exception as exc:
        logger.error("[DIAGNOSTICS] Failed writing bundle: %s", exc)
        write_errors.append({"file": bundle_path.name, "error": str(exc)})

    artifact_meta = _artifact_metadata(safe_run_id, diagnostics_dir)
    final_response["metadata"]["diagnostics"]["write_errors"] = write_errors
    final_response["metadata"]["diagnostics"]["artifacts"] = artifact_meta
    final_response["metadata"]["artifacts"] = artifact_meta
    write_json("full_response.json", final_response)

    try:
        _write_bundle(bundle_path, diagnostics_dir, DIAGNOSTIC_FILENAMES)
    except Exception as exc:
        logger.error("[DIAGNOSTICS] Failed rewriting bundle: %s", exc)
        write_errors.append({"file": bundle_path.name, "error": str(exc)})
        final_response["metadata"]["diagnostics"]["write_errors"] = write_errors
        write_json("full_response.json", final_response)

    return {
        "diagnostics_run_id": safe_run_id,
        "directory": str(diagnostics_dir.resolve()),
        "write_errors": write_errors,
        "artifacts": artifact_meta,
    }


def list_diagnostic_artifacts(diagnostics_run_id: str) -> Dict[str, Any]:
    safe_run_id = _safe_run_id(diagnostics_run_id)
    diagnostics_dir = Path("local_runs") / f"diagnostics_{safe_run_id}"
    if not diagnostics_dir.exists():
        return {
            "diagnostics_run_id": safe_run_id,
            "directory": str(diagnostics_dir.resolve()),
            "artifacts": [],
            "exists": False,
        }
    return {
        "diagnostics_run_id": safe_run_id,
        "directory": str(diagnostics_dir.resolve()),
        "artifacts": _artifact_metadata(safe_run_id, diagnostics_dir),
        "exists": True,
    }


def resolve_diagnostic_artifact_path(diagnostics_run_id: str, artifact_name: str) -> Path:
    safe_run_id = _safe_run_id(diagnostics_run_id)
    safe_name = Path(artifact_name).name
    diagnostics_dir = (Path("local_runs") / f"diagnostics_{safe_run_id}").resolve()
    artifact_path = (diagnostics_dir / safe_name).resolve()
    if diagnostics_dir not in artifact_path.parents and artifact_path != diagnostics_dir:
        raise ValueError("Artifact path escapes diagnostics directory")
    return artifact_path


def normalize_orientation_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    report = _build_processed_image_metadata(metadata, metadata)
    processed = metadata.get("processed_image") if isinstance(metadata.get("processed_image"), dict) else {}
    processed.update({
        "original_width": report["original_image_size"][0],
        "original_height": report["original_image_size"][1],
        "processed_width": report["processed_image_size"][0],
        "processed_height": report["processed_image_size"][1],
        "rotation_angle": report["rotation_angle"],
        "rotation_applied": report["rotation_applied"],
        "rotation_source": report["rotation_source"],
        "rotation_method": report["rotation_method"],
        "orientation_confidence": report["orientation_confidence"],
        "coordinate_space": report["coordinate_space"],
        "coordinates_based_on": report["coordinates_based_on"],
        "rotation_detection": report["rotation_detection"],
        "orientation_ambiguous": report["orientation_ambiguous"],
        "score_margin": report["score_margin"],
        "best_candidate": report["best_candidate"],
        "second_candidate": report["second_candidate"],
        "candidate_scores": report["candidate_scores"],
        "orientation_ambiguity_reason": report["orientation_ambiguity_reason"],
    })
    
    # Copy orientation recovery diagnostics to processed_image and metadata
    for key in (
        "orientation_recovery_attempted",
        "orientation_recovery_reason",
        "original_angle",
        "chosen_angle",
        "chosen_reason",
        "geometry_repaired",
        "repairable_rejections",
        "per_angle_scores",
        "per_angle_selected_table_available",
        "per_angle_item_rows",
        "per_angle_column_count",
        "per_angle_header_hits",
        "per_angle_rejection_reasons",
        "per_angle_salvageable",
        "whether_recovery_improved_the_result",
    ):
        if key in metadata:
            processed[key] = metadata[key]
            
    metadata["processed_image"] = processed
    metadata["rotation_angle"] = report["rotation_angle"]
    metadata["rotation_applied"] = report["rotation_applied"]
    metadata["rotation_source"] = report["rotation_source"]
    metadata["rotation_method"] = report["rotation_method"]
    metadata["orientation_confidence"] = report["orientation_confidence"]
    metadata["orientation_ambiguous"] = report["orientation_ambiguous"]
    metadata["score_margin"] = report["score_margin"]
    metadata["best_candidate"] = report["best_candidate"]
    metadata["second_candidate"] = report["second_candidate"]
    metadata["candidate_scores"] = report["candidate_scores"]
    metadata["orientation_ambiguity_reason"] = report["orientation_ambiguity_reason"]
    metadata.pop("legacy_rotation_applied", None)
    metadata.pop("legacy_rotation_angle", None)
    metadata.pop("legacy_rotation_confidence", None)
    return metadata


def _build_orientation_recovery(metadata: Dict[str, Any]) -> Dict[str, Any]:
    processed = metadata.get("processed_image") if isinstance(metadata.get("processed_image"), dict) else {}
    recovery_data = {}
    for key in (
        "orientation_recovery_attempted",
        "orientation_recovery_reason",
        "original_angle",
        "chosen_angle",
        "chosen_reason",
        "geometry_repaired",
        "repairable_rejections",
        "per_angle_scores",
        "per_angle_selected_table_available",
        "per_angle_item_rows",
        "per_angle_column_count",
        "per_angle_header_hits",
        "per_angle_rejection_reasons",
        "per_angle_salvageable",
        "whether_recovery_improved_the_result",
    ):
        if key in metadata:
            recovery_data[key] = metadata[key]
        elif key in processed:
            recovery_data[key] = processed[key]
    return recovery_data


def _safe_run_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "unknown"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(json_safe(value), indent=2, ensure_ascii=False), encoding="utf-8")


def _write_selected_grid_safe(path: Path, metadata: Dict[str, Any], write_errors: List[Dict[str, str]]) -> None:
    try:
        grid = _selected_table_grid(metadata)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            for row in grid:
                writer.writerow(row)
    except Exception as exc:
        logger.error("[DIAGNOSTICS] Failed writing selected_table_grid.csv: %s", exc)
        write_errors.append({"file": "selected_table_grid.csv", "error": str(exc)})


def _build_candidate_tables(metadata: Dict[str, Any]) -> Dict[str, Any]:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    decision = (
        metadata.get("tsr_candidate_decision")
        or metrics.get("tsr_candidate_decision")
        or metadata.get("table_routing_diagnostics")
        or {}
    )
    wide_diag = metrics.get("wide_table_diagnostics") if isinstance(metrics.get("wide_table_diagnostics"), dict) else {}
    table_sanity = metrics.get("table_sanity") or metadata.get("table_sanity") or {}
    sanity_by_id = {
        str(item.get("table_id")): item
        for item in table_sanity.get("per_candidate", [])
        if isinstance(item, dict) and item.get("table_id")
    } if isinstance(table_sanity, dict) else {}
    selected_available = bool(
        metadata.get("selected_table_available", metrics.get("selected_table_available", True))
    )
    selected_table = _select_main_table(metadata)
    selected_id = (
        (_selected_table_id(metadata) or _table_id(selected_table) or metadata.get("selected_table_id"))
        if selected_available
        else None
    )

    candidates: List[Dict[str, Any]] = []
    structured_tables = metadata.get("structured_tables")
    if isinstance(structured_tables, list):
        for index, table in enumerate(structured_tables):
            if not isinstance(table, dict):
                continue
            table_id = _table_id(table) or f"table_{index}"
            sanity = sanity_by_id.get(str(table_id), {})
            candidates.append({
                "table_id": table_id,
                "source_engine": table.get("source_engine") or table.get("engine") or "unknown",
                "rows": _count_rows(table),
                "columns": _count_cols(table),
                "cell_count": len(table.get("cells") or []),
                "score": table.get("score") or table.get("confidence") or table.get("representability_score"),
                "selected": bool(table_id == selected_id),
                "valid": sanity.get("valid"),
                "table_sanity_score": sanity.get("table_sanity_score"),
                "rejection_reason": None if table_id == selected_id else (
                    sanity.get("rejection_reasons") or table.get("rejection_reason")
                ),
                "representability_score": table.get("representability_score"),
                "wide_table_mode": wide_diag.get("wide_table_mode"),
                "header_expansion": (wide_diag.get("header_expansion") or {}).get(table_id),
                "bbox": _geometry(table),
                "geometry": table.get("geometry") or table.get("normalized_geometry"),
            })

    return {
        "selected_candidate_id": selected_id,
        "selected_table_available": selected_available,
        "wide_table_mode": wide_diag.get("wide_table_mode"),
        "wide_table_diagnostics": wide_diag,
        "table_sanity": table_sanity,
        "candidate_decision": decision,
        "candidates": candidates,
    }


def _selected_table_grid(metadata: Dict[str, Any]) -> List[List[str]]:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    if metadata.get("selected_table_available", metrics.get("selected_table_available", True)) is False:
        return []
    table = _select_main_table(metadata)
    if not isinstance(table, dict):
        return []

    cells = table.get("cells")
    if not isinstance(cells, list) or not cells:
        return []

    row_keys = sorted({_axis_key(cell, "row") for cell in cells}, key=_sort_key)
    col_keys = sorted({_axis_key(cell, "col") for cell in cells}, key=_sort_key)
    row_map = {key: idx for idx, key in enumerate(row_keys)}
    col_map = {key: idx for idx, key in enumerate(col_keys)}
    grid = [["" for _ in col_keys] for _ in row_keys]
    for cell in cells:
        row_idx = row_map.get(_axis_key(cell, "row"))
        col_idx = col_map.get(_axis_key(cell, "col"))
        if row_idx is None or col_idx is None:
            continue
        grid[row_idx][col_idx] = str(cell.get("text") or "")
    return grid


def _build_semantic_mapping(metadata: Dict[str, Any]) -> Dict[str, Any]:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    semantic_results = (
        metrics.get("semantic_column_results")
        or metadata.get("semantic_column_results")
        or metadata.get("semantic_columns")
        or {}
    )
    selected_table = _select_main_table(metadata)
    selected_id = _table_id(selected_table)
    selected_semantics = {}
    if isinstance(semantic_results, dict):
        selected_semantics = semantic_results.get(selected_id) or next(
            (value for value in semantic_results.values() if isinstance(value, dict)),
            {},
        )

    columns = []
    if isinstance(selected_semantics, dict):
        for col_id, col_data in selected_semantics.items():
            if str(col_id).startswith("_"):
                continue
            if isinstance(col_data, dict):
                columns.append({
                    "column_id": col_id,
                    "header_text": col_data.get("header_text") or col_data.get("header") or "",
                    "predicted_type": col_data.get("type") or col_data.get("predicted_type") or "unknown",
                    "confidence": col_data.get("confidence") or col_data.get("score") or 0.0,
                    "sample_values": col_data.get("sample_values") or col_data.get("samples") or [],
                    "competing_candidates": col_data.get("competing_candidates") or col_data.get("candidates") or [],
                })

    return {
        "selected_table_id": selected_id,
        "columns": columns,
        "raw_semantic_column_results": semantic_results,
        "final_column_semantics": metrics.get("final_column_semantics"),
    }


def _build_quality_gate(metadata: Dict[str, Any]) -> Dict[str, Any]:
    qg = metadata.get("quality_gate") if isinstance(metadata.get("quality_gate"), dict) else {}
    canonical = metadata.get("canonical_invoice") if isinstance(metadata.get("canonical_invoice"), dict) else {}
    metrics = qg.get("metrics") if isinstance(qg.get("metrics"), dict) else {}
    coordinate_report = validate_coordinate_space(metadata)
    missing_fields = (
        qg.get("missing_fields")
        or metrics.get("missing_footer_fields")
        or canonical.get("missing_fields")
        or []
    )
    reasons = list(qg.get("reasons") or [])
    if coordinate_report["has_violation"] and "coordinate_space_violation" not in reasons:
        reasons.append("coordinate_space_violation")
    return {
        "safe_for_erp": False if coordinate_report["has_violation"] else qg.get("safe_for_erp", metadata.get("safe_for_erp", False)),
        "status": "REVIEW" if coordinate_report["has_violation"] else (qg.get("status") or metadata.get("status_effective")),
        "confidence": qg.get("confidence") or metadata.get("invoice_confidence"),
        "reasons": reasons,
        "missing_fields": missing_fields,
        "row_math_status": metadata.get("row_math_status") or qg.get("row_math_status") or _row_math_status(metadata),
        "footer_status": qg.get("footer_status") or _footer_status(qg),
        "checklist": qg.get("checklist") or [],
        "coordinate_space_violation": coordinate_report,
        "raw_quality_gate": qg,
    }


def _build_processed_image_metadata(ocr_metadata: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    processed = (
        ocr_metadata.get("processed_image")
        or metadata.get("processed_image")
        or {}
    )
    rotation = (
        processed.get("rotation_detection")
        or ocr_metadata.get("rotation_detection")
        or metadata.get("rotation_detection")
        or {}
    )
    original_width = processed.get("original_width") or metadata.get("image_width")
    original_height = processed.get("original_height") or metadata.get("image_height")
    processed_width = processed.get("processed_width") or original_width
    processed_height = processed.get("processed_height") or original_height
    rotation_angle = (
        processed.get("rotation_angle")
        if processed.get("rotation_angle") is not None
        else ocr_metadata.get("rotation_angle", metadata.get("rotation_angle", 0))
    )
    rotation_applied = (
        processed.get("rotation_applied")
        if processed.get("rotation_applied") is not None
        else ocr_metadata.get("rotation_applied", metadata.get("rotation_applied", False))
    )
    swapped = (
        original_width == processed_height
        and original_height == processed_width
        and original_width is not None
        and original_height is not None
    )
    if swapped and not rotation_applied:
        rotation_applied = True
        if rotation_angle not in {90, 270}:
            rotation_angle = (
                ocr_metadata.get("legacy_rotation_angle")
                or metadata.get("legacy_rotation_angle")
                or 90
            )
    rotation_source = (
        processed.get("rotation_source")
        or processed.get("rotation_method")
        or ocr_metadata.get("rotation_source")
        or metadata.get("rotation_source")
        or ("inferred_from_processed_dimensions" if swapped else "none")
    )
    orientation_confidence = (
        processed.get("orientation_confidence")
        if processed.get("orientation_confidence") is not None
        else ocr_metadata.get("orientation_confidence", metadata.get("orientation_confidence"))
    )
    ambiguity = _orientation_ambiguity_report(rotation)
    return {
        "original_image_size": [
            original_width,
            original_height,
        ],
        "processed_image_size": [
            processed_width,
            processed_height,
        ],
        "rotation_angle": rotation_angle or 0,
        "rotation_applied": bool(rotation_applied),
        "rotation_source": rotation_source,
        "rotation_method": rotation_source,
        "orientation_confidence": orientation_confidence if orientation_confidence is not None else rotation.get("confidence"),
        **ambiguity,
        "coordinate_space": processed.get("coordinate_space") or "processed_image",
        "coordinates_based_on": processed.get("coordinates_based_on") or processed.get("coordinate_space") or "processed_image",
        "corrected_image_path": processed.get("processed_image_path"),
        "rotation_detection": rotation,
        "processed_image": processed,
    }


def _orientation_ambiguity_report(rotation: Dict[str, Any]) -> Dict[str, Any]:
    rotation = rotation if isinstance(rotation, dict) else {}
    scores = rotation.get("scores") if isinstance(rotation.get("scores"), dict) else {}
    candidate_scores = {}
    for key, value in scores.items():
        number = _number(value)
        if number is None:
            continue
        candidate_scores[str(key)] = round(number, 4)

    ranked = sorted(
        ((int(key), value) for key, value in candidate_scores.items() if str(key).lstrip("-").isdigit()),
        key=lambda item: item[1],
        reverse=True,
    )
    metadata = rotation.get("metadata") if isinstance(rotation.get("metadata"), dict) else {}
    best_candidate = ranked[0][0] if ranked else metadata.get("best_candidate")
    second_candidate = ranked[1][0] if len(ranked) > 1 else None
    best_score = ranked[0][1] if ranked else _number(metadata.get("best_score")) or 0.0
    second_score = ranked[1][1] if len(ranked) > 1 else _number(metadata.get("second_score")) or 0.0
    score_margin = _number(metadata.get("score_margin"))
    if score_margin is None:
        score_margin = best_score - second_score
    min_margin = _number(metadata.get("min_margin")) or 0.12
    orientation_ambiguous = bool(score_margin < min_margin)
    return {
        "orientation_ambiguous": orientation_ambiguous,
        "score_margin": round(score_margin, 4),
        "best_candidate": best_candidate,
        "second_candidate": second_candidate,
        "candidate_scores": candidate_scores,
        "orientation_ambiguity_reason": (
            f"score_margin_below_min_margin:{score_margin:.4f}<{min_margin:.4f}"
            if orientation_ambiguous
            else None
        ),
    }


def validate_coordinate_space(metadata: Dict[str, Any]) -> Dict[str, Any]:
    processed = metadata.get("processed_image") if isinstance(metadata.get("processed_image"), dict) else {}
    width = _number(processed.get("processed_width") or metadata.get("image_width"))
    height = _number(processed.get("processed_height") or metadata.get("image_height"))
    violations: List[Dict[str, Any]] = []

    if not width or not height:
        return {
            "has_violation": False,
            "coordinate_space": processed.get("coordinate_space") or "processed_image",
            "processed_width": width,
            "processed_height": height,
            "violations": [],
            "skipped": "missing_processed_image_size",
        }

    for index, block in enumerate(metadata.get("blocks") or metadata.get("ocr_blocks") or []):
        bbox = _object_bbox(block)
        _append_bounds_violation(violations, "ocr_block", str(block.get("block_id") or index), bbox, width, height)

    selected_table = _select_main_table(metadata)
    if isinstance(selected_table, dict):
        _append_bounds_violation(
            violations,
            "selected_table",
            _table_id(selected_table) or "selected_table",
            _object_bbox(selected_table),
            width,
            height,
        )
        for index, cell in enumerate(selected_table.get("cells") or []):
            if isinstance(cell, dict):
                _append_bounds_violation(
                    violations,
                    "selected_table_cell",
                    str(cell.get("cell_id") or index),
                    _object_bbox(cell),
                    width,
                    height,
                )

    return {
        "has_violation": bool(violations),
        "coordinate_space": processed.get("coordinate_space") or "processed_image",
        "processed_width": width,
        "processed_height": height,
        "violations": violations,
    }


def _object_bbox(obj: Any) -> Optional[List[float]]:
    if not isinstance(obj, dict):
        return None
    bbox = obj.get("bbox") or obj.get("absolute_bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return [_number(value) or 0.0 for value in bbox[:4]]
    polygon = obj.get("polygon")
    if isinstance(polygon, list) and polygon:
        xs = []
        ys = []
        for point in polygon:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                x = _number(point[0])
                y = _number(point[1])
                if x is not None and y is not None:
                    xs.append(x)
                    ys.append(y)
        if xs and ys:
            return [min(xs), min(ys), max(xs), max(ys)]
    geom = obj.get("geometry") or obj.get("normalized_geometry")
    if isinstance(geom, dict):
        values = [geom.get("min_x"), geom.get("min_y"), geom.get("max_x"), geom.get("max_y")]
        if any(value is not None for value in values):
            return [_number(value) or 0.0 for value in values]
    return None


def _append_bounds_violation(
    violations: List[Dict[str, Any]],
    kind: str,
    object_id: str,
    bbox: Optional[List[float]],
    width: float,
    height: float,
) -> None:
    if not bbox or len(bbox) < 4:
        return
    if max(abs(value) for value in bbox) <= 1.0:
        return
    x1, y1, x2, y2 = bbox[:4]
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        violations.append({
            "kind": kind,
            "id": object_id,
            "bbox": bbox,
            "processed_bounds": [0, 0, width, height],
        })


def _number(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _write_bundle(bundle_path: Path, diagnostics_dir: Path, filenames: Iterable[str]) -> None:
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in filenames:
            path = diagnostics_dir / name
            if path.exists():
                archive.write(path, arcname=name)


def _artifact_metadata(diagnostics_run_id: str, diagnostics_dir: Path) -> List[Dict[str, Any]]:
    artifacts = []
    for path in sorted(diagnostics_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        artifacts.append({
            "name": path.name,
            "type": _artifact_type(path),
            "path": str(path.resolve()),
            "size": _format_size(path.stat().st_size),
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "content_url": f"/diagnostics/{diagnostics_run_id}/artifacts/{path.name}",
            "download_url": f"/diagnostics/{diagnostics_run_id}/artifacts/{path.name}?download=true",
        })
    return artifacts


def _artifact_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "image"
    if suffix == ".zip":
        return "zip"
    return "text"


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _select_main_table(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    if metadata.get("selected_table_available", metrics.get("selected_table_available", True)) is False:
        return None
    tables = metadata.get("structured_tables")
    if not isinstance(tables, list) or not tables:
        return None

    selected_id = _selected_table_id(metadata)
    if selected_id:
        for table in tables:
            if isinstance(table, dict) and _table_id(table) == selected_id:
                return table

    return max(
        (table for table in tables if isinstance(table, dict)),
        key=lambda table: (
            float(table.get("representability_score") or 0.0),
            _count_rows(table),
            _count_cols(table),
        ),
        default=None,
    )


def _selected_table_id(metadata: Dict[str, Any]) -> Optional[str]:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    if metadata.get("selected_table_available", metrics.get("selected_table_available", True)) is False:
        return None
    selected_id = metadata.get("selected_table_id") or metrics.get("selected_main_table_id")
    if selected_id:
        return str(selected_id)

    scores = metrics.get("main_table_candidate_scores")
    if isinstance(scores, list) and scores:
        top = scores[0]
        if isinstance(top, dict) and top.get("table_id"):
            return str(top["table_id"])

    return None


def _table_id(table: Any) -> Optional[str]:
    return table.get("table_id") if isinstance(table, dict) else None


def _count_rows(table: Dict[str, Any]) -> int:
    rows = table.get("rows")
    if isinstance(rows, list):
        return len(rows)
    if isinstance(rows, int):
        return rows
    return len({_axis_key(cell, "row") for cell in table.get("cells") or []})


def _count_cols(table: Dict[str, Any]) -> int:
    cols = table.get("columns") or table.get("cols")
    if isinstance(cols, list):
        return len(cols)
    if isinstance(cols, int):
        return cols
    return len({_axis_key(cell, "col") for cell in table.get("cells") or []})


def _axis_key(cell: Dict[str, Any], axis: str) -> str:
    if axis == "row":
        return str(cell.get("row_index", cell.get("row_id", cell.get("row", 0))))
    return str(cell.get("col_index", cell.get("col_id", cell.get("col", 0))))


def _sort_key(value: str) -> tuple[int, str]:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return (int(digits) if digits else 10**9, str(value))


def _geometry(table: Dict[str, Any]) -> Any:
    geom = table.get("geometry") or table.get("normalized_geometry")
    if isinstance(geom, dict):
        return [
            geom.get("min_x"),
            geom.get("min_y"),
            geom.get("max_x"),
            geom.get("max_y"),
        ]
    return table.get("bbox") or table.get("normalized_bbox")


def _row_math_status(metadata: Dict[str, Any]) -> str:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    failed = metrics.get("rows_math_failed")
    passed = metrics.get("rows_math_passed")
    if failed:
        return "fail"
    if passed:
        return "pass"
    return "unmeasurable"


def _footer_status(qg: Dict[str, Any]) -> str:
    reasons = qg.get("reasons") or []
    footer_reasons = [reason for reason in reasons if "footer" in str(reason).lower()]
    return ", ".join(map(str, footer_reasons)) if footer_reasons else ""


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return json_safe(asdict(value))
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        safe_dict = {}
        for k, v in value.items():
            key = str(k)
            lower_key = key.lower()
            if "data_url" in lower_key or "base64" in lower_key or "image_data" in lower_key:
                safe_dict[key] = f"<redacted {len(str(v))} chars>"
            else:
                safe_dict[key] = json_safe(v)
        return safe_dict
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    return str(value)
