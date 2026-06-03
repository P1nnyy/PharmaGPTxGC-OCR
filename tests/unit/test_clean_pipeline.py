import os
import pytest
from services.spatial_reconstruction import reconstruct_layout

def test_reconstruct_layout_runs_clean_pipeline_with_no_mutations():
    # 1. Ensure any stale vendor priors files are cleared before run
    priors_path = "forensic_runs/vendor_priors.json"
    if os.path.exists(priors_path):
        try:
            os.remove(priors_path)
        except Exception:
            pass

    # 2. Mock a basic structured sequence of OCR blocks representing a standard medicine invoice
    mock_blocks = [
        # Headers
        {"id": "b_h_product", "text": "Product Name", "polygon": [[10, 10], [100, 10], [100, 20], [10, 20]], "confidence": 0.95},
        {"id": "b_h_qty", "text": "Qty", "polygon": [[200, 10], [240, 10], [240, 20], [200, 20]], "confidence": 0.95},
        {"id": "b_h_rate", "text": "Rate", "polygon": [[300, 10], [350, 10], [350, 20], [300, 20]], "confidence": 0.95},
        {"id": "b_h_amount", "text": "Amount", "polygon": [[400, 10], [460, 10], [460, 20], [400, 20]], "confidence": 0.95},

        # Row 1 (Medicine product A)
        {"id": "b_r1_prod", "text": "PARACETAMOL 650", "polygon": [[10, 30], [100, 30], [100, 40], [10, 40]], "confidence": 0.95},
        {"id": "b_r1_qty", "text": "2", "polygon": [[200, 30], [240, 30], [240, 40], [200, 40]], "confidence": 0.95},
        {"id": "b_r1_rate", "text": "15.00", "polygon": [[300, 30], [350, 30], [350, 40], [300, 40]], "confidence": 0.95},
        {"id": "b_r1_amount", "text": "30.00", "polygon": [[400, 30], [460, 30], [460, 40], [400, 40]], "confidence": 0.95},

        # Footer Subtotal and Grand Total
        {"id": "b_f_sub", "text": "SUBTOTAL", "polygon": [[10, 60], [80, 60], [80, 70], [10, 70]], "confidence": 0.95},
        {"id": "b_f_sub_val", "text": "30.00", "polygon": [[400, 60], [460, 60], [460, 70], [400, 70]], "confidence": 0.95},
        {"id": "b_f_gt", "text": "GRAND TOTAL", "polygon": [[10, 80], [100, 80], [100, 90], [10, 90]], "confidence": 0.95},
        {"id": "b_f_gt_val", "text": "30.00", "polygon": [[400, 80], [460, 80], [460, 90], [400, 90]], "confidence": 0.95},
    ]

    # 3. Call reconstruct_layout
    result = reconstruct_layout(mock_blocks, debug=False, reconstruct_mode="heuristic")

    # 4. Assert core pipeline returns the expected structured tables and schema fields
    assert "structured_tables" in result
    assert "item_rows_clean" in result
    assert "metadata" in result
    assert "metrics" in result

    metrics = result["metrics"]
    metadata = result["metadata"]

    # Verify token coverage diagnostics are computed and present
    assert "token_coverage" in metrics
    assert "token_coverage_debug" in metrics

    # Verify row validation results exist
    assert "row_validation" in metrics

    # Verify financial reconciliation metrics are included
    assert "financial_reconciliation" in metrics
    assert "invoice_financial_reconciliation" in metrics

    # 5. Assert all experimental mutation/repair pipelines are disabled/stubbed
    # Assert no document graph selection or promotion
    assert metadata["selected_topology_source"] == "heuristic_anchor"
    assert metadata["topology_source"] == "heuristic_anchor"
    assert result["topology_source"] == "heuristic_anchor"
    assert result["selected_topology_source"] == "heuristic_anchor"

    # Assert emergency document graph fallback was not used
    assert metrics["graph_fallback_used"] is False
    assert metrics["graph_rejection_reason"] == "reconstruction_confidence_high"

    # Assert column band rescue was not selected
    assert metrics.get("column_band_rescue_selected") is False

    # Assert product phase shift did not perform any changes
    assert metrics.get("product_phase_shift_repair_count", 0) == 0

    # Assert anchor repair was not active
    assert metrics.get("anchor_repair", {}).get("enabled") is False

    # 6. Assert no vendor priors file was written to disk
    assert not os.path.exists(priors_path)
