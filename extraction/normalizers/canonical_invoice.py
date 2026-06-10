from pydantic import BaseModel
from typing import List, Optional, Any, Dict

class CanonicalLineItem(BaseModel):
    """
    Standardized line item schema for pharma invoice rows.
    Supports integers, decimals, packs, and scheme discount quantities.
    """
    name: Optional[str] = None
    pack: Optional[str] = None
    batch: Optional[str] = None
    expiry: Optional[str] = None
    hsn: Optional[str] = None
    quantity: Optional[Any] = None
    free_quantity: Optional[Any] = None
    mrp: Optional[Any] = None
    rate: Optional[Any] = None
    discount: Optional[Any] = None
    gst_percent: Optional[Any] = None
    amount: Optional[Any] = None
    confidence: Optional[float] = None

    class Config:
        extra = "allow"


class CanonicalInvoice(BaseModel):
    """
    Canonical invoice schema for mapping multi-engine outputs.
    """
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    seller_name: Optional[str] = None
    buyer_name: Optional[str] = None
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    grand_total: Optional[float] = None
    line_items: List[CanonicalLineItem] = []
    confidence: Optional[float] = None
    extraction_engine: Optional[str] = None
    raw_engine_metadata: Dict[str, Any] = {}

    class Config:
        extra = "allow"
