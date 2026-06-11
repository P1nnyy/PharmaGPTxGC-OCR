import io
import os
import tempfile
from pathlib import Path
from PIL import Image
import torch
from fastapi import APIRouter, UploadFile, File, HTTPException

from core.config import settings
from core.logger import logger
from models.schemas import HealthResponse, OCRResponse
from services import cache_service, ocr_engine, spatial_reconstruction
from services.error_handler import classify_error
from services.llm_extractor import LLMExtractor

from extraction.router import get_extraction_engine
from extraction.engines.azure_document_intelligence_engine import AzureDocumentIntelligenceEngine

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
def health_check():
    gpu_available = torch.cuda.is_available()
    response = HealthResponse(
        status="ok",
        gpu_available=gpu_available
    )
    if gpu_available:
        response.gpu_name = torch.cuda.get_device_name(0)
        response.cuda_version = torch.version.cuda
    return response

@router.post("/upload-invoice")
async def upload_invoice(
    file: UploadFile = File(...),
    reconstruct: bool = False,
    reconstruct_mode: str = settings.TSR_PRIMARY_ENGINE,
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
                # Call the Azure engine and return direct JSON representation
                invoice_data = engine.extract(temp_path)
                return invoice_data.model_dump(mode="json")
            finally:
                # Clean up the temporary file
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception as clean_err:
                        logger.warning(f"Failed to remove temp file {temp_path}: {clean_err}")
                        
        # 3. Branch logic for Legacy Extraction (OCR + spatial reconstruction)
        else:
            logger.info("Routing extraction to Legacy OCR pipeline")
            # Skip checking the cache if bypass_cache is explicitly requested (forces fresh OCR invocation)
            cached_result = None if bypass_cache else cache_service.get_cached_result(invoice_id)
            if cached_result:
                logger.info("OCR cache hit: reusing OCR blocks only")
                blocks = cached_result.get("blocks", [])
                metadata = {
                    "blocks": blocks,
                    "image_validation": val_report
                }
                if reconstruct or extract:
                    logger.info("Cached reconstruction response disabled")
                    logger.info("Running fresh reconstruction with current code")
                    image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
                    reconstruction_data = spatial_reconstruction.reconstruct_layout(
                        blocks, 
                        debug=(not benchmark_mode), 
                        reconstruct_mode=reconstruct_mode, 
                        image=image, 
                        benchmark_mode=benchmark_mode
                    )
                    logger.info(f"Reconstruction keys from cache path: {reconstruction_data.keys()}")
                    metadata.update(reconstruction_data)
                    
                if extract and "semantic_markdown" in metadata:
                    extractor = LLMExtractor()
                    extraction_json = extractor.extract(metadata["semantic_markdown"])
                    metadata["llm_extraction"] = extraction_json
                    
                return OCRResponse(
                    invoice_id=invoice_id,
                    cached=True,
                    text=cached_result.get("text", ""),
                    metadata=metadata
                )
                
            image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            ocr_result = ocr_engine.process_image(image)
            
            cache_service.save_result(invoice_id, ocr_result)
            
            blocks = ocr_result.get("blocks", [])
            ocr_metadata = ocr_result.get("metadata") if isinstance(ocr_result.get("metadata"), dict) else {}
            metadata = {
                **ocr_metadata,
                "blocks": blocks,
                "image_validation": val_report
            }
            if reconstruct or extract:
                logger.info("Cached reconstruction response disabled")
                logger.info("Running fresh reconstruction with current code")
                reconstruction_data = spatial_reconstruction.reconstruct_layout(
                    blocks, 
                    debug=(not benchmark_mode), 
                    reconstruct_mode=reconstruct_mode, 
                    image=image, 
                    benchmark_mode=benchmark_mode
                )
                logger.info(f"Reconstruction keys from fresh path: {reconstruction_data.keys()}")
                metadata.update(reconstruction_data)
                
            if extract and "semantic_markdown" in metadata:
                extractor = LLMExtractor()
                extraction_json = extractor.extract(metadata["semantic_markdown"])
                metadata["llm_extraction"] = extraction_json
            
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

