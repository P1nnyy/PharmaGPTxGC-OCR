import argparse
import json
import traceback
from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw

from services.layout_pipeline.canonical_invoice import build_canonical_invoice
from services.layout_pipeline.reconstruction_forensics import build_reconstruction_forensics


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


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


def find_images(input_dir: Path, only: set[str] | None = None) -> list[Path]:
    images = [
        path for path in sorted(input_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if only:
        images = [path for path in images if path.stem in only or any(path.stem.startswith(stem) for stem in only)]
    return images


def process_image(image_path: Path) -> tuple[dict, dict | None]:
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
        return {"pipeline_crashed": True, "errors": [error], "blocks": []}, error

    image = Image.open(image_path).convert("RGB")
    ocr_result = run_ocr(image)
    blocks = ocr_result.get("blocks", []) if isinstance(ocr_result, dict) else getattr(ocr_result, "blocks", [])
    reconstruction = reconstruct_layout(blocks, debug=False, image=image)
    if isinstance(reconstruction, dict):
        reconstruction.setdefault("blocks", blocks)
        reconstruction.setdefault("image_path", str(image_path))
    return reconstruction, None


def render_markdown(report: dict, json_path: Path) -> str:
    lines = [
        "# Reconstruction Forensics",
        "",
        f"- JSON report: `{json_path.name}`",
        f"- Invoice count: {len(report.get('invoices') or [])}",
        "",
    ]
    for invoice in report.get("invoices") or []:
        forensic = invoice.get("forensics") or {}
        summary = forensic.get("summary") or {}
        lines.extend([
            f"## {invoice.get('filename')}",
            "",
            "### A. Summary",
            "",
            f"- OCR tokens: {summary.get('ocr_token_count', 0)}",
            f"- Rows: {summary.get('row_count', 0)}",
            f"- Cells: {summary.get('cell_count', 0)}",
            f"- Canonical items: {summary.get('canonical_item_count', 0)}",
            f"- Suspected failure layer: `{summary.get('suspected_failure_layer')}`",
            f"- Top issues: {', '.join(summary.get('top_issues') or []) or 'none'}",
            "",
            "### B. Top 10 Suspicious Rows",
            "",
            "| row_id | role | text | numeric tokens | canonical mapping | issues |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        suspicious_rows = sorted(
            forensic.get("rows") or [],
            key=lambda row: (0 if row.get("issues") else 1, -(len(row.get("issues") or []))),
        )[:10]
        for row in suspicious_rows:
            lines.append(
                "| {row_id} | {role} | {text} | {nums} | {mapping} | {issues} |".format(
                    row_id=row.get("row_id"),
                    role=_md(row.get("role")),
                    text=_md(_short(row.get("raw_text"), 120)),
                    nums=_md(", ".join(row.get("numeric_tokens") or []) or "none"),
                    mapping=_md(row.get("assigned_canonical_row") or "none"),
                    issues=_md(", ".join(row.get("issues") or []) or "none"),
                )
            )
        lines.extend(["", "### C. Semantic Poisoning Candidates", ""])
        candidates = forensic.get("semantic_poisoning_candidates") or []
        if not candidates:
            lines.append("none")
        else:
            lines.extend(["| column | label | contamination tokens | affected rows |", "| --- | --- | --- | --- |"])
            for candidate in candidates:
                lines.append(
                    f"| {candidate.get('column_id')} | {_md(candidate.get('label'))} | {_md(', '.join(candidate.get('contamination_tokens') or []))} | {_md(', '.join(candidate.get('affected_rows') or []) or 'n/a')} |"
                )
        lines.extend(["", "### D. Footer Leakage Candidates", ""])
        leakage = forensic.get("footer_leakage_candidates") or []
        if not leakage:
            lines.append("none")
        else:
            lines.extend(["| row_id | text | why suspicious |", "| --- | --- | --- |"])
            for candidate in leakage:
                lines.append(f"| {candidate.get('row_id')} | {_md(_short(candidate.get('text'), 120))} | {_md(candidate.get('why'))} |")
        lines.extend(["", "### E. Canonical Source Gaps", ""])
        gaps = [entry for entry in forensic.get("canonical_trace") or [] if entry.get("fields_missing_source_evidence")]
        if not gaps:
            lines.append("none")
        else:
            lines.extend(["| row/product | missing source fields | possible nearby candidates |", "| --- | --- | --- |"])
            for entry in gaps[:10]:
                nearby = ", ".join(token.get("text") for token in (entry.get("matched_source_tokens") or []) if token.get("text"))
                lines.append(
                    f"| {_md(entry.get('row_id'))}/{_md(_short(entry.get('product'), 50))} | {_md(', '.join(entry.get('fields_missing_source_evidence') or []))} | {_md(nearby or 'none')} |"
                )
        lines.extend(["", "### F. Target Product Trace", ""])
        traces = forensic.get("target_product_trace") or []
        if not traces:
            lines.append("none")
        else:
            for trace in traces:
                lines.append(f"- Target `{_md(trace.get('target'))}`: tokens={len(trace.get('matching_tokens') or [])}, rows={len(trace.get('matching_rows') or [])}, canonical={len(trace.get('matching_canonical_rows') or [])}")
                lines.append(f"  - Nearby numeric tokens: {_md(', '.join(token.get('text') for token in (trace.get('nearby_numeric_tokens') or [])[:20]) or 'none')}")
                lines.append(f"  - Expected values present: {trace.get('expected_value_presence')}")
        diagnosis = invoice.get("diagnosis") or {}
        lines.extend([
            "",
            "### G. Final Diagnosis",
            "",
            f"- Diagnosis: `{diagnosis.get('layer') or summary.get('suspected_failure_layer')}`",
            f"- Reasoning: {diagnosis.get('reasoning') or 'See top issues and traces above.'}",
            "",
        ])
    return "\n".join(lines)


def final_diagnosis(forensics: dict) -> dict:
    summary = forensics.get("summary") or {}
    layer = summary.get("suspected_failure_layer") or "insufficient_debug_evidence"
    tokens = summary.get("ocr_token_count", 0)
    rows = summary.get("row_count", 0)
    cells = summary.get("cell_count", 0)
    issues = summary.get("top_issues") or []
    reasoning = f"tokens={tokens}, rows={rows}, cells={cells}, top_issues={', '.join(issues) or 'none'}"
    return {"layer": layer, "reasoning": reasoning}


def generate_overlays(image_path: Path, forensics: dict, out_dir: Path, no_overlays: bool = False) -> dict:
    if no_overlays:
        return {"status": "skipped", "reason": "disabled"}
    try:
        image = Image.open(image_path).convert("RGB")
    except Exception as exc:
        return {"status": "skipped", "reason": f"image_open_failed:{exc}"}

    stem = image_path.stem
    outputs = {}
    overlay_specs = {
        "ocr_tokens": _draw_tokens,
        "rows": _draw_rows,
        "columns": _draw_columns,
        "semantic": _draw_semantic,
    }
    for name, draw_fn in overlay_specs.items():
        canvas = image.copy()
        draw = ImageDraw.Draw(canvas)
        draw_fn(draw, forensics)
        path = out_dir / f"{stem}_{name}.png"
        canvas.save(path)
        outputs[name] = str(path)
    return {"status": "generated", "paths": outputs}


def _draw_tokens(draw, forensics):
    for token in forensics.get("tokens") or []:
        box = _box(token)
        if not box:
            continue
        draw.rectangle(box, outline=(230, 80, 40), width=2)
        draw.text((box[0], max(0, box[1] - 10)), str(token.get("text") or "")[:12], fill=(230, 80, 40))


def _draw_rows(draw, forensics):
    for row in forensics.get("rows") or []:
        y_min, y_max = row.get("y_min"), row.get("y_max")
        if y_min is None or y_max is None:
            continue
        color = (50, 150, 80)
        role = str(row.get("role") or "").lower()
        if "footer" in role:
            color = (70, 100, 230)
        elif "tax" in role:
            color = (200, 120, 30)
        elif row.get("issues"):
            color = (230, 40, 60)
        draw.rectangle((0, y_min, 2000, y_max), outline=color, width=2)
        draw.text((4, y_min), f"{row.get('row_id')} {row.get('role')}", fill=color)


def _draw_columns(draw, forensics):
    for column in forensics.get("columns") or []:
        x_min, x_max = column.get("x_min"), column.get("x_max")
        if x_min is None or x_max is None:
            continue
        color = (120, 70, 220) if not column.get("issues") else (230, 40, 60)
        draw.rectangle((x_min, 0, x_max, 3000), outline=color, width=2)
        draw.text((x_min, 4), f"{column.get('column_id')} {column.get('semantic_label')}", fill=color)


def _draw_semantic(draw, forensics):
    for column in forensics.get("columns") or []:
        x_min, x_max = column.get("x_min"), column.get("x_max")
        if x_min is None or x_max is None:
            continue
        label = str(column.get("semantic_label") or "unknown")
        color = _semantic_color(label)
        draw.rectangle((x_min, 0, x_max, 3000), outline=color, width=3)
        draw.text((x_min, 18), label, fill=color)


def _semantic_color(label: str):
    label = label.lower()
    if "amount" in label:
        return (220, 40, 40)
    if "rate" in label:
        return (220, 120, 30)
    if "qty" in label or "quantity" in label:
        return (40, 150, 80)
    if "product" in label:
        return (40, 90, 220)
    return (100, 100, 100)


def _box(item):
    keys = ("x_min", "y_min", "x_max", "y_max")
    values = [item.get(key) for key in keys]
    if any(value is None for value in values):
        return None
    return tuple(values)


def _short(value, limit=100):
    text = str(value or "").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _md(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def main():
    parser = argparse.ArgumentParser(description="Run reconstruction forensic audit on selected invoices.")
    parser.add_argument("--input-dir", default="test_images", help="Directory containing invoice images")
    parser.add_argument("--only", default="", help="Comma-separated filename stems to audit")
    parser.add_argument("--target-product", action="append", default=[], help="Product token to trace, can be repeated")
    parser.add_argument("--output-dir", default="local_runs/reconstruction_forensics", help="Base output directory")
    parser.add_argument("--no-overlays", action="store_true", help="Skip overlay PNG generation")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    only = {part.strip() for part in args.only.split(",") if part.strip()} or None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir).expanduser().resolve() / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    images = find_images(input_dir, only)
    invoices = []
    for image_path in images:
        try:
            reconstruction, error = process_image(image_path)
            canonical = build_canonical_invoice(reconstruction, invoice_id=image_path.stem)
            forensics = build_reconstruction_forensics(reconstruction, canonical, target_products=args.target_product)
            overlays = generate_overlays(image_path, forensics, out_dir, no_overlays=args.no_overlays)
        except Exception as exc:
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            reconstruction = {"pipeline_crashed": True, "errors": [error]}
            forensics = build_reconstruction_forensics(reconstruction, target_products=args.target_product)
            overlays = {"status": "skipped", "reason": "pipeline_error"}
        invoices.append({
            "filename": image_path.name,
            "image_path": str(image_path),
            "error": error,
            "forensics": forensics,
            "diagnosis": final_diagnosis(forensics),
            "overlays": overlays,
        })

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_dir": str(input_dir),
        "output_dir": str(out_dir),
        "target_products": args.target_product,
        "image_count": len(images),
        "invoices": invoices,
    }
    json_path = out_dir / "reconstruction_forensics.json"
    md_path = out_dir / "reconstruction_forensics.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report, json_path), encoding="utf-8")

    print(f"Output folder: {out_dir}")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    for invoice in invoices:
        print(f"{invoice['filename']}: {invoice['diagnosis']['layer']} | overlays={invoice['overlays'].get('status')}")


if __name__ == "__main__":
    main()
