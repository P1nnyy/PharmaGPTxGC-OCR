from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "PharmaGPT OCR API"
    LOG_LEVEL: str = "INFO"
    DATASETS_DIR: str = "datasets"
    OCR_RESULTS_DIR: str = f"{DATASETS_DIR}/ocr_results"
    ENABLE_CACHE: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
