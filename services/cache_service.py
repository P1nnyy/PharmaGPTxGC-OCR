import hashlib
import json
import os
import uuid
from typing import Optional
from core.config import settings
from core.logger import logger

# Log the active pipeline version on initialization
logger.info(f"[PIPELINE VERSION] {settings.PIPELINE_VERSION}")

# Track cache status globally to prevent repetitive check overhead
_CACHE_WRITABLE: Optional[bool] = None
_CACHE_STATUS_LOGGED = False
_CACHE_WARNING_LOGGED = False
_SAVE_DISABLED_FOR_PROCESS = False

# Keys representing layout reconstruction results that should not be cached.
# We always regenerate reconstruction on the fly to support live layout edits.
RECONSTRUCTION_RESPONSE_KEYS = {
    "reconstructed_rows",
    "detected_table_rows",
    "structured_tables",
    "columns_extracted",
    "metrics",
    "semantic_markdown",
    "table_routing",
    "invoice_confidence",
    "financial_validation",
    "auxiliary_tables",
    "topology_source",
    "fast_fail",
    "fast_fail_reason",
}

OCR_METADATA_KEYS = {
    "rotation_detection",
    "rotation_applied",
    "rotation_angle",
    "rotation_auto_correct_threshold",
    "legacy_rotation_applied",
    "legacy_rotation_angle",
    "legacy_rotation_confidence",
    "processed_image",
}

def _cache_fix_suggestion(path: str) -> str:
    # Generates a standard command suggestion to resolve file permissions on the directory
    return f"Fix with: sudo chown -R $USER:$USER {path} && chmod -R u+rwX {path}"

def _versioned_key(invoice_id: str) -> str:
    """Generate a cache key incorporating pipeline version to prevent stale reuse."""
    # Append the pipeline version to make caches self-invalidating when version increments
    return f"{invoice_id}_v{settings.PIPELINE_VERSION}"

def _log_cache_warning_once(path: str, reason: str):
    global _CACHE_WARNING_LOGGED
    if _CACHE_WARNING_LOGGED:
        return
    # Use global tracking to ensure we only log the warning once per process lifecycle
    logger.warning(
        f"[CACHE STATUS] Cache disabled due to unwritable path. "
        f"path={path} reason={reason}. {_cache_fix_suggestion(path)}"
    )
    _CACHE_WARNING_LOGGED = True

def check_cache_status(log_status: bool = True) -> bool:
    """
    Ensure the OCR cache directory exists and is writable.
    Disables save attempts for this process if the path is unwritable.
    """
    global _CACHE_WRITABLE, _CACHE_STATUS_LOGGED, _SAVE_DISABLED_FOR_PROCESS

    path = settings.OCR_RESULTS_DIR
    writable = False
    reason = ""

    if not settings.ENABLE_CACHE:
        reason = "cache_disabled_by_config"
        _SAVE_DISABLED_FOR_PROCESS = True
    else:
        try:
            # Recursively build paths to cache output directory
            os.makedirs(path, exist_ok=True)
            # Create a short-lived random probe file to guarantee write/delete capabilities
            probe_path = os.path.join(path, f".cache_write_probe_{uuid.uuid4().hex}")
            with open(probe_path, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe_path)
            writable = True
            _SAVE_DISABLED_FOR_PROCESS = False
        except PermissionError as e:
            reason = f"permission_denied:{e}"
            _SAVE_DISABLED_FOR_PROCESS = True
        except OSError as e:
            reason = f"os_error:{e}"
            _SAVE_DISABLED_FOR_PROCESS = True

    _CACHE_WRITABLE = writable

    if log_status and not _CACHE_STATUS_LOGGED:
        logger.info(f"[CACHE STATUS] writable={str(writable).lower()} path={path}")
        _CACHE_STATUS_LOGGED = True

    if not writable and settings.ENABLE_CACHE:
        _log_cache_warning_once(path, reason or "unknown")

    return writable

def compute_md5(file_bytes: bytes) -> str:
    # MD5 hashing logic that supports both python standard libraries with security flags and standard platforms
    try:
        return hashlib.md5(file_bytes, usedforsecurity=False).hexdigest()
    except TypeError:
        return hashlib.md5(file_bytes).hexdigest()

def _ocr_only_payload(data: dict) -> dict:
    """
    Return only cached OCR primitives. Cached reconstruction output is intentionally
    ignored so current code always rebuilds layout, routing, metrics, and validation.
    """
    if not isinstance(data, dict):
        return {"text": "", "blocks": []}

    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    blocks = data.get("blocks")
    if blocks is None:
        blocks = metadata.get("blocks", [])

    text = data.get("text", "")
    if not text and isinstance(metadata.get("text"), str):
        text = metadata.get("text", "")

    ocr_metadata = {
        key: metadata[key]
        for key in OCR_METADATA_KEYS
        if key in metadata
    }

    return {
        "text": text,
        "blocks": blocks or [],
        "metadata": ocr_metadata,
    }

def get_cached_result(invoice_id: str) -> Optional[dict]:
    if not settings.ENABLE_CACHE:
        return None
        
    cache_key = _versioned_key(invoice_id)
    cache_path = os.path.join(settings.OCR_RESULTS_DIR, f"{cache_key}.json")
    if os.path.exists(cache_path):
        logger.info(f"Cache hit for invoice_id: {invoice_id} (key: {cache_key})")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            logger.info("Cached reconstruction response disabled")
            # Strip out cached layout topology and return clean primitive OCR coordinates
            return _ocr_only_payload(cached_data)
        except Exception as e:
            logger.error(f"Failed to read cache for {cache_key}: {e}")
            return None
            
    logger.info(f"Cache miss for invoice_id: {invoice_id} (key: {cache_key})")
    return None

def save_result(invoice_id: str, data: dict):
    global _SAVE_DISABLED_FOR_PROCESS, _CACHE_WRITABLE

    if not settings.ENABLE_CACHE:
        return
    if _SAVE_DISABLED_FOR_PROCESS:
        return
    if _CACHE_WRITABLE is not True and not check_cache_status(log_status=False):
        return

    cache_key = _versioned_key(invoice_id)
    cache_path = os.path.join(settings.OCR_RESULTS_DIR, f"{cache_key}.json")
    try:
        # Strip all reconstruction items from results before dumping to cache
        data = _ocr_only_payload(data)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved OCR result to cache for invoice_id: {invoice_id} (key: {cache_key})")
    except PermissionError as e:
        _SAVE_DISABLED_FOR_PROCESS = True
        _CACHE_WRITABLE = False
        _log_cache_warning_once(settings.OCR_RESULTS_DIR, f"permission_denied:{e}")
    except OSError as e:
        _SAVE_DISABLED_FOR_PROCESS = True
        _CACHE_WRITABLE = False
        _log_cache_warning_once(settings.OCR_RESULTS_DIR, f"os_error:{e}")
    except Exception as e:
        logger.warning(f"Failed to save cache for {cache_key}: {type(e).__name__}: {e}")

def clear_all_cache() -> int:
    """
    Deletes all JSON files stored in the OCR_RESULTS_DIR directory.
    Returns the total number of files successfully deleted.
    """
    path = settings.OCR_RESULTS_DIR
    if not os.path.exists(path):
        logger.info(f"Cache directory does not exist, nothing to clear: {path}")
        return 0
        
    deleted_count = 0
    # List files and filter for JSON results
    for filename in os.listdir(path):
        if filename.endswith(".json"):
            file_path = os.path.join(path, filename)
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to remove cache file {file_path}: {e}")
                
    logger.info(f"Cleared OCR cache: deleted {deleted_count} files from {path}")
    return deleted_count
