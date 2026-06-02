import argparse
import json
import traceback
from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
DEFAULT_INPUT_DIRS = ("test_images", "benchmarks", "scripts/benchmarks", "local_runs")


def json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=json_default), encoding="utf-8")


def find_images(input_dir: Path | None) -> list[Path]:
    search_dirs = [input_dir] if input_dir else [REPO_ROOT / path for path in DEFAULT_INPUT_DIRS]
    images = []
    for directory in search_dirs:
        if not directory or not directory.exists() or not directory.is_dir():
            continue
        images.extend(
            path for path in sorted(directory.rglob("*"))
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
        if images:
            break
    return images


def safe_get(data, path, default=None):
    current = data
    for part in path:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and isinstance(part, int):
            current = current[part] if 0 <= part < len(current) else None
        else:
            return default
        if current is None:
            return default
    return current


def first_footer_value(canonical_invoice, label):
    for field in canonical_invoice.get("footer_fields") or []:
        if field.get("label") == label:
            return field.get("value")
    return None


def summarize_selected_candidates(selected_candidates):
    if not isinstance(selected_candidates, dict):
        return {}
    summary = {}
    for label, candidate in selected_candidates.items():
        if not isinstance(candidate, dict):
            continue
        summary[label] = {
            "value": candidate.get("value"),
            "confidence": candidate.get("confidence"),
            "line_text": candidate.get("line_text"),
        }
    return summary


def format_selected_candidates(selected_candidates):
    if not selected_candidates:
        return "none"
    parts = []
    for label, candidate in sorted(selected_candidates.items()):
        if not isinstance(candidate, dict):
            continue
        confidence = candidate.get("confidence")
        confidence_text = f"{float(confidence):.2f}" if isinstance(confidence, (int, float)) else "n/a"
        parts.append(f"{label}={candidate.get('value')} ({confidence_text})")
    return ", ".join(parts) or "none"


def format_applied_fields(applied_fields):
    if not applied_fields:
        return "none"
    parts = []
    for field in applied_fields:
        if isinstance(field, dict):
            parts.append(f"{field.get('label')}={field.get('value')}")
        else:
            parts.append(str(field))
    return ", ".join(parts) or "none"


def summarize_reconstruction(image_path: Path, original_status: str, reconstruction: dict, error: dict | None = None) -> dict:
    reconstruction = reconstruction if isinstance(reconstruction, dict) else {}
    canonical = reconstruction.get("canonical_invoice") or {}
    quality_gate = reconstruction.get("quality_gate") or {}
    layout_profile = reconstruction.get("layout_profile") or {}
    footer_rescue = reconstruction.get("footer_rescue") or {}
    q_metrics = quality_gate.get("metrics") or {}
    metrics = reconstruction.get("metrics") or {}

    row_math_passed = q_metrics.get("rows_math_passed")
    row_math_failed = q_metrics.get("rows_math_failed")
    row_math_missing = row_math_passed is None and row_math_failed is None
    missing_footer_fields = (
        footer_rescue.get("missing_fields")
        or q_metrics.get("missing_footer_fields")
        or []
    )
    selected_candidates = summarize_selected_candidates(footer_rescue.get("selected_candidates"))
    applied_fields = footer_rescue.get("applied_fields") or []
    candidate_fields = footer_rescue.get("candidate_fields") or {}
    if isinstance(candidate_fields, dict):
        candidate_count = sum(len(candidates) for candidates in candidate_fields.values() if isinstance(candidates, list))
    else:
        candidate_count = len(candidate_fields)

    return {
        "filename": image_path.name,
        "image_path": str(image_path),
        "original_status": original_status,
        "status_effective": reconstruction.get("status_effective") or quality_gate.get("status"),
        "safe_for_erp": reconstruction.get("safe_for_erp"),
        "invoice_confidence": (
            reconstruction.get("invoice_confidence")
            if reconstruction.get("invoice_confidence") is not None
            else safe_get(reconstruction, ("metadata", "invoice_confidence"))
        ),
        "item_rows": len(canonical.get("item_rows") or reconstruction.get("item_rows_clean") or []),
        "row_math_passed": row_math_passed,
        "row_math_failed": row_math_failed,
        "row_math_missing": row_math_missing,
        "subtotal": first_footer_value(canonical, "subtotal"),
        "discount": first_footer_value(canonical, "discount"),
        "sgst": first_footer_value(canonical, "sgst"),
        "cgst": first_footer_value(canonical, "cgst"),
        "grand_total": first_footer_value(canonical, "grand_total"),
        "layout_profile": layout_profile.get("profile"),
        "quality_reasons": quality_gate.get("reasons") or [],
        "footer_missing_fields": missing_footer_fields,
        "footer_missing_before_rescue": footer_rescue.get("missing_fields") or [],
        "footer_selected_candidates": selected_candidates,
        "footer_applied_fields": applied_fields,
        "footer_rescue_warnings": footer_rescue.get("warnings") or [],
        "footer_conflicting_candidates": footer_rescue.get("conflicting_candidates") or {},
        "footer_bottom_region_line_count": footer_rescue.get("bottom_region_line_count"),
        "footer_lines_used": footer_rescue.get("footer_lines_used") or [],
        "footer_rescue_candidate_count": candidate_count,
        "footer_rescue_applied_count": len(applied_fields),
        "fast_fail": reconstruction.get("fast_fail"),
        "fast_fail_reason": reconstruction.get("fast_fail_reason"),
        "raw_token_count": metrics.get("raw_token_count"),
        "error": error,
    }


def process_image(image_path: Path, benchmark_mode: bool = False) -> tuple[dict, dict]:
    from services.validators.image_validator import ImageValidator
    from services.ocr_engine import process_image as run_ocr
    from services.spatial_reconstruction import reconstruct_layout

    validation = ImageValidator.validate_image(image_path.read_bytes())
    if not validation.get("is_valid"):
        error = {
            "type": "ImageValidationError",
            "message": validation.get("error_message", "Image validation failed."),
            "errors": validation.get("errors", []),
        }
        reconstruction = {
            "pipeline_crashed": True,
            "errors": [error],
            "blocks": [],
        }
        from services.layout_pipeline.invoice_diagnostics import attach_invoice_diagnostics
        attach_invoice_diagnostics(reconstruction, invoice_id=image_path.stem)
        return reconstruction, error

    image = Image.open(image_path).convert("RGB")
    ocr_result = run_ocr(image)
    blocks = ocr_result.get("blocks", []) if isinstance(ocr_result, dict) else getattr(ocr_result, "blocks", [])
    reconstruction = reconstruct_layout(
        blocks,
        debug=False,
        image=image,
        benchmark_mode=benchmark_mode,
    )
    return reconstruction, None


def render_markdown(rows: list[dict], json_path: Path) -> str:
    lines = [
        "# Invoice Batch Diagnostics",
        "",
        f"- JSON report: `{json_path.name}`",
        f"- Invoice count: {len(rows)}",
        "",
        "| Filename | Original | Effective | Confidence | Missing before rescue | Selected candidates | Applied fields | Warnings | Profile | Reasons |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        confidence = row.get("invoice_confidence")
        confidence_text = f"{float(confidence):.3f}" if isinstance(confidence, (int, float)) else "n/a"
        lines.append(
            "| {filename} | {original} | {effective} | {confidence} | {missing} | {selected} | {applied} | {warnings} | {profile} | {reasons} |".format(
                filename=row.get("filename"),
                original=row.get("original_status"),
                effective=row.get("status_effective"),
                confidence=confidence_text,
                missing=", ".join(row.get("footer_missing_before_rescue") or []) or "none",
                selected=format_selected_candidates(row.get("footer_selected_candidates")),
                applied=format_applied_fields(row.get("footer_applied_fields")),
                warnings=", ".join(row.get("footer_rescue_warnings") or []) or "none",
                profile=row.get("layout_profile") or "unknown",
                reasons=", ".join(row.get("quality_reasons") or []) or "none",
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run same-day invoice OCR batch diagnostics.")
    parser.add_argument("--input-dir", default=None, help="Directory containing invoice images")
    parser.add_argument("--out-dir", default="local_runs/batch_diagnostics", help="Directory for report outputs")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable reconstruction benchmark-mode fast-fail behavior")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve() if args.input_dir else None
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"batch_diagnostics_{timestamp}.json"
    md_path = out_dir / f"batch_diagnostics_{timestamp}.md"

    images = find_images(input_dir)
    rows = []
    full_results = []
    for image_path in images:
        try:
            reconstruction, error = process_image(image_path, benchmark_mode=args.benchmark_mode)
            original_status = "failed" if error else "ok"
        except Exception as exc:
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            reconstruction = {
                "pipeline_crashed": True,
                "errors": [error],
                "blocks": [],
            }
            from services.layout_pipeline.invoice_diagnostics import attach_invoice_diagnostics
            attach_invoice_diagnostics(reconstruction, invoice_id=image_path.stem)
            original_status = "failed"

        rows.append(summarize_reconstruction(image_path, original_status, reconstruction, error=error))
        full_results.append({
            "filename": image_path.name,
            "summary": rows[-1],
            "quality_gate": reconstruction.get("quality_gate"),
            "layout_profile": reconstruction.get("layout_profile"),
            "footer_rescue": reconstruction.get("footer_rescue"),
            "canonical_invoice": reconstruction.get("canonical_invoice"),
        })

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_dir": str(input_dir) if input_dir else None,
        "image_count": len(images),
        "rows": rows,
        "results": full_results,
    }
    write_json(json_path, report)
    md_path.write_text(render_markdown(rows, json_path), encoding="utf-8")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    print(render_markdown(rows, json_path))


if __name__ == "__main__":
    main()
