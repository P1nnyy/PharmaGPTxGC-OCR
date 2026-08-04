"""Invoice upload and extraction endpoints."""

import io
import uuid
from typing import List

from PIL import Image
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from core.config import settings
from core.logger import logger
from extraction.engines.azure_document_intelligence_engine import AzureDocumentIntelligenceEngine
from extraction.normalizers.invoice_merger import check_pages_consistent, merge_invoice_pages
from extraction.router import get_extraction_engine
from models.schemas import OCRResponse
from services import cache_service, ocr_engine
from services.error_handler import classify_error
from services.invoices import ingestion
from services.validators.image_validator import ImageValidator

router = APIRouter(tags=["uploads"])


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
        for index, upload in enumerate(files, start=1):
            page_bytes.append(await ingestion.read_and_gate(upload, f"Page {index}"))

        logger.info(f"[MULTIPAGE] extracting {len(files)} pages as a single invoice")
        pages = []
        for index, (upload, data) in enumerate(zip(files, page_bytes), start=1):
            page_invoice = await ingestion.extract_from_bytes(
                engine, data, upload.filename, bypass_cache
            )
            pages.append(page_invoice)
            logger.info(
                f"[MULTIPAGE] page {index}/{len(files)} ({upload.filename}): "
                f"invoice_number={page_invoice.invoice_number!r} "
                f"line_items={len(page_invoice.line_items)} grand_total={page_invoice.grand_total}"
            )

        consistency = check_pages_consistent(pages)
        page_summaries = [
            {
                "page": index,
                "filename": upload.filename,
                "invoice_number": page.invoice_number,
                "invoice_date": page.invoice_date,
                "seller_name": page.seller_name,
                "line_item_count": len(page.line_items),
                "grand_total": page.grand_total,
            }
            for index, (upload, page) in enumerate(zip(files, pages), start=1)
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

        response.update(
            await ingestion.persist(
                merged,
                [
                    {
                        "bytes": data,
                        "filename": upload.filename,
                        "content_type": upload.content_type,
                    }
                    for upload, data in zip(files, page_bytes)
                ],
                invoice_id=str(uuid.uuid4()),
            )
        )
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
    bypass_cache: bool = False,
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    # Reject on the declared size before reading the body where the client
    # provided one, so an oversized upload is refused without buffering it.
    if file.size is not None and file.size > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum upload size is {settings.MAX_UPLOAD_SIZE_BYTES} bytes.",
        )

    try:
        file_bytes = await ingestion.read_and_gate(file, "File")
        invoice_id = cache_service.compute_md5(file_bytes)
        logger.info(f"Received file: {file.filename}, computed invoice_id: {invoice_id}")

        engine = get_extraction_engine()

        if isinstance(engine, AzureDocumentIntelligenceEngine):
            logger.info("Routing extraction to AzureDocumentIntelligenceEngine")
            invoice_data = await ingestion.extract_from_bytes(
                engine, file_bytes, file.filename, bypass_cache
            )
            response = invoice_data.model_dump(mode="json")
            response.update(
                await ingestion.persist(
                    invoice_data,
                    [
                        {
                            "bytes": file_bytes,
                            "filename": file.filename,
                            "content_type": file.content_type,
                        }
                    ],
                    invoice_id=str(uuid.uuid4()),
                )
            )
            return response

        logger.info("Routing extraction to OCR engine")
        return await _run_legacy_ocr(file_bytes, invoice_id, bypass_cache)

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        classification = classify_error(e, stage="upload_invoice").to_dict()
        logger.error(f"Error processing upload: {e}", extra={"error_classification": classification})
        raise HTTPException(status_code=500, detail=str(e))


async def _run_legacy_ocr(file_bytes: bytes, invoice_id: str, bypass_cache: bool) -> OCRResponse:
    """The pre-Azure OCR path, kept for the workbench and offline runs.

    Re-validates the image because the report is echoed back in the response
    metadata, where the debugging UI reads it.
    """
    validation = ImageValidator.validate_image(file_bytes)

    cached = None if bypass_cache else cache_service.get_cached_result(invoice_id)
    if cached:
        logger.info("OCR cache hit: reusing cached result")
        return OCRResponse(
            invoice_id=invoice_id,
            cached=True,
            text=cached.get("text", ""),
            metadata={"blocks": cached.get("blocks", []), "image_validation": validation},
        )

    image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    result = await run_in_threadpool(ocr_engine.process_image, image)
    cache_service.save_result(invoice_id, result)

    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    return OCRResponse(
        invoice_id=invoice_id,
        cached=False,
        text=result.get("text", ""),
        metadata={
            **metadata,
            "blocks": result.get("blocks", []),
            "tables": result.get("tables", []),
            "image_validation": validation,
        },
    )
