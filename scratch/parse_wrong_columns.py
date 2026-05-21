#!/usr/bin/env python3
"""
Parse row-math failures caused by cell assignment to the wrong column.

This is diagnostic-only. It reads forensic markdown and benchmark JSON outputs,
normalizes the evidence into a small record shape, and classifies deterministic
confusion patterns for audit reporting.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


WRONG_COLUMN_CAUSE = "cell assignment to wrong column"
REPO_ROOT = Path(__file__).resolve().parents[1]
FORENSIC_ROOT = REPO_ROOT / "forensic_runs"
BENCHMARK_OUTPUTS = REPO_ROOT / "scripts" / "benchmarks" / "outputs"

FIELD_ALIASES = {
    "invoice_filename": ("invoice filename", "invoice", "filename", "file"),
    "selected_topology_source": ("selected topology source", "topology source", "selected topology", "topology"),
    "row_id": ("row_id", "row id", "row"),
    "product_text": ("product cell text", "product text", "product", "product cell"),
    "qty_text": ("qty cell text", "quantity cell text", "qty", "quantity"),
    "free_qty_text": ("free qty cell text", "free_qty cell text", "free quantity", "free_qty", "free qty"),
    "rate_text": ("rate cell text", "rate"),
    "mrp_text": ("mrp cell text", "mrp"),
    "gst_text": ("gst cell text", "gst", "tax"),
    "amount_text": ("amount cell text", "amount"),
    "parsed_qty": ("parsed qty", "parsed quantity"),
    "parsed_rate": ("parsed rate",),
    "parsed_amount": ("parsed amount",),
}

RELEVANT_TEXT_FIELDS = (
    "product_text",
    "qty_text",
    "free_qty_text",
    "rate_text",
    "mrp_text",
    "gst_text",
    "amount_text",
)

MONEY_RE = re.compile(r"^-?\d{1,6}(?:,\d{2}|\.\d{2,3})$")
DECIMAL_COMMA_RE = re.compile(r"\b-?\d{1,6},\d{2,3}\b")
NUMERIC_ONLY_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
COMPOUND_QTY_RE = re.compile(r"^\d+(?:\.\d+)?\s*\+\s*\d+(?:\.\d+)?$")
GST_RATE_VALUES = {0, 2.5, 5, 6, 9, 12, 18, 28}


@dataclass
class WrongColumnFailure:
    invoice_filename: str = "unknown"
    selected_topology_source: str = "unknown"
    row_id: str = "unknown"
    product_text: str = ""
    qty_text: str = ""
    free_qty_text: str = ""
    rate_text: str = ""
    mrp_text: str = ""
    gst_text: str = ""
    amount_text: str = ""
    parsed_qty: str = ""
    parsed_rate: str = ""
    parsed_amount: str = ""
    mapped_block_ids: Dict[str, List[str]] = field(default_factory=dict)
    source_path: str = ""
    raw_excerpt: str = ""
    diagnosis: str = ""
    confusion_pattern: str = "unknown wrong-column pattern"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "invoice_filename": self.invoice_filename,
            "selected_topology_source": self.selected_topology_source,
            "row_id": self.row_id,
            "product_text": self.product_text,
            "qty_text": self.qty_text,
            "free_qty_text": self.free_qty_text,
            "rate_text": self.rate_text,
            "mrp_text": self.mrp_text,
            "gst_text": self.gst_text,
            "amount_text": self.amount_text,
            "parsed_qty": self.parsed_qty,
            "parsed_rate": self.parsed_rate,
            "parsed_amount": self.parsed_amount,
            "mapped_block_ids": self.mapped_block_ids,
            "source_path": self.source_path,
            "raw_excerpt": self.raw_excerpt,
            "diagnosis": self.diagnosis,
            "confusion_pattern": self.confusion_pattern,
        }


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_clean(item) for item in value)
    text = str(value).strip()
    text = re.sub(r"^\*\*|\*\*$", "", text)
    return text.strip("` ").strip()


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", key.lower()).strip()


def _canonical_field(key: str) -> Optional[str]:
    norm = _norm_key(key)
    for canonical, aliases in FIELD_ALIASES.items():
        if norm in aliases:
            return canonical
    return None


def _parse_value_lines(lines: List[str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in lines:
        stripped = line.strip().strip("|").strip()
        if not stripped:
            continue

        match = re.match(r"^(?:[-*]\s*)?(?:\*\*)?([^:*|]+?)(?:\*\*)?\s*[:|]\s*(.+)$", stripped)
        if not match:
            continue
        key, value = match.groups()
        canonical = _canonical_field(key)
        if canonical and canonical not in values:
            values[canonical] = _clean(value)
    return values


def _window_for_line(lines: List[str], idx: int) -> List[str]:
    start = idx
    while start > 0:
        prev = lines[start - 1].strip()
        if prev.startswith("#") or prev.startswith("##") or prev.startswith("###"):
            break
        if prev.startswith("---"):
            break
        start -= 1

    end = idx + 1
    while end < len(lines):
        current = lines[end].strip()
        if current.startswith("##") or current.startswith("---"):
            break
        end += 1
    return lines[start:end]


def parse_forensic_markdown(path: Path) -> List[WrongColumnFailure]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    records = []

    for idx, line in enumerate(lines):
        if "assigned cause" not in line.lower():
            continue
        if WRONG_COLUMN_CAUSE not in line.lower():
            continue

        window = _window_for_line(lines, idx)
        values = _parse_value_lines(window)
        record = WrongColumnFailure(
            invoice_filename=values.get("invoice_filename", "unknown"),
            selected_topology_source=values.get("selected_topology_source", "unknown"),
            row_id=values.get("row_id", "unknown"),
            product_text=values.get("product_text", ""),
            qty_text=values.get("qty_text", ""),
            free_qty_text=values.get("free_qty_text", ""),
            rate_text=values.get("rate_text", ""),
            mrp_text=values.get("mrp_text", ""),
            gst_text=values.get("gst_text", ""),
            amount_text=values.get("amount_text", ""),
            parsed_qty=values.get("parsed_qty", ""),
            parsed_rate=values.get("parsed_rate", ""),
            parsed_amount=values.get("parsed_amount", ""),
            source_path=str(path.relative_to(REPO_ROOT)),
            raw_excerpt="\n".join(window[:80]),
        )
        _classify_record(record)
        records.append(record)

    return records


def _walk_json(node: Any, path: Tuple[Any, ...] = ()) -> Iterable[Tuple[Tuple[Any, ...], Any]]:
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_json(value, path + (key,))
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from _walk_json(value, path + (idx,))


def _contains_wrong_column_cause(node: Any) -> bool:
    if isinstance(node, str):
        return WRONG_COLUMN_CAUSE in node.lower()
    if isinstance(node, dict):
        return any(_contains_wrong_column_cause(value) for value in node.values())
    if isinstance(node, list):
        return any(_contains_wrong_column_cause(value) for value in node)
    return False


def _semantic_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("type", value.get("semantic", ""))
    return str(value or "").lower().split(".")[-1]


def _cells_for_table(metadata: Dict[str, Any], table_id: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    for table in metadata.get("structured_tables", []) or []:
        if table.get("table_id") != table_id:
            continue
        by_row: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        for cell in table.get("cells", []) or []:
            by_row[str(cell.get("row_id"))][str(cell.get("col_id"))] = cell
        return by_row
    return {}


def _semantics_for_table(metrics: Dict[str, Any], table_id: str) -> Dict[str, str]:
    candidates = [
        (metrics.get("semantic_debug") or {}).get("final_column_semantics", {}),
        metrics.get("final_column_semantics", {}),
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


def _record_from_json_context(path: Path, payload: Dict[str, Any], context: Dict[str, Any]) -> WrongColumnFailure:
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    metrics = metadata.get("metrics", {}) if isinstance(metadata, dict) else {}
    row_id = _clean(context.get("row_id") or context.get("row") or "unknown")
    table_id = _clean(context.get("table_id") or context.get("selected_table_id") or "")
    if not table_id:
        row_validation = metrics.get("row_validation") or {}
        for key, value in row_validation.items():
            if isinstance(value, dict) and any(diag.get("row_id") == row_id for diag in value.get("row_diagnostics", []) if isinstance(diag, dict)):
                table_id = str(key)
                break

    cells_by_row = _cells_for_table(metadata, table_id)
    semantics = _semantics_for_table(metrics, table_id)
    semantic_cells: Dict[str, Dict[str, Any]] = {}
    for col_id, cell in cells_by_row.get(row_id, {}).items():
        semantic = semantics.get(col_id, "").lower()
        if semantic:
            semantic_cells[semantic] = cell

    def cell_text(*names: str) -> str:
        for name in names:
            cell = semantic_cells.get(name)
            if cell:
                return _clean(cell.get("text"))
        return _clean(context.get(names[0]) or context.get(f"{names[0]}_text"))

    mapped = {}
    for semantic, cell in semantic_cells.items():
        if semantic in {"product", "quantity", "qty", "free_quantity", "rate", "mrp", "gst", "amount"}:
            mapped[semantic] = [str(item) for item in cell.get("mapped_block_ids", [])]

    record = WrongColumnFailure(
        invoice_filename=Path(path).name,
        selected_topology_source=_clean(
            metadata.get("topology_source")
            or metrics.get("topology_source")
            or (metrics.get("tsr_status") or {}).get("topology_source")
            or "unknown"
        ),
        row_id=row_id,
        product_text=cell_text("product"),
        qty_text=cell_text("quantity", "qty"),
        free_qty_text=cell_text("free_quantity"),
        rate_text=cell_text("rate"),
        mrp_text=cell_text("mrp"),
        gst_text=cell_text("gst", "tax"),
        amount_text=cell_text("amount"),
        parsed_qty=_clean(context.get("parsed_qty") or context.get("qty_val")),
        parsed_rate=_clean(context.get("parsed_rate") or context.get("rate_val")),
        parsed_amount=_clean(context.get("parsed_amount") or context.get("amount_val")),
        mapped_block_ids=mapped,
        source_path=str(path.relative_to(REPO_ROOT)),
        raw_excerpt=json.dumps(context, ensure_ascii=False, indent=2)[:3000],
    )
    _classify_record(record)
    return record


def parse_benchmark_json(path: Path) -> List[WrongColumnFailure]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    records = []
    seen = set()
    for _, node in _walk_json(payload):
        if not isinstance(node, dict) or not _contains_wrong_column_cause(node):
            continue
        key = json.dumps(node, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        records.append(_record_from_json_context(path, payload, node))
    return records


def _to_float(text: str) -> Optional[float]:
    cleaned = _clean(text).replace(",", ".")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_money_like(text: str) -> bool:
    compact = _clean(text).replace(" ", "")
    return bool(MONEY_RE.match(compact))


def _is_numeric_only(text: str) -> bool:
    compact = _clean(text).replace(" ", "")
    return bool(NUMERIC_ONLY_RE.match(compact))


def _is_quantity_like(text: str) -> bool:
    compact = _clean(text).replace(" ", "")
    if COMPOUND_QTY_RE.match(compact):
        return True
    value = _to_float(compact)
    return value is not None and value <= 999 and not _is_money_like(compact)


def _is_gst_quantity_confusion(text: str) -> bool:
    compact = _clean(text).replace(" ", "")
    if "+" in compact:
        return True
    value = _to_float(compact)
    if value is None:
        return False
    return value not in GST_RATE_VALUES and (float(value).is_integer() or value > 28)


def _classify_record(record: WrongColumnFailure) -> None:
    qty = record.qty_text
    free_qty = record.free_qty_text
    gst = record.gst_text
    amount = record.amount_text
    rate = record.rate_text
    product = record.product_text

    if any(DECIMAL_COMMA_RE.search(text or "") for text in (amount, rate, qty, free_qty, gst)):
        record.confusion_pattern = "amount decimal-comma normalization issue"
        record.diagnosis = "Decimal comma appears in a numeric cell involved in the wrong-column failure."
    elif qty and _is_money_like(qty):
        record.confusion_pattern = "qty received amount-like value"
        record.diagnosis = "Quantity column contains a decimal money-like value."
    elif free_qty and _is_money_like(free_qty):
        record.confusion_pattern = "free_qty received price-like value"
        record.diagnosis = "Free quantity column contains a decimal price-like value."
    elif gst and _is_gst_quantity_confusion(gst):
        record.confusion_pattern = "GST received quantity/free quantity"
        record.diagnosis = "GST column contains a quantity-like value rather than a known GST rate."
    elif amount and rate and _to_float(amount) is not None and _to_float(rate) is not None and abs((_to_float(amount) or 0) - (_to_float(rate) or 0)) <= 0.01:
        record.confusion_pattern = "amount received rate"
        record.diagnosis = "Amount cell equals the row rate, suggesting the rate band was assigned as amount."
    elif product and _is_numeric_only(product):
        record.confusion_pattern = "product received numeric-only value"
        record.diagnosis = "Product column contains only a numeric value."
    elif not qty and rate and amount:
        record.confusion_pattern = "quantity missing but rate/amount present"
        record.diagnosis = "Rate and amount are present but no quantity cell was assigned."
    else:
        record.confusion_pattern = "unknown wrong-column pattern"
        record.diagnosis = "Wrong-column cause found, but available cell text does not match a named confusion rule."


def discover_sources() -> Tuple[List[Path], List[Path]]:
    forensic = sorted(FORENSIC_ROOT.glob("*/row_math_failure_audit.md")) if FORENSIC_ROOT.exists() else []
    json_outputs = sorted(BENCHMARK_OUTPUTS.glob("*.json")) if BENCHMARK_OUTPUTS.exists() else []
    return forensic, json_outputs


def parse_all() -> List[WrongColumnFailure]:
    forensic, json_outputs = discover_sources()
    records: List[WrongColumnFailure] = []
    for path in forensic:
        records.extend(parse_forensic_markdown(path))
    for path in json_outputs:
        records.extend(parse_benchmark_json(path))
    return records


def summarize(records: List[WrongColumnFailure]) -> Dict[str, Counter]:
    return {
        "by_invoice": Counter(record.invoice_filename for record in records),
        "by_topology": Counter(record.selected_topology_source for record in records),
        "by_pattern": Counter(record.confusion_pattern for record in records),
        "text_patterns": Counter(
            text
            for record in records
            for text in (_clean(getattr(record, field_name)) for field_name in RELEVANT_TEXT_FIELDS)
            if text
        ),
    }


if __name__ == "__main__":
    failures = parse_all()
    summary = summarize(failures)
    print(f"wrong_column_failures={len(failures)}")
    print("by_pattern=", dict(summary["by_pattern"].most_common()))
