import json
import argparse
from pathlib import Path
from statistics import median


def bbox_from_polygon(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--y-threshold", type=float, default=10.0)
    args = parser.parse_args()

    data = json.loads(Path(args.ocr).read_text())
    blocks = data.get("blocks", [])

    items = []
    heights = []

    for b in blocks:
        text = (b.get("text") or "").strip()
        poly = b.get("polygon") or []
        if not text or not poly:
            continue

        x1, y1, x2, y2 = bbox_from_polygon(poly)
        h = y2 - y1
        heights.append(h)

        items.append({
            "text": text,
            "confidence": b.get("confidence"),
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "cy": (y1 + y2) / 2,
        })

    if not items:
        print("No OCR blocks found.")
        return

    # Use dynamic y threshold if possible.
    med_h = median(heights) if heights else args.y_threshold
    y_threshold = max(args.y_threshold, med_h * 0.75)

    items.sort(key=lambda r: (r["cy"], r["x1"]))

    lines = []
    current = []

    for item in items:
        if not current:
            current.append(item)
            continue

        current_y = median([r["cy"] for r in current])

        if abs(item["cy"] - current_y) <= y_threshold:
            current.append(item)
        else:
            current.sort(key=lambda r: r["x1"])
            lines.append(current)
            current = [item]

    if current:
        current.sort(key=lambda r: r["x1"])
        lines.append(current)

    output_lines = []
    output_lines.append(f"OCR blocks: {len(blocks)}")
    output_lines.append(f"Grouped lines: {len(lines)}")
    output_lines.append(f"Median token height: {med_h:.2f}")
    output_lines.append(f"Y threshold: {y_threshold:.2f}")
    output_lines.append("")
    output_lines.append("=" * 120)
    output_lines.append("LINE-BY-LINE OCR TEXT")
    output_lines.append("=" * 120)
    output_lines.append("")

    for i, line in enumerate(lines, 1):
        text = " | ".join(r["text"] for r in line)
        y = median([r["cy"] for r in line])
        output_lines.append(f"{i:03d} [y={y:.1f}] {text}")

    output = "\n".join(output_lines)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Saved line view to: {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
