import io
import json

from PIL import Image, ImageDraw

from services.validators.rotation_detector import RotationDetectionResult, RotationDetector


def _synthetic_invoice(size=(900, 1300)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    width, _ = size
    y = 80
    for idx in range(18):
        left = 70 + (idx % 3) * 15
        right = width - 80 - (idx % 4) * 35
        draw.rectangle((left, y, right, y + 12), fill="black")
        y += 45
    for x in (80, 250, 460, 680):
        draw.line((x, 900, x, 1160), fill="black", width=2)
    for y in range(900, 1161, 40):
        draw.line((80, y, width - 80, y), fill="black", width=2)
    return image


def _image_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_upright_portrait_invoice_returns_zero_or_no_rotation():
    result = RotationDetector().detect(_synthetic_invoice())

    assert result.detected_rotation == 0
    assert result.should_rotate is False
    assert 0.0 <= result.confidence <= 1.0
    assert set(result.scores.keys()) == {0, 90, 180, 270}


def test_landscape_sideways_image_returns_structured_result_without_crashing():
    sideways = _synthetic_invoice().transpose(Image.Transpose.ROTATE_90)

    result = RotationDetector().detect(sideways)

    assert isinstance(result, RotationDetectionResult)
    assert result.detected_rotation in {0, 90, 180, 270}
    assert isinstance(result.should_rotate, bool)
    assert set(result.scores.keys()) == {0, 90, 180, 270}


def test_bytes_input_works():
    result = RotationDetector().detect(_image_bytes(_synthetic_invoice()))

    assert result.metadata["original_size"] == {"width": 900, "height": 1300}
    assert set(result.scores.keys()) == {0, 90, 180, 270}


def test_invalid_bytes_return_warning_low_confidence_without_crashing():
    result = RotationDetector().detect(b"not an image")

    assert result.detected_rotation == 0
    assert result.confidence == 0.0
    assert result.should_rotate is False
    assert result.warnings
    assert result.metadata["readable"] is False


def test_result_to_dict_is_json_serializable():
    result = RotationDetector().detect(_synthetic_invoice()).to_dict()

    encoded = json.dumps(result)
    decoded = json.loads(encoded)

    assert decoded["detected_rotation"] == 0
    assert decoded["method"] == "projection_edge_density"
    assert set(decoded["scores"].keys()) == {"0", "90", "180", "270"}


def test_confidence_is_between_zero_and_one():
    result = RotationDetector().detect(_synthetic_invoice())

    assert 0.0 <= result.confidence <= 1.0
    assert all(0.0 <= score <= 1.0 for score in result.scores.values())


def test_scores_include_all_candidate_rotations():
    result = RotationDetector().detect(_synthetic_invoice())

    assert set(result.scores.keys()) == {0, 90, 180, 270}
