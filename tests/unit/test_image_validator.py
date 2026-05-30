import io
import json
from pathlib import Path

from PIL import Image

from services.validators.image_validator import ImageValidator


def _image_bytes(mode="RGB", size=(1200, 1600), image_format="PNG", dpi=None):
    image = Image.new(mode, size, color=255 if mode in {"L", "1"} else (255, 255, 255))
    buffer = io.BytesIO()
    save_kwargs = {}
    if dpi is not None:
        save_kwargs["dpi"] = dpi
    image.save(buffer, format=image_format, **save_kwargs)
    return buffer.getvalue()


def test_valid_rgb_invoice_like_image():
    result = ImageValidator().validate(_image_bytes("RGB", (1200, 1600), "JPEG", dpi=(300, 300)))

    assert result.is_valid is True
    assert result.errors == []
    assert result.properties.width == 1200
    assert result.properties.height == 1600
    assert result.properties.aspect_ratio == 0.75
    assert result.properties.color_space == "RGB"
    assert result.properties.format == "JPEG"
    assert result.properties.mode == "RGB"
    assert 0.0 <= result.quality_score <= 1.0


def test_valid_grayscale_image_with_warning():
    result = ImageValidator().validate(_image_bytes("L", (1200, 1600), "PNG", dpi=(300, 300)))

    assert result.is_valid is True
    assert any("grayscale" in warning.lower() for warning in result.warnings)
    assert result.properties.color_space == "grayscale"
    assert result.properties.mode == "L"


def test_too_small_image_invalid():
    result = ImageValidator().validate(_image_bytes("RGB", (255, 900)))

    assert result.is_valid is False
    assert any("too small" in error for error in result.errors)


def test_too_large_image_invalid():
    result = ImageValidator().validate(_image_bytes("RGB", (4097, 1200)))

    assert result.is_valid is False
    assert any("too large" in error for error in result.errors)


def test_bad_aspect_ratio_invalid():
    result = ImageValidator().validate(_image_bytes("RGB", (3000, 1000)))

    assert result.is_valid is False
    assert any("aspect ratio" in error for error in result.errors)


def test_missing_dpi_accepted_with_warning():
    result = ImageValidator().validate(_image_bytes("RGB", (1200, 1600), "PNG"))

    assert result.is_valid is True
    assert result.properties.estimated_dpi is None
    assert any("DPI metadata missing" in warning for warning in result.warnings)


def test_low_dpi_warning_if_dpi_exists():
    result = ImageValidator().validate(_image_bytes("RGB", (1200, 1600), "JPEG", dpi=(72, 72)))

    assert result.is_valid is True
    assert result.properties.estimated_dpi < 150
    assert any("Low DPI" in warning for warning in result.warnings)


def test_result_json_serialization():
    result = ImageValidator.validate_image(_image_bytes("RGB", (1200, 1600), "PNG"))

    encoded = json.dumps(result)
    decoded = json.loads(encoded)

    assert decoded["is_valid"] is True
    assert decoded["errors"] == []
    assert decoded["properties"]["width"] == 1200
    assert "format" in decoded["properties"]


def test_file_path_input(tmp_path: Path):
    path = tmp_path / "invoice.png"
    path.write_bytes(_image_bytes("RGB", (1200, 1600), "PNG"))

    result = ImageValidator().validate(path)

    assert result.is_valid is True
    assert result.properties.format == "PNG"
