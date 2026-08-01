import io
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional
from PIL import Image
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.concurrency import run_in_threadpool

from core.config import settings
from core.logger import logger
from models.schemas import HealthResponse, OCRResponse
from services import cache_service, ocr_engine, image_storage
from services.error_handler import classify_error
from services.validators import content_validator

from db import invoice_repository

from extraction.router import get_extraction_engine
from extraction.engines.azure_document_intelligence_engine import AzureDocumentIntelligenceEngine
from extraction.normalizers.invoice_merger import check_pages_consistent, merge_invoice_pages

router = APIRouter()

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

@router.get("/invoices")
def list_invoices():
    invoices = invoice_repository.list_invoices()
    for inv in invoices:
        _attach_image_urls(inv)
    return invoices

@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    invoice = invoice_repository.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")
    _attach_image_urls(invoice)
    return invoice

class LineItemUpdate(BaseModel):
    name: Optional[str] = None
    pack: Optional[str] = None
    batch: Optional[str] = None
    expiry: Optional[str] = None
    hsn: Optional[str] = None
    quantity: Optional[float] = None
    free_quantity: Optional[float] = None
    mrp: Optional[float] = None
    rate: Optional[float] = None
    discount: Optional[float] = None
    discount_percent: Optional[float] = None
    gst_percent: Optional[float] = None
    amount: Optional[float] = None
    is_estimated_amount: Optional[bool] = None
    bounding_box: Optional[List[float]] = None

