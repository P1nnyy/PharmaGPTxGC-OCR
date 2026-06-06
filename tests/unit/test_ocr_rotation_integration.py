from types import SimpleNamespace

from PIL import Image

from services.diagnostics_writer import validate_coordinate_space
from services.ocr_engine import (
    _apply_rotation_if_confident,
    _finalize_rotation_metadata,
    _legacy_rotation_contradicted_by_detector,
)


def _rotation_result(angle=0, confidence=0.0, should_rotate=False):
    return SimpleNamespace(
        detected_rotation=angle,
        confidence=confidence,
        should_rotate=should_rotate,
        to_dict=lambda: {
            "detected_rotation": angle,
            "confidence": confidence,
            "should_rotate": should_rotate,
            "scores": {0: 0.1, 90: confidence, 180: 0.2, 270: 0.3},
        },
    )


def test_high_confidence_rotation_is_applied():
    image = Image.new("RGB", (120, 80), "white")

    rotated, metadata = _apply_rotation_if_confident(
        image,
        _rotation_result(angle=90, confidence=0.9, should_rotate=True),
    )

    assert rotated.size == (80, 120)
    assert metadata["rotation_applied"] is True
    assert metadata["rotation_angle"] == 90
    assert metadata["rotation_detection"]["detected_rotation"] == 90


def test_low_confidence_rotation_is_not_applied():
    image = Image.new("RGB", (120, 80), "white")

    rotated, metadata = _apply_rotation_if_confident(
        image,
        _rotation_result(angle=90, confidence=0.7, should_rotate=True),
    )

    assert rotated.size == image.size
    assert rotated is not image
    assert metadata["rotation_applied"] is False
    assert metadata["rotation_angle"] == 0


def test_zero_degree_rotation_is_not_applied():
    image = Image.new("RGB", (120, 80), "white")

    rotated, metadata = _apply_rotation_if_confident(
        image,
        _rotation_result(angle=0, confidence=0.95, should_rotate=True),
    )

    assert rotated.size == image.size
    assert metadata["rotation_applied"] is False
    assert metadata["rotation_angle"] == 0


def test_uncertain_rotation_is_not_applied():
    image = Image.new("RGB", (120, 80), "white")

    rotated, metadata = _apply_rotation_if_confident(
        image,
        _rotation_result(angle=270, confidence=0.95, should_rotate=False),
    )

    assert rotated.size == image.size
    assert metadata["rotation_applied"] is False
    assert metadata["rotation_angle"] == 0


def test_processed_orientation_no_rotation_keeps_sizes_matching():
    image = Image.new("RGB", (899, 1599), "white")

    metadata = _finalize_rotation_metadata(
        original_size=image.size,
        processed_image=image,
        rotation_metadata={"rotation_detection": {"confidence": 0.4}, "rotation_applied": False, "rotation_angle": 0},
    )

    processed = metadata["processed_image"]
    assert processed["original_width"] == 899
    assert processed["original_height"] == 1599
    assert processed["processed_width"] == 899
    assert processed["processed_height"] == 1599
    assert processed["rotation_applied"] is False
    assert processed["rotation_angle"] == 0


def test_processed_orientation_90_rotation_reports_swapped_size():
    original = Image.new("RGB", (899, 1599), "white")
    processed = Image.new("RGB", (1599, 899), "white")

    metadata = _finalize_rotation_metadata(
        original_size=original.size,
        processed_image=processed,
        rotation_metadata={"rotation_detection": {"confidence": 0.91}, "rotation_applied": True, "rotation_angle": 90},
    )

    report = metadata["processed_image"]
    assert report["processed_width"] == 1599
    assert report["processed_height"] == 899
    assert report["rotation_applied"] is True
    assert report["rotation_angle"] == 90


def test_processed_orientation_270_rotation_reports_swapped_size():
    original = Image.new("RGB", (899, 1599), "white")
    processed = Image.new("RGB", (1599, 899), "white")

    metadata = _finalize_rotation_metadata(
        original_size=original.size,
        processed_image=processed,
        rotation_metadata={"rotation_detection": {"confidence": 0.93}, "rotation_applied": True, "rotation_angle": 270},
    )

    report = metadata["processed_image"]
    assert report["processed_width"] == 1599
    assert report["processed_height"] == 899
    assert report["rotation_applied"] is True
    assert report["rotation_angle"] == 270


