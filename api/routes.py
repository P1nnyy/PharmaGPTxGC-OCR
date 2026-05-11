from fastapi import APIRouter, UploadFile, File, HTTPException
from core.logger import logger
from models.schemas import HealthResponse, OCRResponse
from services import cache_service, ocr_engine, spatial_reconstruction
from services.llm_extractor import LLMExtractor
from PIL import Image
import io
import torch

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

@router.post("/upload-invoice", response_model=OCRResponse)
async def upload_invoice(file: UploadFile = File(...), reconstruct: bool = False, reconstruct_mode: str = "ppstructure", extract: bool = False, benchmark_mode: bool = False):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")
        
    try:
        file_bytes = await file.read()
        invoice_id = cache_service.compute_md5(file_bytes)
        
        logger.info(f"Received file: {file.filename}, computed invoice_id: {invoice_id}")
        
        cached_result = cache_service.get_cached_result(invoice_id)
        if cached_result:
            blocks = cached_result.get("blocks", [])
            metadata = {"blocks": blocks}
            if reconstruct or extract:
                image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
                reconstruction_data = spatial_reconstruction.reconstruct_layout(blocks, debug=(not benchmark_mode), reconstruct_mode=reconstruct_mode, image=image, benchmark_mode=benchmark_mode)
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
        metadata = {"blocks": blocks}
        if reconstruct or extract:
            reconstruction_data = spatial_reconstruction.reconstruct_layout(blocks, debug=(not benchmark_mode), reconstruct_mode=reconstruct_mode, image=image, benchmark_mode=benchmark_mode)
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
        logger.error(f"Error processing upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))
