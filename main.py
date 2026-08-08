from fastapi import FastAPI
from core.logger import logger
from api.routers import api_router
from services import cache_service
from db.graph_db import init_graph_db
from db import item_type_repository
import uvicorn

app = FastAPI(
    title="PharmaGPT OCR API",
    description="Lightweight OCR & Document API Service",
    version="2.0.0"
)

app.include_router(api_router)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up PharmaGPT OCR API...")
    cache_service.check_cache_status()
    init_graph_db()
    # The built-in item types are the vocabulary the product pickers read from,
    # so they must exist before the first request rather than being created by
    # whichever request happens to look first.
    try:
        item_type_repository.ensure_seeded()
    except Exception as exc:  # a seeding failure must not take the API down
        logger.warning(f"Item type seeding skipped: {exc}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
