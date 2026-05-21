#!/usr/bin/env python3
"""
Generate forensic wrong-column assignment audit markdown.

Diagnostic-only: this script reads current forensic/benchmark artifacts and
does not mutate extraction, reconstruction, validation, or topology code.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scratch.parse_wrong_columns import (  # noqa: E402
    BENCHMARK_OUTPUTS,
    FORENSIC_ROOT,
    WrongColumnFailure,
    discover_sources,
    parse_all,
    summarize,
)


def _escape(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", "<br>")
    return text.replace("|", "\\|")


def _table(headers: List[str], rows: Iterable[Iterable[object]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(_escape(value) for value in row) + " |")
    return "\n".join(output)


def _counter_rows(counter, limit: int | None = None) -> List[Tuple[object, object]]:
    rows = counter.most_common(limit)
    return rows if rows else [("none", 0)]


def _mapped_ids(record: WrongColumnFailure) -> str:
    if not record.mapped_block_ids:
        return "n/a"
    parts = []
    for key in sorted(record.mapped_block_ids):
        values = record.mapped_block_ids[key]
        parts.append(f"{key}: {', '.join(values) if values else '[]'}")
    return "<br>".join(parts)


def _example_rows(records: List[WrongColumnFailure]) -> List[List[object]]:
    rows = []
    for record in records[:3]:
        rows.append([
            record.invoice_filename,
            record.selected_topology_source,
            record.row_id,
            record.product_text or "n/a",
            record.qty_text or "n/a",
            record.free_qty_text or "n/a",
            record.rate_text or "n/a",
            record.mrp_text or "n/a",
            record.gst_text or "n/a",
            record.amount_text or "n/a",
            record.parsed_qty or "n/a",
            record.parsed_rate or "n/a",
            record.parsed_amount or "n/a",
            _mapped_ids(record),
            record.diagnosis,
        ])
    return rows


def _write_report(records: List[WrongColumnFailure], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "wrong_column_assignment_audit.md"
    summary = summarize(records)
    forensic_sources, json_sources = discover_sources()

    grouped = defaultdict(list)
    for record in records:
        grouped[record.confusion_pattern].append(record)

    lines = [
        "# Wrong Column Assignment Audit",
        "",
        f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Forensic audit inputs: `{len(forensic_sources)}` from `{FORENSIC_ROOT.relative_to(PROJECT_ROOT)}`",
        f"- Benchmark JSON inputs: `{len(json_sources)}` from `{BENCHMARK_OUTPUTS.relative_to(PROJECT_ROOT)}`",
        f"- Total wrong-column failures: **{len(records)}**",
        "",
        "## Summary",
        "",
        _table(["Metric", "Value"], [["Total wrong-column failures", len(records)]]),
        "",
        "## Failures By Invoice",
        "",
        _table(["Invoice", "Failures"], _counter_rows(summary["by_invoice"])),
        "",
        "## Failures By Selected Topology",
        "",
        _table(["Selected topology", "Failures"], _counter_rows(summary["by_topology"])),
        "",
        "## Failures By Confusion Pattern",
        "",
        _table(["Confusion pattern", "Failures"], _counter_rows(summary["by_pattern"])),
        "",
        "## Top Repeated Text Patterns",
        "",
        _table(["Cell text", "Occurrences"], _counter_rows(summary["text_patterns"], 20)),
        "",
        "## Pattern Examples",
        "",
    ]

    if not records:
        lines.extend([
            "No failures with `Assigned Cause = cell assignment to wrong column` were found in the current local artifacts.",
            "",
            "This usually means the benchmark outputs or `forensic_runs/*/row_math_failure_audit.md` files are absent from this checkout.",
            "",
        ])
    else:
        for pattern, pattern_records in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
            lines.extend([
                f"### {pattern}",
                "",
                f"Failures: **{len(pattern_records)}**",
                "",
                _table(
                    [
                        "Invoice filename",
                        "Selected topology source",
                        "Row ID",
                        "Product cell text",
                        "Qty cell text",
                        "Free qty cell text",
                        "Rate cell text",
                        "MRP cell text",
                        "GST cell text",
                        "Amount cell text",
                        "Parsed qty",
                        "Parsed rate",
                        "Parsed amount",
                        "Mapped block IDs",
                        "Short diagnosis",
                    ],
                    _example_rows(pattern_records),
                ),
                "",
            ])

    lines.extend([
        "## Notes",
        "",
        "- This report is diagnostic-only.",
        "- No extraction, topology selection, row validation, or reconciliation code is modified by the audit generator.",
        "- Confusion patterns are assigned by deterministic cell-text rules in `scratch/parse_wrong_columns.py`.",
        "",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> int:
    timestamp = os.environ.get("WRONG_COLUMN_AUDIT_TS") or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "forensic_runs" / timestamp
    records = parse_all()
    report_path = _write_report(records, output_dir)
    summary = summarize(records)
    print(f"report_path={report_path.relative_to(PROJECT_ROOT)}")
    print(f"total_wrong_column_failures={len(records)}")
    top_patterns = ", ".join(f"{name}:{count}" for name, count in summary["by_pattern"].most_common(3)) or "none"
    print(f"top_patterns={top_patterns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
