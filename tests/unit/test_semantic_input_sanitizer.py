import pytest
from models.layout_models import RowRegion, TableCell, GeometryBox
from services.layout_pipeline.semantic_input_sanitizer import sanitize_rows_for_semantic_inference

def _geom(x=0, y=0):
    """Utility to construct mock GeometryBox."""
    return GeometryBox(
        min_x=float(x),
        max_x=float(x + 10),
        min_y=float(y),
        max_y=float(y + 10),
        center_x=float(x + 5),
        center_y=float(y + 5)
    )

def test_excludes_cgst_sgst_pattern():
    # CGST 2.500 + SGST 2.500
    rows = [RowRegion(row_id="row_1", row_role="item_row", geometry=_geom())]
    cells = [
        TableCell(row_id="row_1", col_id="col_0", text="CGST 2.500 + SGST 2.500", geometry=_geom())
    ]
    res = sanitize_rows_for_semantic_inference(rows, cells=cells)
    assert "row_1" in res["excluded_row_ids"]
    assert len(res["item_rows"]) == 0

def test_excludes_grand_total_pattern():
    # Grand Total 2291.00
    rows = [RowRegion(row_id="row_1", row_role="item_row", geometry=_geom())]
    cells = [
        TableCell(row_id="row_1", col_id="col_0", text="Grand Total 2291.00", geometry=_geom())
    ]
    res = sanitize_rows_for_semantic_inference(rows, cells=cells)
    assert "row_1" in res["excluded_row_ids"]
    assert len(res["item_rows"]) == 0

def test_does_not_exclude_normal_medicine_row():
    rows = [RowRegion(row_id="row_1", row_role="item_row", geometry=_geom())]
    cells = [
        TableCell(row_id="row_1", col_id="col_0", text="LUBIMOIST EYE DROPS", geometry=_geom())
    ]
    res = sanitize_rows_for_semantic_inference(rows, cells=cells)
    assert "row_1" not in res["excluded_row_ids"]
    assert len(res["item_rows"]) == 1

def test_respects_explicit_footer_summary_row():
    rows = [RowRegion(row_id="row_1", row_role="footer_summary_row", geometry=_geom())]
    cells = [
        TableCell(row_id="row_1", col_id="col_0", text="Some value", geometry=_geom())
    ]
    res = sanitize_rows_for_semantic_inference(rows, cells=cells)
    assert "row_1" in res["excluded_row_ids"]

def test_respects_explicit_tax_summary_row():
    rows = [RowRegion(row_id="row_1", row_role="tax_summary_row", geometry=_geom())]
    cells = [
        TableCell(row_id="row_1", col_id="col_0", text="Some value", geometry=_geom())
    ]
    res = sanitize_rows_for_semantic_inference(rows, cells=cells)
    assert "row_1" in res["excluded_row_ids"]
