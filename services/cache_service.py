import hashlib
import json
import os
import re
import uuid
from typing import Optional
from core.config import settings
from core.logger import logger

logger.info(f"[PIPELINE VERSION] {settings.PIPELINE_VERSION}")

_CACHE_WRITABLE: Optional[bool] = None
_CACHE_STATUS_LOGGED = False
_CACHE_WARNING_LOGGED = False
_SAVE_DISABLED_FOR_PROCESS = False

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

def _cache_fix_suggestion(path: str) -> str:
    return f"Fix with: sudo chown -R $USER:$USER {path} && chmod -R u+rwX {path}"

def _versioned_key(invoice_id: str) -> str:
    """Generate a cache key incorporating pipeline version to prevent stale reuse."""
    return f"{invoice_id}_v{settings.PIPELINE_VERSION}"

def _log_cache_warning_once(path: str, reason: str):
    global _CACHE_WARNING_LOGGED
    if _CACHE_WARNING_LOGGED:
        return
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
            os.makedirs(path, exist_ok=True)
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

def clear_cache() -> int:
    """Deletes all cached OCR result JSON files. Returns the number of files removed."""
    path = settings.OCR_RESULTS_DIR
    if not os.path.isdir(path):
        return 0

    cleared = 0
    for name in os.listdir(path):
        if name.endswith(".json"):
            try:
                os.remove(os.path.join(path, name))
                cleared += 1
            except OSError as e:
                logger.warning(f"Failed to remove cache file {name}: {e}")

    logger.info(f"[CACHE CLEARED] removed {cleared} cached result(s) from {path}")
    return cleared

def compute_md5(file_bytes: bytes) -> str:
    try:
        return hashlib.md5(file_bytes, usedforsecurity=False).hexdigest()
    except TypeError:
        return hashlib.md5(file_bytes).hexdigest()

# --- Raw Azure Document Intelligence response cache -------------------------
#
# Kept deliberately separate from the OCR cache above. That one runs every
# payload through _ocr_only_payload, which flattens to {text, blocks} and so
# destroys the tables/documents structure the invoice normalizer needs.
#
# What's cached here is the *unmodified* Azure response - the part that costs
# money. Normalization is re-run on every request against the cached raw
# response, so fixing a normalizer bug (a mis-read header, a missed footer
# label) re-applies to every previously-scanned invoice for free instead of
# requiring a paid re-scan. That's the whole point of caching at this layer
# rather than caching the finished CanonicalInvoice.

AZURE_RAW_SUBDIR = "azure_raw"

def _azure_cache_dir() -> str:
    return os.path.join(settings.OCR_RESULTS_DIR, AZURE_RAW_SUBDIR)

def azure_cache_key(file_bytes: bytes, model_id: str) -> str:
    """Content hash + model id. The model id is part of the key because the
    same bytes analyzed by a different DI model produce a different response,
    so a model switch must miss rather than silently reuse."""
    safe_model = re.sub(r"[^A-Za-z0-9._-]", "_", str(model_id or "unknown"))
    return f"{compute_md5(file_bytes)}_{safe_model}"

def get_cached_azure_response(cache_key: str) -> Optional[dict]:
    """Returns the cached raw Azure response, or None on miss/unreadable."""
    if not settings.ENABLE_CACHE:
        return None

    cache_path = os.path.join(_azure_cache_dir(), f"{cache_key}.json")
    if not os.path.exists(cache_path):
        logger.info(f"[AZURE CACHE] miss key={cache_key}")
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # A corrupt/truncated entry must not wedge extraction - fall through
        # to a live call, which will overwrite this entry on success.
        logger.warning(f"[AZURE CACHE] unreadable entry key={cache_key}: {type(e).__name__}: {e}")
        return None

    if not isinstance(data, dict):
        logger.warning(f"[AZURE CACHE] ignoring non-dict entry key={cache_key}")
        return None

    logger.info(f"[AZURE CACHE] HIT key={cache_key} (skipped a paid Azure call)")
    return data

def save_azure_response(cache_key: str, raw_response: dict) -> bool:
    """Persists a raw Azure response. Returns True if it was written."""
    global _SAVE_DISABLED_FOR_PROCESS, _CACHE_WRITABLE

    if not settings.ENABLE_CACHE or _SAVE_DISABLED_FOR_PROCESS:
        return False
    if _CACHE_WRITABLE is not True and not check_cache_status(log_status=False):
        return False
    if not isinstance(raw_response, dict):
        return False

    cache_dir = _azure_cache_dir()
    cache_path = os.path.join(cache_dir, f"{cache_key}.json")
    try:
        os.makedirs(cache_dir, exist_ok=True)
        # Write to a temp file then move, so an interrupted write can't leave a
        # half-written entry that later reads would treat as a usable response.
        tmp_path = f"{cache_path}.{uuid.uuid4().hex}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw_response, f, ensure_ascii=False, default=str)
        os.replace(tmp_path, cache_path)
        logger.info(f"[AZURE CACHE] stored key={cache_key}")
        return True
    except (PermissionError, OSError) as e:
        _log_cache_warning_once(cache_dir, f"azure_raw_write_failed:{e}")
        return False
    except Exception as e:
        logger.warning(f"[AZURE CACHE] failed to store key={cache_key}: {type(e).__name__}: {e}")
        return False

def clear_azure_cache() -> int:
    """Deletes cached raw Azure responses. Separate from clear_cache() because
    every entry dropped here is one that has to be paid for again."""
    path = _azure_cache_dir()
    if not os.path.isdir(path):
        return 0

    cleared = 0
    for name in os.listdir(path):
        if name.endswith(".json"):
            try:
                os.remove(os.path.join(path, name))
                cleared += 1
            except OSError as e:
                logger.warning(f"Failed to remove Azure cache file {name}: {e}")

    logger.info(f"[AZURE CACHE CLEARED] removed {cleared} raw response(s) from {path}")
    return cleared

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

    return {
        "text": text,
        "blocks": blocks or [],
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
