"""Pre-flight content gate.

Runs before the (billable) Azure Document Intelligence call and rejects images
that provably contain nothing recoverable - blank frames, lens-cap shots,
blown-out captures, pure sensor noise. Every rejection here is an API call
not paid for.

Deliberately narrow scope
-------------------------
This does NOT try to answer "is this an invoice?". An earlier iteration scored
tiles for printed-text structure (ink coverage, edge density, row-projection
periodicity). It separated cleanly on sharp scans but collapsed on realistic
degradation: a 2.5px-blurred invoice scored identically to a blank page, while
a photo of a keyboard scored higher than a real invoice. No threshold in that
design avoided rejecting genuine invoices.

Since a false rejection blocks real work - a pharmacist who cannot file a
supplier bill - while a false acceptance costs one API call, the gate is tuned
strictly for the safe direction: reject only what is structurally empty, let
everything ambiguous through. Garbage that gets past this is caught later by
the extraction confidence score.

Thresholds were fitted against real invoice photographs under 14 capture
degradations each (blur to 4px, brightness 0.25x-1.8x, contrast to 0.30x,
7-degree rotation, 3x downscale, JPEG q15, grayscale, document occupying a
quarter of the frame) versus blank/uniform/noise frames. Observed separation:

    coherence   real imagery >= 0.93      empty/noise <= 0.36
    dyn. range  real imagery >= 40        empty       <= 9
"""

import io
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter
from pydantic import BaseModel

from core.config import settings
from core.logger import logger

# Analysis resolution. Only aggregate statistics are computed, so the long side
# is capped to keep the check at a few milliseconds regardless of input size.
_ANALYSIS_MAX_SIDE = 1200
_COHERENCE_BLUR_RADIUS = 2.0


class ContentAssessment(BaseModel):
    is_processable: bool
    reason: Optional[str] = None
    dynamic_range: float = 0.0
    std_dev: float = 0.0
    coherence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


def _to_luminance(image_input: Any) -> Optional[Tuple[Image.Image, np.ndarray]]:
    """Returns (downscaled greyscale image, its array), or None if unreadable.
    Format errors are ImageValidator's job, so they are not re-reported here."""
    try:
        if isinstance(image_input, Image.Image):
            image = image_input
        elif isinstance(image_input, (bytes, bytearray, memoryview)):
            image = Image.open(io.BytesIO(bytes(image_input)))
        else:
            image = Image.open(image_input)

        grey = image.convert("L")
        width, height = grey.size
        if max(width, height) > _ANALYSIS_MAX_SIDE:
            scale = _ANALYSIS_MAX_SIDE / max(width, height)
            grey = grey.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.BILINEAR,
            )
        return grey, np.asarray(grey, dtype=np.float32)
    except Exception as e:
        logger.warning(f"[CONTENT GATE] could not read image for analysis: {type(e).__name__}: {e}")
        return None


def assess(image_input: Any) -> ContentAssessment:
    """Assesses whether an image carries enough structure to be worth sending
    to Azure. Anything unreadable here is passed through rather than rejected -
    this gate must never be the reason a valid invoice fails."""
    loaded = _to_luminance(image_input)
    if loaded is None:
        return ContentAssessment(is_processable=True, reason=None)

    grey, arr = loaded

    p1, p99 = np.percentile(arr, [1, 99])
    dynamic_range = float(p99 - p1)
    std_dev = float(arr.std())

    # Spatial coherence: genuine imagery is spatially correlated and survives a
    # blur nearly intact; uncorrelated sensor noise averages away. This is the
    # single cleanest discriminator found - it separates real photographs from
    # noise by roughly 3x with nothing in between.
    blurred = np.asarray(
        grey.filter(ImageFilter.GaussianBlur(_COHERENCE_BLUR_RADIUS)), dtype=np.float32
    )
    coherence = float(blurred.std() / (std_dev + 1e-6))

    reason = None
    if dynamic_range < settings.CONTENT_MIN_DYNAMIC_RANGE or std_dev < settings.CONTENT_MIN_STD_DEV:
        reason = (
            "The image is blank or uniformly exposed - no document content was detected. "
            "Please retake the photo with the invoice in frame and adequate lighting."
        )
    elif coherence < settings.CONTENT_MIN_COHERENCE:
        reason = (
            "The image is dominated by sensor noise and contains no readable document. "
            "Please retake the photo in better lighting."
        )

    assessment = ContentAssessment(
        is_processable=reason is None,
        reason=reason,
        dynamic_range=round(dynamic_range, 2),
        std_dev=round(std_dev, 2),
        coherence=round(coherence, 4),
    )

    # Logged on every upload, pass or fail, so real-world thresholds can be
    # retuned from production data rather than guesswork.
    logger.info(
        "[CONTENT GATE] processable=%s dynamic_range=%.1f std=%.2f coherence=%.3f",
        assessment.is_processable,
        assessment.dynamic_range,
        assessment.std_dev,
        assessment.coherence,
    )
    if not assessment.is_processable:
        logger.warning(f"[CONTENT GATE] rejected before Azure call: {reason}")

    return assessment
