"""Tests for the pre-flight content gate.

The asymmetry these encode: rejecting a real invoice blocks a user from filing
a supplier bill, while accepting junk costs one API call. So the "must pass"
cases are the load-bearing ones and are deliberately extreme.
"""

import io

import numpy as np
import pytest
from PIL import Image, ImageEnhance, ImageFilter

from core.config import settings
from services.validators import content_validator


def to_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def synthetic_invoice() -> Image.Image:
    """A photographed-page image: a bright sheet on a darker surface, carrying
    ruled table rows and word-shaped ink.

    Built rather than fixture-loaded so the suite carries no binary assets.
    The shape matters: an earlier version drew 5px-wide marks with 2px gaps,
    which is statistically closer to high-frequency noise than to print and
    scored coherence 0.45 where real invoice photos score 0.93. Words are
    therefore drawn as connected blocks, and the sheet sits inset on a darker
    background so the page edge contributes the low-frequency structure every
    real photograph of a document has.
    """
    rng = np.random.default_rng(7)
    a = np.full((1500, 1100), 92, dtype=np.uint8)          # desk surface
    a[60:1440, 70:1030] = 238                              # paper sheet

    for row in range(150, 1380, 44):                       # ruled table rows
        a[row, 100:1000] = 45
        col = 110
        while col < 980:                                   # word-shaped ink
            width = int(rng.integers(28, 90))
            if col + width > 980:
                break
            a[row + 9:row + 23, col:col + width] = int(rng.integers(20, 65))
            col += width + int(rng.integers(12, 26))

    a[140:1385, 100] = 45                                  # table borders
    a[140:1385, 1000] = 45
    noise = rng.normal(0, 3, a.shape)
    return Image.fromarray(np.clip(a + noise, 0, 255).astype(np.uint8)).convert("RGB")


# --------------------------------------------------------------------------
# Must pass: anything with real recoverable structure
# --------------------------------------------------------------------------

def test_synthetic_invoice_passes():
    assert content_validator.assess(to_bytes(synthetic_invoice())).is_processable


@pytest.mark.parametrize(
    "label,transform",
    [
        ("blur_1_6", lambda im: im.filter(ImageFilter.GaussianBlur(1.6))),
        ("blur_2_5", lambda im: im.filter(ImageFilter.GaussianBlur(2.5))),
        ("blur_4_0", lambda im: im.filter(ImageFilter.GaussianBlur(4.0))),
        ("dark_0_45", lambda im: ImageEnhance.Brightness(im).enhance(0.45)),
        ("dark_0_25", lambda im: ImageEnhance.Brightness(im).enhance(0.25)),
        ("bright_1_8", lambda im: ImageEnhance.Brightness(im).enhance(1.8)),
        ("low_contrast", lambda im: ImageEnhance.Contrast(im).enhance(0.45)),
        ("very_low_contrast", lambda im: ImageEnhance.Contrast(im).enhance(0.30)),
        ("rotated_7deg", lambda im: im.rotate(7, expand=True, fillcolor=(90, 70, 50))),
        ("downscaled_3x", lambda im: im.resize((im.width // 3, im.height // 3))),
        ("grayscale", lambda im: im.convert("L").convert("RGB")),
    ],
)
def test_degraded_invoices_still_pass(label, transform):
    """A poor-quality invoice photo must still reach the extractor - Azure may
    well read it, and a false rejection blocks the user entirely."""
    result = content_validator.assess(to_bytes(transform(synthetic_invoice())))
    assert result.is_processable, f"{label} was wrongly rejected: {result.reason}"


def test_document_occupying_small_part_of_frame_passes():
    """Photographed at a distance, on a desk - the document is a minority of
    the pixels but the upload is still legitimate."""
    doc = synthetic_invoice()
    canvas = Image.new("RGB", (doc.width * 2, doc.height * 2), (85, 65, 45))
    canvas.paste(doc, (doc.width // 2, doc.height // 2))
    assert content_validator.assess(to_bytes(canvas)).is_processable


def test_ordinary_photograph_is_not_rejected():
    """The gate does not claim to detect invoices. A real photo that is not a
    document must pass - deciding that is the extractor's job, not this.

    Modelled as large-amplitude smooth structure, matching the dynamic range
    and spread measured on real desk/background crops (dyn 109-168, std 27-51)
    rather than heavily blurred noise, which collapses to a flat grey field
    no real camera would produce.
    """
    yy, xx = np.mgrid[0:900, 0:1200]
    scene = (
        128
        + 70 * np.sin(xx / 130.0) * np.cos(yy / 95.0)
        + 40 * np.sin((xx + yy) / 260.0)
    )
    scene = np.clip(scene, 0, 255).astype(np.uint8)
    result = content_validator.assess(to_bytes(Image.fromarray(scene).convert("RGB")))
    assert result.is_processable, f"ordinary photo wrongly rejected: {result.reason}"


# --------------------------------------------------------------------------
# Must reject: structurally empty, no recoverable content
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label,colour",
    [("black_lens_cap", (0, 0, 0)), ("white_blank", (255, 255, 255)), ("solid_mid", (120, 90, 60))],
)
def test_uniform_frames_rejected(label, colour):
    result = content_validator.assess(to_bytes(Image.new("RGB", (1200, 1600), colour)))
    assert not result.is_processable, f"{label} should not reach Azure"
    assert "blank" in result.reason.lower() or "uniform" in result.reason.lower()


def test_pure_noise_rejected():
    rng = np.random.default_rng(0)
    noise = Image.fromarray(rng.integers(0, 255, (1200, 900, 3), dtype=np.uint8))
    result = content_validator.assess(to_bytes(noise))
    assert not result.is_processable
    assert "noise" in result.reason.lower()


def test_dark_sensor_noise_rejected():
    """A shot taken with the lens covered: not uniform enough to read as
    blank, but nothing but noise."""
    rng = np.random.default_rng(1)
    dark = np.clip(rng.normal(30, 14, (1400, 1000)), 0, 255).astype(np.uint8)
    result = content_validator.assess(to_bytes(Image.fromarray(dark).convert("RGB")))
    assert not result.is_processable


def test_blown_out_exposure_rejected():
    rng = np.random.default_rng(2)
    blown = np.clip(rng.normal(252, 3, (1400, 1000)), 0, 255).astype(np.uint8)
    assert not content_validator.assess(to_bytes(Image.fromarray(blown).convert("RGB"))).is_processable


# --------------------------------------------------------------------------
# Failure modes of the gate itself
# --------------------------------------------------------------------------

def test_unreadable_input_passes_through():
    """The gate must never be the reason a valid invoice fails. If it cannot
    analyse the bytes it defers rather than rejecting."""
    assert content_validator.assess(b"not an image at all").is_processable


def test_metrics_are_reported_for_tuning():
    result = content_validator.assess(to_bytes(synthetic_invoice()))
    assert result.dynamic_range > 0
    assert result.coherence > 0


def test_gate_can_be_disabled(monkeypatch):
    """Escape hatch: if thresholds ever misfire in production the gate can be
    turned off without a deploy."""
    monkeypatch.setattr(settings, "CONTENT_MIN_COHERENCE", 0.0)
    monkeypatch.setattr(settings, "CONTENT_MIN_DYNAMIC_RANGE", 0.0)
    monkeypatch.setattr(settings, "CONTENT_MIN_STD_DEV", 0.0)
    rng = np.random.default_rng(0)
    noise = Image.fromarray(rng.integers(0, 255, (600, 600, 3), dtype=np.uint8))
    assert content_validator.assess(to_bytes(noise)).is_processable
