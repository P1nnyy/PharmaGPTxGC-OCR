"""HTTP routers, one module per resource.

Routers stay thin: parse the request, call a service, map domain errors onto
status codes. Business rules live in `services/`, Cypher in `db/repositories/`.

Authentication is applied here rather than endpoint by endpoint, so that a
route added later is protected by default. The failure mode of per-endpoint
guards is the endpoint someone forgets, and that one is not visible in review -
it looks exactly like a route that did not need protecting.

Two routers stay public, deliberately:
  * `auth`  - /auth/login must be reachable by someone with no session, and
              its other routes declare their own guards.
  * `health`- the container healthcheck calls it with no credentials, and it
              reports only liveness.
"""

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.routers import (
    auth, health, inventory, invoices, item_types, products, reports, tax_periods, uploads,
)

_authenticated = [Depends(current_user)]

api_router = APIRouter()

# Public.
api_router.include_router(auth.router)
api_router.include_router(health.router)

# Everything that reads or writes pharmacy data.
api_router.include_router(invoices.router, dependencies=_authenticated)
api_router.include_router(uploads.router, dependencies=_authenticated)
api_router.include_router(products.router, dependencies=_authenticated)
api_router.include_router(item_types.router, dependencies=_authenticated)
api_router.include_router(reports.router, dependencies=_authenticated)
api_router.include_router(inventory.router, dependencies=_authenticated)
api_router.include_router(tax_periods.router, dependencies=_authenticated)

__all__ = ["api_router"]
