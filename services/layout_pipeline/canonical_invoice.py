from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


FOOTER_FIELD_ALIASES = {
    "subtotal": ("subtotal", "sub_total", "footer_subtotal", "parsed_subtotal"),
    "discount": ("discount", "discount_total", "disc"),
    "sgst": ("sgst", "sgst_total"),
    "cgst": ("cgst", "cgst_total"),
    "igst": ("igst", "igst_total"),
    "gst_total": ("gst", "gst_total", "parsed_gst"),
    "roundoff": ("roundoff", "round_off", "roundoff_effect"),
    "grand_total": (
        "grand_total",
        "parsed_grand_total",
        "invoice_amount",
        "net_amount",
    ),
}


@dataclass
class CanonicalItemRow:
    row_id: str
    raw_text: str = ""
    product: str = ""
    qty: Any = None
    free_qty: Any = None
    rate: Any = None
    amount: Any = None
    confidence: Optional[float] = None
    source_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_id": self.row_id,
            "raw_text": self.raw_text,
            "product": self.product,
            "qty": self.qty,
            "free_qty": self.free_qty,
            "rate": self.rate,
            "ptr": self.rate,
            "amount": self.amount,
            "line_amount": self.amount,
            "confidence": self.confidence,
            "source_path": self.source_path,
        }


@dataclass
class CanonicalFooterField:
    label: str
    value: Any = None
    confidence: Optional[float] = None
    source_text: str = ""
    source_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "confidence": self.confidence,
            "source_text": self.source_text,
            "source_path": self.source_path,
        }


@dataclass
class CanonicalInvoice:
    invoice_id: str = "unknown"
    item_rows: List[CanonicalItemRow] = field(default_factory=list)
    footer_fields: List[CanonicalFooterField] = field(default_factory=list)
    layout_profile: Dict[str, Any] = field(default_factory=dict)
    confidence: Optional[float] = None
    issues: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "item_rows": [row.to_dict() for row in self.item_rows],
            "footer_fields": [field.to_dict() for field in self.footer_fields],
            "layout_profile": self.layout_profile,
            "confidence": self.confidence,
            "issues": list(self.issues),
            "metrics": dict(self.metrics),
        }

    def get_footer_value(self, label: str) -> Any:
        normalized = _normalize_label(label)
        for footer_field in self.footer_fields:
            if _normalize_label(footer_field.label) == normalized:
                return footer_field.value
        return None


