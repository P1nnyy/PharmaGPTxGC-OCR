"""Item types: the vocabulary a product can be, and the units it is measured in.

Split out of the old single-module api/routes.py when the backend moved to one
router per resource. The handlers are unchanged; only their home is.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import item_type_repository

router = APIRouter(tags=["item-types"])


class ItemTypeCreate(BaseModel):
    name: str
    base_unit: Optional[str] = None
    supported_units: List[str] = []
    single_container: bool = False
    keywords: List[str] = []


class ItemTypeUpdate(BaseModel):
    name: Optional[str] = None
    base_unit: Optional[str] = None
    supported_units: Optional[List[str]] = None
    single_container: Optional[bool] = None
    keywords: Optional[List[str]] = None
    active: Optional[bool] = None


@router.get("/item-types")
def list_item_types(include_inactive: bool = False):
    """The catalogue's vocabulary: what a product can be, and its units."""
    return {
        "item_types": item_type_repository.list_item_types(include_inactive),
        "known_units": item_type_repository.KNOWN_UNITS,
        "count_units": item_type_repository.COUNT_UNITS,
        "measure_units": item_type_repository.MEASURE_UNITS,
    }


@router.post("/item-types")
def create_item_type(payload: ItemTypeCreate):
    try:
        return item_type_repository.create_item_type(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/item-types/{type_id}")
def update_item_type(type_id: str, payload: ItemTypeUpdate):
    try:
        updated = item_type_repository.update_item_type(
            type_id, payload.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Item type {type_id} not found.")
    return updated


@router.delete("/item-types/{type_id}")
def delete_item_type(type_id: str):
    result = item_type_repository.delete_item_type(type_id)
    if result["deleted"]:
        return {"status": "deleted"}

    if result["reason"] == "not_found":
        raise HTTPException(status_code=404, detail=f"Item type {type_id} not found.")
    if result["reason"] == "builtin":
        raise HTTPException(
            status_code=409,
            detail="Built-in item types cannot be deleted. Switch it off instead — "
                   "that removes it from the pickers while existing products stay readable.",
        )
    # 409, not 400: the request is valid, it conflicts with data that exists.
    raise HTTPException(
        status_code=409,
        detail=f"{result['products']} product(s) are still using this item type. "
               f"Switch it off instead, or move those products to another type first.",
    )
