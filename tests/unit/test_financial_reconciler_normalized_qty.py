import json

from models.layout_models import GeometryBox, RowRegion, TableCell, TableRegion
from services.financial_reconciler import FinancialReconciler


def _geom(x=0, y=0):
    return GeometryBox(min_x=x, max_x=x + 10, min_y=y, max_y=y + 10, center_x=x + 5, center_y=y + 5)


def _row(row_id="graph_row_17", role="item_row"):
    return RowRegion(row_id=row_id, row_role=role, geometry=_geom())


def _cell(row_id, col_id, text, x=0):
    return TableCell(row_id=row_id, col_id=col_id, text=text, geometry=_geom(x=x))


def _table(cells, rows=None):
    return TableRegion(
        table_id="graph_fallback_region",
        rows=rows or [_row()],
        cells=cells,
        geometry=_geom(),
    )


def _reconcile(cells, item_rows_clean=None, rows=None):
    reconciler = FinancialReconciler(
        semantic_column_cache={
            "graph_fallback_region": {
                "c_product": {"type": "product"},
                "c_qty": {"type": "quantity"},
                "c_rate": {"type": "rate"},
                "c_amount": {"type": "amount"},
            }
        },
        item_rows_clean=item_rows_clean,
    )
    return reconciler.reconcile_all([_table(cells, rows=rows)])["graph_fallback_region"]


def _base_cells(row_id="graph_row_17", qty_text=""):
    return [
        _cell(row_id, "c_product", "MAHAFLOX-LP EYE DROPS", x=1),
        _cell(row_id, "c_qty", qty_text, x=2),
        _cell(row_id, "c_rate", "250.64", x=3),
        _cell(row_id, "c_amount", "250.64", x=4),
    ]


def test_row_math_uses_normalized_qty_when_table_cell_qty_is_missing():
    result = _reconcile(
        _base_cells(qty_text=""),
        item_rows_clean=[
            {
                "visual_row_id": "graph_row_17",
                "source": "selected_graph_table",
                "qty": "1",
            }
        ],
    )

    detail = result["row_math_details"][0]
    assert result["rows_math_passed"] == 1
    assert result["rows_math_failed"] == 0
    assert detail["status"] == "pass"
    assert detail["qty_raw"] == "1"
    assert detail["qty_source"] == "normalized_item_rows_clean:graph_row_17"
    assert detail["qty_original_table_cell_raw"] == ""
    assert detail["qty_normalized_candidate"] == "1"


def test_table_cell_qty_is_used_when_normalized_qty_unavailable():
    result = _reconcile(_base_cells(qty_text="1"))

    detail = result["row_math_details"][0]
    assert detail["status"] == "pass"
    assert detail["qty_raw"] == "1"
    assert detail["qty_source"].startswith("table_cell:graph_fallback_region:graph_row_17:c_qty")


def test_normalized_qty_does_not_override_non_selected_graph_rows():
    result = _reconcile(
        _base_cells(qty_text=""),
        item_rows_clean=[
            {
                "visual_row_id": "graph_row_17",
                "source": "raw_ocr_coordinate_reconstruction",
                "qty": "1",
            }
        ],
    )

    detail = result["row_math_details"][0]
    assert result["rows_math_passed"] == 0
    assert result["rows_math_failed"] == 1
    assert detail["failure_reason"] == "qty_missing"
    assert detail["qty_source"].startswith("table_cell:graph_fallback_region:graph_row_17:c_qty")


def test_amount_selection_remains_semantic_amount_column():
    result = _reconcile(
        _base_cells(qty_text=""),
        item_rows_clean=[
            {
                "visual_row_id": "graph_row_17",
                "source": "selected_graph_table",
                "qty": "1",
            }
        ],
    )

    amount_source = result["item_amount_sources"][0]
    detail = result["row_math_details"][0]
    assert amount_source["selected_amount_col_id"] == "c_amount"
    assert amount_source["selected_amount_text"] == "250.64"
    assert detail["amount_source"].startswith("table_cell:graph_fallback_region:graph_row_17:c_amount")


def test_normalized_qty_output_is_json_serializable():
    result = _reconcile(
        _base_cells(qty_text=""),
        item_rows_clean=[
            {
                "visual_row_id": "graph_row_17",
                "source": "selected_graph_table",
                "qty": "1",
            }
        ],
    )

    json.dumps(result)
