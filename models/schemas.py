from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class HealthResponse(BaseModel):
    status: str
    gpu_available: bool
    gpu_name: Optional[str] = None
    cuda_version: Optional[str] = None

class ImageProperties(BaseModel):
    width: int
    height: int
    aspect_ratio: float
    estimated_dpi: int
    color_space: str
    likely_rotation: Optional[int] = None

class ImageValidationReport(BaseModel):
    is_valid: bool
    quality_score: float
    warnings: List[str] = []
    properties: ImageProperties

class OCRMetadata(BaseModel):
    blocks: List[Dict[str, Any]] = []
    reconstructed_rows: Optional[List[Dict[str, Any]]] = None
    detected_table_rows: Optional[List[Dict[str, Any]]] = None
    structured_tables: Optional[List[Dict[str, Any]]] = None
    columns_extracted: Optional[bool] = None
    metrics: Optional[Dict[str, Any]] = None
    image_validation: Optional[ImageValidationReport] = None

    class Config:
        extra = "allow"

class OCRResponse(BaseModel):
    invoice_id: str
    cached: bool
    text: str
    metadata: OCRMetadata
