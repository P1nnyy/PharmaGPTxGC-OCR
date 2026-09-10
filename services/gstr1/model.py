"""What the aggregation engine computes over.

The engine is deliberately pure: it takes documents and returns tables, and it
never opens a database. Two reasons, and the second matters more than it looks.

The obvious one is testability. A month of mixed sales, returns, cancellations
and a series gap can be built in a fixture and asserted to the paise, which is
the only way to know an aggregation is right before a return is filed on it.

The other is that `.env` in this repo points at the production Neo4j instance.
A tax engine that reads the graph directly is a tax engine whose tests read
production, so the read lives in `db/repositories/gstr1_repository.py` and
everything downstream of it works on these frozen structures.

`OutwardDocument` is a *normalised* view of a Sale, not the Sale node. The node
carries what the counter and the importers needed; this carries what a return
needs, which is not the same set. Where the node has no answer - a sale with no
place of supply recorded, a line with no HSN - the field is None and the
validation report says so, rather than a default being invented here.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


class SupplyClass:
    """What kind of supply a line is, for GSTR-1's purposes.

    Nil-rated and exempt are separate rows in Table 8 and are not the same
    thing: a nil-rated supply is taxable at 0%, an exempt one is outside the
    charge. A pharmacy now has both, because the notified list of life-saving
    drugs is nil rated while things like blood products are exempt.
    """

    TAXABLE = "TAXABLE"
    EXEMPT = "EXEMPT"
    NIL_RATED = "NIL_RATED"
    NON_GST = "NON_GST"

    ALL = {TAXABLE, EXEMPT, NIL_RATED, NON_GST}
    # The three that Table 8 reports and Table 12 leaves out of the tax columns.
    UNTAXED = {EXEMPT, NIL_RATED, NON_GST}


class SupplyType:
    """Intra-state or inter-state. Derived, never stored as an opinion."""

    INTRA = "INTRA"
    INTER = "INTER"


class DocumentType:
    """An invoice adds to a return; a credit note subtracts from it.

    Held separately from `document_class` because they answer different
    questions. The class is what the document is under Rule 46/46A - a tax
    invoice, a bill of supply, or the combined document a counter issues. The
    type is which direction it moves the numbers.
    """

    INVOICE = "INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"

    ALL = {INVOICE, CREDIT_NOTE}


class DocumentStatus:
    """Extends A1's DRAFT/CONFIRMED with the state Table 13 has to count.

    A cancelled document is not a deleted one. The portal cross-checks the
    documents-issued table against the document-level tables, so a number that
    was issued and then cancelled has to be *reported as cancelled* - it cannot
    simply be absent, or the series shows a gap the shop cannot explain.
    """

    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"

    ALL = {DRAFT, CONFIRMED, CANCELLED}
    # What reaches a return. A draft has not been confirmed by a person and a
    # cancelled document carries no supply, so neither contributes a figure -
    # though a cancelled one still appears in Table 13.
    REPORTABLE = {CONFIRMED}


def quantity(value) -> Decimal:
    """Reads a quantity into an exact decimal.

    Via `str` deliberately: a float 0.1 is not one tenth, and Decimal(0.1)
    faithfully preserves that error where Decimal("0.1") does not. Quantities
    are summed across a whole month in Table 12, so the error would accumulate
    into a figure somebody files.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class OutwardLine:
    """One line of a bill, as a return sees it."""

    line_id: Optional[str] = None
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    hsn: Optional[str] = None
    uqc: Optional[str] = None
    quantity: Decimal = Decimal("0")
    supply_class: str = SupplyClass.TAXABLE
    rate_bp: int = 0
    taxable_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise


@dataclass(frozen=True)
class RateBlock:
    """A slab's total on a document that has no lines.

    A day total declares "this much at 12%" and nothing more. It can answer
    Table 7 and Table 8, and it cannot answer Table 12 - which is why the HSN
    summary is built from lines only and a shop filing on day totals is told
    it has no HSN data rather than being given a summary that looks complete.
    """

    rate_bp: int = 0
    taxable_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise


