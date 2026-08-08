"""HTTP routers, one module per resource.

Routers stay thin: parse the request, call a service, map domain errors onto
status codes. Business rules live in `services/`, Cypher in `db/repositories/`.
"""

from fastapi import APIRouter

from api.routers import health, invoices, item_types, products, reports, uploads

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(invoices.router)
api_router.include_router(uploads.router)
api_router.include_router(products.router)
api_router.include_router(item_types.router)
api_router.include_router(reports.router)

__all__ = ["api_router"]
