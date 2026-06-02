from services.layout_pipeline.canonical_invoice import build_canonical_invoice
from services.layout_pipeline.layout_profile import classify_layout_profile


def test_missing_footer_is_profiled():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 10, "amount": 10}],
        "invoice_confidence": 0.8,
    })

    report = classify_layout_profile(canonical)

    assert report["profile"] in {"borderless_footer_risk", "footer_missing"}
    assert "footer_missing" in report["issues"]


def test_high_row_math_failures_are_profiled_as_risk():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 10, "amount": 12}],
        "totals": {"subtotal": 12, "discount": 0, "sgst": 0, "cgst": 0, "grand_total": 12},
        "invoice_confidence": 0.8,
        "metrics": {"financial_reconciliation": {"main": {"rows_math_passed": 1, "rows_math_failed": 3}}},
    })

    report = classify_layout_profile(canonical)

    assert report["profile"] == "row_math_risk"
    assert "row_math_risk" in report["issues"]
