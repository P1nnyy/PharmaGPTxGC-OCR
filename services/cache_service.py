import hashlib
import json
import os
from typing import Optional
from core.config import settings
from core.logger import logger

logger.info(f"[PIPELINE VERSION] {settings.PIPELINE_VERSION}")

def _versioned_key(invoice_id: str) -> str:
    """Generate a cache key incorporating pipeline version to prevent stale reuse."""
    return f"{invoice_id}_v{settings.PIPELINE_VERSION}"

def compute_md5(file_bytes: bytes) -> str:
    return hashlib.md5(file_bytes).hexdigest()

def get_cached_result(invoice_id: str) -> Optional[dict]:
    if not settings.ENABLE_CACHE:
        return None
        
    cache_key = _versioned_key(invoice_id)
    cache_path = os.path.join(settings.OCR_RESULTS_DIR, f"{cache_key}.json")
    if os.path.exists(cache_path):
        logger.info(f"Cache hit for invoice_id: {invoice_id} (key: {cache_key})")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read cache for {cache_key}: {e}")
            return None
            
    logger.info(f"Cache miss for invoice_id: {invoice_id} (key: {cache_key})")
    return None

def save_result(invoice_id: str, data: dict):
    os.makedirs(settings.OCR_RESULTS_DIR, exist_ok=True)
    cache_key = _versioned_key(invoice_id)
    cache_path = os.path.join(settings.OCR_RESULTS_DIR, f"{cache_key}.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved OCR result to cache for invoice_id: {invoice_id} (key: {cache_key})")
    except Exception as e:
        logger.error(f"Failed to save cache for {cache_key}: {e}")

