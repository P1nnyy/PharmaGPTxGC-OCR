"""Liveness and cache maintenance."""

from fastapi import APIRouter, Depends

from models.schemas import HealthResponse
from services import cache_service
from api.deps import require_super_admin
from db.repositories import audit_repository

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(status="ok")


@router.post("/clear-cache")
def clear_cache(include_azure: bool = False, user: dict = Depends(require_super_admin)):
    """Clears the local OCR result cache.

    The cached raw Azure Document Intelligence responses are NOT cleared by
    default: every entry dropped there has to be paid for again on the next
    scan. Pass include_azure=true to drop those too.
    """
    cleared = cache_service.clear_cache()
    audit_repository.record(
        "cache.cleared", actor=user, target_type="cache",
        summary=f"{user['email']} cleared the cache"
               + (" including paid Azure responses" if include_azure else ""),
        include_azure=include_azure,
    )
    payload = {"message": "Cache cleared.", "cleared_keys_count": cleared}
    if include_azure:
        payload["cleared_azure_responses"] = cache_service.clear_azure_cache()
    return payload
