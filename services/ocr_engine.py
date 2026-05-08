import os
from PIL import Image
from typing import List, Dict, Any
from core.logger import logger
from surya.ocr import run_ocr
from surya.model.detection.model import load_model as load_det_model, load_processor as load_det_processor
from surya.model.recognition.model import load_model as load_rec_model
from surya.model.recognition.processor import load_processor as load_rec_processor

# Global variables to cache the loaded models
_det_model = None
_det_processor = None
_rec_model = None
_rec_processor = None

def load_models_if_needed():
    global _det_model, _det_processor, _rec_model, _rec_processor
    if _det_model is None:
        logger.info("Lazy loading Surya OCR detection models...")
        _det_processor = load_det_processor()
        _det_model = load_det_model()
        logger.info("Detection models loaded.")
    
    if _rec_model is None:
        logger.info("Lazy loading Surya OCR recognition models...")
        _rec_processor = load_rec_processor()
        _rec_model = load_rec_model()
        logger.info("Recognition models loaded.")

def process_image(image: Image.Image, langs: List[str] = ["en"]) -> Dict[str, Any]:
    load_models_if_needed()
    logger.info(f"Running Surya OCR with languages: {langs}")
    
    # run_ocr expects lists of images and lists of langs
    predictions = run_ocr([image], [langs], _det_model, _det_processor, _rec_model, _rec_processor)
    
    if not predictions:
        return {"text": "", "blocks": []}
    
    result = predictions[0]
    
    full_text = "\n".join([line.text for line in result.text_lines])
    
    blocks = [
        {
            "text": line.text,
            "bbox": line.bbox,
            "confidence": getattr(line, "confidence", None)
        }
        for line in result.text_lines
    ]
    
    return {
        "text": full_text,
        "blocks": blocks
    }
