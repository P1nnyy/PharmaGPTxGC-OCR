"""Upload validation, extraction and persistence.

Pulled out of the route handlers so the two upload endpoints cannot drift apart
on what they accept, and so the persistence path — which touches two external
systems — is testable without an HTTP client.

The ordering here is not incidental. Every page is validated and content-gated
before any page is extracted, because extraction is billable: a bad page 3
should not leave pages 1 and 2 already paid for.
"""

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from core.config import settings
from core.logger import logger
from db.repositories import invoice_repository, scan_repository
from services import image_storage
from services.invoices.presentation import presign_or_none
from services.validators import content_validator
from services.validators.image_validator import ImageValidator


async def read_and_gate(file: UploadFile, page_label: str = "File") -> bytes:
    """Reads one upload and rejects it unless it is a usable invoice image.

    `page_label` is woven into the error messages so a multi-page upload can say
    which page was rejected rather than failing anonymously.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"{page_label} must be an image.")

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{page_label} is too large. Maximum upload size is {settings.MAX_UPLOAD_SIZE_BYTES} bytes.",
        )

    report = ImageValidator.validate_image(file_bytes)
    if not report["is_valid"]:
        logger.warning(
            f"[IMAGE VALIDATION FAILURE] {page_label} ({file.filename}): {report.get('error_message')}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"{page_label}: {report.get('error_message', 'not a valid invoice image.')}",
        )

    # The image is readable, but does it carry anything a document reader could
    # use? This runs before the billable extraction call so blank, lens-cap and
    # noise uploads cost nothing.
    if settings.CONTENT_GATE_ENABLED:
        assessment = content_validator.assess(file_bytes)
        if not assessment.is_processable:
            logger.warning(f"[CONTENT GATE FAILURE] {page_label} ({file.filename}): {assessment.reason}")
            raise HTTPException(status_code=400, detail=f"{page_label}: {assessment.reason}")

    return file_bytes


async def extract_from_bytes(
    engine, file_bytes: bytes, filename: Optional[str], bypass_cache: bool
):
    """Runs an extraction engine over one image's bytes via a temp file.

    Engines take a path rather than bytes, so the temp file is unavoidable; it
    is removed in a `finally` so a failed extraction does not leak it.
    """
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


async def persist(
    invoice,
    pages: list[dict[str, Any]],
    invoice_id: Optional[str] = None,
) -> dict:
    """Stores page images in R2 and the invoice in the graph.

    `pages` is a list of `{bytes, filename, content_type}`, in page order.

    Returns the fields the frontend needs to display the invoice immediately,
    without a follow-up GET — that extra read races Neo4j Aura's replication lag
    right after the write and can 404 on an invoice that was just saved.

    Failures are returned rather than raised: the extraction itself already
    succeeded, and losing that result because object storage hiccuped would mean
    paying for the extraction twice.
    """
    invoice_id = invoice_id or str(uuid.uuid4())

    # Recorded before the save is attempted, and never deleted afterwards.
    # The scan happened - it cost an API call and a minute of someone's
    # attention - whether or not the invoice it produced survives, or is even
    # created. Counting invoices instead would make the number fall every time
    # a mistake is tidied up.
    scan_id = await run_in_threadpool(
        scan_repository.record_scan,
        settings.DEFAULT_PHARMACY_ID,
        len(pages),
        None,
        "extracted",
        getattr(invoice, "extraction_engine", None),
        (pages[0].get("filename") if pages else None),
    )

    try:
        object_keys = []
        for index, page in enumerate(pages, start=1):
            extension = (Path(page.get("filename") or "invoice.jpg").suffix or ".jpg").lstrip(".") or "jpg"
            # Single-page invoices keep the bare id as their object key, so keys
            # written before multi-page support stay addressable.
            key_id = invoice_id if len(pages) == 1 else f"{invoice_id}_p{index}"
            object_keys.append(
                await run_in_threadpool(
                    image_storage.upload_invoice_image,
                    settings.DEFAULT_PHARMACY_ID,
                    key_id,
                    page["bytes"],
                    page.get("content_type") or "image/jpeg",
                    extension,
                )
            )

        saved_id = await run_in_threadpool(
            invoice_repository.save_invoice,
            invoice,
            object_keys,
            settings.DEFAULT_PHARMACY_ID,
            settings.DEFAULT_USER_ID,
            invoice_id,
        )

        await run_in_threadpool(scan_repository.link_invoice, scan_id, saved_id)

        urls = [u for u in (presign_or_none(key) for key in object_keys) if u]
        return {
            "id": saved_id,
            "graph_invoice_id": saved_id,
            "status": "needs_review",
            "source_image_ref": object_keys[0] if object_keys else None,
            "source_image_refs": object_keys,
            "image_urls": urls,
            "image_url": urls[0] if urls else None,
            "page_count": len(object_keys),
            "persisted": True,
        }
    except Exception as persist_err:
        logger.error(f"Failed to persist invoice to R2/Neo4j: {persist_err}")
        # The ledger row stays, marked failed. A scan that cost an API call and
        # produced nothing is the one most worth being able to see.
        await run_in_threadpool(scan_repository.mark_failed, scan_id, str(persist_err))
        return {"persisted": False, "persist_error": str(persist_err)}
