from pydantic import BaseModel
from typing import List, Optional, Any, Dict

class CanonicalLineItem(BaseModel):
    """
    Standardized line item schema for pharma invoice rows.
    Supports integers, decimals, packs, and scheme discount quantities.
    """
    name: Optional[str] = None
    pack: Optional[str] = None
    # Maker as printed on the invoice ("Mfr"/"Company Name" column). Usually an
    # abbreviation - ABBO, LEEFORD, INTAS - but it is the supplier's own
    # statement of who makes the item, which no public listing can contradict.
    manufacturer: Optional[str] = None
    batch: Optional[str] = None
    expiry: Optional[str] = None
    hsn: Optional[str] = None
    quantity: Optional[Any] = None
    free_quantity: Optional[Any] = None
    mrp: Optional[Any] = None
    rate: Optional[Any] = None
    # Rupee discount deducted from this line.
    discount: Optional[Any] = None
    # Discount stated as a percentage. Kept separate from the rupee amount
    # because subtracting a percentage as if it were currency mis-prices the
    # line, and many invoices print both columns side by side.
    discount_percent: Optional[Any] = None
    gst_percent: Optional[Any] = None
    amount: Optional[Any] = None
    # True when amount was not printed on the invoice and has been derived
    # from the other columns. Never presented as extracted data.
    is_estimated_amount: bool = False
    confidence: Optional[float] = None
    bounding_box: Optional[List[float]] = None

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
    seller_gstin: Optional[str] = None
    buyer_gstin: Optional[str] = None
    seller_address: Optional[str] = None
    buyer_address: Optional[str] = None
    seller_phone: Optional[str] = None
    drug_license: Optional[str] = None
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    grand_total: Optional[float] = None
    # Rounding adjustment the invoice itself applied to reach grand_total
    # (e.g. -0.20). None when the invoice has no such line at all - distinct
    # from an invoice that explicitly rounds off by zero.
    roundoff: Optional[float] = None
    line_items: List[CanonicalLineItem] = []
    confidence: Optional[float] = None
    extraction_engine: Optional[str] = None
    raw_engine_metadata: Dict[str, Any] = {}
    # Azure Document Intelligence page rotation angle (degrees, counter-clockwise)
    page_angle: Optional[float] = None
    # One angle per page, in page order. Pages of the same invoice are often
    # photographed at different angles - one sheet landscape, the next upright -
    # so a single invoice-level angle would orient every page but the first
    # incorrectly. Missing angles are recorded as 0.0 rather than null because
    # Neo4j list properties cannot contain nulls.
    page_angles: List[float] = []

    class Config:
        extra = "allow"

