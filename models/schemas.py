from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class HealthResponse(BaseModel):
    status: str
    gpu_available: bool
    gpu_name: Optional[str] = None
    cuda_version: Optional[str] = None

class OCRMetadata(BaseModel):
    blocks: List[Dict[str, Any]] = []
    reconstructed_rows: Optional[List[Dict[str, Any]]] = None
    detected_table_rows: Optional[List[Dict[str, Any]]] = None
    structured_tables: Optional[List[Dict[str, Any]]] = None
    columns_extracted: Optional[bool] = None
    metrics: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"

class OCRResponse(BaseModel):
    invoice_id: str
    cached: bool
    text: str
    metadata: OCRMetadata
