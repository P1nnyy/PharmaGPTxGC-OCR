import json
from types import SimpleNamespace

from services.table_segmenter import (
    normalize_selected_graph_item_row,
    select_item_rows_clean_source,
    selected_table_to_clean_item_rows,
)


def _geom(x=0, y=0):
    return SimpleNamespace(min_x=x, min_y=y)


def _row(row_id, role="item_row", y=0):
    return SimpleNamespace(row_id=row_id, row_role=role, geometry=_geom(y=y))


def _cell(row_id, col_id, text, x=0):
    return SimpleNamespace(row_id=row_id, col_id=col_id, text=text, geometry=_geom(x=x))


def _table(rows, cells):
    return SimpleNamespace(table_id="graph_fallback_region", rows=rows, cells=cells)


def test_graph_table_rows_map_to_clean_item_rows():
    table = _table(
        [_row("r1")],
        [
            _cell("r1", "c_product", "Paracetamol", x=10),
            _cell("r1", "c_hsn", "300490", x=20),
            _cell("r1", "c_qty", "2", x=30),
            _cell("r1", "c_rate", "10.00", x=40),
            _cell("r1", "c_amount", "20.00", x=50),
        ],
    )
    rows = selected_table_to_clean_item_rows(
        table,
        {
            "c_product": "product",
            "c_hsn": "hsn",
            "c_qty": "quantity",
            "c_rate": "rate",
            "c_amount": "amount",
        },
    )

    assert rows == [
        {
            "pcode": "",
            "item_description": "Paracetamol",
            "hsn": "300490",
            "batch": "",
            "expiry": "",
            "mrp": "",
            "qty": "2",
            "rate": "10.00",
            "discount": "",
            "gst": "",
            "net_amt": "20.00",
            "low_confidence": True,
            "confidence_reasons": ["missing_pcode"],
            "visual_row_id": "r1",
            "source": "selected_graph_table",
        }
    ]


def test_graph_table_missing_fields_sets_low_confidence():
    table = _table(
        [_row("r1")],
        [_cell("r1", "c_product", "Paracetamol", x=10)],
    )
    rows = selected_table_to_clean_item_rows(table, {"c_product": "product"})

    assert rows[0]["low_confidence"] is True
    assert "missing_hsn" in rows[0]["confidence_reasons"]
    assert "missing_qty" in rows[0]["confidence_reasons"]
    assert "missing_rate" in rows[0]["confidence_reasons"]
    assert "missing_net_amt" in rows[0]["confidence_reasons"]


def test_normalize_selected_graph_item_row_strips_manufacturer_from_qty():
    row = normalize_selected_graph_item_row({
        "item_description": "RANIDOM-MPS SUSP",
        "batch": "",
        "expiry": "",
        "hsn": "30049099",
        "qty": "2.500+.500 MANKIN",
    })

    assert row["qty"] == "2.500+.500"


def test_normalize_selected_graph_item_row_splits_expiry_and_hsn():
    row = normalize_selected_graph_item_row({
        "item_description": "LUBIMOIST EYE DROPS",
        "batch": "",
        "expiry": "",
        "hsn": "10/25 30049099",
        "qty": "1",
    })

    assert row["expiry"] == "10/25"
    assert row["hsn"] == "30049099"


def test_normalize_selected_graph_item_row_moves_batch_prefix_from_description():
    row = normalize_selected_graph_item_row({
        "item_description": "B4MVY018 MANKIN MAHAFLOX-LP EYE DROPS",
        "batch": "",
        "expiry": "",
        "hsn": "30049099",
        "qty": "1",
    })

    assert row["batch"] == "B4MVY018"
    assert row["item_description"] == "MANKIN MAHAFLOX-LP EYE DROPS"


def test_normalize_selected_graph_item_row_removes_serial_prefix_without_serial_field():
    row = normalize_selected_graph_item_row({
        "item_description": "8 TROIKA DYNAPAR QPS PLUS 30 ML",
        "batch": "",
        "expiry": "",
        "hsn": "30049099",
        "qty": "1",
    })

    assert "serial" not in row
    assert row["item_description"] == "TROIKA DYNAPAR QPS PLUS 30 ML"


def test_normalize_selected_graph_item_row_moves_serial_prefix_when_serial_field_exists():
    row = normalize_selected_graph_item_row({
        "serial": "",
        "item_description": "9 NUROKIND LC TAB",
        "batch": "",
        "expiry": "",
        "hsn": "30049099",
        "qty": "1",
    })

    assert row["serial"] == "9"
    assert row["item_description"] == "NUROKIND LC TAB"