def build_canonical_invoice(result: Dict[str, Any], invoice_id: str = "unknown") -> CanonicalInvoice:
    result = result if isinstance(result, dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    issues: List[str] = []

    canonical = CanonicalInvoice(
        invoice_id=str(invoice_id or metadata.get("invoice_id") or "unknown"),
        confidence=_extract_confidence(result),
        metrics=_extract_metrics(result),
        issues=issues,
    )
    canonical.item_rows = _extract_item_rows(result)
    canonical.footer_fields = _extract_footer_fields(result)

    if not canonical.item_rows:
        issues.append("no_item_rows")
    if not canonical.footer_fields:
        issues.append("no_footer_fields")
    if canonical.confidence is None:
        issues.append("missing_invoice_confidence")

    layout_hint = metrics.get("layout_profile") or result.get("layout_profile")
    if isinstance(layout_hint, dict):
        canonical.layout_profile = dict(layout_hint)

    return canonical


def _extract_item_rows(result: Dict[str, Any]) -> List[CanonicalItemRow]:
    row_keys = (
        "item_rows_clean",
        "item_rows",
        "reconstructed_item_rows",
        "structured_rows",
        "items",
        "line_items",
    )
    for key in row_keys:
        rows = result.get(key)
        if isinstance(rows, list) and rows:
            return [_canonical_item_row(row, f"{key}[{idx}]", idx) for idx, row in enumerate(rows)]

    structured_tables = result.get("structured_tables")
    if isinstance(structured_tables, list):
        rows = []
        for table_idx, table in enumerate(structured_tables):
            if not isinstance(table, dict):
                continue
            for row_idx, row in enumerate(table.get("rows") or []):
                if isinstance(row, dict) and row.get("row_role") == "item_row":
                    rows.append(_canonical_item_row(row, f"structured_tables[{table_idx}].rows[{row_idx}]", len(rows)))
        if rows:
            return rows
    return []


def _canonical_item_row(row: Any, source_path: str, idx: int) -> CanonicalItemRow:
    if not isinstance(row, dict):
        return CanonicalItemRow(row_id=str(idx), raw_text=str(row), source_path=source_path)

    product = _first_present(row, ("product", "product_name", "description", "item", "medicine_name", "name"))
    qty = _first_present(row, ("qty", "quantity", "billed_qty", "total_qty"))
    free_qty = _first_present(row, ("free_qty", "free_quantity", "free"))
    rate = _first_present(row, ("rate", "ptr", "unit_rate", "price", "mrp"))
    amount = _first_present(row, ("amount", "line_amount", "net_amount", "total", "value"))
    raw_text = _first_present(row, ("raw_text", "text", "description", "product", "product_name"))
    if not raw_text:
        raw_text = " ".join(str(v) for v in (product, qty, rate, amount) if v not in (None, ""))
    confidence = _safe_float(_first_present(row, ("confidence", "row_confidence", "stability_score", "stability")))
    row_id = _first_present(row, ("row_id", "visual_row_id", "id", "index")) or str(idx)

    return CanonicalItemRow(
        row_id=str(row_id),
        raw_text=str(raw_text or ""),
        product=str(product or ""),
        qty=qty,
        free_qty=free_qty,
        rate=rate,
        amount=amount,
        confidence=confidence,
        source_path=source_path,
    )


def _extract_footer_fields(result: Dict[str, Any]) -> List[CanonicalFooterField]:
    fields: List[CanonicalFooterField] = []
    seen = set()

    for source_key in ("footer_fields", "financial_summary", "totals"):
        value = result.get(source_key)
        fields.extend(_footer_fields_from_value(value, source_key, seen))

    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    for source_path, value in (
        ("metrics.financial_reconciliation.invoice_level", _get_path(metrics, ("financial_reconciliation", "invoice_level"))),
        ("metrics.invoice_financial_reconciliation", metrics.get("invoice_financial_reconciliation")),
    ):
        fields.extend(_footer_fields_from_value(value, source_path, seen))

    return fields


def _footer_fields_from_value(value: Any, source_path: str, seen: set) -> List[CanonicalFooterField]:
    fields: List[CanonicalFooterField] = []
    if isinstance(value, list):
        for idx, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            label = _first_present(item, ("label", "name", "key", "field"))
            raw_value = _first_present(item, ("value", "amount", "parsed_value"))
            if label and raw_value not in (None, ""):
                fields.extend(_append_footer_field(label, raw_value, item, f"{source_path}[{idx}]", seen))
        return fields

    if not isinstance(value, dict):
        return fields

    for canonical_label, aliases in FOOTER_FIELD_ALIASES.items():
        raw_value = None
        matched_key = None
        for alias in aliases:
            if alias in value and value.get(alias) not in (None, ""):
                raw_value = value.get(alias)
                matched_key = alias
                break
        if raw_value not in (None, ""):
            fields.extend(_append_footer_field(canonical_label, raw_value, value, f"{source_path}.{matched_key}", seen))
    return fields


def _append_footer_field(
    label: Any,
    value: Any,
    source: Dict[str, Any],
    source_path: str,
    seen: set,
) -> List[CanonicalFooterField]:
    normalized = _normalize_label(str(label))
    key = (normalized, str(value))
    if key in seen:
        return []
    seen.add(key)
    confidence = _safe_float(_first_present(source, ("confidence", "field_confidence", "score")))
    source_text = str(_first_present(source, ("source_text", "text", "label_text")) or "")
    return [
        CanonicalFooterField(
            label=normalized,
            value=value,
            confidence=confidence,
            source_text=source_text,
            source_path=source_path,
        )
    ]


def _extract_confidence(result: Dict[str, Any]) -> Optional[float]:
    candidates = (
        result.get("invoice_confidence"),
        result.get("overall_confidence"),
        _get_path(result, ("metadata", "invoice_confidence")),
        _get_path(result, ("metrics", "invoice_confidence")),
        _get_path(result, ("metrics", "confidence_hierarchy", "invoice_confidence")),
    )
    for candidate in candidates:
        numeric = _safe_float(candidate)
        if numeric is not None:
            return numeric
    return None


def _extract_metrics(result: Dict[str, Any]) -> Dict[str, Any]:
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    reconciliation = metrics.get("financial_reconciliation") if isinstance(metrics.get("financial_reconciliation"), dict) else {}
    invoice_level = reconciliation.get("invoice_level") if isinstance(reconciliation.get("invoice_level"), dict) else {}
    main_rec = _first_table_reconciliation(reconciliation)
    return {
        "invoice_confidence": _extract_confidence(result),
        "raw_token_count": metrics.get("raw_token_count"),
        "ocr_block_count": len(result.get("blocks")) if isinstance(result.get("blocks"), list) else None,
        "item_rows_count": metrics.get("item_rows_count"),
        "footer_rows_count": metrics.get("footer_rows_count"),
        "tax_rows_count": metrics.get("tax_rows_count"),
        "rows_math_passed": _first_present(invoice_level, ("rows_math_passed",)) if invoice_level else main_rec.get("rows_math_passed"),
        "rows_math_failed": _first_present(invoice_level, ("rows_math_failed",)) if invoice_level else main_rec.get("rows_math_failed"),
        "row_math_details_count": len(main_rec.get("row_math_details") or []) if isinstance(main_rec.get("row_math_details"), list) else None,
        "row_math_failures_count": len(main_rec.get("row_math_failures") or []) if isinstance(main_rec.get("row_math_failures"), list) else None,
        "token_coverage": metrics.get("token_coverage"),
    }


def _first_table_reconciliation(reconciliation: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in reconciliation.items():
        if key == "invoice_level":
            continue
        if isinstance(value, dict) and ("rows_math_passed" in value or "row_math_details" in value):
            return value
    return {}


def _first_present(data: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _get_path(data: Dict[str, Any], path: Iterable[str]) -> Any:
    current = data
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_label(label: str) -> str:
    return str(label or "").strip().lower().replace(" ", "_").replace("-", "_")
