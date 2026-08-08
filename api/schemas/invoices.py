"""Invoice edit payloads.

Every field is optional: the review UI sends partial updates, and a field
absent from the payload means "leave it alone" rather than "set it to null".
"""

from typing import List, Optional

from pydantic import BaseModel


class LineItemUpdate(BaseModel):
    name: Optional[str] = None
    pack: Optional[str] = None
    batch: Optional[str] = None
    expiry: Optional[str] = None
    hsn: Optional[str] = None
    quantity: Optional[float] = None
    free_quantity: Optional[float] = None
    mrp: Optional[float] = None
    rate: Optional[float] = None
    discount: Optional[float] = None
    discount_percent: Optional[float] = None
    gst_percent: Optional[float] = None
    amount: Optional[float] = None
    is_estimated_amount: Optional[bool] = None
    bounding_box: Optional[List[float]] = None


class InvoiceUpdate(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    seller_name: Optional[str] = None
    seller_gstin: Optional[str] = None
    seller_address: Optional[str] = None
    seller_phone: Optional[str] = None
    drug_license: Optional[str] = None
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    grand_total: Optional[float] = None
    roundoff: Optional[float] = None
    status: Optional[str] = None
    line_items: Optional[List[LineItemUpdate]] = None
    # Opt-in required to clear an invoice's table, so that an empty line_items
    # array arriving by accident cannot delete rows. See EmptyLineItemsError.
    allow_empty_line_items: Optional[bool] = False
