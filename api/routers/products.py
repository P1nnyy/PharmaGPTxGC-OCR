"""Product catalogue: the master record behind the names invoices print.

Split out of the old single-module api/routes.py when the backend moved to one
router per resource. The handlers are unchanged; only their home is.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from api.deps import current_user
from core.logger import logger
from db import product_repository, product_review
from db.repositories import audit_repository, product_code_repository
from enrichment import reference_index, reference_service
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


class CodeBinding(BaseModel):
    """A scanned code the user is claiming belongs to a product."""

    value: str
    # What the scanner said the symbology was, and what the parser made of the
    # payload. Kept because a GS1 DataMatrix and a plain EAN bound to the same
    # product are different facts about it.
    type: Optional[str] = None


class BulkConfirm(BaseModel):
    """Products the user approved as a batch, by id."""

    product_ids: List[str]


class ReferenceSuggest(BaseModel):
    """Which products to look up. Empty means the whole catalogue, which is
    reasonable only because the index is local."""

    product_ids: List[str] = []


class ReferenceApplyItem(BaseModel):
    product_id: str
    fields: Dict[str, Any] = {}


class ReferenceApply(BaseModel):
    """Exactly the proposals the user approved. Sent back rather than
    recomputed so that what is written is what they were shown."""

    items: List[ReferenceApplyItem] = []


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


@router.get("/products/review-queue")
def review_queue(band: Optional[str] = None):
    """The catalogue sorted by what it actually needs from a person.

    Declared above /products/{product_id} deliberately: FastAPI matches in
    declaration order, and below it this path would be read as a product id.

    The queue exists because "needs review" was never one job. Some items are
    missing a fact only a human has (blocked); some are complete but resting on
    a guess (review); and most are complete and confidently read, and want
    nothing but a signature (ready). Serving them as one undifferentiated list
    is what made the section unusable - the three hundred that needed a click
    hid the six that needed thought.
    """
    products = product_repository.list_products()
    outstanding = [
        p for p in products
        if p.get("review_status") != "confirmed"
        or any(f["code"] == "new_alias" for f in p.get("flags", []))
    ]

    assessed = product_review.assess_catalogue(outstanding)
    by_id = {p["id"]: p for p in outstanding}

    # Each entry carries its product, so the queue renders without a fetch per
    # row - the round trip per item is most of what made reviewing slow.
    items = [
        {**assessment, "product": by_id[assessment["product_id"]]}
        for assessment in assessed["assessments"]
        if assessment["product_id"] in by_id
    ]

    if band:
        items = [i for i in items if i["band"] == band]

    return {
        "items": items,
        "counts": assessed["counts"],
        "total_outstanding": len(outstanding),
        "catalogue_total": len(products),
    }


@router.get("/products/duplicates")
def product_duplicates(limit: int = 50):
    """Merge suggestions: items that are probably one product recorded twice.

    Products whose identity_key agrees merged when they were written, so
    everything offered here is a pair that survived that - one invoice stated a
    strength and another didn't, or two distributors spelled a brand
    differently enough to matter. Those are found by reading four hundred rows
    side by side, which is why in practice they are never found at all.

    Suggestions only. Merging still goes through POST /products/merge with a
    person choosing, and every candidate carries the reasoning that produced it
    so that choice can be an informed one.
    """
    products = product_repository.list_products()
    return {
        "candidates": product_review.find_duplicate_candidates(products, limit=max(1, min(limit, 200))),
        "scanned": len(products),
    }


@router.post("/products/bulk-confirm")
def bulk_confirm_products(payload: BulkConfirm):
    """Approves a batch of products in one action.

    The ids come from the client rather than being recomputed here, so the user
    confirms exactly the list they were shown. Re-deriving "everything ready"
    server-side would let an item that changed between the render and the click
    be approved without anyone having seen it.
    """
    if not payload.product_ids:
        raise HTTPException(status_code=400, detail="No products were selected.")

    return product_repository.bulk_confirm(payload.product_ids)


@router.get("/products/reference-status")
def reference_status():
    """Whether the local reference index is installed, and how big it is.

    The index is a build artefact in a gitignored directory, so a fresh
    checkout has none. The UI needs to say "reference data is not installed"
    rather than presenting an empty result as though nothing matched.
    """
    available = reference_index.is_available()
    meta = {}
    if available:
        with reference_index.connect() as connection:
            meta = dict(reference_index.iter_meta(connection))
    return {"available": available, **meta}


@router.post("/products/reference-suggest")
def reference_suggest(payload: ReferenceSuggest):
    """Reference proposals for a batch of products. Read-only.

    Batching is affordable here and nowhere else: the index is local SQLite,
    so a hundred products cost a hundred indexed reads rather than a hundred
    requests to somebody else's server.

    `new_fields` on each result is the safe subset - agreed by every surviving
    listing AND still empty on the product. `conflicts` is where the reference
    disagrees with something already recorded, which is a question for a person
    and never part of a batch apply.
    """
    if not reference_index.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Reference data is not installed. Build it with "
                "scripts/build_product_reference.py."
            ),
        )

    products = product_repository.list_products()
    wanted = set(payload.product_ids or [])
    selected = [p for p in products if not wanted or p["id"] in wanted]

    results = reference_service.suggest_for_products(selected)
    fillable = [r for r in results if r.get("new_fields")]
    return {
        "results": results,
        "matched": sum(1 for r in results if r.get("status") == "ok"),
        "fillable": len(fillable),
        "scanned": len(selected),
    }


@router.post("/products/reference-apply")
def reference_apply(payload: ReferenceApply):
    """Writes approved reference proposals onto their products.

    Deliberately does NOT mark the values confirmed. They were proposed by a
    matcher and approved in bulk from a summary, which is a weaker act than a
    person reading the product - so the filled products go back into the
    review queue, now complete enough to be approved there in one pass. The
    autofill shortens the review; it does not replace it.

    Only the fields the matcher is allowed to propose are accepted, whatever
    the client sends.
    """
    applied, skipped = [], []
    for item in payload.items:
        fields = {
            k: v for k, v in (item.fields or {}).items()
            if k in reference_service.PROPOSABLE and v not in (None, "", [])
        }
        if not fields:
            skipped.append({"id": item.product_id, "reason": "Nothing to apply."})
            continue
        try:
            result = product_repository.update_product(
                item.product_id, fields, confirm=False, mark_confirmed=False
            )
            if result is None:
                skipped.append({"id": item.product_id, "reason": "No longer in the catalogue."})
            elif result.get("conflict"):
                # The fill turned this into a product that already exists.
                # Merging is a decision, never a side effect of autofill.
                skipped.append({
                    "id": item.product_id,
                    "reason": (
                        f"Filling this in makes it identical to "
                        f"\u201c{result['conflict'].get('canonical_name')}\u201d — open it to merge or separate them."
                    ),
                })
            else:
                applied.append(item.product_id)
        except ValueError as exc:
            skipped.append({"id": item.product_id, "reason": str(exc)})
        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the batch
            logger.warning(f"[REFERENCE] Apply failed for {item.product_id}: {exc}")
            skipped.append({"id": item.product_id, "reason": "Could not be saved."})

    logger.info(f"[REFERENCE] Applied to {len(applied)} products, {len(skipped)} skipped")
    return {"applied": applied, "skipped": skipped}


@router.post("/products/reference-autofill")
def reference_autofill(payload: ReferenceSuggest):
    """Runs the ingestion-time autofill over existing products.

    Same code path invoices take when they are verified, exposed so a
    catalogue that predates the reference index can be brought up to date in
    one pass. An empty id list means every product.

    Idempotent: it only fills fields that are empty, so running it twice
    changes nothing the second time.
    """
    if not reference_index.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Reference data is not installed. Build it with "
                "scripts/build_product_reference.py."
            ),
        )
    return reference_service.autofill_products(payload.product_ids or None)


@router.get("/products/delta")
def products_delta(since: Optional[str] = Query(None, description="server_time from the last sync.")):
    """The catalogue changes a device has not seen yet.

    Declared before `/products/{product_id}`, which would otherwise match
    "delta" as an id.
    """
    products, server_time = product_repository.products_changed_since(since)
    return {
        "products": products,
        "server_time": server_time,
        # A device that has never synced gets everything; saying so lets it
        # replace its mirror rather than merging into a half-empty one.
        "full": since is None,
        "count": len(products),
    }


@router.get("/products/by-code")
def resolve_product_code(value: str = Query(..., description="The scanned payload, exactly as read.")):
    """The product a scanned code is bound to.

    Declared before `/products/{product_id}` because FastAPI matches in
    declaration order and would otherwise read "by-code" as a product id.

    A 404 here is the normal, expected case for a code never seen before — it
    is what makes the counter offer to bind it rather than an error.
    """
    match = product_code_repository.resolve(value)
    if match is None:
        raise HTTPException(status_code=404, detail="That code is not bound to a product yet.")
    return match


@router.post("/products/{product_id}/codes", status_code=201)
def bind_product_code(product_id: str, payload: CodeBinding, user: dict = Depends(current_user)):
    """Binds a scanned code to a product, so the next scan resolves instantly.

    This is the learning loop the scanner is built around: unrecognised once,
    known from then on.
    """
    if not payload.value or not payload.value.strip():
        raise HTTPException(status_code=400, detail="A code cannot be empty.")
    try:
        result = product_code_repository.bind(
            product_id, payload.value, payload.type, bound_by=user.get("id")
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    audit_repository.record(
        action="product.code.bound",
        actor=user,
        target_type="Product",
        target_id=product_id,
        summary=f"Bound scanned code to {result['product'].get('canonical_name') or product_id}",
    )
    return result


@router.get("/products/{product_id}/codes")
def list_product_codes(product_id: str):
    return {"codes": product_code_repository.codes_for_product(product_id)}


@router.delete("/products/codes", status_code=204)
def unbind_product_code(
    value: str = Query(..., description="The code to unbind."),
    user: dict = Depends(current_user),
):
    """Removes a binding. A mistyped one has to be undoable."""
    if not product_code_repository.unbind(value):
        raise HTTPException(status_code=404, detail="That code is not bound to anything.")
    audit_repository.record(
        action="product.code.unbound", actor=user, target_type="ProductCode",
        target_id=value[:64], summary="Unbound a scanned code",
    )


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
