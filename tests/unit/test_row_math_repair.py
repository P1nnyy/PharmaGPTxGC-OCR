from decimal import Decimal

from services.layout_pipeline.canonical_invoice import build_canonical_invoice
from services.layout_pipeline.row_math_repair import (
    diagnose_row_math_repairs,
    parse_compound_quantity,
    parse_decimal,
)


def test_parse_decimal_handles_indian_and_compound_quantities():
    assert parse_decimal("1,23,456.78") == Decimal("123456.78")
    assert parse_decimal(".500") == Decimal("0.500")
    assert parse_decimal("2.500+.500") == Decimal("2.500")
    assert parse_compound_quantity("2.500 + .500") == (Decimal("2.500"), Decimal("0.500"))
    assert parse_compound_quantity("2+1") == (Decimal("2"), Decimal("1"))
    assert parse_decimal("garbage") is None


def test_high_confidence_compound_qty_repair_applies_with_trace():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{
            "row_id": "r1",
            "product": "RANIDOM-MPS SUSP",
            "qty": "2.500",
            "free_qty": "0.500",
            "rate": "71.34",
            "amount": "196.19",
            "raw_text": "RANIDOM-MPS SUSP 2.750+0.250 71.34 196.19",
            "confidence": 0.95,
        }],
        "invoice_confidence": 0.8,
    })

    report = diagnose_row_math_repairs(canonical, {})

    assert report["rows_checked"] == 1
    assert report["rows_failed"] == 1
    assert report["summary"]["candidate_count"] == 1
    assert report["summary"]["applied_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["candidate_qty"] == "2.750"
    assert candidate["candidate_free_qty"] == "0.250"
    assert candidate["applied"] is True
    row = canonical.item_rows[0]
    assert row.qty == "2.750"
    assert row.free_qty == "0.250"
    assert row.to_dict()["repair_source"] == "row_math_repair"
    assert row.to_dict()["repair_original_values"]["qty"] == "2.500"


def test_missing_free_qty_reports_candidate_but_does_not_apply():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{
            "row_id": "r2",
            "product": "ABC TAB",
            "qty": "2",
            "rate": "10.00",
            "amount": "25.00",
            "raw_text": "ABC TAB qty 2 rate 10 amount 25",
        }],
        "invoice_confidence": 0.8,
    })

    report = diagnose_row_math_repairs(canonical, {})

    assert report["summary"]["candidate_count"] == 1
    assert report["summary"]["applied_count"] == 0
    assert report["repair_candidates"][0]["candidate_qty"] == "2.500"
    assert report["repair_candidates"][0]["applied"] is False
    assert canonical.item_rows[0].qty == "2"


def test_conflicting_compound_source_does_not_apply_candidate():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{
            "row_id": "r3",
            "product": "RANIDOM-MPS SUSP",
            "qty": "2.500",
            "free_qty": "0.500",
            "rate": "71.34",
            "amount": "196.19",
            "raw_text": "RANIDOM-MPS SUSP 2.500+0.500 71.34 196.19",
            "confidence": 0.95,
        }],
        "invoice_confidence": 0.8,
    })

    report = diagnose_row_math_repairs(canonical, {})

    assert report["summary"]["candidate_count"] == 1
    assert report["summary"]["applied_count"] == 0
    assert report["repair_candidates"][0]["candidate_qty"] == "2.750"
    assert report["repair_candidates"][0]["candidate_free_qty"] == "0.250"
    assert report["repair_candidates"][0]["applied"] is False
    assert canonical.item_rows[0].qty == "2.500"
    assert canonical.item_rows[0].free_qty == "0.500"


def test_malformed_rows_do_not_crash_or_create_candidates():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{
            "row_id": "bad",
            "product": "BAD",
            "qty": "??",
            "rate": "",
            "amount": "nope",
        }],
        "invoice_confidence": 0.8,
    })

    report = diagnose_row_math_repairs(canonical, {})

    assert report["rows_checked"] == 1
    assert report["rows_failed"] == 0
    assert report["repair_candidates"] == []
