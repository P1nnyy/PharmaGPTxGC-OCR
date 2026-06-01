import json

from services.table_segmenter import (
    infer_missing_quantities_for_item_rows,
    infer_missing_qty_from_rate_amount,
)


def _graph_row(**overrides):
    row = {
        "visual_row_id": "graph_row_1",
        "item_description": "LUBIMOIST EYE DROPS",
        "qty": "",
        "rate": "10.00",
        "net_amt": "10.00",
        "source": "selected_graph_table",
        "confidence_reasons": ["missing_qty"],
        "low_confidence": True,
    }
    row.update(overrides)
    return row


def test_blank_qty_amount_equals_rate_infers_one():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(rate="250.64", net_amt="250.64"))

    assert row["qty"] == "1"
    assert "missing_qty" not in row["confidence_reasons"]
    assert "qty_inferred_from_amount_rate" in row["confidence_reasons"]
    assert diagnostic["used"] is True
    assert diagnostic["inferred_qty"] == "1"


def test_blank_qty_amount_rate_ratio_two_infers_two():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(rate="95.76", net_amt="191.52"))

    assert row["qty"] == "2"
    assert diagnostic["implied_qty"] == 2.0


def test_blank_qty_amount_rate_ratio_two_point_five_infers_two_point_five():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(rate="94.19", net_amt="235.48"))

    assert row["qty"] == "2.5"
    assert diagnostic["inferred_qty"] == "2.5"


def test_blank_qty_amount_rate_ratio_two_point_seven_five_infers_two_point_seven_five():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(rate="182.03", net_amt="500.58"))

    assert row["qty"] == "2.75"
    assert diagnostic["inferred_qty"] == "2.75"


def test_nonblank_qty_is_not_overwritten():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(qty="3", rate="10.00", net_amt="20.00"))

    assert row["qty"] == "3"
    assert diagnostic["used"] is False
    assert diagnostic["reason"] == "qty_already_present"


def test_unparseable_rate_or_amount_is_skipped():
    rate_row, rate_diagnostic = infer_missing_qty_from_rate_amount(_graph_row(rate="ABC", net_amt="20.00"))
    amount_row, amount_diagnostic = infer_missing_qty_from_rate_amount(_graph_row(rate="10.00", net_amt="ABC"))

    assert rate_row["qty"] == ""
    assert rate_diagnostic["reason"] == "unparseable_rate"
    assert amount_row["qty"] == ""
    assert amount_diagnostic["reason"] == "unparseable_amount"


def test_empty_description_is_skipped():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(item_description=""))

    assert row["qty"] == ""
    assert diagnostic["used"] is False
    assert diagnostic["reason"] == "empty_description"


def test_batch_only_row_with_batch_rate_amount_infers_qty_without_inventing_description():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(
        item_description="B95Y104-",
        batch="B95Y104",
        rate="182.03",
        net_amt="500.58",
    ))

    assert row["qty"] == "2.75"
    assert row["item_description"] == "B95Y104-"
    assert row["low_confidence"] is True
    assert "qty_inferred_from_amount_rate_batch_only" in row["confidence_reasons"]
    assert diagnostic["used"] is True
    assert diagnostic["reason"] == "batch_only_qty_inferred_from_amount_rate"
    assert diagnostic["batch"] == "B95Y104"


def test_batch_only_row_without_batch_is_skipped():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(
        item_description="B95Y104-",
        batch="",
        rate="182.03",
        net_amt="500.58",
    ))

    assert row["qty"] == ""
    assert diagnostic["used"] is False
    assert diagnostic["reason"] == "batch_only_missing_batch"


def test_batch_only_row_with_bad_ratio_is_skipped():
    row, diagnostic = infer_missing_qty_from_rate_amount(_graph_row(
        item_description="B95Y104-",
        batch="B95Y104",
        rate="182.03",
        net_amt="460.00",
    ))

    assert row["qty"] == ""
    assert diagnostic["used"] is False
    assert diagnostic["reason"] == "implied_qty_not_safe"


def test_batch_only_summary_reports_batch_only_reason():
    rows, summary = infer_missing_quantities_for_item_rows([
        _graph_row(
            visual_row_id="graph_row_25",
            item_description="B95Y104-",
            batch="B95Y104",
            rate="182.03",
            net_amt="500.58",
        )
    ])

    assert rows[0]["qty"] == "2.75"
    assert summary["attempted"] == 1
    assert summary["inferred_count"] == 1
    assert summary["rows"][0]["reason"] == "batch_only_qty_inferred_from_amount_rate"


def test_inference_summary_is_json_serializable():
    rows, summary = infer_missing_quantities_for_item_rows([
        _graph_row(visual_row_id="graph_row_17", rate="250.64", net_amt="250.64"),
        _graph_row(visual_row_id="graph_row_18", rate="ABC", net_amt="159.89"),
    ])

    assert rows[0]["qty"] == "1"
    assert rows[1]["qty"] == ""
    assert summary["attempted"] == 2
    assert summary["inferred_count"] == 1
    assert summary["skipped_count"] == 1
    json.dumps({"rows": rows, "summary": summary})
