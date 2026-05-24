"""
Image Rotation Detector and Corrector for Surya OCR.

Performs 4-rotation clockwise hypothesis testing (0°, 90°, 180°, 270°) using coarse
text box shape aspects (wider horizontal lines = correct) and Y-coordinate text flow
progression (increasing top-to-bottom).
"""

import time
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image
from core.logger import logger

def rotate_image_clockwise(image: Image.Image, angle: int) -> Image.Image:
    """
    Rotates a PIL Image clockwise by a given angle (0, 90, 180, 270 degrees)
    using Pillow's highly optimized, transpose operations.
    """
    if angle == 0 or angle % 360 == 0:
        return image
    
    # Standard clockwise rotations mapped to optimized PIL transposes
    if angle == 90:
        return image.transpose(Image.Transpose.ROTATE_270)
    elif angle == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    elif angle == 270:
        return image.transpose(Image.Transpose.ROTATE_90)
        
    return image

class RotationDetector:
    """Validator class to dynamically detect and correct document rotation orientations."""

    @staticmethod
    def calculate_rotation_score(boxes: List[Any], angle: int, width: int, height: int) -> float:
        """
        Scores a rotation hypothesis based on box aspect ratios and Y reading progression.
        
        Args:
            boxes: Bounding box predictions from Surya coarse detection.
            angle: Clockwise rotation angle tested.
            width: Width of the rotated image.
            height: Height of the rotated image.
            
        Returns:
            A score between 0.0 and 1.0 (higher = more coherent text alignment).
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

        # 1. Shape aspect ratio analysis:
        # In a correctly aligned invoice page, text line segments should be predominantly
        # horizontal (width > height * 1.3). Collapsed/vertical boxes suggest a wrong rotation.
        horizontal_count = sum(1 for w, h, _ in b_properties if w > (h * 1.3))
        shape_score = horizontal_count / len(b_properties)

        # 2. Text flow Y-progression (increasing top-to-bottom):
        # We check if reading coordinates generally increase from the first detected box to the last.
        y_vals = [cy for _, _, cy in b_properties]
        if len(y_vals) >= 4:
            mid = len(y_vals) // 2
            avg_first = sum(y_vals[:mid]) / mid
            avg_second = sum(y_vals[mid:]) / (len(y_vals) - mid)
            
            # Standard flow: Y should increase (avg_second > avg_first)
            flow_diff = avg_second - avg_first
            norm_diff = flow_diff / max(1.0, float(height))
            # Shift center to 0.5; positive progress yields > 0.5, negative yields < 0.5
            flow_score = min(1.0, max(0.0, 0.5 + norm_diff))
        else:
            flow_score = 0.5

        # 3. Composite score:
        # Aspect ratio is the strongest indicator of rotation (e.g. 90/270),
        # while Y-progression resolves standard vs. upside-down (180).
        combined_score = (0.75 * shape_score) + (0.25 * flow_score)
        
        return round(combined_score, 4)

    @staticmethod
    def detect_and_correct(
        image: Image.Image, 
        det_predictor: Any, 
        threshold: float = 0.70
    ) -> Tuple[Image.Image, Any, int, float]:
        """
        Tests 4 orientation hypotheses, selects the winner, and applies correction if confidence is high.
        
        Args:
            image: Input PIL Image object.
            det_predictor: Surya text detection model function.
            threshold: Minimum score threshold to accept a rotation correction.
            
        Returns:
            A tuple of (corrected_image, best_detection_results, selected_rotation, confidence_score).
        """
        start_time = time.time()
        scores = {}
        candidate_boxes = {}
        candidate_images = {}
        candidate_results = {}

        # 1. Evaluate all 4 rotations
        for angle in [0, 90, 180, 270]:
            rotated_img = rotate_image_clockwise(image, angle)
            candidate_images[angle] = rotated_img
            
            # Coarse fast detection call
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
            candidate_boxes[angle] = boxes
            candidate_results[angle] = results_obj
            
            logger.info(f"[ROTATION HYPOTHESIS] angle={angle}°, boxes={len(boxes)}, score={score:.4f}")

        # 2. Select orientation with highest confidence score
        best_angle = max(scores, key=scores.get)
        best_score = scores[best_angle]
        elapsed_ms = (time.time() - start_time) * 1000.0

        logger.info(
            f"[ROTATION DECISION] Selected: {best_angle}° clockwise, score={best_score:.4f}, "
            f"original_0_score={scores[0]:.4f}, time={elapsed_ms:.1f}ms"
        )

        # 3. Apply correction if winner exceeds confidence gate
        if best_angle != 0 and best_score > threshold and best_score > (scores[0] + 0.10):
            logger.warning(
                f"🚨 Applying image rotation correction of {best_angle}° clockwise! "
                f"Confidence score = {best_score:.4f}"
            )
            return candidate_images[best_angle], candidate_results[best_angle], best_angle, best_score
            
        return image, candidate_results[0], 0, scores[0]
