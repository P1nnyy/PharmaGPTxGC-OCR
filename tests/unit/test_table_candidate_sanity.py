from models.layout_models import ColumnRegion, GeometryBox, RowRegion, TableCell, TableRegion
from services.table_candidate_sanity import (
    evaluate_table_candidate_sanity,
    select_valid_table_candidate,
)


def _geom(x1, y1, x2, y2):
    return GeometryBox(
        min_x=x1,
        min_y=y1,
        max_x=x2,
        max_y=y2,
        center_x=(x1 + x2) / 2,
        center_y=(y1 + y2) / 2,
    )


def _table(
    table_id="table_1",
    rows=4,
    cols=5,
    bbox=(10, 10, 500, 300),
    item_rows=2,
    required_present=None,
    required_missing=None,
    cell_overrides=None,
):
    row_regions = [
        RowRegion(
            row_id=f"row_{idx}",
            geometry=_geom(bbox[0], bbox[1] + idx * 20, bbox[2], bbox[1] + idx * 20 + 15),
            row_role="item_row" if idx < item_rows else "unknown_row",
        )
        for idx in range(rows)
    ]
    col_width = (bbox[2] - bbox[0]) / max(1, cols)
    col_regions = [
        ColumnRegion(
            col_id=f"col_{idx}",
            geometry=_geom(bbox[0] + idx * col_width, bbox[1], bbox[0] + (idx + 1) * col_width, bbox[3]),
        )
        for idx in range(cols)
    ]
    cells = []
    for r_idx in range(rows):
        for c_idx in range(cols):
            cell_bbox = _geom(
                bbox[0] + c_idx * col_width,
                bbox[1] + r_idx * 20,
                bbox[0] + (c_idx + 1) * col_width,
                bbox[1] + r_idx * 20 + 15,
            )
            text = "Product HSN Batch Qty Rate Exp MRP GST Amount" if r_idx == 0 else f"ITEM{r_idx} 300490 B{r_idx} 1 10.00 12/26 12.00 5 10.00"
            cells.append(TableCell(row_id=f"row_{r_idx}", col_id=f"col_{c_idx}", geometry=cell_bbox, text=text))
    for index, override in (cell_overrides or {}).items():
        cells[index].geometry = _geom(*override)
    return TableRegion(
        table_id=table_id,
        geometry=_geom(*bbox),
        rows=row_regions,
        columns=col_regions,
        cells=cells,
        required_fields_present=required_present if required_present is not None else ["product", "quantity", "rate", "amount"],
        required_fields_missing=required_missing if required_missing is not None else [],
        representability_score=0.8,
    )


def test_table_candidate_with_negative_y_bbox_is_rejected():
    table = _table(bbox=(50, -249, 500, 300))

    result = evaluate_table_candidate_sanity(table, processed_width=899, processed_height=1599)

    assert result["valid"] is False
    assert "table_bbox_out_of_bounds" in result["rejection_reasons"]
    assert "coordinate_space_violation" in result["rejection_reasons"]


def test_table_candidate_with_cell_outside_processed_bounds_is_rejected():
    table = _table(cell_overrides={0: (10, 10, 950, 40)})

    result = evaluate_table_candidate_sanity(table, processed_width=899, processed_height=1599)

    assert result["valid"] is False
    assert "cell_bbox_out_of_bounds" in result["rejection_reasons"]


def test_zero_item_rows_all_unknown_columns_cannot_be_main_table():
    table = _table(item_rows=0, required_present=[], required_missing=["product", "quantity", "rate", "amount"])

    result = evaluate_table_candidate_sanity(table, processed_width=899, processed_height=1599)

    assert result["valid"] is False
    assert "zero_item_rows_all_unknown_columns" in result["rejection_reasons"]


def test_candidate_resolver_returns_no_valid_candidate_when_all_invalid():
    invalid = _table(table_id="bad", bbox=(564, -249, 755, 872), item_rows=0, required_present=[])

    result = select_valid_table_candidate(
        [("heuristic_anchor", invalid, -108.039, {"missing_req_cols": ["product", "quantity", "rate", "amount"]})],
        processed_width=899,
        processed_height=1599,
        ocr_block_count=40,
    )

    assert result["selected_table_available"] is False
    assert result["selected_candidate_id"] is None
    assert result["selected_reason"] == "no_valid_candidate"
    assert result["rejected_candidates"][0]["table_id"] == "bad"


def test_valid_candidate_inside_bounds_with_item_rows_can_be_selected():
    valid = _table(table_id="good", item_rows=3)

    result = select_valid_table_candidate(
        [("heuristic_anchor", valid, 84.0, {"missing_req_cols": []})],
        processed_width=899,
        processed_height=1599,
        ocr_block_count=40,
    )

    assert result["selected_table_available"] is True
    assert result["selected_candidate_id"] == "good"


def test_abka_like_valid_13_column_candidate_is_not_rejected():
    table = _table(table_id="abka_like", rows=3, cols=13, bbox=(20, 120, 1480, 460), item_rows=2)

    result = evaluate_table_candidate_sanity(table, processed_width=1599, processed_height=899)

    assert result["valid"] is True
    assert result["column_count"] == 13
    assert result["rejection_reasons"] == []