@dataclass(frozen=True)
class OutwardDocument:
    """A bill, credit note or declared aggregate, as a return sees it."""

    document_id: str
    sale_date: str
    tax_period: str
    supplier_state_code: str

    bill_number: Optional[str] = None
    series_prefix: Optional[str] = None
    serial_sequence: Optional[int] = None

    document_type: str = DocumentType.INVOICE
    document_class: str = "INVOICE_CUM_BILL_OF_SUPPLY"
    capture_mode: str = "COUNTER"
    status: str = DocumentStatus.CONFIRMED

    # None when nothing was recorded. An over-the-counter sale is supplied
    # where the counter is, so the repository fills this with the shop's own
    # state for a counter bill - but it does not invent one for an imported
    # row that never said, because that row might be the interstate delivery.
    place_of_supply_state_code: Optional[str] = None
    customer_gstin: Optional[str] = None
    customer_name: Optional[str] = None

    lines: tuple = ()
    rate_blocks: tuple = ()

    exempt_paise: int = 0
    nil_rated_paise: int = 0
    non_gst_paise: int = 0

    taxable_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0
    round_off_paise: int = 0
    grand_total_paise: int = 0

    is_aggregate: bool = False
    reverses_document_id: Optional[str] = None
    notes: Optional[str] = None

    # ---------------------------------------------------------- derived

    @property
    def supply_type(self) -> Optional[str]:
        """Intra-state when the place of supply is the shop's own state.

        None when the place of supply was never recorded. That is not the same
        as intra-state, and treating it as such is exactly how an interstate
        supply gets filed as CGST+SGST.
        """
        if not self.place_of_supply_state_code or not self.supplier_state_code:
            return None
        if self.place_of_supply_state_code == self.supplier_state_code:
            return SupplyType.INTRA
        return SupplyType.INTER

    @property
    def is_b2b(self) -> bool:
        """A supply to a registered person, identified by their GSTIN."""
        return bool(self.customer_gstin)

    @property
    def sign(self) -> int:
        """+1 for an invoice, -1 for a credit note.

        Amounts are stored as positive magnitudes and the direction is applied
        here. Keeping negatives out of the data means "is this figure
        negative?" stays a question about an aggregate, which is the thing the
        B2CS guard actually needs to ask.
        """
        return -1 if self.document_type == DocumentType.CREDIT_NOTE else 1

    @property
    def is_reportable(self) -> bool:
        """Whether this document contributes figures to a return."""
        return self.status in DocumentStatus.REPORTABLE

    @property
    def has_lines(self) -> bool:
        return bool(self.lines)

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise

    @property
    def invoice_value_paise(self) -> int:
        """What the document is worth, for the B2CL threshold and Table 4A.

        The grand total when there is one. Day totals and some imported rows
        never carry a header total, so it falls back to the parts - which is
        the same number when both exist.
        """
        if self.grand_total_paise:
            return self.grand_total_paise
        return (
            self.taxable_paise
            + self.tax_paise
            + self.cess_paise
            + self.exempt_paise
            + self.nil_rated_paise
            + self.non_gst_paise
            + self.round_off_paise
        )

    @property
    def untaxed_paise(self) -> int:
        """Everything on the document that carries no tax."""
        return self.exempt_paise + self.nil_rated_paise + self.non_gst_paise


@dataclass
class FilingPeriod:
    """The window one GSTR-1 covers, and the months inside it.

    A monthly filer's window is one month; a QRMP filer's is three. Everything
    downstream iterates `months` rather than assuming a single period, and the
    filing lock closes all of them together - filing a quarter has to lock the
    quarter, not the month somebody happened to click.
    """

    label: str
    frequency: str
    months: tuple = ()
    start_date: str = ""
    end_date: str = ""
    financial_year: Optional[int] = None
    quarter: Optional[int] = None

    @property
    def is_quarterly(self) -> bool:
        return self.frequency == "QUARTERLY"
