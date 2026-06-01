import json

from models.layout_models import GeometryBox, RowRegion, TableCell, TableRegion
from services.financial_reconciler import FinancialReconciler


def _geom(x=0, y=0):
    return GeometryBox(min_x=x, max_x=x + 10, min_y=y, max_y=y + 10, center_x=x + 5, center_y=y + 5)


def _row(row_id="row_1", role="item_row"):
    return RowRegion(row_id=row_id, row_role=role, geometry=_geom())


def _cell(row_id, col_id, text, x=0):
    return TableCell(row_id=row_id, col_id=col_id, text=text, geometry=_geom(x=x))


def _table(cells, rows=None):
    return TableRegion(
        table_id="graph_fallback_region",
        rows=rows or [_row("row_1")],
        cells=cells,
        geometry=_geom(),
    )


def _reconcile(cells, rows=None):
    reconciler = FinancialReconciler(semantic_column_cache={
        "graph_fallback_region": {
            "c_product": {"type": "product"},
            "c_qty": {"type": "quantity"},
            "c_rate": {"type": "rate"},
            "c_amount": {"type": "amount"},
        }
    })
    return reconciler.reconcile_all([_table(cells, rows=rows)])["graph_fallback_region"]


def test_pass_row_emits_status_pass_and_expected_amount():
    result = _reconcile([
        _cell("row_1", "c_product", "LUBIMOIST EYE DROPS", x=1),
        _cell("row_1", "c_qty", "2", x=2),
        _cell("row_1", "c_rate", "95.76", x=3),
        _cell("row_1", "c_amount", "191.52", x=4),
    ])

    detail = result["row_math_details"][0]
    assert detail["status"] == "pass"
    assert detail["expected_amount"] == 191.52
    assert detail["actual_amount"] == 191.52
    assert detail["failure_reason"] == ""


def test_missing_qty_emits_qty_missing_failure_reason():
    result = _reconcile([
        _cell("row_1", "c_product", "LUBIMOIST EYE DROPS", x=1),
        _cell("row_1", "c_rate", "95.76", x=3),
        _cell("row_1", "c_amount", "191.52", x=4),
    ])

    detail = result["row_math_details"][0]
    assert detail["status"] == "unknown"
    assert detail["failure_reason"] == "qty_missing"
    assert result["row_math_failures"][0]["failure_reason"] == "qty_missing"


def test_unparseable_qty_emits_qty_parse_failed_failure_reason():
    result = _reconcile([
        _cell("row_1", "c_product", "LUBIMOIST EYE DROPS", x=1),
        _cell("row_1", "c_qty", "ABC", x=2),
        _cell("row_1", "c_rate", "95.76", x=3),
        _cell("row_1", "c_amount", "191.52", x=4),
    ])

    detail = result["row_math_details"][0]
    assert detail["status"] == "fail"
    assert detail["failure_reason"] == "qty_parse_failed"
    assert detail["qty_parsed"] == 0.0


def test_amount_mismatch_emits_delta():
    result = _reconcile([
        _cell("row_1", "c_product", "LUBIMOIST EYE DROPS", x=1),
        _cell("row_1", "c_qty", "2", x=2),
        _cell("row_1", "c_rate", "10.00", x=3),
        _cell("row_1", "c_amount", "25.00", x=4),
    ])

    detail = result["row_math_details"][0]
    assert detail["status"] == "fail"
    assert detail["expected_amount"] == 20.0
    assert detail["actual_amount"] == 25.0
    assert detail["delta"] == 5.0
    assert detail["failure_reason"] == "math_failed"


def test_financial_reconciliation_diagnostics_are_json_serializable():
    result = _reconcile([
        _cell("row_1", "c_product", "LUBIMOIST EYE DROPS", x=1),
        _cell("row_1", "c_qty", "1", x=2),
        _cell("row_1", "c_rate", "250.64", x=3),
        _cell("row_1", "c_amount", "250.64", x=4),
    ])

    assert result["row_math_details"][0]["qty_source"].startswith(
        "table_cell:graph_fallback_region:row_1:c_qty"
    )
    json.dumps(result)
