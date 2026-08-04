"""Invoice read, edit and delete."""

from fastapi import APIRouter, HTTPException

from api.schemas.invoices import InvoiceUpdate
from core.logger import logger
from db.repositories import invoice_repository
from services import image_storage
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
def update_invoice(invoice_id: str, payload: InvoiceUpdate):
    header = payload.model_dump(exclude={"status", "line_items"}, exclude_none=True)
    line_items = (
        [item.model_dump() for item in payload.line_items]
        if payload.line_items is not None
        else None
    )

    ok = invoice_repository.update_invoice(invoice_id, header, line_items, payload.status)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    return attach_image_urls(invoice_repository.get_invoice(invoice_id))


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: str):
    result = invoice_repository.delete_invoice(invoice_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

    # Remove every page image, not just page 1 - a multi-page invoice would
    # otherwise leave its remaining pages orphaned in R2 forever.
    for image_ref in result.get("image_refs") or []:
        try:
            image_storage.delete_invoice_image(image_ref)
        except Exception as e:
            logger.warning(f"Failed to delete R2 object {image_ref}: {e}")

    return {"message": "Invoice deleted.", "id": invoice_id}
