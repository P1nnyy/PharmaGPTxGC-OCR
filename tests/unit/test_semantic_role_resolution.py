import pytest
from models.layout_models import GeometryBox, TableCell
from services.layout_pipeline.semantic_column_classifier import (
    ColumnSemantics,
    resolve_semantic_role_conflicts,
)


def _geom(x=0, y=0):
    """Helper to construct a mock GeometryBox."""
    return GeometryBox(
        min_x=x,
        max_x=x + 10,
        min_y=y,
        max_y=y + 10,
        center_x=x + 5,
        center_y=y + 5,
    )


def test_multiple_amount_candidates_resolve_to_one_amount():
    """Verify that multiple amount candidates resolve to exactly one amount winner."""
    column_scores = {
        "col_amount_1": {ColumnSemantics.AMOUNT: 4.0, ColumnSemantics.RATE: 1.0},
        "col_amount_2": {ColumnSemantics.AMOUNT: 4.5, ColumnSemantics.RATE: 1.0},
    }
    cells = [
        TableCell(row_id="row_1", col_id="col_amount_1", text="100.00", geometry=_geom(x=40)),
        TableCell(row_id="row_1", col_id="col_amount_2", text="120.00", geometry=_geom(x=80)),
    ]
    row_roles = {"row_1": "item_row"}
    headers = {"col_amount_1": "Taxable Value", "col_amount_2": "Net Amount"}

    res = resolve_semantic_role_conflicts(column_scores, cells, row_roles, headers)

    assert res["resolved_semantics"]["col_amount_2"] == ColumnSemantics.AMOUNT
    assert res["resolved_semantics"]["col_amount_1"] == ColumnSemantics.TAXABLE_VALUE


def test_multiple_quantity_candidates_resolve_to_one_quantity():
    """Verify that multiple quantity candidates resolve to exactly one quantity winner."""
    column_scores = {
        "col_qty_1": {ColumnSemantics.QUANTITY: 3.5, ColumnSemantics.FREE_QUANTITY: 1.0},
        "col_qty_2": {ColumnSemantics.QUANTITY: 3.0, ColumnSemantics.FREE_QUANTITY: 1.0},
    }
    cells = [
        TableCell(row_id="row_1", col_id="col_qty_1", text="10", geometry=_geom(x=20)),
        TableCell(row_id="row_1", col_id="col_qty_2", text="2", geometry=_geom(x=30)),
    ]
    row_roles = {"row_1": "item_row"}
    headers = {"col_qty_1": "Billed Qty", "col_qty_2": "Free Qty"}

    res = resolve_semantic_role_conflicts(column_scores, cells, row_roles, headers)

    assert res["resolved_semantics"]["col_qty_1"] == ColumnSemantics.QUANTITY
    assert res["resolved_semantics"]["col_qty_2"] == ColumnSemantics.FREE_QUANTITY


def test_rate_column_is_not_swallowed_by_amount_column():
    """Verify that rate column is not swallowed by amount column."""
    column_scores = {
        "col_rate": {ColumnSemantics.AMOUNT: 3.0, ColumnSemantics.RATE: 4.0},
        "col_amount": {ColumnSemantics.AMOUNT: 5.0, ColumnSemantics.RATE: 2.0},
    }
    cells = [
        TableCell(row_id="row_1", col_id="col_rate", text="150.00", geometry=_geom(x=50)),
        TableCell(row_id="row_1", col_id="col_amount", text="1500.00", geometry=_geom(x=80)),
    ]
    row_roles = {"row_1": "item_row"}
    headers = {"col_rate": "Rate", "col_amount": "Amount"}

    res = resolve_semantic_role_conflicts(column_scores, cells, row_roles, headers)

    assert res["resolved_semantics"]["col_rate"] == ColumnSemantics.RATE
    assert res["resolved_semantics"]["col_amount"] == ColumnSemantics.AMOUNT


def test_contaminated_qty_strings_reduce_quantity_confidence():
    """Verify that contaminated quantity strings lower candidate score/confidence."""
    column_scores = {
        "col_qty_contaminated": {ColumnSemantics.QUANTITY: 4.0},
        "col_qty_clean": {ColumnSemantics.QUANTITY: 3.0},
    }
    cells = [
        TableCell(row_id="row_1", col_id="col_qty_contaminated", text="33 0 2", geometry=_geom(x=20)),
        TableCell(row_id="row_1", col_id="col_qty_clean", text="5", geometry=_geom(x=30)),
    ]
    row_roles = {"row_1": "item_row"}
    headers = {"col_qty_contaminated": "Qty", "col_qty_clean": "Quantity"}

    res = resolve_semantic_role_conflicts(column_scores, cells, row_roles, headers)

    # col_qty_clean should win quantity since contaminated has its score heavily penalized
    assert res["resolved_semantics"]["col_qty_clean"] == ColumnSemantics.QUANTITY
    assert res["resolved_semantics"]["col_qty_contaminated"] != ColumnSemantics.QUANTITY


def test_secondary_amount_like_columns_are_demoted():
    """Verify that secondary amount-like columns are demoted to taxable_value or discount."""
    column_scores = {
        "col_tax": {ColumnSemantics.AMOUNT: 4.0},
        "col_disc": {ColumnSemantics.AMOUNT: 4.0},
        "col_amt": {ColumnSemantics.AMOUNT: 4.5},
    }
    cells = [
        TableCell(row_id="row_1", col_id="col_tax", text="100.00", geometry=_geom(x=50)),
        TableCell(row_id="row_1", col_id="col_disc", text="10.00", geometry=_geom(x=60)),
        TableCell(row_id="row_1", col_id="col_amt", text="110.00", geometry=_geom(x=80)),
    ]
    row_roles = {"row_1": "item_row"}
    headers = {"col_tax": "Taxable Value", "col_disc": "Discount", "col_amt": "Net Amount"}

    res = resolve_semantic_role_conflicts(column_scores, cells, row_roles, headers)

    assert res["resolved_semantics"]["col_amt"] == ColumnSemantics.AMOUNT
    assert res["resolved_semantics"]["col_tax"] == ColumnSemantics.TAXABLE_VALUE
    assert res["resolved_semantics"]["col_disc"] == ColumnSemantics.DISCOUNT


def test_product_column_remains_stable():
    """Verify that product column remains stable and is not disrupted."""
    column_scores = {
        "col_prod": {ColumnSemantics.PRODUCT: 5.0},
        "col_other": {ColumnSemantics.QUANTITY: 3.0},
    }
    cells = [
        TableCell(row_id="row_1", col_id="col_prod", text="CROCIN PEN PAIN RELIEF", geometry=_geom(x=5)),
        TableCell(row_id="row_1", col_id="col_other", text="2", geometry=_geom(x=40)),
    ]
    row_roles = {"row_1": "item_row"}
    headers = {"col_prod": "Product Name", "col_other": "Qty"}

    res = resolve_semantic_role_conflicts(column_scores, cells, row_roles, headers)

    assert res["resolved_semantics"]["col_prod"] == ColumnSemantics.PRODUCT
    assert res["resolved_semantics"]["col_other"] == ColumnSemantics.QUANTITY
