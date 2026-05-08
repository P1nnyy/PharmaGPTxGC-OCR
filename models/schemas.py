from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class HealthResponse(BaseModel):
    status: str
    gpu_available: bool
    gpu_name: Optional[str] = None
    cuda_version: Optional[str] = None

class OCRResponse(BaseModel):
    invoice_id: str
    cached: bool
    text: str
    metadata: Dict[str, Any]
