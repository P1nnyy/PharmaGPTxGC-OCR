import os
from PIL import Image
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
    logger.info("Running Surya OCR (v0.17.1)")
    
    predictions = _recognition_predictor([image], det_predictor=_detection_predictor)
    
    if not predictions:
        return {"text": "", "blocks": []}
    
    result = predictions[0]
    
    full_text = "\n".join([line.text for line in result.text_lines])
    
    blocks = [
        {
            "text": line.text,
            "polygon": line.polygon,
            "confidence": getattr(line, "confidence", None)
        }
        for line in result.text_lines
    ]
    
    return {
        "text": full_text,
        "blocks": blocks
    }
