import os
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "PharmaGPT OCR API"
    LOG_LEVEL: str = "INFO"
    DATASETS_DIR: str = "datasets"
    OCR_RESULTS_DIR: Optional[str] = None
    ENABLE_CACHE: bool = True
    PIPELINE_VERSION: str = "2.0"
    
    # Azure Document Intelligence Configuration
    AZURE_DOCUMENT_ENDPOINT: str = ""
    AZURE_DOCUMENT_KEY: str = ""

    # Neo4j Aura Configuration
    NEO4J_URI: str = ""
    NEO4J_USERNAME: str = ""
    NEO4J_PASSWORD: str = ""

    # Cloudflare R2 Configuration
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""

    # Bootstrap tenant used until real multi-user auth exists
    DEFAULT_PHARMACY_ID: str = "default-pharmacy"
    DEFAULT_PHARMACY_NAME: str = "My Pharmacy"
    DEFAULT_USER_ID: str = "default-user"
    DEFAULT_USER_EMAIL: str = "admin@pharmaflow.local"

    MAX_UPLOAD_SIZE_BYTES: int = 20 * 1024 * 1024
    IMAGE_MIN_SIDE_PX: int = 256
    IMAGE_MAX_SIDE_PX: int = 4096
    IMAGE_MIN_ASPECT_RATIO: float = 0.5
    IMAGE_MAX_ASPECT_RATIO: float = 2.0
    IMAGE_MIN_DPI_WARNING: float = 150

    # Pre-flight content gate: rejects structurally empty images before the
    # billable Azure call. Tuned strictly toward NOT rejecting real invoices -
    # see services/validators/content_validator.py for the measured separation
    # these sit between (real imagery coherence >= 0.93, noise <= 0.36).
    # Upper bound on pages accepted as a single invoice. Each page is a
    # separate billable extraction, so this caps the cost of one submission.
    MAX_INVOICE_PAGES: int = 10

    CONTENT_GATE_ENABLED: bool = True
    CONTENT_MIN_DYNAMIC_RANGE: float = 28.0
    CONTENT_MIN_STD_DEV: float = 6.0
    CONTENT_MIN_COHERENCE: float = 0.60

    @model_validator(mode="after")
    def derive_ocr_results_dir(self):
        if not self.OCR_RESULTS_DIR:
            self.OCR_RESULTS_DIR = os.path.join(self.DATASETS_DIR, "ocr_results")
        return self

settings = Settings()