class InvoiceUpdate(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    seller_name: Optional[str] = None
    seller_gstin: Optional[str] = None
    seller_address: Optional[str] = None
    seller_phone: Optional[str] = None
    drug_license: Optional[str] = None
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    grand_total: Optional[float] = None
    roundoff: Optional[float] = None
    status: Optional[str] = None
    line_items: Optional[List[LineItemUpdate]] = None

@router.patch("/invoices/{invoice_id}")
def update_invoice(invoice_id: str, payload: InvoiceUpdate):
    header = payload.model_dump(exclude={"status", "line_items"}, exclude_none=True)
    line_items = (
        [item.model_dump() for item in payload.line_items]
        if payload.line_items is not None
        else None
    )

    ok = invoice_repository.update_invoice(invoice_id, header, line_items, payload.status)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    updated = invoice_repository.get_invoice(invoice_id)
    _attach_image_urls(updated)
    return updated

@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: str):
    result = invoice_repository.delete_invoice(invoice_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    # Remove every page image, not just page 1 - a multi-page invoice would
    # otherwise leave its remaining pages orphaned in R2 forever.
    for image_ref in result.get("image_refs") or []:
        try:
            image_storage.delete_invoice_image(image_ref)
        except Exception as e:
            logger.warning(f"Failed to delete R2 object {image_ref}: {e}")

    return {"message": "Invoice deleted.", "id": invoice_id}

def _attach_image_urls(invoice: dict) -> dict:
    """Adds presigned URLs for every page of the invoice.

    image_url stays as page 1 so existing callers keep working; image_urls
    carries all pages in order. Invoices saved before multi-page support have
    no source_image_refs, so fall back to the single ref.
    """
    refs = invoice.get("source_image_refs") or []
    if not refs and invoice.get("source_image_ref"):
        refs = [invoice["source_image_ref"]]

    urls = [u for u in (_presign_or_none(ref) for ref in refs) if u]
    invoice["image_urls"] = urls
    invoice["image_url"] = urls[0] if urls else None
    invoice["page_count"] = invoice.get("page_count") or len(urls)
    return invoice


def _presign_or_none(object_key):
    if not object_key:
        return None
    try:
        return image_storage.get_presigned_url(object_key)
    except Exception as e:
        logger.warning(f"Failed to presign image URL for {object_key}: {e}")
        return None

async def _read_and_gate_upload(file: UploadFile, page_label: str) -> bytes:
    """Shared validation for one uploaded image: size, decodability, and the
    pre-flight content gate. page_label is woven into error messages so a
    multi-page upload says which page was rejected.

    Kept as one helper so the single-page and multi-page routes cannot drift
    apart on what they accept.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"{page_label} must be an image.")

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{page_label} is too large. Maximum upload size is {settings.MAX_UPLOAD_SIZE_BYTES} bytes.",
        )

    from services.validators.image_validator import ImageValidator
    val_report = ImageValidator.validate_image(file_bytes)
    if not val_report["is_valid"]:
        logger.warning(
            f"[IMAGE VALIDATION FAILURE] {page_label} ({file.filename}): {val_report.get('error_message')}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"{page_label}: {val_report.get('error_message', 'not a valid invoice image.')}",
        )

    if settings.CONTENT_GATE_ENABLED:
        content_report = content_validator.assess(file_bytes)
        if not content_report.is_processable:
            logger.warning(f"[CONTENT GATE FAILURE] {page_label} ({file.filename}): {content_report.reason}")
            raise HTTPException(status_code=400, detail=f"{page_label}: {content_report.reason}")

    return file_bytes


async def _extract_from_bytes(engine, file_bytes: bytes, filename: Optional[str], bypass_cache: bool):
    """Runs the extraction engine over one image's bytes via a temp file."""
    suffix = Path(filename or "invoice.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        temp_path = tmp.name
    try:
        return await run_in_threadpool(engine.extract, temp_path, bypass_cache=bypass_cache)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as clean_err:
                logger.warning(f"Failed to remove temp file {temp_path}: {clean_err}")


@router.post("/upload-invoice-multipage")
async def upload_invoice_multipage(
    files: List[UploadFile] = File(...),
    confirmed_single_order: bool = False,
    force: bool = False,
    bypass_cache: bool = False,
):
    """Processes several images as the pages of ONE invoice.

    Pages are extracted independently and then merged. Order matters and is
    taken from the order the files arrive in - only the user knows which photo
    is page 1.

    The caller must set confirmed_single_order=true, which is the user having
    confirmed in the UI that these pages belong to a single order. That is an
    assertion, not proof, so the extracted pages are then checked against each
    other; a hard disagreement (different invoice numbers or sellers) returns
    409 with the details rather than silently welding two invoices together.
    Re-submitting with force=true accepts them anyway, and costs nothing extra
    because the Azure responses are already cached.
    """
    if not confirmed_single_order:
        raise HTTPException(
            status_code=400,
            detail="Please confirm that all uploaded pages belong to the same invoice before processing.",
        )
    if not files:
        raise HTTPException(status_code=400, detail="No pages were uploaded.")
    if len(files) > settings.MAX_INVOICE_PAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many pages ({len(files)}). A single invoice may have at most {settings.MAX_INVOICE_PAGES} pages.",
        )

    engine = get_extraction_engine()
    if not isinstance(engine, AzureDocumentIntelligenceEngine):
        raise HTTPException(
            status_code=400,
            detail="Multi-page invoices require the Azure Document Intelligence engine.",
        )

    try:
        # Validate and gate every page BEFORE extracting any of them, so a bad
        # page 3 doesn't leave pages 1-2 already paid for.
        page_bytes: List[bytes] = []
        for idx, upload in enumerate(files, start=1):
            page_bytes.append(await _read_and_gate_upload(upload, f"Page {idx}"))

        logger.info(f"[MULTIPAGE] extracting {len(files)} pages as a single invoice")
        pages = []
        for idx, (upload, data) in enumerate(zip(files, page_bytes), start=1):
            page_invoice = await _extract_from_bytes(engine, data, upload.filename, bypass_cache)
            pages.append(page_invoice)
            logger.info(
                f"[MULTIPAGE] page {idx}/{len(files)} ({upload.filename}): "
                f"invoice_number={page_invoice.invoice_number!r} "
                f"line_items={len(page_invoice.line_items)} grand_total={page_invoice.grand_total}"
            )

        consistency = check_pages_consistent(pages)
        page_summaries = [
            {
                "page": idx,
                "filename": upload.filename,
                "invoice_number": p.invoice_number,
                "invoice_date": p.invoice_date,
                "seller_name": p.seller_name,
                "line_item_count": len(p.line_items),
                "grand_total": p.grand_total,
            }
            for idx, (upload, p) in enumerate(zip(files, pages), start=1)
        ]

        if not consistency.is_consistent and not force:
            logger.warning(f"[MULTIPAGE] pages rejected as inconsistent: {consistency.conflicts}")
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "These pages do not appear to belong to the same invoice.",
                    "consistency": consistency.to_dict(),
                    "pages": page_summaries,
                },
            )

        merged = merge_invoice_pages(pages)
        response = merged.model_dump(mode="json")
        response["consistency"] = consistency.to_dict()
        response["pages"] = page_summaries

        graph_invoice_id = str(uuid.uuid4())
        try:
            object_keys = []
            for idx, (upload, data) in enumerate(zip(files, page_bytes), start=1):
                suffix_ext = (Path(upload.filename or "invoice.jpg").suffix or ".jpg").lstrip(".") or "jpg"
                object_keys.append(
                    await run_in_threadpool(
                        image_storage.upload_invoice_image,
                        settings.DEFAULT_PHARMACY_ID,
                        f"{graph_invoice_id}_p{idx}",
                        data,
                        upload.content_type or "image/jpeg",
                        suffix_ext,
                    )
                )

            saved_id = await run_in_threadpool(
                invoice_repository.save_invoice,
                merged,
                object_keys,
                settings.DEFAULT_PHARMACY_ID,
                settings.DEFAULT_USER_ID,
                graph_invoice_id,
            )
            response["id"] = saved_id
            response["graph_invoice_id"] = saved_id
            response["status"] = "needs_review"
            response["source_image_ref"] = object_keys[0] if object_keys else None
            response["source_image_refs"] = object_keys
            response["image_urls"] = [u for u in (_presign_or_none(k) for k in object_keys) if u]
            response["image_url"] = response["image_urls"][0] if response["image_urls"] else None
            response["page_count"] = len(object_keys)
            response["persisted"] = True
        except Exception as persist_err:
            logger.error(f"Failed to persist multi-page invoice to R2/Neo4j: {persist_err}")
            response["persisted"] = False
            response["persist_error"] = str(persist_err)

        return response

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        classification = classify_error(e, stage="upload_invoice_multipage").to_dict()
        logger.error(f"[MULTIPAGE FAILURE] {classification}")
        raise HTTPException(status_code=500, detail=classification)


