import json
from types import SimpleNamespace

from services.table_segmenter import build_item_row_alignment_diagnostics


def _geom(x=0, y=0):
    return SimpleNamespace(min_x=x, min_y=y)


def _row(row_id, role="item_row", y=0):
    return SimpleNamespace(row_id=row_id, row_role=role, geometry=_geom(y=y))


def _cell(row_id, col_id, text, x=0):
    return SimpleNamespace(row_id=row_id, col_id=col_id, text=text, geometry=_geom(x=x))


def _table(cells):
    return SimpleNamespace(
        table_id="graph_fallback_region",
        rows=[_row("r1")],
        cells=cells,
    )


def _diagnose(cells, clean_row=None, semantics=None):
    clean_row = clean_row or {
        "visual_row_id": "r1",
        "item_description": "LUBIMOIST EYE DROPS",
        "qty": "1",
        "rate": "250.64",
        "net_amt": "250.64",
        "hsn": "30049099",
    }
    semantics = semantics or {
        "c_product": "product",
        "c_qty": "quantity",
        "c_rate": "rate",
        "c_amount": "amount",
        "c_hsn": "hsn",
    }
    return build_item_row_alignment_diagnostics(
        selected_topology_source="document_graph_candidate",
        selected_main_table=_table(cells),
        item_rows_clean=[clean_row],
        column_semantics=semantics,
    )


def test_qty_with_alpha_text_flags_issue():
    diagnostics = _diagnose(
        [
            _cell("r1", "c_product", "RANIDOM-MPS SUSP", x=1),
            _cell("r1", "c_qty", "2.500+.500 MANKIN", x=2),
            _cell("r1", "c_rate", "71.34", x=3),
            _cell("r1", "c_amount", "196.19", x=4),
        ],
        clean_row={
            "visual_row_id": "r1",
            "item_description": "RANIDOM-MPS SUSP",
            "qty": "2.500+.500 MANKIN",
            "rate": "71.34",
            "net_amt": "196.19",
            "hsn": "30049099",
        },
    )

    row = diagnostics["rows"][0]
    assert row["suspected_merged_row"] is True
    assert "qty_contains_alpha_text" in row["issues"]


def test_description_with_batch_token_flags_issue():
    diagnostics = _diagnose(
        [_cell("r1", "c_product", "B4MVY018 MANKIN MAHAFLOX-LP EYE DROPS", x=1)],
        clean_row={
            "visual_row_id": "r1",
            "item_description": "B4MVY018 MANKIN MAHAFLOX-LP EYE DROPS",
            "qty": "",
            "rate": "250.64",
            "net_amt": "250.64",
            "hsn": "30049099",
        },
    )

    row = diagnostics["rows"][0]
    assert row["suspected_merged_row"] is True
    assert "batch_like_token_inside_item_description" in row["issues"]


def test_expiry_and_hsn_combined_flags_issue():
    diagnostics = _diagnose(
        [
            _cell("r1", "c_product", "LUBIMOIST EYE DROPS", x=1),
            _cell("r1", "c_hsn", "10/25 30049099", x=2),
        ],
        clean_row={
            "visual_row_id": "r1",
            "item_description": "LUBIMOIST EYE DROPS",
            "qty": "1",
            "rate": "250.64",
            "net_amt": "250.64",
            "hsn": "10/25 30049099",
        },
    )

    row = diagnostics["rows"][0]
    assert row["suspected_merged_row"] is True
    assert "expiry_and_hsn_combined" in row["issues"]
    assert row["expiry_hsn_tokens"] == ["10/25", "30049099"]


def test_multiple_product_tokens_flags_merged_row_suspicion():
    diagnostics = _diagnose(
        [
            _cell("r1", "c_product_a", "MANKIN LUBIMOIST EYE DROPS", x=1),
            _cell("r1", "c_product_b", "MAHAFLOX-LP EYE DROPS", x=2),
            _cell("r1", "c_amount", "250.64", x=3),
        ],
        semantics={
            "c_product_a": "product",
            "c_product_b": "product",
            "c_amount": "amount",
        },
        clean_row={
            "visual_row_id": "r1",
            "item_description": "MANKIN LUBIMOIST EYE DROPS MAHAFLOX-LP EYE DROPS",
            "qty": "",
            "rate": "",
            "net_amt": "250.64",
            "hsn": "",
        },
    )

    row = diagnostics["rows"][0]
    assert diagnostics["merged_row_suspicions"] == 1
    assert row["product_token_count"] == 2
    assert row["suspected_merged_row"] is True
    assert row["suspected_shifted_amount"] is True
    assert "multiple_product_semantic_cells" in row["issues"]


def test_alignment_diagnostics_output_is_json_serializable():
    diagnostics = _diagnose(
        [
            _cell("r1", "c_product", "LUBIMOIST EYE DROPS", x=1),
            _cell("r1", "c_qty", "2", x=2),
            _cell("r1", "c_rate", "125.32", x=3),
            _cell("r1", "c_amount", "250.64", x=4),
        ]
    )

    assert diagnostics["item_row_count"] == 1
    assert diagnostics["rows"][0]["math_check"] == "pass"
    json.dumps(diagnostics)


def test_alignment_diagnostics_keeps_raw_qty_blank_when_qty_is_inferred():
    diagnostics = _diagnose(
        [
            _cell("r1", "c_product", "LUBIMOIST EYE DROPS", x=1),
            _cell("r1", "c_rate", "250.64", x=3),
            _cell("r1", "c_amount", "250.64", x=4),
        ],
        clean_row={
            "visual_row_id": "r1",
            "item_description": "LUBIMOIST EYE DROPS",
            "qty": "1",
            "rate": "250.64",
            "net_amt": "250.64",
            "hsn": "30049099",
        },
    )

    row = diagnostics["rows"][0]
    assert "qty" not in row["raw_field_values"]
    assert row["normalized_field_values"]["qty"] == "1"
