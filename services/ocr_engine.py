import os
import threading
from PIL import Image, ImageOps
import numpy as np
from typing import List, Dict, Any, Tuple
from core.logger import logger
from surya.foundation import FoundationPredictor
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor
from services.validators.rotation_detector import RotationDetector, rotate_image_clockwise

# Global variables to cache the loaded models
_foundation_predictor = None
_detection_predictor = None
_recognition_predictor = None
_model_load_lock = threading.Lock()
ROTATION_AUTO_CORRECT_CONFIDENCE_THRESHOLD = 0.85


def _apply_rotation_if_confident(
    image: Image.Image,
    rotation_result: Any,
    threshold: float = ROTATION_AUTO_CORRECT_CONFIDENCE_THRESHOLD,
) -> Tuple[Image.Image, Dict[str, Any]]:
    """
    Apply the standalone rotation detector recommendation only when confidence is high.

    Returns a copied image in all cases so caller-owned PIL instances are not mutated.
    """
    result_dict = rotation_result.to_dict() if hasattr(rotation_result, "to_dict") else {}
    angle = int(getattr(rotation_result, "detected_rotation", 0) or 0)
    confidence = float(getattr(rotation_result, "confidence", 0.0) or 0.0)
    should_rotate = bool(getattr(rotation_result, "should_rotate", False))

    metadata = {
        "rotation_detection": result_dict,
        "rotation_applied": False,
        "rotation_angle": 0,
        "rotation_auto_correct_threshold": threshold,
    }

    if should_rotate and angle in {90, 180, 270} and confidence >= threshold:
        logger.warning(
            "Applying conservative rotation correction angle=%s confidence=%.4f threshold=%.2f",
            angle,
            confidence,
            threshold,
        )
        metadata["rotation_applied"] = True
        metadata["rotation_angle"] = angle
        return rotate_image_clockwise(image.copy(), angle), metadata

    return image.copy(), metadata

def load_models_if_needed():
    global _foundation_predictor, _detection_predictor, _recognition_predictor
    if _foundation_predictor is not None and _detection_predictor is not None and _recognition_predictor is not None:
        return

    with _model_load_lock:
        if _foundation_predictor is None:
            logger.info("Lazy loading Surya Foundation Predictor...")
            _foundation_predictor = FoundationPredictor()
            logger.info("Foundation Predictor loaded.")

        if _detection_predictor is None:
            logger.info("Lazy loading Surya Detection Predictor...")
            _detection_predictor = DetectionPredictor()
            logger.info("Detection Predictor loaded.")

        if _recognition_predictor is None:
            logger.info("Lazy loading Surya Recognition Predictor...")
            _recognition_predictor = RecognitionPredictor(_foundation_predictor)
            logger.info("Recognition Predictor loaded.")

def process_image(image: Image.Image, langs: List[str] = ["en"]) -> Dict[str, Any]:
    load_models_if_needed()
    image = image.copy()
    
    # 1. Orientation Normalization
    try:
        original_size = image.size
        image = ImageOps.exif_transpose(image)
        if image.size != original_size:
            logger.info("Detected coarse orientation from EXIF.")
            logger.info("Applying orientation normalization (rotated).")
        else:
            # If we wanted to add OpenCV/contour rotation fallback here, we would.
            # For now, EXIF handles the vast majority of mobile captures.
            pass
    except Exception as e:
        logger.error(f"Error during orientation normalization: {e}")
        
    rotation_result = RotationDetector().detect(image)
    image, rotation_metadata = _apply_rotation_if_confident(image, rotation_result)
    logger.info(
        "Rotation metadata: applied=%s angle=%s confidence=%.4f",
        rotation_metadata["rotation_applied"],
        rotation_metadata["rotation_angle"],
        float(getattr(rotation_result, "confidence", 0.0) or 0.0),
    )

    logger.info("Running Surya OCR (v0.17.1)")
    
    # 2. Adaptive Resolution Upscaling
    # Run coarse detection first to measure token height
    upscaled = False
    det_results = _detection_predictor([image])
    
    # ── Existing OCR-based Multi-Orientation (4-Rotation) Correction Logic ──
    image, det_results, applied_rotation, rot_confidence = RotationDetector.detect_and_correct(
        image, _detection_predictor, threshold=0.70
    )
    rotation_metadata.update({
        "legacy_rotation_applied": bool(applied_rotation),
        "legacy_rotation_angle": int(applied_rotation or 0),
        "legacy_rotation_confidence": float(rot_confidence or 0.0),
    })

    # 2. Adaptive Resolution Upscaling
    # Run coarse detection height validation after potential rotation correction
    if det_results:
        # Surya versions differ:
        # - Some return List[TextDetectionResult]
        # - surya-ocr==0.17.1 may return TextDetectionResult directly
        det_result = det_results[0] if isinstance(det_results, (list, tuple)) else det_results
        boxes = getattr(det_result, 'bboxes', None)
        heights = []
        if boxes:
            for box in boxes:
                polygon = getattr(box, 'polygon', None)
                if polygon:
                    min_y = min(p[1] for p in polygon)
                    max_y = max(p[1] for p in polygon)
                    heights.append(max_y - min_y)
                elif isinstance(box, (list, tuple)) and len(box) >= 4:
                    heights.append(box[3] - box[1])
                
        if heights:
            median_height = np.median(heights)
            logger.info(f"Median text height: {median_height:.1f}px")
            
            if median_height < 15.0:
                logger.info(f"Applying adaptive upscale factor: 2x (Dense Table detected)")
                new_size = (image.width * 2, image.height * 2)
                image = image.resize(new_size, Image.LANCZOS)
                upscaled = True
                det_results = _detection_predictor([image])

    # 3. Run Recognition
    # If we upscaled, we pass the upscaled image and the new detection boxes
    predictions = _recognition_predictor([image], det_predictor=_detection_predictor)
    
    if not predictions:
        return {"text": "", "blocks": [], "metadata": rotation_metadata}
    
    result = predictions[0]
    
    full_text = "\n".join([line.text for line in result.text_lines])
    
    blocks = []
    for line in result.text_lines:
        poly = line.polygon
        
        # If we upscaled the image, we must downscale the coordinates back to the original geometry scale
        # so that downstream processes (and bounding box drawing) align with the original input image.
        if upscaled:
            poly = [[pt[0] / 2.0, pt[1] / 2.0] for pt in poly]
            
        blocks.append({
            "text": line.text,
            "polygon": poly,
            "confidence": getattr(line, "confidence", None)
        })
    
    return {
        "text": full_text,
        "blocks": blocks,
        "metadata": rotation_metadata,
    }
