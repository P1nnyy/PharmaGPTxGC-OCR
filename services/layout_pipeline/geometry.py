import re
from typing import Dict, Any, List
from models.layout_models import OCRBlock, GeometryBox

def compute_base_geometry(block_data: Dict[str, Any]) -> OCRBlock:
    """
    Computes initial bounding box geometry from an OCR polygon and returns a typed OCRBlock.
    Also sanitizes OCR text of HTML/markup.
    """
    polygon = block_data.get("polygon", [])
    raw_text = block_data.get("text", "")
    block_id = block_data.get("id")
    
    # Text Sanitization
    clean_text = re.sub(r"<[^>]+>", "", raw_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    
    if not polygon or len(polygon) < 3:
        geom = GeometryBox(
            min_x=0.0, max_x=0.0,
            min_y=0.0, max_y=0.0,
            center_x=0.0, center_y=0.0
        )
        return OCRBlock(
            id=block_id,
            raw_text=raw_text,
            text=clean_text,
            polygon=polygon,
            original_geometry=geom,
            normalized_geometry=geom.model_copy()
        )
        
    xs = [pt[0] for pt in polygon]
    ys = [pt[1] for pt in polygon]
    
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    
    geom = GeometryBox(
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
        center_x=(min_x + max_x) / 2.0,
        center_y=(min_y + max_y) / 2.0
    )
    
    return OCRBlock(
        id=block_id,
        raw_text=raw_text,
        text=clean_text,
        polygon=polygon,
        original_geometry=geom,
        normalized_geometry=geom.model_copy()
    )

def process_blocks(raw_blocks: List[Dict[str, Any]]) -> List[OCRBlock]:
    return [compute_base_geometry(b) for b in raw_blocks]
