from services.layout_pipeline.canonical_invoice import build_canonical_invoice
from services.layout_pipeline.quality_gate import evaluate_invoice_quality


def test_zero_confidence_with_item_rows_needs_review():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 10, "amount": 10}],
        "totals": {"subtotal": 10, "discount": 0, "sgst": 0, "cgst": 0, "grand_total": 10},
        "invoice_confidence": 0.0,
        "metrics": {"financial_reconciliation": {"main": {"rows_math_passed": 1, "rows_math_failed": 0}}},
    })

    report = evaluate_invoice_quality(canonical)

    assert report["status"] == "needs_review"
    assert "zero_invoice_confidence" in report["reasons"]
    assert report["safe_for_erp"] is False


def test_no_item_rows_failed():
    canonical = build_canonical_invoice({"invoice_confidence": 0.9})

    report = evaluate_invoice_quality(canonical)

    assert report["status"] == "failed"
    assert "no_item_rows" in report["reasons"]


def test_good_confidence_rows_footer_and_row_math_ok():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 10, "amount": 10}],
        "totals": {"subtotal": 10, "discount": 0, "sgst": 0, "cgst": 0, "grand_total": 10},
        "invoice_confidence": 0.85,
        "metrics": {"financial_reconciliation": {"main": {"rows_math_passed": 1, "rows_math_failed": 0}}},
    })

    report = evaluate_invoice_quality(canonical)

    assert report["status"] == "ok"
    assert report["safe_for_erp"] is True


def test_item_rows_with_missing_row_math_metrics_needs_review():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 10, "amount": 10}],
        "totals": {"subtotal": 10, "discount": 0, "sgst": 0, "cgst": 0, "grand_total": 10},
        "invoice_confidence": 0.85,
    })

    report = evaluate_invoice_quality(canonical)

    assert report["status"] == "needs_review"
    assert "row_math_metrics_missing" in report["reasons"]


def test_unapplied_row_math_repair_candidate_keeps_needs_review():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 2, "rate": 10, "amount": 25}],
        "totals": {"subtotal": 25, "discount": 0, "sgst": 0, "cgst": 0, "grand_total": 25},
        "invoice_confidence": 0.85,
        "metrics": {"financial_reconciliation": {"main": {"rows_math_passed": 0, "rows_math_failed": 1}}},
    })

    report = evaluate_invoice_quality(canonical, {
        "row_math_repair": {
            "summary": {"candidate_count": 1, "applied_count": 0, "still_failed_count": 1}
        }
    })

    assert report["status"] == "needs_review"
    assert "row_math_repair_candidates_unapplied" in report["reasons"]
