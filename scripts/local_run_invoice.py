import argparse
import json
import shutil
import traceback
from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image


def safe_json_dump(path: Path, data):
    def default(o):
        if hasattr(o, "model_dump"):
            return o.model_dump()
        if hasattr(o, "dict"):
            return o.dict()
        if hasattr(o, "__dict__"):
            return o.__dict__
        return str(o)

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=default),
        encoding="utf-8",
    )


def get_nested(data, paths):
    for path in paths:
        current = data
        parts = path.split(".") if isinstance(path, str) else list(path)
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, (list, tuple)) and isinstance(part, int):
                current = current[part] if 0 <= part < len(current) else None
            else:
                current = getattr(current, part, None)
            if current is None:
                break
        if current is not None:
            return current
    return None


def find_key_recursive(data, key, max_depth=4):
    if max_depth < 0:
        return None
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = find_key_recursive(value, key, max_depth=max_depth - 1)
            if found is not None:
                return found
    elif isinstance(data, (list, tuple)):
        for value in data:
            found = find_key_recursive(value, key, max_depth=max_depth - 1)
            if found is not None:
                return found
    return None


def build_summary(final, validation=None, ocr_result=None, reconstruction=None):
    errors = final.get("errors", [])
    summary = {
        "status": final.get("status"),
        "image_path": final.get("image_path"),
        "run_dir": final.get("run_dir"),
        "image_validation": _image_validation_summary(validation),
        "ocr": _ocr_summary(ocr_result),
        "reconstruction": _reconstruction_summary(reconstruction),
        "errors": errors,
    }
    return summary


def _image_validation_summary(validation):
    validation = validation if isinstance(validation, dict) else {}
    return {
        "is_valid": validation.get("is_valid"),
        "quality_score": validation.get("quality_score"),
        "warnings": validation.get("warnings", []),
        "errors": validation.get("errors", []),
        "properties": validation.get("properties", {}),
    }


def _ocr_summary(ocr_result):
    if not isinstance(ocr_result, dict):
        return {}

    blocks = ocr_result.get("blocks")
    text = ocr_result.get("text")
    metadata = ocr_result.get("metadata") if isinstance(ocr_result.get("metadata"), dict) else {}
    return {
        "block_count": len(blocks) if isinstance(blocks, list) else None,
        "text_length": len(text) if isinstance(text, str) else None,
        "rotation_detection": metadata.get("rotation_detection"),
        "rotation_applied": metadata.get("rotation_applied"),
        "rotation_angle": metadata.get("rotation_angle"),
        "legacy_rotation_applied": metadata.get("legacy_rotation_applied"),
        "legacy_rotation_angle": metadata.get("legacy_rotation_angle"),
    }


def _reconstruction_summary(reconstruction):
    if not isinstance(reconstruction, dict):
        return {}

    metadata = reconstruction.get("metadata") if isinstance(reconstruction.get("metadata"), dict) else {}
    token_coverage = get_nested(reconstruction, [
        "metadata.token_coverage",
        "metrics.token_coverage",
    ]) or find_key_recursive(reconstruction, "token_coverage")
    tsr_status = get_nested(reconstruction, ["metadata.tsr_status"]) or find_key_recursive(reconstruction, "tsr_status")
    row_role_metrics = (
        get_nested(reconstruction, ["metadata.row_role_metrics"])
        or find_key_recursive(reconstruction, "row_role_metrics")
    )

    structured_tables = reconstruction.get("structured_tables")
    rows_math_failed = find_key_recursive(reconstruction, "rows_math_failed")
    if rows_math_failed is None:
        rows_math_failed = find_key_recursive(reconstruction, "row_math_fail_count")

    return {
        "invoice_confidence": (
            metadata.get("invoice_confidence")
            or reconstruction.get("invoice_confidence")
            or find_key_recursive(reconstruction, "invoice_confidence")
        ),
        "token_coverage": token_coverage,
        "tsr_status": tsr_status,
        "row_role_metrics": row_role_metrics,
        "item_row_count": find_key_recursive(reconstruction, "item_row_count"),
        "structured_table_count": len(structured_tables) if isinstance(structured_tables, list) else None,
        "rows_math_failed": rows_math_failed,
    }


def main():
    parser = argparse.ArgumentParser(description="Run local invoice OCR pipeline end-to-end.")
    parser.add_argument("--image", required=True, help="Path to invoice image")
    parser.add_argument("--out", default=None, help="Output run directory")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    run_dir = Path(args.out or f"local_runs/{datetime.now().strftime('%Y%m%d_%H%M%S')}").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    final = {
        "status": "started",
        "image_path": str(image_path),
        "run_dir": str(run_dir),
        "stages": {},
        "errors": [],
    }
    validation = None
    ocr_result = None
    reconstruction = None

    try:
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        shutil.copyfile(image_path, run_dir / f"input{image_path.suffix.lower()}")

        image_bytes = image_path.read_bytes()
        from services.validators.image_validator import ImageValidator

        validation = ImageValidator.validate_image(image_bytes)
        safe_json_dump(run_dir / "01_image_validation.json", validation)
        final["stages"]["image_validation"] = validation

        if not validation.get("is_valid"):
            final["status"] = "failed"
            final["errors"].append({
                "type": "ImageValidationError",
                "message": validation.get("error_message", "Image validation failed."),
                "errors": validation.get("errors", []),
            })
            return

        image = Image.open(image_path).convert("RGB")

        from services.ocr_engine import process_image

        ocr_result = process_image(image)
        safe_json_dump(run_dir / "02_ocr_result.json", ocr_result)

        if isinstance(ocr_result, dict):
            blocks = ocr_result.get("blocks", [])
        else:
            blocks = getattr(ocr_result, "blocks", [])

        final["stages"]["ocr"] = {
            "block_count": len(blocks) if blocks is not None else 0,
            "type": type(ocr_result).__name__,
        }

        from services.spatial_reconstruction import reconstruct_layout

        reconstruction = reconstruct_layout(blocks, image=image)
        safe_json_dump(run_dir / "03_reconstruction.json", reconstruction)

        final["stages"]["reconstruction"] = {
            "type": type(reconstruction).__name__,
            "keys": list(reconstruction.keys()) if isinstance(reconstruction, dict) else [],
            "metrics": reconstruction.get("metrics", {}) if isinstance(reconstruction, dict) else {},
        }

        final["status"] = "ok"

    except Exception as e:
        final["status"] = "failed"
        final["errors"].append({
            "type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        })
        print(traceback.format_exc())

    finally:
        safe_json_dump(run_dir / "summary.json", build_summary(final, validation, ocr_result, reconstruction))
        safe_json_dump(run_dir / "final_result.json", final)
        print(f"Local run written to: {run_dir}")
        print(json.dumps(final, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
