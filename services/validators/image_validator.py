"""
Image Validator for Invoice Processing.

Performs dimensions, aspect ratio, DPI, color space, upside-down rotation detection,
and quality scoring on uploaded images before passing to the OCR engine.
"""

import io
import time
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image
import numpy as np
from core.logger import logger

class ImageValidator:
    """Validator class to evaluate image characteristics and enforce OCR processing gates."""

    @staticmethod
    def validate_image(file_bytes: bytes) -> Dict[str, Any]:
        """
        Validates an uploaded image and computes structural property metadata and a quality score.
        
        Args:
            file_bytes: Raw binary content of the uploaded file.
            
        Returns:
            A validation report dictionary adhering to the required return structure.
        """
        start_time = time.time()
        warnings = []
        is_valid = True
        error_message = None
        
        # 1. Format Validation (PIL open test)
        try:
            img = Image.open(io.BytesIO(file_bytes))
            # verify() checks format integrity, but closes/invalidates the PIL object
            img.verify()
            # Reopen for actual property checks
            img = Image.open(io.BytesIO(file_bytes))
        except Exception as e:
            logger.error(f"[IMAGE VALIDATION] PIL format verification failed: {e}")
            return {
                "is_valid": False,
                "quality_score": 0.0,
                "warnings": [f"Invalid image format: {str(e)}"],
                "properties": {
                    "width": 0,
                    "height": 0,
                    "aspect_ratio": 0.0,
                    "estimated_dpi": 0,
                    "color_space": "unknown",
                    "likely_rotation": None
                }
            }

        width, height = img.size
        aspect_ratio = round(width / height, 4) if height > 0 else 0.0
        
        # 2. Dimension Checks (256px <= min(width, height) <= 4096px)
        min_dim = min(width, height)
        if min_dim < 256:
            is_valid = False
            error_message = f"Minimum image dimension ({min_dim}px) is too small. Must be at least 256px."
        elif min_dim > 4096:
            is_valid = False
            error_message = f"Minimum image dimension ({min_dim}px) is too large. Must be at most 4096px."

        # 3. Aspect Ratio Validation (0.5 <= aspect_ratio <= 2.0)
        if is_valid and (aspect_ratio < 0.5 or aspect_ratio > 2.0):
            is_valid = False
            error_message = f"Invalid image aspect ratio ({aspect_ratio:.2f}). Invoices must be portrait or landscape between 0.5 and 2.0."

        # 4. Color Space Analysis (Grayscale vs RGB)
        color_space = "grayscale" if img.mode in ("L", "1") else "RGB"

        # 5. DPI Estimation (From EXIF or estimated from A4 length heuristic)
        estimated_dpi = 0
        exif_dpi = img.info.get("dpi")
        if exif_dpi and isinstance(exif_dpi, (tuple, list)) and len(exif_dpi) >= 2:
            estimated_dpi = int(exif_dpi[0])
        else:
            # Fallback A4 length heuristic: assume standard page length is ~11.0 inches
            estimated_dpi = int(max(width, height) / 11.0)

        if estimated_dpi < 150:
            warnings.append(f"Low estimated DPI ({estimated_dpi}). Text recognition accuracy may be reduced.")

        # 6. Pre-Rotation Upside-Down (180 deg) Detection using Top/Bottom brightness projections
        likely_rotation = 0
        try:
            # Convert to grayscale for intensity profile analysis
            gray = img.convert("L")
            w_gray, h_gray = gray.size
            
            # Crop top and bottom 20% bands
            top_band = gray.crop((0, 0, w_gray, int(h_gray * 0.20)))
            bottom_band = gray.crop((0, int(h_gray * 0.80), w_gray, h_gray))
            
            # Compute average brightness (0 = dark, 255 = white)
            top_brightness = np.mean(np.array(top_band))
            bottom_brightness = np.mean(np.array(bottom_band))
            
            # Invoices generally contain dense title text/logo/headers at the top (darker) 
            # and sparse blank margins at the bottom (brighter). 
            # If the top band is significantly whiter/brighter than the bottom band, it is likely upside down.
            if top_brightness > (bottom_brightness + 18.0):
                likely_rotation = 180
                warnings.append("Image appears to be upside-down (180° rotation detected).")
        except Exception as e:
            logger.warning(f"[IMAGE VALIDATION] Pre-rotation estimation failed: {e}")
            likely_rotation = None

        # 7. Quality Score Generation (0.0-1.0)
        quality_score = 1.0
        
        # Deduct for low DPI
        if estimated_dpi < 100:
            quality_score -= 0.35
        elif estimated_dpi < 150:
            quality_score -= 0.15
            
        # Deduct for extremely narrow sizes
        if min_dim < 512:
            quality_score -= 0.20
            
        # Deduct for extreme aspect ratios close to limits
        if aspect_ratio < 0.65 or aspect_ratio > 1.75:
            quality_score -= 0.10
            
        # Deduct for grayscale (reduced color contrast)
        if color_space == "grayscale":
            quality_score -= 0.05
            
        # Clamp quality score between 0.1 and 1.0
        quality_score = round(max(0.1, min(1.0, quality_score)), 2)

        elapsed_ms = (time.time() - start_time) * 1000.0
        
        # Log validator properties as required
        logger.info(
            f"[IMAGE VALIDATION] dims={width}x{height}, aspect={aspect_ratio:.2f}, "
            f"dpi={estimated_dpi}, color={color_space}, rotation={likely_rotation}, "
            f"quality={quality_score}, valid={is_valid}, time={elapsed_ms:.1f}ms"
        )
        
        report = {
            "is_valid": is_valid,
            "quality_score": quality_score,
            "warnings": warnings,
            "properties": {
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
                "estimated_dpi": estimated_dpi,
                "color_space": color_space,
                "likely_rotation": likely_rotation
            }
        }
        
        if error_message:
            report["error_message"] = error_message
            
        return report
