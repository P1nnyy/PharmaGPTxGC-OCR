"""
Standalone image rotation detector for invoice diagnostics.

The lightweight detector scores 0/90/180/270-degree orientation hypotheses using
PIL-only image projections. Existing OCR integration APIs are preserved but the
new detect() method only recommends a correction and never mutates the input.
"""

import io
import os
import time
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from core.logger import logger


def rotate_image_clockwise(image: Image.Image, angle: int) -> Image.Image:
    """
    Rotates a PIL Image clockwise by a given angle (0, 90, 180, 270 degrees)
    using Pillow's highly optimized transpose operations.
    """
    if angle == 0 or angle % 360 == 0:
        return image

    if angle == 90:
        return image.transpose(Image.Transpose.ROTATE_270)
    if angle == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    if angle == 270:
        return image.transpose(Image.Transpose.ROTATE_90)

    return image


class RotationDetectionResult(BaseModel):
    detected_rotation: int = 0
    confidence: float = 0.0
    should_rotate: bool = False
    scores: Dict[int, float] = Field(default_factory=dict)
    method: str = "projection_edge_density"
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class RotationDetector:
    """Detect likely invoice image rotation without invoking OCR."""

    CANDIDATE_ROTATIONS = (0, 90, 180, 270)

    def __init__(
        self,
        confidence_threshold: float = 0.65,
        min_margin: float = 0.12,
        thumbnail_long_side: int = 384,
    ):
        self.confidence_threshold = confidence_threshold
        self.min_margin = min_margin
        self.thumbnail_long_side = thumbnail_long_side

    def detect(self, image_input: Any) -> RotationDetectionResult:
        warnings: List[str] = []
        try:
            image = self._open_image(image_input)
            original_size = image.size
            exif_orientation = self._read_exif_orientation(image)
            if exif_orientation is not None:
                warnings.append(f"EXIF orientation present: {exif_orientation}.")
            image.load()
        except (UnidentifiedImageError, OSError, ValueError, TypeError) as exc:
            warning = f"Unable to read image for rotation detection: {exc}"
            logger.warning("[ROTATION DETECTOR] %s", warning)
            return RotationDetectionResult(
                detected_rotation=0,
                confidence=0.0,
                should_rotate=False,
                scores={angle: 0.0 for angle in self.CANDIDATE_ROTATIONS},
                warnings=[warning],
                metadata={"readable": False},
            )

        scores: Dict[int, float] = {}
        per_angle_metadata: Dict[str, Any] = {}
        for angle in self.CANDIDATE_ROTATIONS:
            candidate = rotate_image_clockwise(image.copy(), angle)
            score, score_meta = self._score_candidate(candidate)
            scores[angle] = score
            per_angle_metadata[str(angle)] = score_meta

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_angle, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = round(best_score - second_score, 4)

        should_rotate = (
            best_angle != 0
            and best_score >= self.confidence_threshold
            and margin >= self.min_margin
        )
        detected_rotation = best_angle if should_rotate else 0
        confidence = best_score if should_rotate else scores.get(0, 0.0)
        if best_angle != 0 and not should_rotate:
            warnings.append("Orientation signal was ambiguous; leaving image unrotated.")

        result = RotationDetectionResult(
            detected_rotation=detected_rotation,
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            should_rotate=should_rotate,
            scores={angle: round(value, 4) for angle, value in scores.items()},
            warnings=warnings,
            metadata={
                "original_size": {"width": original_size[0], "height": original_size[1]},
                "best_candidate": best_angle,
                "best_score": round(best_score, 4),
                "second_score": round(second_score, 4),
                "score_margin": margin,
                "confidence_threshold": self.confidence_threshold,
                "min_margin": self.min_margin,
                "exif_orientation": exif_orientation,
                "candidate_metadata": per_angle_metadata,
            },
        )
        logger.info(
            "[ROTATION DETECTOR] detected_rotation=%s confidence=%.4f should_rotate=%s scores=%s",
            result.detected_rotation,
            result.confidence,
            result.should_rotate,
            result.scores,
        )
        for warning in warnings:
            logger.warning("[ROTATION DETECTOR] %s", warning)
        return result

    @staticmethod
    def calculate_rotation_score(boxes: List[Any], angle: int, width: int, height: int) -> float:
        """
        Scores a rotation hypothesis based on OCR box aspect ratios and Y reading progression.

        Preserved for existing OCR integration callers.
        """
        if not boxes:
            return 0.0

        b_properties = []
        for b in boxes:
            poly = getattr(b, "polygon", [])
            if poly and len(poly) >= 3:
                xs = [pt[0] for pt in poly]
                ys = [pt[1] for pt in poly]
                b_width = max(xs) - min(xs)
                b_height = max(ys) - min(ys)
                center_y = sum(ys) / len(poly)
            else:
                bbox = getattr(b, "bbox", [])
                if bbox and len(bbox) >= 4:
                    b_width = bbox[2] - bbox[0]
                    b_height = bbox[3] - bbox[1]
                    center_y = (bbox[1] + bbox[3]) / 2.0
                else:
                    continue
            b_properties.append((b_width, b_height, center_y))

        if not b_properties:
            return 0.0

        horizontal_count = sum(1 for w, h, _ in b_properties if w > (h * 1.3))
        shape_score = horizontal_count / len(b_properties)

        y_vals = [cy for _, _, cy in b_properties]
        if len(y_vals) >= 4:
            mid = len(y_vals) // 2
            avg_first = sum(y_vals[:mid]) / mid
            avg_second = sum(y_vals[mid:]) / (len(y_vals) - mid)
            flow_diff = avg_second - avg_first
            norm_diff = flow_diff / max(1.0, float(height))
            flow_score = min(1.0, max(0.0, 0.5 + norm_diff))
        else:
            flow_score = 0.5

        combined_score = (0.75 * shape_score) + (0.25 * flow_score)
        return round(combined_score, 4)

    @staticmethod
    def detect_and_correct(
        image: Image.Image,
        det_predictor: Any,
        threshold: float = 0.70,
    ) -> Tuple[Image.Image, Any, int, float]:
        """
        Existing OCR integration: tests 4 OCR detection hypotheses and applies correction.
        Kept for backwards compatibility; standalone detect() does not call this method.
        """
        start_time = time.time()
        scores = {}
        candidate_images = {}
        candidate_results = {}

        for angle in [0, 90, 180, 270]:
            rotated_img = rotate_image_clockwise(image, angle)
            candidate_images[angle] = rotated_img

            try:
                det_results = det_predictor([rotated_img])
                results_obj = det_results[0] if det_results else None
                boxes = results_obj.bboxes if (results_obj and getattr(results_obj, "bboxes", None)) else []
            except Exception as e:
                logger.error(f"[ROTATION] Coarse detection failed for angle {angle}: {e}")
                boxes = []
                results_obj = None

            score = RotationDetector.calculate_rotation_score(boxes, angle, rotated_img.width, rotated_img.height)
            scores[angle] = score
            candidate_results[angle] = results_obj
            logger.info(f"[ROTATION HYPOTHESIS] angle={angle} deg, boxes={len(boxes)}, score={score:.4f}")

        best_angle = max(scores, key=scores.get)
        best_score = scores[best_angle]
        elapsed_ms = (time.time() - start_time) * 1000.0

        logger.info(
            f"[ROTATION DECISION] Selected: {best_angle} deg clockwise, score={best_score:.4f}, "
            f"original_0_score={scores[0]:.4f}, time={elapsed_ms:.1f}ms"
        )

        if best_angle != 0 and best_score > threshold and best_score > (scores[0] + 0.10):
            logger.warning(
                f"Applying image rotation correction of {best_angle} deg clockwise. "
                f"Confidence score = {best_score:.4f}"
            )
            return candidate_images[best_angle], candidate_results[best_angle], best_angle, best_score

        return image, candidate_results[0], 0, scores[0]

    def _score_candidate(self, image: Image.Image) -> Tuple[float, Dict[str, Any]]:
        gray = ImageOps.grayscale(image)
        gray.thumbnail((self.thumbnail_long_side, self.thumbnail_long_side))
        width, height = gray.size
        pixels = gray.load()

        dark_threshold = 210
        row_counts = []
        col_counts = [0 for _ in range(width)]
        for y in range(height):
            row_count = 0
            for x in range(width):
                if pixels[x, y] < dark_threshold:
                    row_count += 1
                    col_counts[x] += 1
            row_counts.append(row_count)

        total_dark = sum(row_counts)
        if total_dark == 0:
            return 0.0, {
                "width": width,
                "height": height,
                "dark_pixel_ratio": 0.0,
                "reason": "blank_or_low_contrast",
            }

        row_variance = self._normalized_variance(row_counts)
        col_variance = self._normalized_variance(col_counts)
        horizontal_banding = row_variance / (row_variance + col_variance + 1e-9)
        dark_pixel_ratio = total_dark / max(1, width * height)

        text_density_score = 1.0 - min(1.0, abs(dark_pixel_ratio - 0.08) / 0.16)
        aspect_score = 0.72 if height >= width else 0.48
        band_score = max(0.0, min(1.0, horizontal_banding))
        score = (0.62 * band_score) + (0.23 * aspect_score) + (0.15 * text_density_score)

        return round(max(0.0, min(1.0, score)), 4), {
            "width": width,
            "height": height,
            "dark_pixel_ratio": round(dark_pixel_ratio, 4),
            "row_variance": round(row_variance, 4),
            "column_variance": round(col_variance, 4),
            "horizontal_banding": round(horizontal_banding, 4),
            "aspect_score": aspect_score,
            "text_density_score": round(text_density_score, 4),
        }

    @staticmethod
    def _normalized_variance(values: List[int]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        if mean <= 0:
            return 0.0
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return variance / (mean ** 2)

    def _open_image(self, image_input: Any) -> Image.Image:
        if isinstance(image_input, Image.Image):
            return image_input.copy()
        if isinstance(image_input, (bytes, bytearray, memoryview)):
            return Image.open(io.BytesIO(bytes(image_input)))
        if isinstance(image_input, (str, os.PathLike, Path)):
            return Image.open(image_input)
        read = getattr(image_input, "read", None)
        if callable(read):
            return self._open_file_like(image_input)
        raise TypeError("Unsupported image input type.")

    @staticmethod
    def _open_file_like(file_obj: BinaryIO) -> Image.Image:
        try:
            position = file_obj.tell()
        except Exception:
            position = None
        data = file_obj.read()
        if position is not None:
            try:
                file_obj.seek(position)
            except Exception:
                pass
        return Image.open(io.BytesIO(data))

    @staticmethod
    def _read_exif_orientation(image: Image.Image) -> Optional[int]:
        try:
            exif = image.getexif()
            orientation = exif.get(274) if exif else None
            return int(orientation) if orientation is not None else None
        except Exception:
            return None
