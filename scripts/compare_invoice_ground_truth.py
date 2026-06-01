import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _normalize_text(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _find_key_recursive(data: Any, key: str, max_depth: int = 5) -> Any:
    if max_depth < 0:
        return None
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = _find_key_recursive(value, key, max_depth=max_depth - 1)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_key_recursive(value, key, max_depth=max_depth - 1)
            if found is not None:
                return found
    return None


def _actual_totals(extracted: Dict[str, Any]) -> Dict[str, Any]:
    totals = extracted.get("invoice_totals")
    if isinstance(totals, dict):
        return totals

    invoice_reconciliation = _find_key_recursive(extracted, "invoice_level")
    if isinstance(invoice_reconciliation, dict):
        return {
            "subtotal": invoice_reconciliation.get("footer_subtotal")
            or invoice_reconciliation.get("item_derived_subtotal"),
            "discount": invoice_reconciliation.get("discount_total"),
            "sgst": invoice_reconciliation.get("sgst_total"),
            "cgst": invoice_reconciliation.get("cgst_total"),
            "roundoff": invoice_reconciliation.get("roundoff"),
            "grand_total": invoice_reconciliation.get("parsed_grand_total")
            or invoice_reconciliation.get("expected_grand_total"),
        }
    return {}


def _product_descriptions(extracted: Dict[str, Any]) -> List[str]:
    rows = extracted.get("item_rows_clean")
    if not isinstance(rows, list):
        return []
    descriptions = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        description = row.get("item_description") or row.get("product") or row.get("description")
        if description:
            descriptions.append(str(description))
    return descriptions


def _contains_product(actual_descriptions: List[str], expected_product: str) -> bool:
    expected_norm = _normalize_text(expected_product)
    return any(expected_norm in _normalize_text(actual) for actual in actual_descriptions)


def _extra_products(actual_descriptions: List[str], expected_products: List[str]) -> List[str]:
    extras = []
    expected_norms = [_normalize_text(product) for product in expected_products]
    for actual in actual_descriptions:
        actual_norm = _normalize_text(actual)
        if actual_norm and not any(expected in actual_norm or actual_norm in expected for expected in expected_norms):
            extras.append(actual)
    return extras


def _qty_missing_count(extracted: Dict[str, Any]) -> int:
    rows = extracted.get("item_rows_clean")
    if not isinstance(rows, list):
        return 0
    return sum(1 for row in rows if isinstance(row, dict) and not str(row.get("qty") or "").strip())


def _suspected_merged_products(extracted: Dict[str, Any]) -> List[Dict[str, Any]]:
    diagnostics = _find_key_recursive(extracted, "item_row_alignment_diagnostics")
    if not isinstance(diagnostics, dict):
        return []
    rows = diagnostics.get("rows")
    if not isinstance(rows, list):
        return []
    suspected = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("suspected_merged_row") or row.get("suspected_shifted_amount"):
            suspected.append({
                "visual_row_id": row.get("visual_row_id"),
                "item_description": row.get("item_description"),
                "issues": row.get("issues", []),
            })
    return suspected


def _rows_math_failed(extracted: Dict[str, Any]) -> Any:
    value = _find_key_recursive(extracted, "rows_math_failed")
    if value is None:
        value = _find_key_recursive(extracted, "row_math_fail_count")
    return value


def compare_invoice_to_expected(extracted: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    """Return JSON-safe diagnostics comparing current output to ENN PEE ground truth."""
    actual_descriptions = _product_descriptions(extracted)
    expected_products = expected.get("expected_products_present") or []
    missing_products = [
        product for product in expected_products
        if not _contains_product(actual_descriptions, product)
    ]
    actual_totals = _actual_totals(extracted)
    total_mismatches = {}
    for field, expected_value in (expected.get("expected_totals") or {}).items():
        actual_value = _as_float(actual_totals.get(field))
        expected_float = _as_float(expected_value)
        if actual_value is None or expected_float is None or abs(actual_value - expected_float) > 0.01:
            total_mismatches[field] = {
                "expected": expected_float,
                "actual": actual_value,
            }

    return {
        "invoice_no": expected.get("invoice_no"),
        "missing_products": missing_products,
        "extra_products": _extra_products(actual_descriptions, expected_products),
        "total_mismatches": total_mismatches,
        "qty_missing_count": _qty_missing_count(extracted),
        "rows_math_failed": _rows_math_failed(extracted),
        "suspected_merged_products": _suspected_merged_products(extracted),
    }


def _load_reconstruction(run_dir: Path) -> Dict[str, Any]:
    reconstruction_path = run_dir / "03_reconstruction.json"
    if not reconstruction_path.exists():
        raise FileNotFoundError(f"Missing reconstruction file: {reconstruction_path}")
    return json.loads(reconstruction_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare invoice run output to a ground-truth fixture.")
    parser.add_argument("--run", required=True, help="Path to local_runs/<timestamp> directory")
    parser.add_argument("--expected", required=True, help="Path to expected ground-truth JSON")
    args = parser.parse_args()

    run_dir = Path(args.run).expanduser().resolve()
    expected_path = Path(args.expected).expanduser().resolve()
    extracted = _load_reconstruction(run_dir)
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    diagnostics = compare_invoice_to_expected(extracted, expected)
    print(json.dumps(diagnostics, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
