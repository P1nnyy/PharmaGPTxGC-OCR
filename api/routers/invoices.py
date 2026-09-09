"""Invoice read, edit and delete."""

from fastapi import APIRouter, Depends, HTTPException

from api.schemas.invoices import InvoiceUpdate
from core.logger import logger
from api.deps import current_user
from db.repositories import audit_repository
from services.invoices import changes as change_log
from db.repositories import invoice_repository
from enrichment import reference_service
from services import image_storage
from extraction.normalizers.amount_inference import fill_missing_amounts
from extraction.normalizers.canonical_invoice import CanonicalLineItem
from services.invoices.presentation import attach_image_urls

router = APIRouter(tags=["invoices"])


@router.get("/invoices")
def list_invoices():
    invoices = invoice_repository.list_invoices()
    for invoice in invoices:
        attach_image_urls(invoice)
    return invoices


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    invoice = invoice_repository.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")
    return attach_image_urls(invoice)


@router.patch("/invoices/{invoice_id}")
def update_invoice(invoice_id: str, payload: InvoiceUpdate, user: dict = Depends(current_user)):
    header = payload.model_dump(exclude={"status", "line_items"}, exclude_none=True)
    line_items = (
        [item.model_dump() for item in payload.line_items]
        if payload.line_items is not None
        else None
    )

    # Read before writing, so the trail can say what a value changed *from*.
    # "Someone changed the tax" is not an answer anyone can act on months
    # later; "changed CGST from 178.16 to 89.08" is.
    previous = invoice_repository.get_invoice(invoice_id) or {}
    field_changes = change_log.header_changes(previous, header)
    row_change = change_log.line_item_change(
        len(previous.get("line_items") or []),
        len(line_items) if line_items is not None else None,
    )
    if row_change:
        field_changes = field_changes + [row_change]

    try:
        ok = invoice_repository.update_invoice(
            invoice_id,
            header,
            line_items,
            payload.status,
            allow_empty_line_items=bool(payload.allow_empty_line_items),
        )
    except invoice_repository.EmptyLineItemsError as exc:
        # 409, not 400: the payload is well-formed, it just conflicts with the
        # invoice's current state. Nothing was written.
        raise HTTPException(status_code=409, detail=str(exc))

    if not ok:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    actor_name = user.get("name") or user.get("email") or "Someone"
    reference = previous.get("invoice_number") or invoice_id

    # Recorded only when something actually moved. The review screen resends
    # every field on every save, so logging each save regardless would bury
    # the real edits under a pile of "no changes".
    if field_changes:
        audit_repository.record(
            "invoice.updated", actor=user, target_type="invoice", target_id=invoice_id,
            summary=change_log.summarise(actor_name, field_changes),
            invoice=reference,
            changes=change_log.as_details(field_changes),
        )

    # Verification is its own event, not a field edit: it is the moment the
    # invoice stops being a draft and its items enter the catalogue.
    if payload.status == "verified" and previous.get("status") != "verified":
        audit_repository.record(
            "invoice.verified", actor=user, target_type="invoice", target_id=invoice_id,
            summary=f"{actor_name} approved invoice {reference}",
            invoice=reference,
        )

    # Verifying is the moment an invoice's items enter the catalogue, so it is
    # where they get matched against the reference. Doing it here rather than
    # on upload is not incidental: the catalogue only ever reads from verified
    # invoices, so before this point there is no catalogue product to fill in.
    #
    # Best effort by design. A reference index that is missing, stale or slow
    # must never be able to stop an invoice being verified.
    if payload.status == "verified":
        try:
            summary = reference_service.autofill_products(_product_ids_for(invoice_id))
            logger.info(f"[INVOICE {invoice_id}] Reference autofill: {summary}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[INVOICE {invoice_id}] Reference autofill skipped: {exc}")

    return attach_image_urls(invoice_repository.get_invoice(invoice_id))


def _product_ids_for(invoice_id: str) -> list:
    """The catalogue products this invoice's lines resolve to."""
    from db.graph_db import get_driver

    with get_driver().session() as session:
        return [
            record["id"]
            for record in session.run(
                """
                MATCH (:Invoice {id: $id})-[:CONTAINS]->(:LineItem)-[:OF_PRODUCT]->(p:Product)
                RETURN DISTINCT p.id AS id
                """,
                id=invoice_id,
            )
        ]


@router.post("/invoices/{invoice_id}/recompute-amounts")
def recompute_invoice_amounts(invoice_id: str):
    """Derives missing line Amounts on an invoice already stored.

    The inference runs during extraction, so an invoice captured before it
    could read a given format keeps its blanks forever. This re-runs it over
    the stored rows using the invoice's own printed subtotal, which is what
    rescues the case this was built for: an Amount column carrying values
    under no column heading, where nothing anchors the column and every row
    extracts blank.

    Only blanks are filled, and only when a formula reproduces the printed
    total. An amount actually read off the page is left alone.
    """
    invoice = invoice_repository.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    rows = invoice.get("line_items") or []
    items = [
        CanonicalLineItem(
            name=row.get("product_name"),
            quantity=row.get("quantity"),
            rate=row.get("rate"),
            discount=row.get("discount"),
            discount_percent=row.get("discount_percent"),
            gst_percent=row.get("gst_percent"),
            amount=row.get("amount"),
        )
        for row in rows
    ]

    before = [item.amount for item in items]
    result = fill_missing_amounts(items, printed_total=invoice.get("subtotal"))

    derived = {
        row["id"]: item.amount
        for row, item, was in zip(rows, items, before)
        if was is None and item.amount is not None
    }
    updated = invoice_repository.update_line_item_amounts(derived)

    refreshed = invoice_repository.get_invoice(invoice_id)
    attach_image_urls(refreshed)
    return {
        "status": "ok",
        "formula": result.get("formula"),
        "evidence": result.get("evidence"),
        "updated": updated,
        "invoice": refreshed,
    }


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: str, user: dict = Depends(current_user)):
    result = invoice_repository.delete_invoice(invoice_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    # Recorded after the fact, with the invoice number copied in: once the
    # node is gone there is nothing left to look the number up from, and
    # "deleted invoice <uuid>" answers nobody's question.
    audit_repository.record(
        "invoice.deleted", actor=user, target_type="invoice", target_id=invoice_id,
        summary=f"{user['email']} deleted invoice {result.get('invoice_number') or invoice_id}",
    )

    # Remove every page image, not just page 1 - a multi-page invoice would
    # otherwise leave its remaining pages orphaned in R2 forever.
    for image_ref in result.get("image_refs") or []:
        try:
            image_storage.delete_invoice_image(image_ref)
        except Exception as e:
            logger.warning(f"Failed to delete R2 object {image_ref}: {e}")

    return {"message": "Invoice deleted.", "id": invoice_id}


@router.get("/invoices/{invoice_id}/activity")
def invoice_activity(invoice_id: str, user: dict = Depends(current_user)):
    """Everything that has happened to this invoice, oldest first.

    Readable by any member of the workspace, not just admins: knowing who
    changed a figure you are about to approve is part of reviewing it, and
    hiding that from the person doing the reviewing would defeat the point.
    Scoped to the caller's workspace by the repository, so one shop cannot
    read another's history.
    """
    trail = audit_repository.list_events(
        pharmacy_id=user["pharmacy_id"], target_id=invoice_id, limit=200,
    )
    # Oldest first here, unlike the workspace-wide feed: this reads as the
    # story of one invoice, and a story runs forwards.
    events = list(reversed(trail.get("events", [])))
    return {"events": events, "count": len(events)}
