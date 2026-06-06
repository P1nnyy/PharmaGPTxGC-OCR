from unittest.mock import MagicMock, patch
import pytest
from PIL import Image
from services.orientation_recovery import (
    should_attempt_orientation_recovery,
    score_orientation_candidate,
    run_orientation_recovery,
)

def test_should_attempt_orientation_recovery_valid_primary_skipped():
    # A valid primary run shouldn't trigger recovery
    metadata = {
        "selected_table_available": True,
        "fast_fail_reason": None,
        "item_rows_clean": [{"name": "medicine"}],
        "orientation_ambiguous": False,
        "metrics": {
            "selected_table_available": True,
            "table_sanity": {
                "per_candidate": [
                    {
                        "table_id": "table_1",
                        "valid": True,
                        "table_sanity_score": 85.0,
                        "rejection_reasons": [],
                        "item_rows": 5,
                        "all_unknown_columns": False,
                    }
                ]
            },
            "selected_main_table_id": "table_1",
        },
        "quality_gate": {
            "reasons": []
        }
    }
    assert should_attempt_orientation_recovery(metadata) is False

def test_should_attempt_orientation_recovery_no_valid_candidate_triggers():
    # If no valid table candidate was found, it should trigger recovery
    metadata = {
        "selected_table_available": False,
        "fast_fail_reason": "no_valid_table_candidate",
        "item_rows_clean": [],
        "orientation_ambiguous": False,
        "metrics": {
            "selected_table_available": False,
            "no_valid_table_candidate": True,
            "table_sanity": {
                "per_candidate": [
                    {
                        "table_id": "table_1",
                        "valid": False,
                        "table_sanity_score": -10.0,
                        "rejection_reasons": ["zero_item_rows_all_unknown_columns"],
                        "item_rows": 0,
                        "all_unknown_columns": True,
                    }
                ]
            }
        },
        "quality_gate": {
            "reasons": ["no_valid_table_candidate"]
        }
    }
    assert should_attempt_orientation_recovery(metadata) is True

def test_should_attempt_orientation_recovery_ambiguous_triggers():
    # ambiguous orientation triggers recovery
    metadata = {
        "selected_table_available": True,
        "orientation_ambiguous": True,
        "metrics": {},
        "quality_gate": {}
    }
    assert should_attempt_orientation_recovery(metadata) is True

def test_should_attempt_orientation_recovery_coordinate_violation_triggers():
    # coordinate space violation triggers recovery
    # We patch validate_coordinate_space to return a violation
    with patch("services.orientation_recovery.validate_coordinate_space") as mock_val:
        mock_val.return_value = {"has_violation": True}
        metadata = {
            "selected_table_available": True,
            "orientation_ambiguous": False,
            "metrics": {},
            "quality_gate": {}
        }
        assert should_attempt_orientation_recovery(metadata) is True

def test_should_attempt_orientation_recovery_recursion_prevented():
    # If already attempted, it must NOT trigger
    metadata = {
        "orientation_recovery_attempted": True,
        "selected_table_available": False,
        "fast_fail_reason": "no_valid_table_candidate",
    }
    assert should_attempt_orientation_recovery(metadata) is False

def test_score_orientation_candidate_pharma_readability():
    # Construct ocr_result and metadata representing a candidate
    ocr_result = {"text": "dummy", "blocks": [], "metadata": {}}
    metadata = {
        "selected_table_available": True,
        "selected_table_id": "table_1",
        "metrics": {
            "table_sanity": {
                "per_candidate": [
                    {
                        "table_id": "table_1",
                        "valid": True,
                        "table_sanity_score": 40.0,
                        "row_count": 10,
                        "column_count": 8,
                        "item_rows": 6,
                        "pharma_header_hits": 4,
                        "all_unknown_columns": False,
                        "cell_bbox_out_of_bounds_count": 0,
                        "rejection_reasons": []
                    }
                ]
            },
            "final_column_semantics": {
                "table_1": {
                    "col_1": "qty",
                    "col_2": "rate",
                    "col_3": "exp",
                }
            }
        }
    }
    result = score_orientation_candidate(90, metadata, ocr_result)
    assert result["selected_table_available"] is True
    assert result["valid"] is True
    assert result["score"] > 50.0

