#!/usr/bin/env python3
"""
Generate a row-token ownership audit for the 7e9a invoice.

Diagnostic-only: this script reads saved reconstruction JSON and forensic
markdown. It does not modify extraction, topology selection, validation, or
reconciliation code.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scratch.parse_wrong_columns import (  # noqa: E402
    FORENSIC_ROOT,
    WrongColumnFailure,
    parse_forensic_markdown,
)


INVOICE_PREFIX = "7e9a0d92"
SEMANTICS_OF_INTEREST = {
    "product",
    "quantity",
    "free_quantity",
    "mrp",
    "rate",
    "amount",
}


@dataclass
class Token:
    token_id: str
    text: str
    center_x: float
    center_y: float


@dataclass
class RowExport:
    row_id: str
    y_min: float
    y_max: float
    center_y: float
    cells: Dict[str, Dict[str, Any]]
    previous_overlap: List[str]
    next_overlap: List[str]
    assigned_closer_to_other_row: List[str]
    product_vs_numeric_leakage: str
    internal_baseline_gap_px: Optional[float]
    product_repair: Dict[str, Any]


def _escape(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", "<br>").replace("|", "\\|")


def _table(headers: List[str], rows: Iterable[Iterable[object]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(_escape(value) for value in row) + " |")
    return "\n".join(output)


def _find_reconstruction_json() -> Path:
    candidates = [
        PROJECT_ROOT / "results",
        PROJECT_ROOT / "scripts" / "benchmarks" / "outputs",
        PROJECT_ROOT / "datasets" / "ocr_results",
        PROJECT_ROOT.parent / "PharmaGPTxGC" / "results",
        PROJECT_ROOT.parent / "results",
        Path.home() / "Desktop" / "PharmaGPTxGC" / "results",
        Path.home() / "Desktop" / "results",
    ]
    for root in candidates:
        if not root.exists():
            continue
        matches = sorted(root.glob(f"*{INVOICE_PREFIX}*.json"))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"No saved JSON found for invoice prefix {INVOICE_PREFIX}")


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _center_from_polygon(block: Dict[str, Any]) -> tuple[float, float]:
    polygon = block.get("polygon") or []
    if polygon:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    geometry = block.get("geometry") or {}
    return float(geometry.get("center_x", 0.0)), float(geometry.get("center_y", 0.0))


def _tokens_by_id(metadata: Dict[str, Any]) -> Dict[str, Token]:
    tokens: Dict[str, Token] = {}
    for block in metadata.get("blocks", []) or []:
        token_id = str(block.get("id", ""))
        if not token_id:
            continue
        center_x, center_y = _center_from_polygon(block)
        tokens[token_id] = Token(token_id, str(block.get("text", "")), center_x, center_y)
    return tokens


def _semantic_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("type", value.get("semantic", ""))
    return str(value or "").lower().split(".")[-1]


def _selected_table(metadata: Dict[str, Any]) -> Dict[str, Any]:
    metrics = metadata.get("metrics") or {}
    financial = metrics.get("financial_reconciliation") or {}
    table_ids = [key for key in financial if key != "invoice_level"]
    if table_ids:
        for table in metadata.get("structured_tables", []) or []:
            if table.get("table_id") == table_ids[0]:
                return table
    for table in metadata.get("structured_tables", []) or []:
        if any((row.get("row_role") == "item_row") for row in table.get("rows", []) or []):
            return table
    raise ValueError("No selected/item table found in reconstruction JSON")


def _semantics_for_table(metadata: Dict[str, Any], table_id: str) -> Dict[str, str]:
    metrics = metadata.get("metrics") or {}
    candidates = [
        metrics.get("final_column_semantics", {}),
        (metrics.get("semantic_debug") or {}).get("final_column_semantics", {}),
        metrics.get("column_semantic_cache", {}),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        table_semantics = candidate.get(table_id, candidate)
        if not isinstance(table_semantics, dict):
            continue
        output = {
            str(col_id): _semantic_name(meta)
            for col_id, meta in table_semantics.items()
            if not str(col_id).startswith("_")
        }
        if output:
            return output
    return {}


def _fmt_tokens(tokens: List[Token]) -> str:
    if not tokens:
        return "n/a"
    return "<br>".join(f"{token.text} (`{token.token_id}` @ y={token.center_y:.1f})" for token in tokens)


def _fmt_ids(ids: List[str]) -> str:
    return ", ".join(ids) if ids else "none"


def _row_center(row: Dict[str, Any]) -> float:
    return float((row.get("geometry") or {}).get("center_y", 0.0))


def _nearest_row_id(center_y: float, rows: List[Dict[str, Any]]) -> str:
    nearest = min(rows, key=lambda row: abs(_row_center(row) - center_y))
    return str(nearest.get("row_id"))


def _cell_tokens(cell: Dict[str, Any], tokens_by_id: Dict[str, Token]) -> List[Token]:
    output = []
    for token_id in cell.get("mapped_block_ids", []) or []:
        token = tokens_by_id.get(str(token_id))
        if token:
            output.append(token)
    return output


def _build_row_exports(table: Dict[str, Any], semantics: Dict[str, str], tokens_by_id: Dict[str, Token]) -> List[RowExport]:
    rows = [row for row in table.get("rows", []) or [] if row.get("row_role") == "item_row"]
    rows.sort(key=_row_center)
    cells_by_row: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cell in table.get("cells", []) or []:
        cells_by_row[str(cell.get("row_id"))].append(cell)

    exports: List[RowExport] = []
    for idx, row in enumerate(rows):
        row_id = str(row.get("row_id"))
        row_geom = row.get("geometry") or {}
        previous_ids = {
            token_id
            for cell in cells_by_row.get(str(rows[idx - 1].get("row_id")), []) if idx > 0
            for token_id in (cell.get("mapped_block_ids") or [])
        }
        current_ids = {
            token_id
            for cell in cells_by_row.get(row_id, [])
            for token_id in (cell.get("mapped_block_ids") or [])
        }
        next_ids: set[str] = set()
        if idx + 1 < len(rows):
            next_ids = {
                token_id
                for cell in cells_by_row.get(str(rows[idx + 1].get("row_id")), [])
                for token_id in (cell.get("mapped_block_ids") or [])
            }

        cells: Dict[str, Dict[str, Any]] = {}
        assigned_closer: List[str] = []
        product_y: List[float] = []
        numeric_y: List[float] = []
        for cell in cells_by_row.get(row_id, []):
            semantic = semantics.get(str(cell.get("col_id")), "unknown")
            if semantic not in SEMANTICS_OF_INTEREST:
                continue
            cell_tokens = _cell_tokens(cell, tokens_by_id)
            token_ids = [token.token_id for token in cell_tokens]
            cells[semantic] = {
                "text": cell.get("text") or "",
                "mapped_block_ids": token_ids,
                "tokens": cell_tokens,
            }
            for token in cell_tokens:
                nearest = _nearest_row_id(token.center_y, rows)
                if nearest != row_id:
                    assigned_closer.append(f"{token.token_id}:{token.text} -> {nearest}")
            y_values = [token.center_y for token in cell_tokens]
            if semantic == "product":
                product_y.extend(y_values)
            elif semantic in {"quantity", "free_quantity", "mrp", "rate", "amount"}:
                numeric_y.extend(y_values)

        product_vs_numeric = "n/a"
        baseline_gap = None
        if product_y and numeric_y:
            baseline_gap = median(product_y) - median(numeric_y)
            if abs(baseline_gap) >= 3.0:
                direction = "below" if baseline_gap > 0 else "above"
                product_vs_numeric = f"product baseline is {abs(baseline_gap):.1f}px {direction} numeric baseline"
            else:
                product_vs_numeric = "product/numeric baselines aligned within 3px"

        exports.append(
            RowExport(
                row_id=row_id,
                y_min=float(row_geom.get("min_y", math.nan)),
                y_max=float(row_geom.get("max_y", math.nan)),
                center_y=float(row_geom.get("center_y", math.nan)),
                cells=cells,
                previous_overlap=sorted(current_ids & previous_ids),
                next_overlap=sorted(current_ids & next_ids),
                assigned_closer_to_other_row=assigned_closer,
                product_vs_numeric_leakage=product_vs_numeric,
                internal_baseline_gap_px=baseline_gap,
                product_repair=((row.get("provenance") if isinstance(row, dict) else getattr(row, "provenance", {})) or {}).get(
                    "product_phase_shift_repair", {}
                ),
            )
        )
    return exports


def _wrong_column_rows() -> Dict[str, WrongColumnFailure]:
    latest = sorted(FORENSIC_ROOT.glob("*/row_math_failure_audit.md"))
    by_row: Dict[str, WrongColumnFailure] = {}
    for path in latest:
        for record in parse_forensic_markdown(path):
            if record.invoice_filename.startswith(INVOICE_PREFIX):
                by_row[record.row_id] = record
    return by_row


def _visual_product_tokens(metadata: Dict[str, Any], table: Dict[str, Any], semantics: Dict[str, str]) -> List[Token]:
    tokens = _tokens_by_id(metadata)
    product_col_id = next((col_id for col_id, semantic in semantics.items() if semantic == "product"), "")
    product_geometry: Dict[str, Any] = {}
    for column in table.get("columns", []) or []:
        if column.get("col_id") == product_col_id:
            product_geometry = column.get("geometry") or {}
            break
    table_geometry = table.get("geometry") or {}
    x_min = max(float(product_geometry.get("min_x", 0.0)) + 35.0, 185.0)
    x_max = float(product_geometry.get("max_x", 0.0)) + 45.0
    y_min = float(table_geometry.get("min_y", 0.0)) - 25.0
    y_max = float(table_geometry.get("max_y", 0.0)) + 10.0
    output = []
    for token in tokens.values():
        text = token.text.upper()
        if not (x_min <= token.center_x <= x_max and y_min <= token.center_y <= y_max):
            continue
        if not any(char.isalpha() for char in text):
            continue
        if text in {"PRODUCT", "PRODUCT NAME"}:
            continue
        output.append(token)
    return sorted(output, key=lambda token: token.center_y)


def _orphan_product_evidence(
    metadata: Dict[str, Any],
    table: Dict[str, Any],
    tokens_by_id: Dict[str, Token],
    semantics: Dict[str, str],
) -> List[List[object]]:
    table_ids = {
        token_id
        for cell in table.get("cells", []) or []
        for token_id in (cell.get("mapped_block_ids") or [])
    }
    rows = []
    for token in _visual_product_tokens(metadata, table, semantics):
        if token.token_id in table_ids:
            continue
        owner = "unmapped"
        for other_table in metadata.get("structured_tables", []) or []:
            for cell in other_table.get("cells", []) or []:
                if token.token_id in (cell.get("mapped_block_ids") or []):
                    owner = f"{other_table.get('table_id')} / {cell.get('row_id')} / {cell.get('col_id')}"
                    break
            if owner != "unmapped":
                break
        rows.append([token.token_id, token.text, f"{token.center_y:.1f}", owner])
    return rows[:12]


def _owner_for_token(metadata: Dict[str, Any], token_id: str) -> str:
    for table in metadata.get("structured_tables", []) or []:
        for cell in table.get("cells", []) or []:
            if token_id in (cell.get("mapped_block_ids") or []):
                return f"{table.get('table_id')} / {cell.get('row_id')} / {cell.get('col_id')}"
    return "unmapped"


def _sequence_alignment_rows(metadata: Dict[str, Any], table: Dict[str, Any], exports: List[RowExport]) -> List[List[object]]:
    semantics = _semantics_for_table(metadata, str(table.get("table_id")))
    visual_products = _visual_product_tokens(metadata, table, semantics)
    visual_products.sort(key=lambda token: token.center_y)

    rows: List[List[object]] = []
    for idx in range(max(len(visual_products), len(exports))):
        visual = visual_products[idx] if idx < len(visual_products) else None
        export = exports[idx] if idx < len(exports) else None
        selected_product = ""
        amount = ""
        if export:
            selected_product = (export.cells.get("product") or {}).get("text", "")
            amount = (export.cells.get("amount") or {}).get("text", "")
        diagnosis = "aligned"
        if visual and export and visual.text != selected_product:
            diagnosis = "visual product sequence differs from selected row product"
        if visual and _owner_for_token(metadata, visual.token_id).split(" / ")[0] != table.get("table_id"):
            diagnosis = "visual product token is outside selected main table"
        rows.append([
            idx + 1,
            f"{visual.text} (`{visual.token_id}` @ y={visual.center_y:.1f})" if visual else "n/a",
            _owner_for_token(metadata, visual.token_id) if visual else "n/a",
            export.row_id if export else "n/a",
            selected_product or "n/a",
            amount or "n/a",
            diagnosis,
        ])
    return rows


def _row_export_rows(exports: List[RowExport], wrong_rows: Dict[str, WrongColumnFailure]) -> List[List[object]]:
    rows = []
    for export in exports:
        cells = export.cells
        product = cells.get("product", {})
        qty = cells.get("quantity", {})
        free_qty = cells.get("free_quantity", {})
        mrp = cells.get("mrp", {})
        rate = cells.get("rate", {})
        amount = cells.get("amount", {})
        rows.append([
            export.row_id,
            "yes" if export.row_id in wrong_rows else "no",
            f"{export.y_min:.1f}/{export.y_max:.1f}/{export.center_y:.1f}",
            _fmt_tokens(product.get("tokens", [])),
            _fmt_tokens(qty.get("tokens", [])),
            _fmt_tokens(free_qty.get("tokens", [])),
            _fmt_tokens(mrp.get("tokens", [])),
            _fmt_tokens(rate.get("tokens", [])),
            _fmt_tokens(amount.get("tokens", [])),
            _fmt_ids(product.get("mapped_block_ids", [])),
            _fmt_ids(qty.get("mapped_block_ids", [])),
            _fmt_ids(rate.get("mapped_block_ids", [])),
            _fmt_ids(amount.get("mapped_block_ids", [])),
            _fmt_ids(export.previous_overlap),
            _fmt_ids(export.next_overlap),
            "<br>".join(export.assigned_closer_to_other_row) if export.assigned_closer_to_other_row else "none",
            export.product_vs_numeric_leakage,
            _format_repair(export.product_repair),
        ])
    return rows


def _format_repair(repair: Dict[str, Any]) -> str:
    if not repair:
        return "n/a"
    before = repair.get("before") or {}
    after = repair.get("after") or {}
    return (
        f"before: {before.get('text', '')} [{_fmt_ids(before.get('mapped_block_ids') or [])}]"
        f"<br>after: {after.get('text', '')} [{_fmt_ids(after.get('mapped_block_ids') or [])}]"
    )


def _leakage_rows(exports: List[RowExport], wrong_rows: Dict[str, WrongColumnFailure]) -> List[List[object]]:
    rows = []
    for export in exports:
        checks = []
        if export.assigned_closer_to_other_row:
            checks.append("assigned token vertically closer to another row")
        if export.previous_overlap or export.next_overlap:
            checks.append("mapped block overlap with adjacent row")
        if export.internal_baseline_gap_px is not None and abs(export.internal_baseline_gap_px) >= 3.0:
            checks.append("product/numeric baseline phase gap")
        if export.row_id in wrong_rows:
            checks.append("row_math wrong-column failure")
        if not checks:
            continue
        rows.append([
            export.row_id,
            ", ".join(checks),
            f"{export.internal_baseline_gap_px:.1f}px" if export.internal_baseline_gap_px is not None else "n/a",
            export.product_vs_numeric_leakage,
            "<br>".join(export.assigned_closer_to_other_row) if export.assigned_closer_to_other_row else "none",
            _fmt_ids(export.previous_overlap),
            _fmt_ids(export.next_overlap),
        ])
    return rows


def _write_report(output_dir: Path, json_path: Path, payload: Dict[str, Any]) -> Path:
    metadata = payload.get("metadata") or {}
    tokens_by_id = _tokens_by_id(metadata)
    table = _selected_table(metadata)
    semantics = _semantics_for_table(metadata, str(table.get("table_id")))
    exports = _build_row_exports(table, semantics, tokens_by_id)
    wrong_rows = _wrong_column_rows()
    orphan_products = _orphan_product_evidence(metadata, table, tokens_by_id, semantics)
    leakage_rows = _leakage_rows(exports, wrong_rows)

    metrics = metadata.get("metrics") or {}
    report_path = output_dir / "row_token_ownership_audit.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Row Token Ownership Audit",
        "",
        f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Invoice prefix: `{INVOICE_PREFIX}`",
        f"- Reconstruction JSON: `{json_path}`",
        f"- Selected table: `{table.get('table_id')}`",
        f"- Selected topology source: `{metadata.get('selected_topology_source') or metadata.get('topology_source')}`",
        f"- Table source engine: `{table.get('source_engine')}`",
        f"- Item rows exported: **{len(exports)}**",
        f"- Wrong-column row-math failures for this invoice: **{len(wrong_rows)}**",
        f"- Final column semantics: `{json.dumps(semantics, sort_keys=True)}`",
        f"- Invoice reconciliation status: `{((metrics.get('invoice_financial_reconciliation') or {}).get('status'))}`",
        "",
        "## Row Token Export",
        "",
        _table(
            [
                "row_id",
                "wrong-column failure",
                "row y_min/y_max/center",
                "product tokens",
                "qty tokens",
                "free qty tokens",
                "mrp tokens",
                "rate tokens",
                "amount tokens",
                "product block IDs",
                "qty block IDs",
                "rate block IDs",
                "amount block IDs",
                "previous row overlap",
                "next row overlap",
                "tokens closer to another row",
                "baseline diagnostic",
                "product repair before/after",
            ],
            _row_export_rows(exports, wrong_rows),
        ),
        "",
        "## Adjacent Row Leakage Checks",
        "",
        _table(
            [
                "row_id",
                "detected signal",
                "product-minus-numeric baseline gap",
                "baseline diagnostic",
                "tokens closer to another row",
                "previous overlap",
                "next overlap",
            ],
            leakage_rows or [["none", "none", "n/a", "n/a", "none", "none", "none"]],
        ),
        "",
        "## Product Tokens Outside Selected Main Table",
        "",
        "These product-like OCR tokens are not owned by the selected main table, but are vertically adjacent to the item rows.",
        "",
        _table(
            ["block_id", "text", "y_center", "current owner"],
            orphan_products or [["none", "none", "n/a", "n/a"]],
        ),
        "",
        "## Visual Product Sequence Versus Selected Row Sequence",
        "",
        "This compares product-like OCR tokens in visual y-order against selected main-table rows in y-order.",
        "",
        _table(
            [
                "visual item index",
                "visual product token",
                "visual token owner",
                "selected row_id",
                "selected row product",
                "selected row amount",
                "diagnosis",
            ],
            _sequence_alignment_rows(metadata, table, exports),
        ),
        "",
        "## Interpretation",
        "",
        "- The selected main table starts at `row_14`, but the product token `PANTOP 40 TAB` is owned by `heuristic_region_6 / row_13`, outside the selected main table.",
        "- From `row_14` onward, the selected main table pairs a lower product baseline with the numeric baseline above it. This explains why rows such as TELMIKIND BETA 50 and TELVAS 20 TAB receive neighboring numeric values.",
        "- Direct mapped-block overlap between adjacent selected rows is not the main failure mode in this artifact; the stronger signal is row/table boundary ownership plus product/numeric baseline phase shift.",
        "- This report is audit-only and does not infer quantities from amount/rate or alter reconciliation math.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> int:
    timestamp = os.environ.get("ROW_TOKEN_AUDIT_TS") or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "forensic_runs" / timestamp
    json_path = _find_reconstruction_json()
    payload = _load_json(json_path)
    report_path = _write_report(output_dir, json_path, payload)
    print(f"report_path={report_path.relative_to(PROJECT_ROOT)}")
    print(f"source_json={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
