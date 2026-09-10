"""The GSTR-1 tables, aggregated from outward documents.

Every function here is pure: documents in, an aggregate out, no database and no
clock. All arithmetic is integer paise summed exactly - there is no rounding
anywhere in this module, because there is nothing to round. A sum of exact
paise is exact, and the only conversion to rupees happens in `payload.py` on
the way to the portal.

Where a figure could come from two places, it comes from the more primitive
one. Table 12 is recomputed from line items rather than read off a stored
summary, and the rate-level tables prefer lines to declared rate blocks. A
stored aggregate is a figure that was right when it was written; a return needs
one that is right now.

Credit notes are held as positive magnitudes and subtracted here via
`document.sign`. That keeps negative numbers out of the stored data, so "did
this go negative?" stays a question about an aggregate - which is exactly what
Table 7's guard has to ask.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional

from core.hsn import normalize_hsn
from services.gstr1.model import (
    DocumentStatus,
    DocumentType,
    OutwardDocument,
    SupplyClass,
    SupplyType,
    quantity as to_quantity,
)

# ₹2,50,000 in paise. The threshold above which an inter-state supply to an
# unregistered person is reported invoice-wise in Table 5 rather than folded
# into the Table 7 aggregate.
B2CL_THRESHOLD_PAISE = 2_50_000_00


# ---------------------------------------------------------------- helpers


def reportable(documents: Iterable[OutwardDocument]) -> list:
    """The documents that contribute figures to a return.

    Drafts have not been confirmed by a person and cancelled documents carry no
    supply. Both still matter to Table 13, which counts numbers issued rather
    than supplies made, so that table takes the unfiltered list.
    """
    return [d for d in documents if d.is_reportable]


def _taxable_components(document: OutwardDocument) -> list:
    """A document's taxable slabs, preferring lines to declared blocks.

    A day total has no lines and can only answer at the slab level; a counter
    bill has lines and is summed from them. Rate blocks are ignored when lines
    exist so that a stale stored block cannot contradict the lines it was
    derived from.

    Nil-rated, exempt and non-GST are excluded: they are Table 8's, not
    Table 7's. A slab at 0% is likewise excluded - a zero-rated taxable supply
    is a nil-rated supply, and the validation report says so rather than this
    quietly filing a 0% row the portal does not expect.
    """
    if document.has_lines:
        return [
            line
            for line in document.lines
            if line.supply_class == SupplyClass.TAXABLE and line.rate_bp > 0
        ]
    return [block for block in document.rate_blocks if block.rate_bp > 0]


def _untaxed_totals(document: OutwardDocument) -> dict:
    """The nil-rated, exempt and non-GST amounts on a document.

    From lines when it has them, from the header when it does not. A day total
    declares these three directly; a counter bill classifies each line.
    """
    if not document.has_lines:
        return {
            SupplyClass.NIL_RATED: document.nil_rated_paise,
            SupplyClass.EXEMPT: document.exempt_paise,
            SupplyClass.NON_GST: document.non_gst_paise,
        }
    totals = {SupplyClass.NIL_RATED: 0, SupplyClass.EXEMPT: 0, SupplyClass.NON_GST: 0}
    for line in document.lines:
        if line.supply_class in totals:
            totals[line.supply_class] += line.taxable_paise
    return totals


# ------------------------------------------------------- Table 7: B2CS


@dataclass
class B2csBucket:
    """One (place of supply, rate, supply type) aggregate."""

    place_of_supply: str
    rate_bp: int
    supply_type: str
    taxable_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0
    # Kept so the review UI can open the bills behind a bucket. A figure with
    # no route back to its documents is a figure nobody can check.
    document_ids: list = field(default_factory=list)

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise

    @property
    def is_negative(self) -> bool:
        """Whether returns have exceeded sales anywhere in this bucket."""
        return (
            self.taxable_paise < 0
            or self.cgst_paise < 0
            or self.sgst_paise < 0
            or self.igst_paise < 0
            or self.cess_paise < 0
        )


@dataclass
class B2csResult:
    buckets: list = field(default_factory=list)
    negative_buckets: list = field(default_factory=list)


def aggregate_b2cs(
    documents: Iterable[OutwardDocument],
    b2cl_document_ids: Optional[set] = None,
) -> B2csResult:
    """Table 7. Supplies to unregistered persons, aggregated rate-wise.

    Grouped by place of supply, rate and supply type. Sale returns to
    unregistered customers net into the same buckets - that is what a credit
    note to a walk-in customer does to a return, and reporting it anywhere else
    would leave the aggregate overstating what was actually supplied.

    Buckets that go negative are separated out rather than emitted. A negative
    B2CS aggregate means the period's returns exceeded its sales for that
    combination, which is a real thing that happens - a customer returning in
    October what they bought in September - but it is not something the portal
    accepts, and the fix is an amendment to the earlier period rather than a
    negative figure in this one. So it stops and is raised for review.
    """
    b2cl_document_ids = b2cl_document_ids or set()
    buckets: dict = {}

    for document in reportable(documents):
        if document.is_b2b or document.document_id in b2cl_document_ids:
            continue
        supply_type = document.supply_type
        place_of_supply = document.place_of_supply_state_code
        # Without a place of supply there is no bucket to put this in. The
        # validation report raises it; inventing the shop's own state here
        # would file an interstate supply as intra-state.
        if not supply_type or not place_of_supply:
            continue

        sign = document.sign
        for component in _taxable_components(document):
            key = (place_of_supply, component.rate_bp, supply_type)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = buckets[key] = B2csBucket(
                    place_of_supply=place_of_supply,
                    rate_bp=component.rate_bp,
                    supply_type=supply_type,
                )
            bucket.taxable_paise += sign * component.taxable_paise
            bucket.cgst_paise += sign * component.cgst_paise
            bucket.sgst_paise += sign * component.sgst_paise
            bucket.igst_paise += sign * component.igst_paise
            bucket.cess_paise += sign * component.cess_paise
            if document.document_id not in bucket.document_ids:
                bucket.document_ids.append(document.document_id)

    ordered = sorted(
        buckets.values(), key=lambda b: (b.place_of_supply, b.supply_type, b.rate_bp)
    )
    return B2csResult(
        buckets=[b for b in ordered if not b.is_negative],
        negative_buckets=[b for b in ordered if b.is_negative],
    )


# ------------------------------------------------------- Table 5: B2CL


@dataclass
class B2clInvoice:
    document_id: str
    bill_number: Optional[str]
    sale_date: str
    place_of_supply: str
    invoice_value_paise: int
    document_type: str
    rate_blocks: list = field(default_factory=list)


def qualifies_for_b2cl(document: OutwardDocument) -> bool:
    """Whether a bill belongs in Table 5.

    Inter-state, to an unregistered person, above ₹2,50,000.

    This should almost never be true for a pharmacy, and that is the point of
    having it as a predicate rather than a code path. An over-the-counter sale
    is supplied where the counter stands, so it is intra-state however far the
    customer has travelled - a customer from another state buying medicine in
    person does not make the supply inter-state. A bill that does qualify is
    therefore far more likely to be a place of supply entered wrongly than a
    genuine large inter-state consumer sale, which is why the engine flags it
    for a person to look at instead of quietly filing it.
    """
    return (
        document.is_reportable
        # Invoices only. A credit note to an unregistered person nets into the
        # Table 7 aggregate; a large inter-state one would be Table 9B's
        # CDNUR, which this engine does not build.
        and document.document_type == DocumentType.INVOICE
        and not document.is_b2b
        and document.supply_type == SupplyType.INTER
        and document.invoice_value_paise > B2CL_THRESHOLD_PAISE
    )


def aggregate_b2cl(documents: Iterable[OutwardDocument]) -> list:
    """Table 5, invoice-wise. Every entry here is also a review item."""
    entries = []
    for document in documents:
        if not qualifies_for_b2cl(document):
            continue
        entries.append(
            B2clInvoice(
                document_id=document.document_id,
                bill_number=document.bill_number,
                sale_date=document.sale_date,
                place_of_supply=document.place_of_supply_state_code or "",
                invoice_value_paise=document.invoice_value_paise,
                document_type=document.document_type,
                rate_blocks=_rate_summary(document),
            )
        )
    return sorted(entries, key=lambda e: (e.sale_date, e.bill_number or ""))


def _rate_summary(document: OutwardDocument) -> list:
    """A document's taxable slabs collapsed to one row per rate."""
    by_rate: dict = defaultdict(
        lambda: {
            "rate_bp": 0,
            "taxable_paise": 0,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "igst_paise": 0,
            "cess_paise": 0,
        }
    )
    for component in _taxable_components(document):
        row = by_rate[component.rate_bp]
        row["rate_bp"] = component.rate_bp
        row["taxable_paise"] += component.taxable_paise
        row["cgst_paise"] += component.cgst_paise
        row["sgst_paise"] += component.sgst_paise
        row["igst_paise"] += component.igst_paise
        row["cess_paise"] += component.cess_paise
    return [by_rate[rate] for rate in sorted(by_rate)]