def test_legacy_rotation_cannot_leave_swapped_size_marked_unrotated():
    original = Image.new("RGB", (899, 1599), "white")
    processed = Image.new("RGB", (1599, 899), "white")

    metadata = _finalize_rotation_metadata(
        original_size=original.size,
        processed_image=processed,
        rotation_metadata={"rotation_detection": {"confidence": 0.39}, "rotation_applied": False, "rotation_angle": 0},
        legacy_rotation_angle=90,
        legacy_rotation_confidence=0.82,
    )

    report = metadata["processed_image"]
    assert report["rotation_applied"] is True
    assert report["rotation_angle"] == 90
    assert "legacy_rotation_applied" not in metadata
    assert "legacy_rotation_angle" not in metadata


def test_legacy_rotation_is_rejected_when_projection_scores_contradict_it():
    rotation_metadata = {
        "rotation_detection": {
            "detected_rotation": 0,
            "confidence": 0.755,
            "should_rotate": False,
            "scores": {"0": 0.755, "90": 0.1408, "180": 0.7547, "270": 0.141},
        },
        "rotation_applied": False,
        "rotation_angle": 0,
    }

    assert _legacy_rotation_contradicted_by_detector(rotation_metadata, 90) is True


def test_final_metadata_ignores_contradicted_legacy_rotation():
    image = Image.new("RGB", (899, 1599), "white")

    metadata = _finalize_rotation_metadata(
        original_size=image.size,
        processed_image=image,
        rotation_metadata={
            "rotation_detection": {
                "detected_rotation": 0,
                "confidence": 0.755,
                "should_rotate": False,
                "scores": {"0": 0.755, "90": 0.1408, "180": 0.7547, "270": 0.141},
            },
            "rotation_applied": False,
            "rotation_angle": 0,
        },
        legacy_rotation_angle=90,
        legacy_rotation_confidence=0.9702,
    )

    report = metadata["processed_image"]
    assert report["processed_width"] == 899
    assert report["processed_height"] == 1599
    assert report["rotation_applied"] is False
    assert report["rotation_angle"] == 0
    assert report["rotation_source"] == "none"


def test_orientation_ambiguity_marked_when_score_margin_is_tiny():
    image = Image.new("RGB", (899, 1599), "white")

    metadata = _finalize_rotation_metadata(
        original_size=image.size,
        processed_image=image,
        rotation_metadata={
            "rotation_detection": {
                "detected_rotation": 0,
                "confidence": 0.755,
                "should_rotate": False,
                "scores": {"0": 0.755, "90": 0.1408, "180": 0.7547, "270": 0.141},
                "metadata": {"score_margin": 0.0003, "min_margin": 0.12},
            },
            "rotation_applied": False,
            "rotation_angle": 0,
        },
    )

    report = metadata["processed_image"]
    assert report["orientation_ambiguous"] is True
    assert report["score_margin"] == 0.0003
    assert report["best_candidate"] == 0
    assert report["second_candidate"] == 180


def test_orientation_ambiguity_not_marked_when_margin_is_healthy():
    image = Image.new("RGB", (899, 1599), "white")

    metadata = _finalize_rotation_metadata(
        original_size=image.size,
        processed_image=image,
        rotation_metadata={
            "rotation_detection": {
                "detected_rotation": 0,
                "confidence": 0.91,
                "should_rotate": False,
                "scores": {"0": 0.91, "90": 0.12, "180": 0.52, "270": 0.10},
                "metadata": {"score_margin": 0.39, "min_margin": 0.12},
            },
            "rotation_applied": False,
            "rotation_angle": 0,
        },
    )

    assert metadata["processed_image"]["orientation_ambiguous"] is False
    assert metadata["processed_image"]["score_margin"] == 0.39


def test_coordinate_space_validator_catches_out_of_bounds_boxes():
    report = validate_coordinate_space({
        "processed_image": {
            "processed_width": 100,
            "processed_height": 200,
            "coordinate_space": "processed_image",
        },
        "blocks": [
            {"block_id": "ok", "bbox": [5, 5, 40, 40]},
            {"block_id": "bad", "bbox": [5, 5, 140, 40]},
        ],
        "structured_tables": [
            {
                "table_id": "table_1",
                "representability_score": 1,
                "cells": [
                    {"cell_id": "cell_bad", "bbox": [0, 0, 20, 260]},
                ],
            }
        ],
    })

    assert report["has_violation"] is True
    ids = {item["id"] for item in report["violations"]}
    assert {"bad", "cell_bad"} <= ids
