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

    try:
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        shutil.copyfile(image_path, run_dir / f"input{image_path.suffix.lower()}")

        image = Image.open(image_path).convert("RGB")

        validation = {
            "skipped": True,
            "reason": "image_validator not wired yet",
            "properties": {
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
            },
        }
        safe_json_dump(run_dir / "01_image_validation.json", validation)
        final["stages"]["image_validation"] = validation

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
        safe_json_dump(run_dir / "final_result.json", final)
        print(f"Local run written to: {run_dir}")
        print(json.dumps(final, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
