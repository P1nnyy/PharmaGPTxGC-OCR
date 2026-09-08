"""Stock-on-hand endpoint.

Lives under a `/inventory/` prefix rather than at `/inventory` because the SPA
owns that bare path as a page route; the edge forwards `/inventory/*` and
leaves `/inventory` to the frontend. Same split as `/reports`.
"""

from typing import Optional

from fastapi import APIRouter, Query

from db.repositories import inventory_repository

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/stock")
def stock(
    statuses: Optional[str] = Query(
        None,
        description="Comma-separated invoice statuses. Defaults to verified only; pass 'all' to include invoices still in review.",
    )
):
    """Current holdings, one row per product/batch.

    Read-only: this composes what the invoices already say, and writes
    nothing. Quantities are what was received - see the repository module for
    why that is not the same as what is left.
    """
    if statuses is None:
        scoped = inventory_repository.DEFAULT_STATUSES
    elif statuses.strip().lower() == "all":
        scoped = None
    else:
        scoped = [s.strip() for s in statuses.split(",") if s.strip()]

    return inventory_repository.stock_on_hand(statuses=scoped)
