from types import SimpleNamespace

from PIL import Image

from services.ocr_engine import _apply_rotation_if_confident


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