@router.post("/upload-invoice")
async def upload_invoice(
    file: UploadFile = File(...),
    reconstruct: bool = False,
    extract: bool = False,
    benchmark_mode: bool = False,
    bypass_cache: bool = False
):
    # Validate content type is an image
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")
        
    # Validate size bounds if file size metadata exists
    if file.size is not None and file.size > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413, 
            detail=f"File too large. Maximum upload size is {settings.MAX_UPLOAD_SIZE_BYTES} bytes."
        )
        
    try:
        file_bytes = await file.read()
        if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413, 
                detail=f"File too large. Maximum upload size is {settings.MAX_UPLOAD_SIZE_BYTES} bytes."
            )
            
        # Pre-validate the image using the lightweight ImageValidator
        from services.validators.image_validator import ImageValidator
        val_report = ImageValidator.validate_image(file_bytes)
        if not val_report["is_valid"]:
            logger.warning(f"[IMAGE VALIDATION FAILURE] File: {file.filename}, error: {val_report.get('error_message')}")
            raise HTTPException(
                status_code=400,
                detail=val_report.get("error_message", "Uploaded file is not a valid invoice image.")
            )

        # Content gate: the image is a readable image, but does it actually
        # carry anything a document reader could use? Runs before the billable
        # Azure call so blank/lens-cap/noise uploads cost nothing.
        content_report = None
        if settings.CONTENT_GATE_ENABLED:
            content_report = content_validator.assess(file_bytes)
            if not content_report.is_processable:
                logger.warning(
                    f"[CONTENT GATE FAILURE] File: {file.filename}, reason: {content_report.reason}"
                )
                raise HTTPException(status_code=400, detail=content_report.reason)

        invoice_id = cache_service.compute_md5(file_bytes)
        logger.info(f"Received file: {file.filename}, computed invoice_id: {invoice_id}")
        
        # 1. Resolve configured extraction engine
        engine = get_extraction_engine()
        
        # 2. Branch logic for Azure Document Intelligence Engine
        if isinstance(engine, AzureDocumentIntelligenceEngine):
            logger.info("Routing extraction to AzureDocumentIntelligenceEngine")
            
            # Save uploaded bytes to a temp file in the workspace directory
            suffix = Path(file.filename or "invoice.jpg").suffix or ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_bytes)
                temp_path = tmp.name
                
            try:
                # Execute long-running Azure network request on threadpool to avoid blocking main event loop
                invoice_data = await run_in_threadpool(
                    engine.extract, temp_path, bypass_cache=bypass_cache
                )
                response = invoice_data.model_dump(mode="json")

                # Persist the extracted invoice + source image. Failures here are
                # logged and surfaced in the response, but don't fail the upload —
                # the extraction itself already succeeded.
                graph_invoice_id = str(uuid.uuid4())
                try:
                    suffix_ext = suffix.lstrip(".") or "jpg"
                    object_key = await run_in_threadpool(
                        image_storage.upload_invoice_image,
                        settings.DEFAULT_PHARMACY_ID,
                        graph_invoice_id,
                        file_bytes,
                        file.content_type or "image/jpeg",
                        suffix_ext,
                    )
                    saved_id = await run_in_threadpool(
                        invoice_repository.save_invoice,
                        invoice_data,
                        object_key,
                        settings.DEFAULT_PHARMACY_ID,
                        settings.DEFAULT_USER_ID,
                        graph_invoice_id,
                    )
                    # Return everything the frontend needs to display this invoice
                    # immediately, without an extra GET — avoids racing Neo4j Aura's
                    # read-replica replication lag right after the write.
                    response["id"] = saved_id
                    response["graph_invoice_id"] = saved_id
                    response["status"] = "needs_review"
                    response["source_image_ref"] = object_key
                    response["image_url"] = _presign_or_none(object_key)
                    response["persisted"] = True
                except Exception as persist_err:
                    logger.error(f"Failed to persist invoice to R2/Neo4j: {persist_err}")
                    response["persisted"] = False
                    response["persist_error"] = str(persist_err)

                return response
            finally:
                # Clean up the temporary file
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception as clean_err:
                        logger.warning(f"Failed to remove temp file {temp_path}: {clean_err}")
                        
        # 3. Branch logic for OCR engine
        else:
            logger.info("Routing extraction to OCR engine")
            cached_result = None if bypass_cache else cache_service.get_cached_result(invoice_id)
            if cached_result:
                logger.info("OCR cache hit: reusing cached result")
                blocks = cached_result.get("blocks", [])
                metadata = {
                    "blocks": blocks,
                    "image_validation": val_report
                }
                return OCRResponse(
                    invoice_id=invoice_id,
                    cached=True,
                    text=cached_result.get("text", ""),
                    metadata=metadata
                )
                
            image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            ocr_result = await run_in_threadpool(ocr_engine.process_image, image)
            
            cache_service.save_result(invoice_id, ocr_result)
            
            blocks = ocr_result.get("blocks", [])
            ocr_metadata = ocr_result.get("metadata") if isinstance(ocr_result.get("metadata"), dict) else {}
            metadata = {
                **ocr_metadata,
                "blocks": blocks,
                "tables": ocr_result.get("tables", []),
                "image_validation": val_report
            }
            
            return OCRResponse(
                invoice_id=invoice_id,
                cached=False,
                text=ocr_result.get("text", ""),
                metadata=metadata
            )
            
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        classification = classify_error(e, stage="upload_invoice").to_dict()
        logger.error(f"Error processing upload: {e}", extra={"error_classification": classification})
        raise HTTPException(status_code=500, detail=str(e))