# ------------------------------------------------------- Table 4A: B2B


@dataclass
class B2bInvoice:
    document_id: str
    customer_gstin: str
    customer_name: Optional[str]
    bill_number: Optional[str]
    sale_date: str
    place_of_supply: str
    supply_type: Optional[str]
    invoice_value_paise: int
    document_type: str
    document_class: str
    rate_blocks: list = field(default_factory=list)


def credit_notes_to_registered(documents: Iterable[OutwardDocument]) -> list:
    """B2B credit notes, which Table 4A must not swallow.

    A credit note against a registered person is reported in Table 9B (CDNR),
    which is a document-level table of its own and outside what this engine
    builds. It is collected here rather than ignored so the validation report
    can say it has been left out - listing it in Table 4A would file a
    reduction as if it were a supply, and dropping it silently would understate
    the shop's credit notes with nothing to show for it.
    """
    return [
        d for d in reportable(documents)
        if d.is_b2b and d.document_type == DocumentType.CREDIT_NOTE
    ]


def aggregate_b2b(documents: Iterable[OutwardDocument]) -> list:
    """Table 4A. Supplies to registered persons, invoice-wise.

    Rare for a pharmacy but real: returning expired stock to a distributor is
    commonly handled by the pharmacy raising its own outward tax invoice
    against the distributor's GSTIN, which is an outward B2B supply and has to
    be reported as one.

    Invoices only. A credit note to a registered person belongs in Table 9B -
    see `credit_notes_to_registered`.
    """
    entries = []
    for document in reportable(documents):
        if not document.is_b2b or document.document_type != DocumentType.INVOICE:
            continue
        entries.append(
            B2bInvoice(
                document_id=document.document_id,
                customer_gstin=document.customer_gstin or "",
                customer_name=document.customer_name,
                bill_number=document.bill_number,
                sale_date=document.sale_date,
                place_of_supply=document.place_of_supply_state_code or "",
                supply_type=document.supply_type,
                invoice_value_paise=document.invoice_value_paise,
                document_type=document.document_type,
                document_class=document.document_class,
                rate_blocks=_rate_summary(document),
            )
        )
    return sorted(entries, key=lambda e: (e.sale_date, e.bill_number or ""))


