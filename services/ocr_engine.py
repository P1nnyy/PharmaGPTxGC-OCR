import os
import threading
from PIL import Image, ImageOps
import numpy as np
from typing import List, Dict, Any, Tuple
from pathlib import Path
from io import BytesIO
import base64
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
LEGACY_ROTATION_CONTRADICTION_MARGIN = 0.20


def _image_data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _save_processed_image(image: Image.Image, path: str) -> str:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return str(output_path)


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


def _rotation_score(rotation_detection: Dict[str, Any], angle: int) -> float:
    scores = rotation_detection.get("scores") or {}
    value = scores.get(angle, scores.get(str(angle), 0.0))
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _orientation_ambiguity_metadata(rotation_detection: Dict[str, Any]) -> Dict[str, Any]:
    rotation_detection = rotation_detection if isinstance(rotation_detection, dict) else {}
    scores = rotation_detection.get("scores") if isinstance(rotation_detection, dict) else {}
    normalized_scores = {}
    if isinstance(scores, dict):
        for key, value in scores.items():
            try:
                normalized_scores[int(key)] = float(value)
            except (TypeError, ValueError):
                continue

    ranked = sorted(normalized_scores.items(), key=lambda item: item[1], reverse=True)
    best_candidate = ranked[0][0] if ranked else rotation_detection.get("metadata", {}).get("best_candidate")
    second_candidate = ranked[1][0] if len(ranked) > 1 else None
    best_score = ranked[0][1] if ranked else _rotation_score(rotation_detection, int(best_candidate or 0))
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    metadata = rotation_detection.get("metadata") if isinstance(rotation_detection.get("metadata"), dict) else {}
    min_margin = float(metadata.get("min_margin") or 0.12)
    score_margin = float(metadata.get("score_margin") if metadata.get("score_margin") is not None else best_score - second_score)
    orientation_ambiguous = bool(score_margin < min_margin)
    return {
        "orientation_ambiguous": orientation_ambiguous,
        "score_margin": round(score_margin, 4),
        "best_candidate": best_candidate,
        "second_candidate": second_candidate,
        "candidate_scores": {str(key): round(value, 4) for key, value in normalized_scores.items()},
        "orientation_ambiguity_reason": (
            f"score_margin_below_min_margin:{score_margin:.4f}<{min_margin:.4f}"
            if orientation_ambiguous
            else None
        ),
    }


def _legacy_rotation_contradicted_by_detector(
    rotation_metadata: Dict[str, Any],
    legacy_rotation_angle: int,
    margin: float = LEGACY_ROTATION_CONTRADICTION_MARGIN,
) -> bool:
    legacy_angle = int(legacy_rotation_angle or 0) % 360
    if legacy_angle not in {90, 180, 270}:
        return False

    rotation_detection = rotation_metadata.get("rotation_detection") or {}
    if bool(rotation_detection.get("should_rotate")):
        detected_angle = int(rotation_detection.get("detected_rotation") or 0) % 360
        return detected_angle not in {0, legacy_angle}

    legacy_score = _rotation_score(rotation_detection, legacy_angle)
    upright_scores = [
        _rotation_score(rotation_detection, angle)
        for angle in (0, 180)
        if angle != legacy_angle
    ]
    best_upright_score = max(upright_scores or [0.0])
    return best_upright_score >= legacy_score + margin


