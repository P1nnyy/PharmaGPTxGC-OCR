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

from db import invoice_repository

from extraction.router import get_extraction_engine
from extraction.engines.azure_document_intelligence_engine import AzureDocumentIntelligenceEngine

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(status="ok")

@router.post("/clear-cache")
def clear_cache():
    cleared = cache_service.clear_cache()
    return {"message": "Cache cleared.", "cleared_keys_count": cleared}

@router.get("/invoices")
def list_invoices():
    invoices = invoice_repository.list_invoices()
    for inv in invoices:
        inv["image_url"] = _presign_or_none(inv.get("source_image_ref"))
    return invoices

@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    invoice = invoice_repository.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")
    invoice["image_url"] = _presign_or_none(invoice.get("source_image_ref"))
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
    gst_percent: Optional[float] = None
    amount: Optional[float] = None
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
    updated["image_url"] = _presign_or_none(updated.get("source_image_ref"))
    return updated

@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: str):
    result = invoice_repository.delete_invoice(invoice_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    image_ref = result.get("image_ref")
    if image_ref:
        try:
            image_storage.delete_invoice_image(image_ref)
        except Exception as e:
            logger.warning(f"Failed to delete R2 object {image_ref}: {e}")

    return {"message": "Invoice deleted.", "id": invoice_id}

def _presign_or_none(object_key):
    if not object_key:
        return None
    try:
        return image_storage.get_presigned_url(object_key)
    except Exception as e:
        logger.warning(f"Failed to presign image URL for {object_key}: {e}")
        return None

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
                invoice_data = await run_in_threadpool(engine.extract, temp_path)
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
