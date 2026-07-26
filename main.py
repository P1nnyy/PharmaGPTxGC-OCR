from fastapi import FastAPI
from core.logger import logger
from api.routes import router
from services import cache_service
from db.graph_db import init_graph_db
import uvicorn

app = FastAPI(
    title="PharmaGPT OCR API",
    description="Lightweight OCR & Document API Service",
    version="2.0.0"
)

app.include_router(router)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up PharmaGPT OCR API...")
    cache_service.check_cache_status()
    init_graph_db()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
