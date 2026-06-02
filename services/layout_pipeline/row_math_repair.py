from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from services.layout_pipeline.canonical_invoice import CanonicalInvoice, CanonicalItemRow


MONEY_QUANT = Decimal("0.01")
QTY_QUANT = Decimal("0.001")
COMPOUND_QTY_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?|\.\d+)\s*\+\s*(\d+(?:\.\d+)?|\.\d+)(?!\d)")
NUMBER_RE = re.compile(r"-?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?|-?\.\d+")


def diagnose_row_math_repairs(
    canonical_invoice: CanonicalInvoice,
    raw_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_result = raw_result if isinstance(raw_result, dict) else {}
    repair_candidates: List[Dict[str, Any]] = []
    applied_repairs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rows_failed = 0
    still_failed = 0

    for row in canonical_invoice.item_rows:
        parsed = _parse_row_values(row)
        if not all(parsed.get(key) is not None for key in ("qty", "rate", "amount")):
            continue

        qty = parsed["qty"]
        free_qty = parsed.get("free_qty") or Decimal("0")
        rate = parsed["rate"]
        amount = parsed["amount"]
        if rate == 0:
            warnings.append(f"row_math_repair_zero_rate:{row.row_id}")
            continue

        delta_before = _row_delta(qty, rate, amount)
        tolerance = _row_tolerance(amount)
        if delta_before <= tolerance:
            continue

        rows_failed += 1
        candidate = _build_candidate(
            row=row,
            qty=qty,
            free_qty=free_qty,
            rate=rate,
            amount=amount,
            delta_before=delta_before,
            tolerance=tolerance,
            raw_result=raw_result,
        )
        if not candidate:
            still_failed += 1
            continue

        repair_candidates.append(candidate)
        if _should_apply(candidate, tolerance):
            _apply_candidate(row, candidate)
            candidate["applied"] = True
            applied_repairs.append(candidate)
        else:
            still_failed += 1

    for candidate in repair_candidates:
        if not candidate.get("applied"):
            candidate["applied"] = False

    return {
        "rows_checked": len(canonical_invoice.item_rows),
        "rows_failed": rows_failed,
        "repair_candidates": repair_candidates,
        "applied_repairs": applied_repairs,
        "warnings": warnings,
        "summary": {
            "candidate_count": len(repair_candidates),
            "applied_count": len(applied_repairs),
            "still_failed_count": still_failed,
        },
    }


def parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    compound = parse_compound_quantity(text)
    if compound:
        return compound[0]
    match = NUMBER_RE.search(text.replace("₹", ""))
    if not match:
        return None
    cleaned = match.group(0).replace(",", "")
    if cleaned.startswith("."):
        cleaned = "0" + cleaned
    if cleaned.startswith("-."):
        cleaned = "-0" + cleaned[1:]
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_compound_quantity(value: Any) -> Optional[Tuple[Decimal, Decimal]]:
    text = str(value or "").strip()
    match = COMPOUND_QTY_RE.search(text)
    if not match:
        return None
    paid = parse_decimal(match.group(1))
    free = parse_decimal(match.group(2))
    if paid is None or free is None:
        return None
    return paid, free


def _parse_row_values(row: CanonicalItemRow) -> Dict[str, Optional[Decimal]]:
    compound = parse_compound_quantity(getattr(row, "qty", None))
    qty = compound[0] if compound else parse_decimal(getattr(row, "qty", None))
    free_from_compound = compound[1] if compound else None
    free_qty = parse_decimal(getattr(row, "free_qty", None))
    return {
        "qty": qty,
        "free_qty": free_qty if free_qty is not None else free_from_compound,
        "rate": parse_decimal(getattr(row, "rate", None)),
        "amount": parse_decimal(getattr(row, "amount", None)),
    }


def _build_candidate(
    row: CanonicalItemRow,
    qty: Decimal,
    free_qty: Decimal,
    rate: Decimal,
    amount: Decimal,
    delta_before: Decimal,
    tolerance: Decimal,
    raw_result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    implied_paid_qty = (amount / rate).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
    if implied_paid_qty <= 0 or implied_paid_qty > Decimal("999"):
        return None

    total_qty = qty + free_qty
    source_text = _row_source_text(row, raw_result)
    preserves_total = free_qty > 0 and implied_paid_qty < total_qty

    if preserves_total:
        candidate_free_qty = (total_qty - implied_paid_qty).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
    elif free_qty == 0 and _source_has_quantity_like_token(source_text):
        candidate_free_qty = Decimal("0")
    else:
        return None

    if candidate_free_qty < 0:
        return None

    delta_after = _row_delta(implied_paid_qty, rate, amount)
    if delta_after > tolerance:
        return None

    source_supports_compound = _source_compound_supports_candidate(
        source_text,
        implied_paid_qty,
        candidate_free_qty,
    )
    confidence = _score_candidate(
        row=row,
        implied_paid_qty=implied_paid_qty,
        candidate_free_qty=candidate_free_qty,
        delta_after=delta_after,
        tolerance=tolerance,
        preserves_total=preserves_total,
        source_supports_compound=source_supports_compound,
        source_text=source_text,
    )

    return {
        "row_id": str(row.row_id),
        "product": str(row.product or ""),
        "original_qty": _string_value(row.qty),
        "original_free_qty": _string_value(row.free_qty),
        "original_rate": _string_value(row.rate),
        "original_amount": _string_value(row.amount),
        "implied_paid_qty": _format_decimal(implied_paid_qty, QTY_QUANT),
        "candidate_qty": _format_decimal(implied_paid_qty, QTY_QUANT),
        "candidate_free_qty": _format_decimal(candidate_free_qty, QTY_QUANT),
        "delta_before": _format_decimal(delta_before, MONEY_QUANT),
        "delta_after": _format_decimal(delta_after, MONEY_QUANT),
        "confidence": confidence,
        "reason": _candidate_reason(preserves_total, source_supports_compound, delta_after, tolerance),
        "source_text": source_text,
        "applied": False,
    }


def _score_candidate(
    row: CanonicalItemRow,
    implied_paid_qty: Decimal,
    candidate_free_qty: Decimal,
    delta_after: Decimal,
    tolerance: Decimal,
    preserves_total: bool,
    source_supports_compound: bool,
    source_text: str,
) -> float:
    score = Decimal("0.45")
    if delta_after <= tolerance:
        score += Decimal("0.20")
    if _decimal_places(implied_paid_qty) in (2, 3):
        score += Decimal("0.08")
    if preserves_total:
        score += Decimal("0.16")
    if source_supports_compound:
        score += Decimal("0.12")
    if row.product:
        score += Decimal("0.04")
    if _safe_float(row.confidence) is not None:
        score += Decimal(str(min(max(_safe_float(row.confidence) or 0, 0), 1))) * Decimal("0.04")
    if not _source_has_quantity_like_token(source_text):
        score -= Decimal("0.18")
    if implied_paid_qty > Decimal("100"):
        score -= Decimal("0.20")
    if len(source_text) < 8:
        score -= Decimal("0.08")
    if candidate_free_qty < 0:
        score -= Decimal("0.50")
    return float(max(Decimal("0"), min(Decimal("0.99"), score)))


def _should_apply(candidate: Dict[str, Any], tolerance: Decimal) -> bool:
    confidence = candidate.get("confidence") or 0
    parsed_delta_after = parse_decimal(candidate.get("delta_after"))
    delta_after = parsed_delta_after if parsed_delta_after is not None else Decimal("999999")
    source_text = str(candidate.get("source_text") or "")
    parsed_candidate_qty = parse_decimal(candidate.get("candidate_qty"))
    parsed_candidate_free_qty = parse_decimal(candidate.get("candidate_free_qty"))
    return (
        confidence >= 0.85
        and delta_after <= tolerance
        and parsed_candidate_qty is not None
        and parsed_candidate_free_qty is not None
        and _source_compound_supports_candidate(
            source_text,
            parsed_candidate_qty,
            parsed_candidate_free_qty,
        )
    )


def _apply_candidate(row: CanonicalItemRow, candidate: Dict[str, Any]) -> None:
    original_values = {
        "qty": row.qty,
        "free_qty": row.free_qty,
        "rate": row.rate,
        "amount": row.amount,
    }
    row.qty = candidate["candidate_qty"]
    row.free_qty = candidate["candidate_free_qty"]
    setattr(row, "repair_source", "row_math_repair")
    setattr(row, "repair_original_values", original_values)


def _row_delta(qty: Decimal, rate: Decimal, amount: Decimal) -> Decimal:
    return abs((qty * rate).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP) - amount)


def _row_tolerance(amount: Decimal) -> Decimal:
    return max(Decimal("0.05"), abs(amount) * Decimal("0.002"))


def _row_source_text(row: CanonicalItemRow, raw_result: Dict[str, Any]) -> str:
    parts = [str(row.raw_text or ""), str(row.product or "")]
    source_path = str(row.source_path or "")
    for value in _iter_row_like_values(raw_result):
        text = str(value.get("text") or value.get("raw_text") or value.get("line_text") or "")
        if not text:
            continue
        row_id = str(value.get("row_id") or value.get("visual_row_id") or value.get("id") or "")
        if row_id and row_id == str(row.row_id):
            parts.append(text)
        elif row.product and str(row.product).lower() in text.lower():
            parts.append(text)
        elif source_path and source_path.endswith(f"[{value.get('index')}]"):
            parts.append(text)
    return " ".join(part for part in parts if part).strip()


def _iter_row_like_values(raw_result: Dict[str, Any]):
    for key in ("item_rows_clean", "item_rows", "reconstructed_item_rows", "structured_rows", "line_items"):
        rows = raw_result.get(key)
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    copied = dict(row)
                    copied.setdefault("index", idx)
                    yield copied


def _source_has_quantity_like_token(source_text: str) -> bool:
    return bool(COMPOUND_QTY_RE.search(source_text) or NUMBER_RE.search(source_text))


def _source_compound_supports_candidate(source_text: str, candidate_qty: Decimal, candidate_free_qty: Decimal) -> bool:
    for match in COMPOUND_QTY_RE.finditer(source_text):
        paid = parse_decimal(match.group(1))
        free = parse_decimal(match.group(2))
        if paid is None or free is None:
            continue
        if _qty_close(paid, candidate_qty) and _qty_close(free, candidate_free_qty):
            return True
    return False


def _qty_close(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= Decimal("0.001")


def _candidate_reason(
    preserves_total: bool,
    source_supports_compound: bool,
    delta_after: Decimal,
    tolerance: Decimal,
) -> str:
    parts = ["amount_div_rate_implies_paid_qty"]
    if preserves_total:
        parts.append("physical_qty_preserved")
    if source_supports_compound:
        parts.append("compound_qty_source")
    if delta_after <= tolerance:
        parts.append("delta_after_within_tolerance")
    return ",".join(parts)


def _decimal_places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return abs(exponent) if exponent < 0 else 0


def _format_decimal(value: Decimal, quantum: Decimal) -> str:
    return str(value.quantize(quantum, rounding=ROUND_HALF_UP))


def _string_value(value: Any) -> str:
    return "" if value is None else str(value)


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
