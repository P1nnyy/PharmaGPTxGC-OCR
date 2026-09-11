"""The sales domain: what a Sale is, and how it got here.

`capture_mode` is the field the rest of the system turns on. A pharmacy joining
PharmaFlow does not change its counter workflow on day one, so the same table
holds records of very different evidential weight:

  COUNTER     - billed through our own counter screen. Full lines, batches,
                stock movements, a serial we allocated.
  BILL_PHOTO  - the shop's own bill, photographed and extracted. Lines exist
                but were read by a machine and confirmed by a human.
  IMPORT      - a row from the shop's day book or sales register export.
  DAY_TOTAL   - a declared daily aggregate. No lines at all.

Reporting must not flatten those together. A margin figure computed over
DAY_TOTAL rows is meaningless, and a stock figure computed over them is worse
than meaningless because it looks precise. `CAPTURE_MODES_WITH_LINES` and
`CAPTURE_MODES_WITH_STOCK` below are what let a report say what it can and
cannot claim, rather than each report re-deciding.
"""

from typing import Optional

from pydantic import BaseModel, Field


class CaptureMode:
    COUNTER = "COUNTER"
    BILL_PHOTO = "BILL_PHOTO"
    IMPORT = "IMPORT"
    DAY_TOTAL = "DAY_TOTAL"

    ALL = {COUNTER, BILL_PHOTO, IMPORT, DAY_TOTAL}


class DocumentClass:
    # Rule 46A: one document covering taxable and exempt supplies to an
    # unregistered person. What a pharmacy counter issues almost every time.
    INVOICE_CUM_BILL_OF_SUPPLY = "INVOICE_CUM_BILL_OF_SUPPLY"
    TAX_INVOICE = "TAX_INVOICE"
    BILL_OF_SUPPLY = "BILL_OF_SUPPLY"

    ALL = {INVOICE_CUM_BILL_OF_SUPPLY, TAX_INVOICE, BILL_OF_SUPPLY}


class SaleStatus:
    # Extracted or imported but not yet confirmed by a person. Nothing in DRAFT
    # reaches a return.
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"

    ALL = {DRAFT, CONFIRMED}


# Modes that carry item-level lines, and so can answer "what sold".
CAPTURE_MODES_WITH_LINES = {CaptureMode.COUNTER, CaptureMode.BILL_PHOTO, CaptureMode.IMPORT}

# Modes that move stock. Only our own counter knows which batch left the shelf;
# a photographed or imported bill names a product but not necessarily a batch
# we hold, and a day total names nothing at all.
CAPTURE_MODES_WITH_STOCK = {CaptureMode.COUNTER}


class RateBlockInput(BaseModel):
    """One GST slab's declared total for the day.

    `gross_paise` is tax-inclusive — what the till took at this slab. The
    taxable value is derived from it rather than typed, so the two can never
    disagree.
    """

    rate_bp: int = Field(..., description="Rate in basis points: 1200 is 12%.")
    gross_paise: int = Field(..., description="Tax-inclusive total collected at this slab.")


class PaymentInput(BaseModel):
    method: str
    amount_paise: int
    reference: Optional[str] = None


class DayTotalRequest(BaseModel):
    """A day declared in one screen.

    Every amount is integer paise. The API boundary is the only place rupees
    exist, and this is inside it.
    """

    sale_date: str
    rate_blocks: list[RateBlockInput] = []
    exempt_paise: int = 0
    nil_rated_paise: int = 0
    # GSTR-1 Table 8 reports nil-rated, exempted and non-GST separately. A
    # shop with no non-GST supplies leaves this zero; one that has them needs
    # somewhere to put them that is not "exempt".
    non_gst_paise: int = 0
    payments: list[PaymentInput] = []
    notes: Optional[str] = None