# --------------------------------------- Table 8: nil rated, exempt, non-GST


@dataclass
class NilExemptRow:
    """One of Table 8's four rows."""

    code: str            # 8A, 8B, 8C or 8D
    description: str
    supply_type: str
    registered: bool
    nil_rated_paise: int = 0
    exempted_paise: int = 0
    non_gst_paise: int = 0

    @property
    def total_paise(self) -> int:
        return self.nil_rated_paise + self.exempted_paise + self.non_gst_paise


# The four rows the portal expects, in its order. Always emitted, even at zero:
# Table 8 is a complete statement of untaxed supplies, and an absent row is not
# the same claim as a zero one.
_TABLE_8_ROWS = (
    ("8A", "Inter-State supplies to registered persons", SupplyType.INTER, True),
    ("8B", "Intra-State supplies to registered persons", SupplyType.INTRA, True),
    ("8C", "Inter-State supplies to unregistered persons", SupplyType.INTER, False),
    ("8D", "Intra-State supplies to unregistered persons", SupplyType.INTRA, False),
)


def aggregate_nil_exempt(documents: Iterable[OutwardDocument]) -> list:
    """Table 8, split intra/inter and registered/unregistered.

    Material for a pharmacy rather than a formality: the notified list of
    life-saving drugs is nil rated, so a shop that stocks any of them has a
    Table 8 with real figures in it every month.
    """
    rows = {
        (supply_type, registered): NilExemptRow(
            code=code,
            description=description,
            supply_type=supply_type,
            registered=registered,
        )
        for code, description, supply_type, registered in _TABLE_8_ROWS
    }

    for document in reportable(documents):
        supply_type = document.supply_type
        if not supply_type:
            continue
        row = rows.get((supply_type, document.is_b2b))
        if row is None:
            continue
        sign = document.sign
        totals = _untaxed_totals(document)
        row.nil_rated_paise += sign * totals[SupplyClass.NIL_RATED]
        row.exempted_paise += sign * totals[SupplyClass.EXEMPT]
        row.non_gst_paise += sign * totals[SupplyClass.NON_GST]

    return [rows[(supply_type, registered)] for _, _, supply_type, registered in _TABLE_8_ROWS]


