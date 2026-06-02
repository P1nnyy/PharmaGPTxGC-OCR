from services.layout_pipeline.canonical_invoice import build_canonical_invoice
from services.layout_pipeline.footer_rescue import (
    diagnose_footer_rescue,
    extract_geometry_text_units,
    group_footer_lines,
    parse_footer_label_value_lines,
    select_bottom_region,
)


def block(text, x1, y1, x2, y2, confidence=0.96):
    return {
        "text": text,
        "polygon": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        "confidence": confidence,
    }


def candidates_from_blocks(blocks):
    units = extract_geometry_text_units({"blocks": blocks})
    bottom = select_bottom_region(units)
    lines = group_footer_lines(bottom)
    return parse_footer_label_value_lines(lines)


def missing_footer_invoice():
    return build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 100, "amount": 100}],
        "totals": {"discount": 0},
        "invoice_confidence": 0.8,
    })


def test_bottom_grand_total_line_maps_to_grand_total():
    candidates = candidates_from_blocks([
        block("Grand Total", 60, 900, 190, 920),
        block("2,291.00", 710, 900, 790, 920),
    ])

    assert candidates["grand_total"][0]["value"] == 2291.0
    assert candidates["grand_total"][0]["confidence"] >= 0.70


def test_sub_total_line_maps_to_subtotal():
    candidates = candidates_from_blocks([
        block("Sub Total", 60, 870, 170, 890),
        block("2,320.90", 710, 870, 790, 890),
    ])

    assert candidates["subtotal"][0]["value"] == 2320.9


def test_cgst_and_sgst_lines_map_to_tax_fields():
    candidates = candidates_from_blocks([
        block("CGST", 60, 850, 130, 870),
        block("54.55", 720, 850, 790, 870),
        block("SGST", 60, 880, 130, 900),
        block("54.55", 720, 880, 790, 900),
    ])

    assert candidates["cgst"][0]["value"] == 54.55
    assert candidates["sgst"][0]["value"] == 54.55


def test_total_alone_ambiguous_is_not_selected_or_applied():
    canonical = missing_footer_invoice()

    report = diagnose_footer_rescue(
        canonical,
        {"blocks": [
            block("Total", 60, 840, 130, 860),
            block("100.00", 720, 840, 790, 860),
            block("Total", 60, 900, 130, 920),
            block("118.00", 720, 900, 790, 920),
        ]},
    )

    assert "footer_rescue_conflicting_candidates:grand_total" in report["warnings"]
    assert "grand_total" not in report["selected_candidates"]
    assert canonical.get_footer_value("grand_total") is None


def test_percentages_are_not_parsed_as_amounts():
    candidates = candidates_from_blocks([
        block("SGST", 60, 880, 120, 900),
        block("6%", 720, 880, 790, 900),
    ])

    assert "sgst" not in candidates


def test_geometry_missing_falls_back_to_text_only_lines():
    canonical = missing_footer_invoice()

    report = diagnose_footer_rescue(canonical, {"semantic_markdown": "Grand Total : 118.00"})

    assert report["selected_candidates"]["grand_total"]["value"] == 118.0
    assert report["selected_candidates"]["grand_total"]["geometry_used"] is False


def test_high_confidence_missing_field_is_applied_from_geometry():
    canonical = build_canonical_invoice({
        "item_rows_clean": [{"product": "ABC", "qty": 1, "rate": 100, "amount": 100}],
        "totals": {"discount": 0, "sgst": 0, "cgst": 0, "grand_total": 2320.90},
        "invoice_confidence": 0.8,
    })

    report = diagnose_footer_rescue(
        canonical,
        {"blocks": [
            block("Sub Total", 60, 900, 170, 920),
            block("2,320.90", 710, 900, 790, 920),
        ]},
    )

    assert report["applied_fields"][0]["label"] == "subtotal"
    assert report["applied_fields"][0]["source_path"] == "footer_rescue.geometry"
    assert canonical.get_footer_value("subtotal") == 2320.9


def test_roundoff_and_rightmost_amount_preference():
    candidates = candidates_from_blocks([
        block("Round Off 0.10", 60, 900, 230, 920),
        block("0.00", 720, 900, 790, 920),
    ])

    assert candidates["roundoff"][0]["value"] == 0.0


def test_grand_total_without_comma_parses_whole_amount():
    candidates = candidates_from_blocks([
        block("Grand Total", 60, 900, 190, 920),
        block("2291.00", 710, 900, 790, 920),
    ])

    assert candidates["grand_total"][0]["value"] == 2291.0


def test_bank_account_line_does_not_create_grand_total_amount():
    candidates = candidates_from_blocks([
        block("Terms A/c No.: 50200066236285 Bank Details Grand Total", 60, 900, 640, 920),
    ])

    assert "grand_total" not in candidates
