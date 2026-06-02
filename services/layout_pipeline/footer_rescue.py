from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from services.layout_pipeline.canonical_invoice import CanonicalFooterField, CanonicalInvoice
from services.layout_pipeline.layout_profile import EXPECTED_FOOTER_FIELDS


LABEL_PATTERNS = {
    "subtotal": re.compile(r"\b(sub\s*total|subtotal|taxable)\b", re.IGNORECASE),
    "discount": re.compile(r"\b(discount|disc|less\s+td|trade\s+discount)\b", re.IGNORECASE),
    "sgst": re.compile(r"\bsgst\b", re.IGNORECASE),
    "cgst": re.compile(r"\bcgst\b", re.IGNORECASE),
    "gst_total": re.compile(r"\bgst\b", re.IGNORECASE),
    "roundoff": re.compile(r"\b(round\s*off|roundoff)\b", re.IGNORECASE),
    "grand_total": re.compile(r"\b(grand\s*total|net\s*amount|invoice\s*amount|total\s*payable|bill\s*amount|total)\b", re.IGNORECASE),
}

NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d{1,2})?")


def diagnose_footer_rescue(canonical_invoice: CanonicalInvoice, raw_result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    raw_result = raw_result if isinstance(raw_result, dict) else {}
    missing_fields = [
        field for field in EXPECTED_FOOTER_FIELDS
        if canonical_invoice.get_footer_value(field) in (None, "")
    ]
    candidate_fields = _find_candidates(raw_result)
    warnings: List[str] = []
    applied_fields: List[Dict[str, Any]] = []

    by_label: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidate_fields:
        by_label.setdefault(candidate["label"], []).append(candidate)

    for label in missing_fields:
        candidates = by_label.get(label, [])
        if not candidates:
            continue
        values = {str(candidate.get("value")) for candidate in candidates}
        if len(values) > 1:
            warnings.append(f"conflicting_candidates:{label}")
            continue
        candidate = candidates[0]
        confidence = candidate.get("confidence") or 0.0
        if confidence >= 0.85:
            field = CanonicalFooterField(
                label=label,
                value=candidate.get("value"),
                confidence=confidence,
                source_text=candidate.get("source_text", ""),
                source_path="footer_rescue",
            )
            canonical_invoice.footer_fields.append(field)
            applied_fields.append(field.to_dict())

    computed_item_total = _computed_item_total(canonical_invoice)
    if computed_item_total is not None:
        candidate_fields.append({
            "label": "computed_item_total",
            "value": computed_item_total,
            "confidence": 0.5,
            "source_text": "sum(canonical_item_rows.amount)",
            "source_path": "canonical_invoice.item_rows",
            "applied": False,
        })

    return {
        "missing_fields": missing_fields,
        "candidate_fields": candidate_fields,
        "warnings": warnings,
        "applied_fields": applied_fields,
        "confidence": _candidate_confidence(candidate_fields),
    }


def _find_candidates(raw_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = []
    for source_path, text in _iter_text_sources(raw_result):
        normalized = " ".join(str(text).split())
        if not normalized:
            continue
        for label, pattern in LABEL_PATTERNS.items():
            if not pattern.search(normalized):
                continue
            number = _last_number(normalized)
            if number is None:
                continue
            candidate_label = "grand_total" if label == "gst_total" and re.search(r"grand|net|invoice|payable", normalized, re.I) else label
            confidence = 0.75
            if _label_value_like(normalized):
                confidence += 0.1
            if candidate_label == "grand_total" and re.search(r"grand|net|invoice|payable", normalized, re.I):
                confidence += 0.1
            candidates.append({
                "label": candidate_label,
                "value": number,
                "confidence": round(min(confidence, 0.95), 2),
                "source_text": normalized[:220],
                "source_path": source_path,
                "applied": False,
            })
    return _dedupe_candidates(candidates)


def _iter_text_sources(raw_result: Dict[str, Any]) -> Iterable[tuple[str, str]]:
    for key in ("semantic_markdown", "text"):
        value = raw_result.get(key)
        if isinstance(value, str):
            for idx, line in enumerate(value.splitlines()):
                yield f"{key}.line[{idx}]", line

    for key in ("blocks", "reconstructed_rows", "detected_table_rows"):
        value = raw_result.get(key)
        if isinstance(value, list):
            for idx, item in enumerate(value):
                text = _text_from_object(item)
                if text:
                    yield f"{key}[{idx}]", text

    for table_idx, table in enumerate(raw_result.get("structured_tables") or []):
        if not isinstance(table, dict):
            continue
        for cell_idx, cell in enumerate(table.get("cells") or []):
            text = _text_from_object(cell)
            if text:
                yield f"structured_tables[{table_idx}].cells[{cell_idx}]", text


def _text_from_object(value: Any) -> str:
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("columns"), dict):
            return " ".join(str(v) for v in value["columns"].values() if v)
        if isinstance(value.get("blocks"), list):
            return " ".join(_text_from_object(block) for block in value["blocks"])
    return ""


def _last_number(text: str) -> float | None:
    matches = NUMBER_RE.findall(text)
    if not matches:
        return None
    cleaned = matches[-1].replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _label_value_like(text: str) -> bool:
    return bool(re.search(r"[:=]|\s{2,}", text)) or bool(re.search(r"[A-Za-z].*\d", text))


def _dedupe_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for candidate in candidates:
        key = (candidate.get("label"), candidate.get("value"), candidate.get("source_text"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _computed_item_total(canonical_invoice: CanonicalInvoice) -> float | None:
    total = 0.0
    found = False
    for row in canonical_invoice.item_rows:
        try:
            total += float(str(row.amount).replace(",", ""))
            found = True
        except (TypeError, ValueError):
            continue
    return round(total, 2) if found else None


def _candidate_confidence(candidates: List[Dict[str, Any]]) -> float:
    if not candidates:
        return 0.0
    return max(float(candidate.get("confidence") or 0.0) for candidate in candidates)
