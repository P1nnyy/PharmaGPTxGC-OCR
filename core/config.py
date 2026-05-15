import os
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    PROJECT_NAME: str = "PharmaGPT OCR API"
    LOG_LEVEL: str = "INFO"
    DATASETS_DIR: str = "datasets"
    OCR_RESULTS_DIR: Optional[str] = None
    ENABLE_CACHE: bool = True
    PIPELINE_VERSION: str = "2.0"
    ENABLE_PPSTRUCTURE: bool = False
    TSR_PRIMARY_ENGINE: str = "heuristic_anchor"
    ENABLE_PPSTRUCTURE_MULTI_ORIENTATION: bool = False
    PPSTRUCTURE_CONFIDENCE_THRESHOLD: float = 0.40
    MAX_UPLOAD_SIZE_BYTES: int = 20 * 1024 * 1024

    @model_validator(mode="after")
    def derive_ocr_results_dir(self):
        if not self.OCR_RESULTS_DIR:
            self.OCR_RESULTS_DIR = os.path.join(self.DATASETS_DIR, "ocr_results")
        return self

settings = Settings()
