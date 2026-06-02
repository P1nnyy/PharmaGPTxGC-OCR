from __future__ import annotations

import re
from collections import defaultdict
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.layout_pipeline.canonical_invoice import CanonicalFooterField, CanonicalInvoice


EXPECTED_FOOTER_FIELDS = ("subtotal", "discount", "sgst", "cgst", "grand_total")
APPLY_CONFIDENCE_THRESHOLD = 0.70

SUBTOTAL_LABELS = (
    "subtotal",
    "sub total",
    "sub-total",
    "taxable",
    "taxable value",
    "goods value",
    "gross amount",
)
DISCOUNT_LABELS = ("discount", "disc", "less")
ROUND_OFF_LABELS = ("roundoff", "round off", "round-off", "rounding")
STRONG_GRAND_TOTAL_LABELS = (
    "grand total",
    "net amount",
    "invoice amount",
    "bill amount",
    "amount payable",
    "total amount",
)
GST_LABEL_PATTERNS = {
    "sgst": re.compile(r"\bs\.?\s*g\.?\s*s\.?\s*t\.?\b|\bsgst\b", re.IGNORECASE),
    "cgst": re.compile(r"\bc\.?\s*g\.?\s*s\.?\s*t\.?\b|\bcgst\b", re.IGNORECASE),
    "igst": re.compile(r"\bi\.?\s*g\.?\s*s\.?\s*t\.?\b|\bigst\b", re.IGNORECASE),
}
AMOUNT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:rs\.?\s*)?(?:inr\s*)?(?:₹\s*)?-?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def diagnose_footer_rescue(
    canonical_invoice: CanonicalInvoice,
    raw_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Find footer totals in bottom-page OCR geometry and safely attach missing fields."""

    raw_result = raw_result if isinstance(raw_result, dict) else {}
    missing_fields = [
        field for field in EXPECTED_FOOTER_FIELDS
        if canonical_invoice.get_footer_value(field) in (None, "")
    ]

    units = extract_geometry_text_units(raw_result)
    bottom_units = select_bottom_region(units)
    geometry_used = bool(bottom_units)
    footer_lines = group_footer_lines(bottom_units)

    if not footer_lines:
        footer_lines = _fallback_text_lines(raw_result)

    candidate_fields = parse_footer_label_value_lines(footer_lines)
    selected_candidates: Dict[str, Dict[str, Any]] = {}
    conflicting_candidates: Dict[str, List[Dict[str, Any]]] = {}
    warnings: List[str] = []

    for field, candidates in sorted(candidate_fields.items()):
        ranked = sorted(candidates, key=lambda candidate: candidate.get("confidence") or 0, reverse=True)
        if not ranked:
            continue
        conflict = _has_unresolved_conflict(ranked)
        if conflict:
            conflicting_candidates[field] = ranked
            warnings.append(f"footer_rescue_conflicting_candidates:{field}")
            continue
        selected_candidates[field] = ranked[0]

    applied_fields: List[Dict[str, Any]] = []
    item_sum = _sum_item_amounts(canonical_invoice)
    for field in missing_fields:
        candidate = selected_candidates.get(field)
        if not candidate:
            continue
        if (candidate.get("confidence") or 0) < APPLY_CONFIDENCE_THRESHOLD:
            continue
        if _unsafe_to_apply(candidate):
            warnings.append(f"footer_rescue_noisy_candidate_skipped:{field}")
            continue
        if _matches_item_sum_only(field, candidate.get("value"), item_sum):
            warnings.append(f"footer_rescue_item_sum_candidate_skipped:{field}")
            continue
        source_path = "footer_rescue.geometry" if candidate.get("geometry_used") else "footer_rescue.text"
        footer_field = CanonicalFooterField(
            label=field,
            value=candidate.get("value"),
            confidence=candidate.get("confidence"),
            source_text=candidate.get("line_text") or "",
            source_path=source_path,
        )
        canonical_invoice.footer_fields.append(footer_field)
        applied_fields.append(footer_field.to_dict())

    flat_candidates = [
        candidate
        for candidates in candidate_fields.values()
        for candidate in candidates
    ]
    confidence_values = [
        candidate.get("confidence")
        for candidate in selected_candidates.values()
        if isinstance(candidate.get("confidence"), (int, float))
    ]

    return {
        "missing_fields": missing_fields,
        "candidate_fields": candidate_fields,
        "candidate_fields_flat": flat_candidates,
        "selected_candidates": selected_candidates,
        "applied_fields": applied_fields,
        "conflicting_candidates": conflicting_candidates,
        "warnings": warnings,
        "confidence": max(confidence_values) if confidence_values else None,
        "bottom_region_line_count": len(footer_lines),
        "footer_lines_used": [_summarize_line(line) for line in footer_lines],
        "geometry_used": geometry_used,
        "computed_item_total": item_sum,
    }


def extract_geometry_text_units(raw_result: Any) -> List[Dict[str, Any]]:
    """Extract OCR text units with optional geometry from common reconstruction shapes."""

    raw_result = raw_result if isinstance(raw_result, dict) else {}
    units: List[Dict[str, Any]] = []

    for key in ("blocks", "ocr_blocks", "text_blocks", "raw_ocr"):
        _extend_block_units(units, raw_result.get(key), key)

    for key in ("reconstructed_rows", "detected_table_rows", "structured_rows", "all_rows"):
        _extend_row_units(units, raw_result.get(key), key)

    structured_tables = raw_result.get("structured_tables")
    if isinstance(structured_tables, list):
        for table_idx, table in enumerate(structured_tables):
            if not isinstance(table, dict):
                continue
            _extend_row_units(units, table.get("rows"), f"structured_tables[{table_idx}].rows")
            cells = table.get("cells")
            if isinstance(cells, list):
                for cell_idx, cell in enumerate(cells):
                    _append_unit_from_mapping(units, cell, f"structured_tables[{table_idx}].cells[{cell_idx}]")

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for unit in units:
        text = _clean_space(unit.get("text"))
        if not text:
            continue
        key = (
            text,
            _round_or_none(unit.get("x_min")),
            _round_or_none(unit.get("y_min")),
            _round_or_none(unit.get("x_max")),
            _round_or_none(unit.get("y_max")),
        )
        if key in seen:
            continue
        seen.add(key)
        unit["text"] = text
        deduped.append(unit)
    return deduped


def select_bottom_region(units: List[Dict[str, Any]], y_threshold: float = 0.65) -> List[Dict[str, Any]]:
    geometric = [unit for unit in units if _has_geometry(unit)]
    if not geometric:
        return []

    max_x = max((unit.get("x_max") or 0) for unit in geometric) or 1
    max_y = max((unit.get("y_max") or 0) for unit in geometric) or 1
    normalized_input = max(max_x, max_y) <= 1.5

    selected: List[Dict[str, Any]] = []
    for unit in geometric:
        copied = dict(unit)
        divisor_x = 1 if normalized_input else max_x
        divisor_y = 1 if normalized_input else max_y
        copied["x_min_norm"] = _safe_div(copied.get("x_min"), divisor_x)
        copied["x_max_norm"] = _safe_div(copied.get("x_max"), divisor_x)
        copied["y_min_norm"] = _safe_div(copied.get("y_min"), divisor_y)
        copied["y_max_norm"] = _safe_div(copied.get("y_max"), divisor_y)
        copied["x_center_norm"] = mean((copied["x_min_norm"], copied["x_max_norm"]))
        copied["y_center_norm"] = mean((copied["y_min_norm"], copied["y_max_norm"]))
        if copied["y_center_norm"] >= y_threshold:
            copied["geometry_used"] = True
            selected.append(copied)
    return selected


def group_footer_lines(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not units:
        return []

    sorted_units = sorted(units, key=lambda unit: (unit.get("y_center_norm", unit.get("y_min", 0)), unit.get("x_min_norm", unit.get("x_min", 0))))
    groups: List[List[Dict[str, Any]]] = []
    tolerance = 0.018
    for unit in sorted_units:
        y_center = unit.get("y_center_norm")
        if y_center is None:
            y_center = unit.get("y_min") or 0
        if not groups:
            groups.append([unit])
            continue
        group_y = mean(_unit_y(member) for member in groups[-1])
        if abs(float(y_center) - group_y) <= tolerance:
            groups[-1].append(unit)
        else:
            groups.append([unit])

    lines: List[Dict[str, Any]] = []
    for group_idx, group in enumerate(groups):
        members = sorted(group, key=lambda unit: unit.get("x_min_norm", unit.get("x_min", 0)))
        text = _clean_space(" ".join(str(unit.get("text") or "") for unit in members))
        if not text:
            continue
        confidences = [
            _safe_float(unit.get("confidence"))
            for unit in members
            if _safe_float(unit.get("confidence")) is not None
        ]
        lines.append({
            "line_text": text,
            "text": text,
            "x_min": min((unit.get("x_min") for unit in members if unit.get("x_min") is not None), default=None),
            "x_max": max((unit.get("x_max") for unit in members if unit.get("x_max") is not None), default=None),
            "y_center": mean(_unit_y(member) for member in members),
            "x_min_norm": min((unit.get("x_min_norm") for unit in members if unit.get("x_min_norm") is not None), default=None),
            "x_max_norm": max((unit.get("x_max_norm") for unit in members if unit.get("x_max_norm") is not None), default=None),
            "y_center_norm": mean(_unit_y(member) for member in members),
            "confidence": mean(confidences) if confidences else None,
            "source_units": members,
            "source_path": ",".join(str(unit.get("source_path")) for unit in members if unit.get("source_path")),
            "line_index": group_idx,
            "geometry_used": True,
        })
    return lines


def parse_footer_label_value_lines(lines: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    candidates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not lines:
        return {}

    max_y = max((_line_y(line) for line in lines), default=0)
    strong_grand_total_present = False
    pending_weak_totals: List[Dict[str, Any]] = []

    for line_idx, line in enumerate(lines):
        text = _clean_space(line.get("line_text") or line.get("text") or "")
        if not text:
            continue
        amounts = _extract_amounts(text)
        if not amounts:
            continue
        field, label_strength = _classify_line(text)
        if field is None:
            continue

        candidate = _candidate_from_line(
            field=field,
            label_strength=label_strength,
            line=line,
            line_idx=line_idx,
            line_count=len(lines),
            amount=_choose_amount_for_field(text, amounts, field),
            amount_count=len(amounts),
            max_y=max_y,
        )
        if label_strength == "weak_total":
            pending_weak_totals.append(candidate)
            continue
        if field == "grand_total":
            strong_grand_total_present = True
        candidates[field].append(candidate)

    if not strong_grand_total_present and pending_weak_totals:
        if len(pending_weak_totals) == 1 and _is_bottommost(pending_weak_totals[0], max_y):
            candidates["grand_total"].append(pending_weak_totals[0])
        else:
            candidates["grand_total"].extend(
                dict(candidate, ambiguous_total=True, confidence=max(0.0, candidate["confidence"] - 0.25))
                for candidate in pending_weak_totals
            )

    return dict(candidates)


def _extend_block_units(units: List[Dict[str, Any]], value: Any, source_path: str) -> None:
    if isinstance(value, dict):
        for nested_key in ("blocks", "items", "words", "lines"):
            _extend_block_units(units, value.get(nested_key), f"{source_path}.{nested_key}")
        _append_unit_from_mapping(units, value, source_path)
        return
    if not isinstance(value, list):
        return
    for idx, item in enumerate(value):
        if isinstance(item, dict):
            _append_unit_from_mapping(units, item, f"{source_path}[{idx}]")
            for nested_key in ("blocks", "items", "words", "lines"):
                _extend_block_units(units, item.get(nested_key), f"{source_path}[{idx}].{nested_key}")


def _extend_row_units(units: List[Dict[str, Any]], rows: Any, source_path: str) -> None:
    if not isinstance(rows, list):
        return
    for row_idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        row_path = f"{source_path}[{row_idx}]"
        _append_unit_from_mapping(units, row, row_path)
        _extend_block_units(units, row.get("blocks"), f"{row_path}.blocks")
        _extend_block_units(units, row.get("cells"), f"{row_path}.cells")
        columns = row.get("columns")
        if isinstance(columns, dict):
            for col_key, col_value in columns.items():
                if isinstance(col_value, dict):
                    _append_unit_from_mapping(units, col_value, f"{row_path}.columns.{col_key}")
                elif col_value not in (None, ""):
                    geometry = _extract_geometry(row)
                    units.append(_unit(str(col_value), geometry, row, f"{row_path}.columns.{col_key}"))


def _append_unit_from_mapping(units: List[Dict[str, Any]], item: Dict[str, Any], source_path: str) -> None:
    text = _first_present(item, ("text", "line_text", "raw_text", "value", "content", "description"))
    if text in (None, ""):
        return
    geometry = _extract_geometry(item)
    units.append(_unit(str(text), geometry, item, source_path))


def _unit(text: str, geometry: Optional[Tuple[float, float, float, float]], item: Dict[str, Any], source_path: str) -> Dict[str, Any]:
    unit = {
        "text": text,
        "confidence": _safe_float(_first_present(item, ("confidence", "ocr_confidence", "assignment_confidence", "score"))),
        "source_path": source_path,
    }
    if geometry:
        unit.update({
            "x_min": geometry[0],
            "y_min": geometry[1],
            "x_max": geometry[2],
            "y_max": geometry[3],
        })
    return unit


def _extract_geometry(item: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    for key in ("geometry", "normalized_geometry", "original_geometry", "polygon", "bbox", "bounding_box"):
        geometry = item.get(key)
        parsed = _parse_geometry(geometry)
        if parsed:
            return parsed
    return None


def _parse_geometry(geometry: Any) -> Optional[Tuple[float, float, float, float]]:
    if geometry is None:
        return None
    if isinstance(geometry, dict):
        if all(key in geometry for key in ("x_min", "y_min", "x_max", "y_max")):
            return _geometry_tuple(geometry["x_min"], geometry["y_min"], geometry["x_max"], geometry["y_max"])
        if all(key in geometry for key in ("left", "top", "right", "bottom")):
            return _geometry_tuple(geometry["left"], geometry["top"], geometry["right"], geometry["bottom"])
        if all(key in geometry for key in ("x", "y", "width", "height")):
            x = _safe_float(geometry.get("x"))
            y = _safe_float(geometry.get("y"))
            width = _safe_float(geometry.get("width"))
            height = _safe_float(geometry.get("height"))
            if None not in (x, y, width, height):
                return _geometry_tuple(x, y, x + width, y + height)
        for nested_key in ("bbox", "box", "polygon", "vertices"):
            parsed = _parse_geometry(geometry.get(nested_key))
            if parsed:
                return parsed
    if isinstance(geometry, (list, tuple)):
        if len(geometry) == 4 and all(not isinstance(value, (list, tuple, dict)) for value in geometry):
            x1, y1, x2, y2 = (_safe_float(value) for value in geometry)
            if None not in (x1, y1, x2, y2):
                if x2 < x1 or y2 < y1:
                    return _geometry_tuple(x1, y1, x1 + x2, y1 + y2)
                return _geometry_tuple(x1, y1, x2, y2)
        points = []
        for point in geometry:
            if isinstance(point, dict):
                x = _safe_float(point.get("x"))
                y = _safe_float(point.get("y"))
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                x = _safe_float(point[0])
                y = _safe_float(point[1])
            else:
                continue
            if x is not None and y is not None:
                points.append((x, y))
        if points:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            return _geometry_tuple(min(xs), min(ys), max(xs), max(ys))
    return None


def _geometry_tuple(x_min: Any, y_min: Any, x_max: Any, y_max: Any) -> Optional[Tuple[float, float, float, float]]:
    values = tuple(_safe_float(value) for value in (x_min, y_min, x_max, y_max))
    if any(value is None for value in values):
        return None
    return values  # type: ignore[return-value]


def _fallback_text_lines(raw_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    text_sources = []
    for key in ("semantic_markdown", "text", "raw_text", "markdown"):
        value = raw_result.get(key)
        if isinstance(value, str):
            text_sources.append((key, value))
    for source_path, text in text_sources:
        for idx, line in enumerate(text.splitlines()):
            cleaned = _clean_space(line)
            if not cleaned:
                continue
            lines.append({
                "line_text": cleaned,
                "text": cleaned,
                "confidence": 0.82,
                "source_path": f"{source_path}:{idx}",
                "line_index": len(lines),
                "y_center_norm": 0.75 + min(0.2, len(lines) * 0.01),
                "x_min_norm": None,
                "x_max_norm": None,
                "geometry_used": False,
            })
    if not lines:
        units = extract_geometry_text_units(raw_result)
        for idx, unit in enumerate(units):
            lines.append({
                "line_text": unit.get("text"),
                "text": unit.get("text"),
                "confidence": unit.get("confidence"),
                "source_path": unit.get("source_path"),
                "line_index": idx,
                "y_center_norm": 0.7 + min(0.2, idx * 0.01),
                "geometry_used": False,
            })
    return lines


def _classify_line(text: str) -> Tuple[Optional[str], str]:
    normalized = _label_text(text)
    for field, pattern in GST_LABEL_PATTERNS.items():
        if pattern.search(text):
            return field, "explicit"
    if any(label in normalized for label in SUBTOTAL_LABELS):
        return "subtotal", "explicit"
    if any(label in normalized for label in DISCOUNT_LABELS):
        return "discount", "explicit"
    if any(label in normalized for label in ROUND_OFF_LABELS):
        return "roundoff", "explicit"
    if any(label in normalized for label in STRONG_GRAND_TOTAL_LABELS):
        return "grand_total", "explicit"
    if re.search(r"(^|[^a-z])total([^a-z]|$)", normalized) and "subtotal" not in normalized and "sub total" not in normalized:
        return "grand_total", "weak_total"
    return None, ""


def _candidate_from_line(
    field: str,
    label_strength: str,
    line: Dict[str, Any],
    line_idx: int,
    line_count: int,
    amount: Dict[str, Any],
    amount_count: int,
    max_y: float,
) -> Dict[str, Any]:
    text = _clean_space(line.get("line_text") or line.get("text") or "")
    geometry_used = bool(line.get("geometry_used"))
    x_max_norm = line.get("x_max_norm")
    y_center = _line_y(line)
    amount_text = amount.get("text") or ""
    decimal = "." in amount_text
    right_aligned = isinstance(x_max_norm, (int, float)) and x_max_norm >= 0.70
    bottom_region = y_center >= 0.65
    near_bottom = line_idx >= max(0, line_count - 3) or abs(y_center - max_y) < 0.06
    ocr_confidence = _safe_float(line.get("confidence"))

    score = 0.35
    if label_strength == "explicit":
        score += 0.25
    if bottom_region:
        score += 0.10
    if right_aligned:
        score += 0.10
    if decimal:
        score += 0.08
    if ocr_confidence is not None:
        score += min(max(ocr_confidence, 0), 1) * 0.10
    if field == "grand_total" and near_bottom:
        score += 0.10
    if label_strength == "weak_total":
        score -= 0.15
    if amount_count > 1:
        score -= 0.10
    if not geometry_used:
        score -= 0.04
    score = max(0.0, min(0.95, score))

    return {
        "label": field,
        "field": field,
        "value": amount["value"],
        "raw_value": amount_text,
        "confidence": round(score, 4),
        "line_text": text,
        "source_text": text,
        "source_path": line.get("source_path") or "footer_rescue.line",
        "geometry_used": geometry_used,
        "y_center": y_center,
        "x_max_norm": x_max_norm,
        "label_strength": label_strength,
        "amount_count": amount_count,
        "reason": _candidate_reason(label_strength, bottom_region, right_aligned, decimal, near_bottom),
    }


def _extract_amounts(text: str) -> List[Dict[str, Any]]:
    amounts = []
    for match in AMOUNT_RE.finditer(text):
        token = match.group(0)
        if _is_rejected_amount_match(text, match):
            continue
        value = _parse_amount(token)
        if value is None:
            continue
        amounts.append({
            "text": token.strip(),
            "value": value,
            "start": match.start(),
            "end": match.end(),
        })
    return amounts


def _choose_amount_for_field(text: str, amounts: List[Dict[str, Any]], field: str) -> Dict[str, Any]:
    if not amounts:
        raise ValueError("amounts must not be empty")
    normalized = _label_text(text)
    label_index = _label_index(normalized, field)
    if label_index is None:
        return amounts[-1]
    after_label = [amount for amount in amounts if amount["start"] >= label_index]
    if field == "subtotal":
        discount_index = _first_label_index(normalized, DISCOUNT_LABELS)
        if discount_index is not None and discount_index > label_index:
            subtotal_amounts = [
                amount for amount in after_label
                if amount["start"] < discount_index
            ]
            if subtotal_amounts:
                return subtotal_amounts[-1]
            if len(after_label) >= 2:
                return after_label[-2]
    return after_label[-1] if after_label else amounts[-1]


def _label_index(normalized_text: str, field: str) -> Optional[int]:
    if field == "subtotal":
        return _first_label_index(normalized_text, SUBTOTAL_LABELS)
    if field == "discount":
        return _first_label_index(normalized_text, DISCOUNT_LABELS)
    if field == "roundoff":
        return _first_label_index(normalized_text, ROUND_OFF_LABELS)
    if field == "grand_total":
        index = _first_label_index(normalized_text, STRONG_GRAND_TOTAL_LABELS)
        return index if index is not None else normalized_text.find("total")
    if field in GST_LABEL_PATTERNS:
        match = GST_LABEL_PATTERNS[field].search(normalized_text)
        return match.start() if match else None
    return None


def _first_label_index(normalized_text: str, labels: Sequence[str]) -> Optional[int]:
    matches = [normalized_text.find(label) for label in labels if normalized_text.find(label) >= 0]
    return min(matches) if matches else None


def _is_rejected_amount_match(text: str, match: re.Match[str]) -> bool:
    start, end = match.span()
    if end < len(text) and text[end:].lstrip().startswith("%"):
        return True
    before = text[max(0, start - 2):start]
    after = text[end:end + 2]
    if any(char in before for char in ("/", "-")) or any(char in after for char in ("/", "-")):
        return True
    token = match.group(0)
    digits = re.sub(r"\D", "", token)
    if len(digits) >= 7 and "." not in token and "," not in token:
        return True
    if len(digits) >= 10:
        return True
    return False


def _parse_amount(token: str) -> Optional[float]:
    cleaned = re.sub(r"(?i)\b(rs|inr)\.?", "", token)
    cleaned = cleaned.replace("₹", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _has_unresolved_conflict(candidates: List[Dict[str, Any]]) -> bool:
    values = {_round_amount(candidate.get("value")) for candidate in candidates}
    values.discard(None)
    if len(values) <= 1:
        return False
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    if top.get("label_strength") == "explicit" and second:
        gap = (top.get("confidence") or 0) - (second.get("confidence") or 0)
        if gap >= 0.15 and not top.get("ambiguous_total"):
            return False
    return True


def _matches_item_sum_only(field: str, value: Any, item_sum: Optional[float]) -> bool:
    if field != "grand_total" or item_sum is None:
        return False
    numeric = _safe_float(value)
    if numeric is None:
        return False
    return abs(numeric - item_sum) < 0.01


def _unsafe_to_apply(candidate: Dict[str, Any]) -> bool:
    line_text = _label_text(candidate.get("line_text") or "")
    if candidate.get("amount_count", 0) > 3:
        return True
    if any(term in line_text for term in ("terms", "bank", "account no", "a/c no", "ifsc", "authorised", "signature")):
        return True
    return False


def _sum_item_amounts(canonical_invoice: CanonicalInvoice) -> Optional[float]:
    amounts = []
    for row in canonical_invoice.item_rows:
        amount = _safe_float(getattr(row, "amount", None))
        if amount is not None:
            amounts.append(amount)
    if not amounts:
        return None
    return round(sum(amounts), 2)


def _is_bottommost(candidate: Dict[str, Any], max_y: float) -> bool:
    return abs((candidate.get("y_center") or 0) - max_y) <= 0.05


def _candidate_reason(
    label_strength: str,
    bottom_region: bool,
    right_aligned: bool,
    decimal: bool,
    near_bottom: bool,
) -> str:
    parts = [label_strength]
    if bottom_region:
        parts.append("bottom_region")
    if right_aligned:
        parts.append("right_aligned")
    if decimal:
        parts.append("decimal_amount")
    if near_bottom:
        parts.append("near_bottom")
    return ",".join(parts)


def _summarize_line(line: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "line_text": line.get("line_text") or line.get("text"),
        "confidence": line.get("confidence"),
        "y_center": line.get("y_center_norm", line.get("y_center")),
        "source_path": line.get("source_path"),
        "geometry_used": bool(line.get("geometry_used")),
    }


def _label_text(text: str) -> str:
    return _clean_space(str(text or "").lower().replace("_", " ").replace("-", " "))


def _clean_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _first_present(data: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_div(value: Any, divisor: float) -> float:
    numeric = _safe_float(value)
    if numeric is None or divisor == 0:
        return 0.0
    return numeric / divisor


def _has_geometry(unit: Dict[str, Any]) -> bool:
    return all(unit.get(key) is not None for key in ("x_min", "y_min", "x_max", "y_max"))


def _unit_y(unit: Dict[str, Any]) -> float:
    value = unit.get("y_center_norm")
    if value is not None:
        return float(value)
    if unit.get("y_min_norm") is not None and unit.get("y_max_norm") is not None:
        return mean((float(unit["y_min_norm"]), float(unit["y_max_norm"])))
    if unit.get("y_min") is not None and unit.get("y_max") is not None:
        return mean((float(unit["y_min"]), float(unit["y_max"])))
    return 0.0


def _line_y(line: Dict[str, Any]) -> float:
    value = line.get("y_center_norm", line.get("y_center"))
    if value is None:
        return 0.0
    return float(value)


def _round_or_none(value: Any) -> Optional[float]:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return round(numeric, 3)


def _round_amount(value: Any) -> Optional[float]:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return round(numeric, 2)
