from services.layout_pipeline.canonical_invoice import build_canonical_invoice
from services.layout_pipeline.footer_rescue import diagnose_footer_rescue


def test_footer_rescue_identifies_missing_grand_total_candidate_from_text():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 10, "amount": 10}],
        "totals": {"subtotal": 10, "discount": 0, "sgst": 0, "cgst": 0},
        "invoice_confidence": 0.8,
    })

    report = diagnose_footer_rescue(canonical, {"semantic_markdown": "Grand Total : 118.00"})

    assert "grand_total" in report["missing_fields"]
    assert any(candidate["label"] == "grand_total" and candidate["value"] == 118.0 for candidate in report["candidate_fields"])


def test_footer_rescue_does_not_apply_conflicting_candidates():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 10, "amount": 10}],
        "totals": {"subtotal": 10, "discount": 0, "sgst": 0, "cgst": 0},
        "invoice_confidence": 0.8,
    })

    report = diagnose_footer_rescue(
        canonical,
        {"semantic_markdown": "Grand Total : 118.00\nNet Amount : 120.00"},
    )

    assert report["applied_fields"] == []
    assert "conflicting_candidates:grand_total" in report["warnings"]
    assert canonical.get_footer_value("grand_total") is None
