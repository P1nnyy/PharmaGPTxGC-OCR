from fastapi import FastAPI
from core.logger import logger
from api.routes import router
import uvicorn

app = FastAPI(
    title="PharmaGPT OCR API",
    description="GPU-accelerated OCR API for experimentation",
    version="1.0.0"
)

app.include_router(router)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up PharmaGPT OCR API...")
    import torch
    if torch.cuda.is_available():
        logger.info(f"CUDA is available! GPU: {torch.cuda.get_device_name(0)}")
    else:
        logger.warning("CUDA is NOT available. Falling back to CPU. This will be slow!")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