def _finalize_rotation_metadata(
    *,
    original_size: Tuple[int, int],
    processed_image: Image.Image,
    rotation_metadata: Dict[str, Any],
    legacy_rotation_angle: int = 0,
    legacy_rotation_confidence: float = 0.0,
    processed_image_path: str | None = None,
    include_processed_image_data_url: bool = False,
) -> Dict[str, Any]:
    original_width, original_height = original_size
    processed_width, processed_height = processed_image.size
    legacy_angle = int(legacy_rotation_angle or 0) % 360
    detector_angle = int(rotation_metadata.get("rotation_angle") or 0) % 360
    detector_applied = bool(rotation_metadata.get("rotation_applied"))

    legacy_contradicted = _legacy_rotation_contradicted_by_detector(rotation_metadata, legacy_angle)

    if legacy_angle in {90, 180, 270} and not legacy_contradicted:
        rotation_angle = legacy_angle
        rotation_applied = True
        rotation_source = "legacy_ocr_detection"
        orientation_confidence = float(legacy_rotation_confidence or 0.0)
    elif detector_applied and detector_angle in {90, 180, 270}:
        rotation_angle = detector_angle
        rotation_applied = True
        rotation_source = "projection_edge_density"
        orientation_confidence = float(
            (rotation_metadata.get("rotation_detection") or {}).get("confidence") or 0.0
        )
    else:
        rotation_angle = 0
        rotation_applied = False
        rotation_source = "none"
        orientation_confidence = float(
            (rotation_metadata.get("rotation_detection") or {}).get("confidence") or legacy_rotation_confidence or 0.0
        )

    if legacy_contradicted:
        logger.warning(
            "Ignoring legacy OCR rotation angle=%s because standalone detector scores contradict it.",
            legacy_angle,
        )

    swapped = original_width == processed_height and original_height == processed_width
    if swapped and not rotation_applied:
        rotation_angle = legacy_angle if legacy_angle in {90, 270} else (detector_angle if detector_angle in {90, 270} else 90)
        rotation_applied = True
        rotation_source = "inferred_from_processed_dimensions"

    same_size = original_width == processed_width and original_height == processed_height
    if not rotation_applied and not same_size:
        logger.warning(
            "Processed image dimensions changed without a rotation decision: original=%s processed=%s",
            original_size,
            processed_image.size,
        )

    rotation_detection = rotation_metadata.get("rotation_detection") or {}
    ambiguity = _orientation_ambiguity_metadata(rotation_detection)
    processed_image_metadata = {
        "original_width": int(original_width),
        "original_height": int(original_height),
        "processed_width": int(processed_width),
        "processed_height": int(processed_height),
        "rotation_angle": int(rotation_angle),
        "rotation_applied": bool(rotation_applied),
        "rotation_source": rotation_source,
        "rotation_method": rotation_source,
        "orientation_confidence": orientation_confidence,
        "coordinate_space": "processed_image",
        "coordinates_based_on": "processed_image",
        "rotation_detection": rotation_detection,
        **ambiguity,
    }
    if processed_image_path:
        processed_image_metadata["processed_image_path"] = _save_processed_image(
            processed_image,
            processed_image_path,
        )
    if include_processed_image_data_url:
        processed_image_metadata["processed_image_data_url"] = _image_data_url(processed_image)

    final_metadata = {
        **rotation_metadata,
        "rotation_applied": bool(rotation_applied),
        "rotation_angle": int(rotation_angle),
        "rotation_source": rotation_source,
        "rotation_method": rotation_source,
        "orientation_confidence": orientation_confidence,
        **ambiguity,
        "processed_image": processed_image_metadata,
    }
    final_metadata.pop("legacy_rotation_applied", None)
    final_metadata.pop("legacy_rotation_angle", None)
    final_metadata.pop("legacy_rotation_confidence", None)
    return final_metadata


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

def process_image(
    image: Image.Image,
    langs: List[str] = ["en"],
    processed_image_path: str | None = None,
    include_processed_image_data_url: bool = False,
    bypass_rotation_detection: bool = False,
) -> Dict[str, Any]:
    load_models_if_needed()
    image = image.copy()
    original_width, original_height = image.size
    
    if bypass_rotation_detection:
        rotation_metadata = {
            "rotation_applied": False,
            "rotation_angle": 0,
            "rotation_source": "bypass",
            "orientation_confidence": 1.0,
            "orientation_ambiguous": False,
            "score_margin": 1.0,
            "processed_image": {
                "original_width": original_width,
                "original_height": original_height,
                "processed_width": original_width,
                "processed_height": original_height,
                "rotation_angle": 0,
                "rotation_applied": False,
                "rotation_source": "bypass",
                "orientation_confidence": 1.0,
                "coordinate_space": "processed_image",
                "coordinates_based_on": "processed_image",
                "orientation_ambiguous": False,
                "score_margin": 1.0,
                "best_candidate": 0,
                "second_candidate": None,
                "candidate_scores": {"0": 1.0},
                "orientation_ambiguity_reason": None,
            }
        }
        logger.info("Bypassing rotation detection, running Surya OCR on current orientation.")
        logger.info("Running Surya OCR (v0.17.1)")
        upscaled = False
        det_results = _detection_predictor([image])
    else:
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
        
        # OCR-based Multi-Orientation (4-Rotation) Correction Logic.
        # This legacy detector may still be useful for dense invoices, but its
        # decision is folded into the same authoritative orientation metadata.
        pre_legacy_image = image.copy()
        pre_legacy_det_results = det_results
        legacy_image, legacy_det_results, applied_rotation, rot_confidence = RotationDetector.detect_and_correct(
            image, _detection_predictor, threshold=0.70
        )
        if _legacy_rotation_contradicted_by_detector(rotation_metadata, int(applied_rotation or 0)):
            logger.warning(
                "Discarding legacy OCR rotation angle=%s confidence=%.4f due to standalone detector contradiction.",
                applied_rotation,
                float(rot_confidence or 0.0),
            )
            image = pre_legacy_image
            det_results = pre_legacy_det_results
            applied_rotation = 0
            rot_confidence = 0.0
        else:
            image = legacy_image
            det_results = legacy_det_results
        coordinate_image = image.copy()
        rotation_metadata = _finalize_rotation_metadata(
            original_size=(original_width, original_height),
            processed_image=coordinate_image,
            rotation_metadata=rotation_metadata,
            legacy_rotation_angle=int(applied_rotation or 0),
            legacy_rotation_confidence=float(rot_confidence or 0.0),
            processed_image_path=processed_image_path,
            include_processed_image_data_url=include_processed_image_data_url,
        )

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
