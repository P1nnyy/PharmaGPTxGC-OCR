import pytest
from scratch.token_splitter_audit import (
    is_suspicious_fused_numeric,
    simulate_proportional_geometry,
    replay_row_math
)

def test_fused_numeric_detection():
    # "22 990.88" is detected as suspicious fused numeric
    is_susp, conf, reasons, parts = is_suspicious_fused_numeric("22 990.88")
    assert is_susp
    assert conf >= 0.8
    assert "22" in parts
    assert "990.88" in parts


def test_ambiguous_numeric_detection():
    # "35 0 12" is detected but lower confidence/ambiguous
    is_susp, conf, reasons, parts = is_suspicious_fused_numeric("35 0 12")
    assert is_susp
    assert conf < 0.8
    assert "whitespace_separated_integers_only" in reasons


def test_product_context_not_flagged():
    # "DONEP 5 TAB" is not flagged in product context
    is_susp, _, _, _ = is_suspicious_fused_numeric("DONEP 5 TAB", column_semantic="PRODUCT")
    assert not is_susp
    # "PAN 40" is not flagged in product context
    is_susp, _, _, _ = is_suspicious_fused_numeric("PAN 40", column_semantic="PRODUCT")
    assert not is_susp


def test_single_decimal_not_flagged():
    # single decimal "990.88" is not flagged
    is_susp, _, _, _ = is_suspicious_fused_numeric("990.88")
    assert not is_susp


def test_empty_and_no_crash():
    # empty text and missing geometry do not crash
    is_susp, _, _, _ = is_suspicious_fused_numeric("")
    assert not is_susp
    is_susp, _, _, _ = is_suspicious_fused_numeric("   ")
    assert not is_susp
    
    # simulate geometry without crash
    sim_boxes, sim_polys = simulate_proportional_geometry("22 990.88", ["22", "990.88"], None, None)
    assert sim_boxes == []
    assert sim_polys == []


def test_no_mutation():
    # audit functions do not mutate input dictionaries/objects
    geom = {"min_x": 10.0, "max_x": 20.0, "min_y": 5.0, "max_y": 15.0}
    poly = [[10.0, 5.0], [20.0, 5.0], [20.0, 15.0], [10.0, 15.0]]
    
    geom_copy = dict(geom)
    poly_copy = [list(pt) for pt in poly]
    
    simulate_proportional_geometry("22 990.88", ["22", "990.88"], geom, poly)
    
    assert geom == geom_copy
    assert poly == poly_copy
