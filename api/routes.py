from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from core.config import settings
from core.logger import logger
from models.schemas import HealthResponse, OCRResponse
from services import cache_service, ocr_engine, spatial_reconstruction
from services.diagnostics_writer import (
    list_diagnostic_artifacts,
    normalize_orientation_metadata,
    resolve_diagnostic_artifact_path,
    write_upload_diagnostics,
)
from services.error_handler import classify_error
from services.llm_extractor import LLMExtractor
from PIL import Image
import io
import torch
from pathlib import Path
from typing import Any, Dict

router = APIRouter()


def _is_no_valid_table_candidate(metadata: Dict[str, Any]) -> bool:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    return (
        metadata.get("fast_fail_reason") == "no_valid_table_candidate"
        or metrics.get("no_valid_table_candidate") is True
        or metadata.get("selected_table_available") is False
        or metrics.get("selected_table_available") is False
    )


def _safe_tax_summary() -> Dict[str, float]:
    return {
        "taxable_value": 0.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "igst": 0.0,
        "total_gst": 0.0,
        "total_tax": 0.0,
    }


def _safe_llm_extraction_defaults() -> Dict[str, Any]:
    return {
        "metadata": {},
        "items": [],
        "scheme_items": [],
        "credit_notes": [],
        "subtotal": 0.0,
        "tax": _safe_tax_summary(),
        "grand_total": 0.0,
        "extra_data": {"fast_fail_reason": "no_valid_table_candidate"},
    }


def _apply_no_valid_table_response_defaults(
    metadata: Dict[str, Any],
    *,
    invoice_id: str,
    filename: str | None,
) -> Dict[str, Any]:
    if not _is_no_valid_table_candidate(metadata):
        return metadata

    metadata["invoice_id"] = metadata.get("invoice_id") or invoice_id
    metadata["filename"] = filename
    metadata["fast_fail"] = True
    metadata["fast_fail_reason"] = "no_valid_table_candidate"
    metadata["selected_table_available"] = False
    metadata["selected_table_id"] = None
    metadata["safe_for_erp"] = False
    metadata["status_effective"] = metadata.get("status_effective") or "failed"
    metadata.setdefault("item_rows_clean", [])
    metadata.setdefault("scheme_rows", [])
    metadata.setdefault("credit_note_rows", [])
    metadata.setdefault("invoice_totals", {})
    metadata["invoice_totals"].setdefault("subtotal", 0.0)
    metadata["invoice_totals"].setdefault("grand_total", 0.0)
    metadata["invoice_totals"].setdefault("tax", _safe_tax_summary())
    metadata.setdefault("llm_extraction", _safe_llm_extraction_defaults())

    quality_gate = metadata.get("quality_gate") if isinstance(metadata.get("quality_gate"), dict) else {}
    reasons = list(quality_gate.get("reasons") or [])
    if "no_valid_table_candidate" not in reasons:
        reasons.append("no_valid_table_candidate")
    quality_gate.update({
        "status": quality_gate.get("status") or metadata["status_effective"],
        "safe_for_erp": False,
        "reasons": reasons,
        "confidence": quality_gate.get("confidence", metadata.get("invoice_confidence", 0.0)),
    })
    metadata["quality_gate"] = quality_gate

    canonical = metadata.get("canonical_invoice") if isinstance(metadata.get("canonical_invoice"), dict) else {}
    canonical.setdefault("invoice_id", invoice_id)
    canonical.setdefault("item_rows", [])
    canonical.setdefault("footer_fields", {})
    canonical.setdefault("totals", {})
    canonical["totals"].setdefault("subtotal", 0.0)
    canonical["totals"].setdefault("grand_total", 0.0)
    canonical["totals"].setdefault("tax", _safe_tax_summary())
    canonical.setdefault("issues", [])
    if "no_valid_table_candidate" not in canonical["issues"]:
        canonical["issues"].append("no_valid_table_candidate")
    metadata["canonical_invoice"] = canonical
    return metadata


def _should_run_llm_extraction(metadata: Dict[str, Any]) -> bool:
    if _is_no_valid_table_candidate(metadata):
        return False
    markdown = metadata.get("semantic_markdown")
    return isinstance(markdown, str) and bool(markdown.strip())