# ------------------------------------------------------ Table 12: HSN summary


@dataclass
class HsnRow:
    hsn: str
    uqc: Optional[str]
    rate_bp: int
    quantity: Decimal = Decimal("0")
    taxable_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0
    supply_class: str = SupplyClass.TAXABLE
    document_ids: list = field(default_factory=list)

    @property
    def total_value_paise(self) -> int:
        return (
            self.taxable_paise
            + self.cgst_paise
            + self.sgst_paise
            + self.igst_paise
            + self.cess_paise
        )


@dataclass
class HsnSummary:
    b2b: list = field(default_factory=list)
    b2c: list = field(default_factory=list)
    # Lines that could not be summarised, kept for the validation report.
    lines_without_hsn: list = field(default_factory=list)
    lines_without_uqc: list = field(default_factory=list)
    documents_without_lines: list = field(default_factory=list)


def aggregate_hsn(documents: Iterable[OutwardDocument]) -> HsnSummary:
    """Table 12, recomputed from line items and split B2B from B2C.

    Never from a stored summary. A stored aggregate was correct when it was
    written, and a line corrected afterwards leaves it silently wrong - which
    the portal then cross-checks against the document-level tables and rejects.

    Rows are keyed on HSN, UQC and rate together, because that is how the
    portal keys them: the same code sold at two rates, or in two units, is two
    rows and not one.

    A document with no lines cannot contribute. Day totals are the usual case,
    and they are collected rather than ignored so the report can say the HSN
    summary is incomplete instead of presenting a partial one as whole.
    """
    summary = HsnSummary()
    b2b_rows: dict = {}
    b2c_rows: dict = {}

    for document in reportable(documents):
        if not document.has_lines:
            if document.untaxed_paise or document.taxable_paise:
                summary.documents_without_lines.append(document.document_id)
            continue

        rows = b2b_rows if document.is_b2b else b2c_rows
        sign = document.sign

        for line in document.lines:
            hsn = normalize_hsn(line.hsn)
            if not hsn:
                summary.lines_without_hsn.append(
                    {
                        "document_id": document.document_id,
                        "line_id": line.line_id,
                        "product_id": line.product_id,
                        "product_name": line.product_name,
                        "is_b2b": document.is_b2b,
                    }
                )
                continue
            if not line.uqc:
                summary.lines_without_uqc.append(
                    {
                        "document_id": document.document_id,
                        "line_id": line.line_id,
                        "product_id": line.product_id,
                        "product_name": line.product_name,
                        "hsn": hsn,
                        "is_b2b": document.is_b2b,
                    }
                )

            key = (hsn, line.uqc, line.rate_bp)
            row = rows.get(key)
            if row is None:
                row = rows[key] = HsnRow(
                    hsn=hsn,
                    uqc=line.uqc,
                    rate_bp=line.rate_bp,
                    supply_class=line.supply_class,
                )
            row.quantity += sign * to_quantity(line.quantity)
            row.taxable_paise += sign * line.taxable_paise
            row.cgst_paise += sign * line.cgst_paise
            row.sgst_paise += sign * line.sgst_paise
            row.igst_paise += sign * line.igst_paise
            row.cess_paise += sign * line.cess_paise
            if document.document_id not in row.document_ids:
                row.document_ids.append(document.document_id)

    def ordered(rows: dict) -> list:
        return [rows[key] for key in sorted(rows, key=lambda k: (k[0], k[1] or "", k[2]))]

    summary.b2b = ordered(b2b_rows)
    summary.b2c = ordered(b2c_rows)
    return summary


