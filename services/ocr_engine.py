import os
from PIL import Image, ImageOps
import numpy as np
from typing import List, Dict, Any
from core.logger import logger
from surya.foundation import FoundationPredictor
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor

# Global variables to cache the loaded models
_foundation_predictor = None
_detection_predictor = None
_recognition_predictor = None

def load_models_if_needed():
    global _foundation_predictor, _detection_predictor, _recognition_predictor
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
        
    logger.info("Running Surya OCR (v0.17.1)")
    
    # 2. Adaptive Resolution Upscaling
    # Run coarse detection first to measure token height
    upscaled = False
    det_results = _detection_predictor([image])
    
    # ── 180° Rotation Correction Logic (Failure Mode 5) ──
    # Check if text flow goes from bottom-to-top (indicates 180 inversion)
    if det_results and det_results[0].bboxes:
        boxes = det_results[0].bboxes
        if len(boxes) >= 10:
            # Get Y centers for all boxes in temporal order
            y_vals = []
            for b in boxes:
                 poly = getattr(b, 'polygon', [])
                 if poly:
                     y_vals.append(sum(p[1] for p in poly)/len(poly))
            
            if len(y_vals) >= 10:
                 mid = len(y_vals) // 2
                 avg_first = sum(y_vals[:mid]) / mid
                 avg_second = sum(y_vals[mid:]) / (len(y_vals) - mid)
                 # In standard flow, avg_second > avg_first. If strongly inverted, flip image.
                 if avg_second < (avg_first - 50): 
                     logger.warning(f"🚨 Image 180° inversion detected (AvgY1={avg_first:.0f}, AvgY2={avg_second:.0f}). Rotating 180°...")
                     image = image.rotate(180, expand=True)
                     # RERUN detection on fixed orientation image
                     det_results = _detection_predictor([image])

    # 2. Adaptive Resolution Upscaling
    # Run coarse detection height validation after potential rotation correction
    if det_results:
        boxes = getattr(det_results[0], 'bboxes', None)
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
        return {"text": "", "blocks": []}
    
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
        "blocks": blocks
    }
