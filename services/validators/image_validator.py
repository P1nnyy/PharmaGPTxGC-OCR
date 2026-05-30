"""
Image Validator for Invoice Processing.

Performs lightweight readability, dimensions, aspect ratio, DPI, color mode, and
quality checks on uploaded images before passing them to the OCR engine.
"""

import io
import os
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Union

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from core.config import settings
from core.logger import logger


class ImageValidationProperties(BaseModel):
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[float] = None
    color_space: Optional[str] = None
    estimated_dpi: Optional[float] = None
    format: Optional[str] = None
    mode: Optional[str] = None


class ImageValidationResult(BaseModel):
    is_valid: bool
    quality_score: float
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    properties: ImageValidationProperties = Field(default_factory=ImageValidationProperties)

    def to_dict(self) -> Dict[str, Any]:
        payload = self.model_dump(mode="json")
        if self.errors:
            payload["error_message"] = "; ".join(self.errors)
        return payload


class ImageValidator:
    """Validator class to evaluate image characteristics before OCR processing."""

    def __init__(
        self,
        min_side_px: Optional[int] = None,
        max_side_px: Optional[int] = None,
        min_aspect_ratio: Optional[float] = None,
        max_aspect_ratio: Optional[float] = None,
        min_dpi_warning: Optional[float] = None,
    ):
        self.min_side_px = int(min_side_px if min_side_px is not None else settings.IMAGE_MIN_SIDE_PX)
        self.max_side_px = int(max_side_px if max_side_px is not None else settings.IMAGE_MAX_SIDE_PX)
        self.min_aspect_ratio = float(
            min_aspect_ratio if min_aspect_ratio is not None else settings.IMAGE_MIN_ASPECT_RATIO
        )
        self.max_aspect_ratio = float(
            max_aspect_ratio if max_aspect_ratio is not None else settings.IMAGE_MAX_ASPECT_RATIO
        )
        self.min_dpi_warning = float(
            min_dpi_warning if min_dpi_warning is not None else settings.IMAGE_MIN_DPI_WARNING
        )

    @staticmethod
    def validate_image(image_input: Any) -> Dict[str, Any]:
        """Backward-compatible dict-returning validation entry point."""
        return ImageValidator().validate(image_input).to_dict()

    def validate(self, image_input: Any) -> ImageValidationResult:
        try:
            image = self._open_image(image_input)
            image.load()
        except (UnidentifiedImageError, OSError, ValueError, TypeError) as exc:
            message = f"Invalid image format: {exc}"
            logger.warning("[IMAGE VALIDATION] PIL image read failed: %s", exc)
            return ImageValidationResult(
                is_valid=False,
                quality_score=0.0,
                errors=[message],
            )

        properties = self._properties(image)
        warnings: List[str] = []
        errors: List[str] = []

        width = properties.width
        height = properties.height
        if width is None or height is None or width <= 0 or height <= 0:
            errors.append("Image dimensions could not be read.")
        else:
            min_side = min(width, height)
            max_side = max(width, height)
            if min_side < self.min_side_px:
                errors.append(
                    f"Minimum image dimension ({min_side}px) is too small. Must be at least {self.min_side_px}px."
                )
            if max_side > self.max_side_px:
                errors.append(
                    f"Maximum image dimension ({max_side}px) is too large. Must be at most {self.max_side_px}px."
                )

        aspect_ratio = properties.aspect_ratio
        if aspect_ratio is not None and not (self.min_aspect_ratio <= aspect_ratio <= self.max_aspect_ratio):
            errors.append(
                f"Invalid image aspect ratio ({aspect_ratio:.2f}). "
                f"Invoices must be between {self.min_aspect_ratio:.2f} and {self.max_aspect_ratio:.2f}."
            )

        if properties.mode in {"L", "1"} or properties.color_space == "grayscale":
            warnings.append("Image is grayscale; OCR may have reduced contrast information.")

        if properties.estimated_dpi is None:
            warnings.append("DPI metadata missing; continuing.")
        elif properties.estimated_dpi < self.min_dpi_warning:
            warnings.append(
                f"Low DPI metadata ({properties.estimated_dpi:g}); OCR accuracy may be reduced."
            )

        quality_score = self._quality_score(properties, errors, warnings)
        result = ImageValidationResult(
            is_valid=not errors,
            quality_score=quality_score,
            warnings=warnings,
            errors=errors,
            properties=properties,
        )

        logger.info(
            "[IMAGE VALIDATION] width=%s height=%s aspect_ratio=%s mode=%s color_space=%s format=%s dpi=%s quality=%.2f valid=%s",
            properties.width,
            properties.height,
            properties.aspect_ratio,
            properties.mode,
            properties.color_space,
            properties.format,
            properties.estimated_dpi,
            result.quality_score,
            result.is_valid,
        )
        for warning in warnings:
            logger.warning("[IMAGE VALIDATION] %s", warning)
        for error in errors:
            logger.warning("[IMAGE VALIDATION] %s", error)

        return result

    def _open_image(self, image_input: Any) -> Image.Image:
        if isinstance(image_input, Image.Image):
            return image_input.copy()

        if isinstance(image_input, (bytes, bytearray, memoryview)):
            return Image.open(io.BytesIO(bytes(image_input)))

        if isinstance(image_input, (str, os.PathLike, Path)):
            return Image.open(image_input)

        file_obj = getattr(image_input, "file", None)
        if file_obj is not None:
            return self._open_file_like(file_obj)

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
    def _properties(image: Image.Image) -> ImageValidationProperties:
        width, height = image.size
        aspect_ratio = round(width / height, 4) if height else None
        dpi = ImageValidator._read_dpi(image)
        return ImageValidationProperties(
            width=int(width) if width is not None else None,
            height=int(height) if height is not None else None,
            aspect_ratio=aspect_ratio,
            color_space=ImageValidator._color_space(image.mode),
            estimated_dpi=dpi,
            format=image.format,
            mode=image.mode,
        )

    @staticmethod
    def _read_dpi(image: Image.Image) -> Optional[float]:
        dpi = image.info.get("dpi")
        if isinstance(dpi, (tuple, list)) and dpi:
            numeric = [float(value) for value in dpi if isinstance(value, (int, float))]
            return round(sum(numeric) / len(numeric), 2) if numeric else None
        if isinstance(dpi, (int, float)):
            return float(dpi)
        return None

    @staticmethod
    def _color_space(mode: Optional[str]) -> Optional[str]:
        if mode in {"L", "1"}:
            return "grayscale"
        return mode

    def _quality_score(
        self,
        properties: ImageValidationProperties,
        errors: List[str],
        warnings: List[str],
    ) -> float:
        if errors:
            score = 0.35
        else:
            score = 1.0

        if properties.width and properties.height:
            min_side = min(properties.width, properties.height)
            max_side = max(properties.width, properties.height)
            if min_side < 512:
                score -= 0.20
            if max_side > (self.max_side_px * 0.9):
                score -= 0.10

        if properties.aspect_ratio is not None:
            near_min = self.min_aspect_ratio <= properties.aspect_ratio < (self.min_aspect_ratio + 0.15)
            near_max = (self.max_aspect_ratio - 0.25) < properties.aspect_ratio <= self.max_aspect_ratio
            if near_min or near_max:
                score -= 0.10

        if properties.estimated_dpi is not None:
            if properties.estimated_dpi < 100:
                score -= 0.25
            elif properties.estimated_dpi < self.min_dpi_warning:
                score -= 0.15

        if properties.mode in {"L", "1"}:
            score -= 0.05

        if warnings and properties.estimated_dpi is None:
            score -= 0.02

        return round(max(0.0, min(1.0, score)), 2)