# --------------------------------------------- Table 13: documents issued


@dataclass
class SeriesSummary:
    series_prefix: str
    opening_number: Optional[str] = None
    closing_number: Optional[str] = None
    opening_sequence: Optional[int] = None
    closing_sequence: Optional[int] = None
    total_issued: int = 0
    cancelled: int = 0
    gaps: list = field(default_factory=list)
    # Numbers used by more than one document. Distinct from a gap and more
    # serious: two bills sharing a serial are indistinguishable in a return,
    # and the offline design has no conflict resolver downstream to catch it.
    duplicates: list = field(default_factory=list)

    @property
    def net_issued(self) -> int:
        return self.total_issued - self.cancelled


@dataclass
class DocumentsIssued:
    series: list = field(default_factory=list)
    documents_without_series: list = field(default_factory=list)

    @property
    def has_gaps(self) -> bool:
        return any(s.gaps for s in self.series)

    @property
    def has_duplicates(self) -> bool:
        return any(s.duplicates for s in self.series)


def aggregate_documents_issued(documents: Iterable[OutwardDocument]) -> DocumentsIssued:
    """Table 13, per bill series.

    Counts numbers *issued*, not supplies made, so unlike every other table
    here it does not filter to confirmed documents. A cancelled bill still
    consumed a number and has to be reported as cancelled - it cannot simply be
    absent, because the portal cross-checks these counts against the
    document-level tables and an absent number reads as a gap the shop cannot
    account for. A draft has a number too: the shop issued it whether or not
    anybody has confirmed the figures on it yet.

    Gaps are surfaced rather than smoothed over. Rule 46(b) wants consecutive
    numbering within a financial year, and a missing number in the middle of a
    series is either a bill that was never synced or one that was deleted -
    both of which someone needs to know about before the return goes.
    """
    issued = DocumentsIssued()
    by_prefix: dict = defaultdict(list)

    for document in documents:
        if document.series_prefix is None or document.serial_sequence is None:
            # Only worth reporting for documents that would otherwise appear in
            # a table; a day total has no serial and never claimed to.
            if not document.is_aggregate:
                issued.documents_without_series.append(document.document_id)
            continue
        by_prefix[document.series_prefix].append(document)

    for prefix in sorted(by_prefix):
        group = sorted(by_prefix[prefix], key=lambda d: d.serial_sequence)
        sequences = [d.serial_sequence for d in group]
        first, last = group[0], group[-1]
        present = set(sequences)
        summary = SeriesSummary(
            series_prefix=prefix,
            opening_number=first.bill_number,
            closing_number=last.bill_number,
            opening_sequence=first.serial_sequence,
            closing_sequence=last.serial_sequence,
            total_issued=len(group),
            cancelled=sum(1 for d in group if d.status == DocumentStatus.CANCELLED),
            gaps=[n for n in range(first.serial_sequence, last.serial_sequence + 1) if n not in present],
            duplicates=sorted(n for n, count in Counter(sequences).items() if count > 1),
        )
        issued.series.append(summary)

    return issued
