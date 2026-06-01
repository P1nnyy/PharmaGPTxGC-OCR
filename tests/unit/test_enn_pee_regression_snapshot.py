import json
from pathlib import Path

from scripts.compare_invoice_ground_truth import compare_invoice_to_expected


FIXTURE_PATH = Path("tests/fixtures/expected/enn_pee_a005364_expected.json")


def test_expected_fixture_contains_core_enn_pee_values():
    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert expected["invoice_no"] == "A005364"
    assert expected["date"] == "28-11-2025"
    assert expected["seller_gstin"] == "03AAKFE8451D1ZN"
    assert expected["buyer_gstin"] == "03AAJFR4013K1ZE"
    assert expected["expected_totals"]["grand_total"] == 2200.0
    assert "LUBIMOIST EYE DROPS" in expected["expected_products_present"]


def test_compare_invoice_to_expected_reports_known_mismatch_categories():
    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    extracted = {
        "invoice_totals": {
            "subtotal": 2229.34,
            "discount": 2229.34,
            "sgst": 52.38,
            "cgst": 52.38,
            "roundoff": 0.35,
            "grand_total": 2200.0,
        },
        "item_rows_clean": [
            {
                "visual_row_id": "graph_row_17",
                "item_description": "MAHAFLOX-LP EYE DROPS",
                "qty": "",
                "source": "selected_graph_table",
            },
            {
                "visual_row_id": "graph_row_18",
                "item_description": "LIPIGO 10 MG",
                "qty": None,
                "source": "selected_graph_table",
            },
            {
                "visual_row_id": "graph_row_24",
                "item_description": "NUROKIND LC TAB",
                "qty": "2.750+.250",
                "source": "selected_graph_table",
            },
        ],
        "metrics": {
            "rows_math_failed": 7,
            "item_row_alignment_diagnostics": {
                "rows": [
                    {
                        "visual_row_id": "graph_row_17",
                        "item_description": "MAHAFLOX-LP EYE DROPS",
                        "suspected_merged_row": True,
                        "suspected_shifted_amount": True,
                        "issues": ["multiple_product_semantic_cells"],
                    }
                ]
            },
        },
    }

    diagnostics = compare_invoice_to_expected(extracted, expected)

    assert "LUBIMOIST EYE DROPS" in diagnostics["missing_products"]
    assert diagnostics["total_mismatches"]["discount"] == {
        "expected": 133.75,
        "actual": 2229.34,
    }
    assert diagnostics["total_mismatches"]["cr_dr_note"] == {
        "expected": 0.0,
        "actual": None,
    }
    assert diagnostics["qty_missing_count"] == 2
    assert diagnostics["rows_math_failed"] == 7
    assert diagnostics["suspected_merged_products"][0]["visual_row_id"] == "graph_row_17"
    json.dumps(diagnostics)
