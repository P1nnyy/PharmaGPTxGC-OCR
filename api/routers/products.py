"""Product catalogue: the master record behind the names invoices print.

Split out of the old single-module api/routes.py when the backend moved to one
router per resource. The handlers are unchanged; only their home is.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import product_repository
from enrichment import service as enrichment_service

router = APIRouter(tags=["products"])


class ProductUpdate(BaseModel):
    """Catalogue-level edits only.

    Batch, price and tax figures are deliberately absent: those are facts a
    specific invoice observed, and letting them be retyped on the product
    would create a second version of a number that already exists on the
    line item, with no way to tell which one the books should believe.
    """

    canonical_name: Optional[str] = None
    brand: Optional[str] = None
    strength: Optional[str] = None
    form: Optional[str] = None
    pack_size: Optional[str] = None
    pack_multiplier: Optional[float] = None
    base_unit: Optional[str] = None
    manufacturer: Optional[str] = None
    hsn: Optional[str] = None
    schedule: Optional[str] = None
    notes: Optional[str] = None
    # Marks the product reviewed, which also settles its current spellings.
    confirm: bool = False
    # Opt-in to folding into an existing product when the edit turns out to
    # describe one that already exists.
    allow_merge: bool = False


class ProductMerge(BaseModel):
    source_ids: List[str]
    target_id: str


class AliasSplit(BaseModel):
    """Overrides applied to the product carved out of a spelling. Without at
    least one distinguishing field the split lands on the identity it came
    from, so the UI should collect the strength or pack that separates them."""

    brand: Optional[str] = None
    strength: Optional[str] = None
    form: Optional[str] = None
    pack_size: Optional[str] = None
    pack_multiplier: Optional[float] = None
    base_unit: Optional[str] = None


def _matches_search(product: dict, needle: str) -> bool:
    haystack = " ".join(
        str(v or "")
        for v in (
            product.get("canonical_name"),
            product.get("brand"),
            product.get("hsn"),
            product.get("manufacturer"),
            *[a.get("raw_name") for a in product.get("aliases") or []],
        )
    )
    return needle.lower() in haystack.lower()


@router.get("/products")
def list_products(status: Optional[str] = None, search: Optional[str] = None):
    """The catalogue, with the invoice evidence behind each item.

    Summary counts are computed over the WHOLE catalogue rather than the
    filtered slice, so the tiles keep saying how much work is outstanding
    even while the user is searching within it.
    """
    products = product_repository.list_products()

    summary = {
        "total": len(products),
        "needs_review": sum(1 for p in products if p.get("review_status") != "confirmed"),
        "needs_attention": sum(1 for p in products if p.get("needs_attention")),
        "missing_pack_multiplier": sum(1 for p in products if not p.get("pack_multiplier")),
        "missing_hsn": sum(1 for p in products if not p.get("hsn")),
        "price_conflicts": sum(
            1 for p in products if any(f["code"] == "mrp_conflict" for f in p.get("flags", []))
        ),
    }

    filtered = products
    if status == "needs_review":
        filtered = [p for p in filtered if p.get("review_status") != "confirmed"]
    elif status == "confirmed":
        filtered = [p for p in filtered if p.get("review_status") == "confirmed"]

    if search and search.strip():
        needle = search.strip()
        filtered = [p for p in filtered if _matches_search(p, needle)]

    return {"products": filtered, "summary": summary}


@router.get("/products/{product_id}")
def get_product(product_id: str):
    product = product_repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found.")
    return product


@router.patch("/products/{product_id}")
def update_product(product_id: str, payload: ProductUpdate):
    # exclude_unset, not exclude_none: a client that explicitly sends null is
    # clearing a wrong guess, which has to be distinguishable from a client
    # that simply didn't mention the field.
    fields = payload.model_dump(exclude_unset=True, exclude={"confirm", "allow_merge"})

    try:
        result = product_repository.update_product(
            product_id, fields, confirm=payload.confirm, allow_merge=payload.allow_merge
        )
    except ValueError as exc:
        # A unit the item type does not support. 400 with the type's own list,
        # so the message says how to fix it rather than only that it is wrong.
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found.")

    # A conflict is a normal outcome, not an error: the edit revealed that
    # this product already exists under another record, and the user gets to
    # choose whether to merge rather than having it happen underneath them.
    if result.get("conflict"):
        return {
            "status": "conflict",
            "conflict": result["conflict"],
            "product": product_repository.get_product(product_id),
        }
    return {"status": "ok", "product": result}


@router.post("/products/reparse")
def reparse_products():
    """Re-reads stored products with the current parser.

    Run after the parser learns something new - reading the TA/CA/T/M pack
    codes, for instance. Fields a human confirmed are left untouched; only
    guesses are re-made.
    """
    return product_repository.reparse_products()


@router.post("/products/{product_id}/enrich")
async def enrich_product(product_id: str, fetch_top: int = 2):
    """Looks the product up against public drug listings and returns suggestions.

    Read-only by design: this never writes to the catalogue. The response says
    what a listing claims and how well it matched; applying any of it goes
    through the ordinary PATCH, with a human choosing. Matching an invoice's
    abbreviated item name to a retail listing is fuzzy, and the fields it would
    fill - strength above all - are ones where a silent wrong answer corrupts
    stock and dosing records at catalogue scale.
    """
    product = product_repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found.")

    # Runs in a worker thread: this makes outbound HTTP calls with the
    # blocking client, which would otherwise stall the event loop and every
    # other request with it.
    result = await run_in_threadpool(
        enrichment_service.enrich_product, product, max(0, min(fetch_top, 3))
    )
    return result


@router.post("/products/merge")
def merge_products(payload: ProductMerge):
    merged = product_repository.merge_products(payload.source_ids, payload.target_id)
    if merged is None:
        raise HTTPException(status_code=404, detail=f"Product {payload.target_id} not found.")
    return {"status": "ok", "product": merged}


@router.post("/products/aliases/{alias_id}/split")
def split_alias(alias_id: str, payload: AliasSplit):
    product = product_repository.split_alias(
        alias_id, payload.model_dump(exclude_unset=True)
    )
    if product is None:
        raise HTTPException(status_code=404, detail=f"Alias {alias_id} not found.")
    return {"status": "ok", "product": product}
