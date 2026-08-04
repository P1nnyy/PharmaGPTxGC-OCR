"""Liveness and cache maintenance."""

from fastapi import APIRouter

from models.schemas import HealthResponse
from services import cache_service

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(status="ok")


@router.post("/clear-cache")
def clear_cache(include_azure: bool = False):
    """Clears the local OCR result cache.

    The cached raw Azure Document Intelligence responses are NOT cleared by
    default: every entry dropped there has to be paid for again on the next
    scan. Pass include_azure=true to drop those too.
    """
    cleared = cache_service.clear_cache()
    payload = {"message": "Cache cleared.", "cleared_keys_count": cleared}
    if include_azure:
        payload["cleared_azure_responses"] = cache_service.clear_azure_cache()
    return payload
