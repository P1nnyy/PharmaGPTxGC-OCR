from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "PharmaGPT OCR API"
    LOG_LEVEL: str = "INFO"
    DATASETS_DIR: str = "datasets"
    OCR_RESULTS_DIR: str = f"{DATASETS_DIR}/ocr_results"
    ENABLE_CACHE: bool = True
    PIPELINE_VERSION: str = "2.0"
    ENABLE_PPSTRUCTURE: bool = False
    TSR_PRIMARY_ENGINE: str = "heuristic_anchor"
    ENABLE_PPSTRUCTURE_MULTI_ORIENTATION: bool = False
    PPSTRUCTURE_CONFIDENCE_THRESHOLD: float = 0.40

    class Config:
        env_file = ".env"

settings = Settings()