def test_guard_chooses_graph_when_graph_rows_are_better():
    raw_rows = [
        {
            "item_description": "Mixed raw row",
            "hsn": "",
            "qty": "",
            "rate": "",
            "net_amt": "",
            "source": "raw_ocr_coordinate_reconstruction",
            "confidence_reasons": ["missing_hsn", "missing_qty", "missing_rate", "missing_net_amt"],
        }
    ]
    graph_rows = [
        {
            "item_description": "Clean graph row",
            "hsn": "300490",
            "qty": "1",
            "rate": "10.00",
            "net_amt": "10.00",
            "source": "selected_graph_table",
            "confidence_reasons": [],
        }
    ]

    chosen, diagnostics = select_item_rows_clean_source(
        raw_rows,
        graph_rows,
        selected_topology_source="document_graph_candidate",
        selected_main_table=object(),
    )

    assert chosen == graph_rows
    assert diagnostics["graph_bridge_used"] is True
    assert diagnostics["chosen_source"] == "selected_graph_table"
    assert diagnostics["raw_missing_critical_fields"] == 4
    assert diagnostics["graph_missing_critical_fields"] == 0


def test_guard_keeps_raw_when_graph_rows_are_worse():
    raw_rows = [
        {
            "item_description": "Raw row",
            "hsn": "300490",
            "qty": "1",
            "rate": "10.00",
            "net_amt": "10.00",
            "source": "raw_ocr_coordinate_reconstruction",
            "confidence_reasons": [],
        }
    ]
    graph_rows = [
        {
            "item_description": "Graph row",
            "hsn": "",
            "qty": "",
            "rate": "",
            "net_amt": "",
            "source": "selected_graph_table",
            "confidence_reasons": ["missing_hsn", "missing_qty", "missing_rate", "missing_net_amt"],
        }
    ]

    chosen, diagnostics = select_item_rows_clean_source(
        raw_rows,
        graph_rows,
        selected_topology_source="document_graph_candidate",
        selected_main_table=object(),
    )

    assert chosen == raw_rows
    assert diagnostics["graph_bridge_used"] is False
    assert diagnostics["chosen_source"] == "raw_ocr_coordinate_reconstruction"
    assert "graph_missing_critical_not_better" in diagnostics["reasons"]


def test_guard_chooses_graph_when_distinct_missing_field_types_are_better():
    raw_rows = [
        {
            "item_description": "Raw row 1",
            "hsn": "",
            "qty": "",
            "rate": "",
            "net_amt": "10.00",
            "source": "raw_ocr_coordinate_reconstruction",
            "confidence_reasons": ["missing_hsn", "missing_qty", "missing_rate"],
        },
        {
            "item_description": "Raw row 2",
            "hsn": "",
            "qty": "",
            "rate": "",
            "net_amt": "20.00",
            "source": "raw_ocr_coordinate_reconstruction",
            "confidence_reasons": ["missing_hsn", "missing_qty", "missing_rate"],
        },
    ]
    graph_rows = [
        {
            "item_description": f"Graph row {idx}",
            "hsn": "300490",
            "qty": "" if idx < 6 else "1",
            "rate": "10.00",
            "net_amt": "10.00",
            "source": "selected_graph_table",
            "confidence_reasons": ["missing_qty"] if idx < 6 else [],
        }
        for idx in range(9)
    ]

    chosen, diagnostics = select_item_rows_clean_source(
        raw_rows,
        graph_rows,
        selected_topology_source="document_graph_candidate",
        selected_main_table=object(),
    )

    assert chosen == graph_rows
    assert diagnostics["graph_bridge_used"] is True
    assert diagnostics["raw_missing_critical_fields"] == 6
    assert diagnostics["graph_missing_critical_fields"] == 6
    assert diagnostics["raw_missing_critical_field_types"] == ["hsn", "qty", "rate"]
    assert diagnostics["graph_missing_critical_field_types"] == ["qty"]
    assert "graph_distinct_critical_fields_better" in diagnostics["reasons"]


def test_source_selection_output_is_json_serializable():
    chosen, diagnostics = select_item_rows_clean_source(
        [],
        [
            {
                "item_description": "Graph row",
                "hsn": "300490",
                "qty": "1",
                "rate": "10.00",
                "net_amt": "10.00",
                "source": "selected_graph_table",
                "confidence_reasons": [],
            }
        ],
        selected_topology_source="document_graph_candidate",
        selected_main_table=object(),
    )

    json.dumps({"chosen": chosen, "diagnostics": diagnostics})