@router.get("/health", response_model=HealthResponse)
def health_check():
    # Detect active GPU status to report back VM initialization state
    gpu_available = torch.cuda.is_available()
    response = HealthResponse(
        status="ok",
        gpu_available=gpu_available
    )
    if gpu_available:
        response.gpu_name = torch.cuda.get_device_name(0)
        response.cuda_version = torch.version.cuda
    return response

@router.post("/clear-cache")
async def clear_cache():
    """
    Clears the OCR cache directory. Called when clearing the workbench state.
    """
    try:
        deleted_count = cache_service.clear_all_cache()
        return {"status": "success", "deleted_count": deleted_count}
    except Exception as e:
        logger.error(f"Error clearing OCR scan cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/diagnostics/{diagnostics_run_id}/artifacts")
async def list_diagnostics_artifacts(diagnostics_run_id: str):
    return list_diagnostic_artifacts(diagnostics_run_id)

@router.get("/diagnostics/{diagnostics_run_id}/artifacts/{artifact_name}")
async def get_diagnostics_artifact(
    diagnostics_run_id: str,
    artifact_name: str,
    download: bool = False
):
    try:
        artifact_path = resolve_diagnostic_artifact_path(diagnostics_run_id, artifact_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail=f"Diagnostic artifact not found: {artifact_name}")

    media_type = _artifact_media_type(artifact_path.suffix.lower())
    if download:
        return FileResponse(path=artifact_path, filename=artifact_path.name, media_type=media_type)
    if artifact_path.suffix.lower() in {".json", ".csv", ".md", ".txt"}:
        return PlainTextResponse(artifact_path.read_text(encoding="utf-8"), media_type=media_type)
    return FileResponse(path=artifact_path, media_type=media_type)

@router.post("/upload-invoice", response_model=OCRResponse)
async def upload_invoice(
    file: UploadFile = File(...),
    reconstruct: bool = False,
    reconstruct_mode: str = settings.TSR_PRIMARY_ENGINE,
    extract: bool = False,
    benchmark_mode: bool = False,
    bypass_cache: bool = False
):
    # Enforce basic image upload validation checks on content-type and size limits
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")
    if file.size is not None and file.size > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum upload size is {settings.MAX_UPLOAD_SIZE_BYTES} bytes.")
        
    try:
        file_bytes = await file.read()
        if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"File too large. Maximum upload size is {settings.MAX_UPLOAD_SIZE_BYTES} bytes.")
            
        # Write the uploaded file bytes to a temporary location inside the workspace
        import uuid
        temp_dir = Path("datasets/debug")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file_path = temp_dir / f"temp_upload_{uuid.uuid4().hex}.png"
        
        with open(temp_file_path, "wb") as f:
            f.write(file_bytes)
            
        try:
            from extraction.router import get_extraction_engine
            engine = get_extraction_engine()
            response_payload = engine.extract(
                str(temp_file_path),
                reconstruct=reconstruct,
                reconstruct_mode=reconstruct_mode,
                extract=extract,
                benchmark_mode=benchmark_mode,
                bypass_cache=bypass_cache,
                filename=file.filename,
            )
            return OCRResponse(
                invoice_id=response_payload["invoice_id"],
                cached=response_payload["cached"],
                text=response_payload["text"],
                metadata=response_payload["metadata"]
            )
        finally:
            if temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except Exception as exc:
                    logger.warning(f"Failed to delete temp file {temp_file_path}: {exc}")
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        # Map dynamic exceptions to structured classifier error profiles
        classification = classify_error(e, stage="upload_invoice").to_dict()
        logger.error(f"Error processing upload: {e}", extra={"error_classification": classification})
        raise HTTPException(status_code=500, detail=str(e))


def _artifact_media_type(suffix: str) -> str:
    if suffix == ".json":
        return "application/json"
    if suffix == ".csv":
        return "text/csv"
    if suffix in {".md", ".txt"}:
        return "text/plain"
    if suffix == ".png":
        return "image/png"
    if suffix == ".zip":
        return "application/zip"
    return "application/octet-stream"