@patch("services.orientation_recovery.ocr_engine.process_image")
@patch("services.orientation_recovery.spatial_reconstruction.reconstruct_layout")
def test_run_orientation_recovery_selects_best_alternate(mock_reconstruct, mock_process):
    # Setup mock behavior:
    # Let's say original processed angle is 0, which yields a failed table
    original_ocr = {"text": "failed", "blocks": [], "metadata": {"rotation_angle": 0}}
    original_metadata = {
        "selected_table_available": False,
        "fast_fail_reason": "no_valid_table_candidate",
        "processed_image": {"rotation_angle": 0},
        "metrics": {
            "table_sanity": {
                "per_candidate": [
                    {
                        "table_id": "table_1",
                        "valid": False,
                        "table_sanity_score": -10.0,
                        "rejection_reasons": ["zero_item_rows_all_unknown_columns"],
                        "item_rows": 0,
                        "all_unknown_columns": True,
                    }
                ]
            }
        }
    }
    
    # We probe angles 90, 180, 270. Let's make angle 180 succeed!
    def mock_process_side_effect(image, **kwargs):
        return {"text": "dummy", "blocks": [{"text": "xyz"}], "metadata": {"processed_image": {}}}
        
    mock_process.side_effect = mock_process_side_effect
    
    call_idx = 0
    def mock_reconstruct_side_effect(blocks, **kwargs):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 2 or call_idx == 4: # Angle 180 (second probe and final run)
            return {
                "selected_table_available": True,
                "selected_table_id": "table_best",
                "metrics": {
                    "table_sanity": {
                        "per_candidate": [
                            {
                                "table_id": "table_best",
                                "valid": True,
                                "table_sanity_score": 60.0,
                                "row_count": 8,
                                "column_count": 9,
                                "item_rows": 5,
                                "pharma_header_hits": 5,
                                "all_unknown_columns": False,
                                "cell_bbox_out_of_bounds_count": 0,
                                "rejection_reasons": []
                            }
                        ]
                    },
                    "final_column_semantics": {
                        "table_best": {
                            "col_1": "qty",
                            "col_2": "rate",
                        }
                    }
                }
            }
        else: # Angle 90 or 270
            return {
                "selected_table_available": False,
                "metrics": {
                    "table_sanity": {
                        "per_candidate": [
                            {
                                "table_id": "table_failed",
                                "valid": False,
                                "table_sanity_score": -20.0,
                                "rejection_reasons": ["zero_item_rows"],
                                "item_rows": 0,
                            }
                        ]
                    }
                }
            }
            
    mock_reconstruct.side_effect = mock_reconstruct_side_effect
    
    img = Image.new("RGB", (100, 100))
    recovered_ocr, recovered_metadata = run_orientation_recovery(
        original_image=img,
        normal_payload={"ocr_result": original_ocr, "metadata": original_metadata},
        reconstruct_mode="table_transformer",
        benchmark_mode=False,
    )
    
    # Assert recovery selected angle 180
    assert recovered_metadata["chosen_angle"] == 180
    assert recovered_metadata["orientation_recovery_attempted"] is True
    assert recovered_metadata["whether_recovery_improved_the_result"] is True
    assert recovered_metadata["selected_table_available"] is True
    # The processed image metadata should reflect angle 180
    assert recovered_metadata["processed_image"]["rotation_angle"] == 180


@patch("services.orientation_recovery.ocr_engine.process_image")
@patch("services.orientation_recovery.spatial_reconstruction.reconstruct_layout")
def test_run_orientation_recovery_retains_failure_when_all_fail(mock_reconstruct, mock_process):
    # Setup mock behavior where everything fails
    original_ocr = {"text": "failed", "blocks": [], "metadata": {"rotation_angle": 0}}
    original_metadata = {
        "selected_table_available": False,
        "fast_fail_reason": "no_valid_table_candidate",
        "processed_image": {"rotation_angle": 0},
        "metrics": {
            "table_sanity": {
                "per_candidate": [
                    {
                        "table_id": "table_1",
                        "valid": False,
                        "table_sanity_score": -10.0,
                        "rejection_reasons": ["zero_item_rows_all_unknown_columns"],
                        "item_rows": 0,
                    }
                ]
            }
        }
    }
    
    mock_process.return_value = {"text": "dummy", "blocks": [], "metadata": {"processed_image": {}}}
    
    mock_reconstruct.return_value = {
        "selected_table_available": False,
        "metrics": {
            "table_sanity": {
                "per_candidate": [
                    {
                        "table_id": "table_failed",
                        "valid": False,
                        "table_sanity_score": -30.0,
                        "rejection_reasons": ["zero_item_rows"],
                        "item_rows": 0,
                    }
                ]
            }
        }
    }
    
    img = Image.new("RGB", (100, 100))
    recovered_ocr, recovered_metadata = run_orientation_recovery(
        original_image=img,
        normal_payload={"ocr_result": original_ocr, "metadata": original_metadata},
        reconstruct_mode="table_transformer",
        benchmark_mode=False,
    )
    
    assert recovered_metadata["chosen_angle"] == 0
    assert recovered_metadata["orientation_recovery_attempted"] is True
    assert recovered_metadata["whether_recovery_improved_the_result"] is False
    assert recovered_metadata["selected_table_available"] is False
