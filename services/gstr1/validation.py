"""What has to be true before a return can be filed.

Every check here answers one question: would filing this cause a problem that
is expensive to undo? A GSTR-1 cannot be revised. A figure that is wrong goes
out wrong and is corrected by an amendment in a later period, which means the
cheapest moment to catch it is now, before the period closes.

That is why the split between blocking and warning is not about how serious a
thing sounds. It is about whether filing makes it worse:

  BLOCKING  the return would be rejected by the portal, or would state a
            figure that is wrong. Filing does damage.
  WARNING   the return is filable and correct as far as it goes, but someone
            should look - usually because the underlying record is untidy in a
            way that will cost more later than it does today.

Blocking items can be acknowledged. Some of them are unavoidable facts about a
real month rather than mistakes - a genuine large inter-state consumer sale
does belong in Table 5 - and a system that cannot be overridden by a person who
knows better is a system people work around. An acknowledgement is recorded
against the period with who made it, so the override is evidence rather than a
silence.

Each item carries a route back to the record it is about. A validation message
with no link is a message somebody has to go hunting behind.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Optional

from core.hsn import AATO_SIX_DIGIT_THRESHOLD_PAISE, HsnError, is_valid_uqc, validate_hsn
from services.gstr1.model import (
    DocumentStatus,
    DocumentType,
    OutwardDocument,
    SupplyClass,
)
from services.gstr1.tables import reportable

BLOCKING = "BLOCKING"
WARNING = "WARNING"


@dataclass
class ValidationItem:
    code: str
    severity: str
    message: str
    record_type: str
    record_id: Optional[str] = None
    line_id: Optional[str] = None
    acknowledgeable: bool = True
    context: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        """A stable handle, so an acknowledgement survives a re-run.

        Derived from what the item is about rather than from when it was
        produced: the same problem on the same record has to come back with the
        same id, or acknowledging it once would not stick.
        """
        seed = f"{self.code}|{self.record_type}|{self.record_id or ''}|{self.line_id or ''}"
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


@dataclass
class ValidationReport:
    items: list = field(default_factory=list)
    acknowledged: set = field(default_factory=set)

    @property
    def blocking(self) -> list:
        return [i for i in self.items if i.severity == BLOCKING]

    @property
    def warnings(self) -> list:
        return [i for i in self.items if i.severity == WARNING]

    @property
    def unacknowledged_blocking(self) -> list:
        return [i for i in self.blocking if i.id not in self.acknowledged]

    @property
    def can_close(self) -> bool:
        return not self.unacknowledged_blocking

    def add(self, **kwargs) -> None:
        self.items.append(ValidationItem(**kwargs))


# --------------------------------------------------------- reconciliation


def reconcile_document(document: OutwardDocument) -> list:
    """Where a document's parts do not add up to its header.

    The house rule is that tax is computed per line, summed per rate block and
    reconciled to the header, and that a mismatch is an error rather than
    something to absorb. A header that disagrees with its own lines means one
    of the two is stale, and there is no way to tell which from here - so it
    stops rather than picking.

    Only checked where both exist. A day total has a header and no lines, which
    is not a disagreement.
    """
    problems = []
    if not document.has_lines:
        return problems

    sums = {
        "taxable_paise": sum(l.taxable_paise for l in document.lines
                             if l.supply_class == SupplyClass.TAXABLE),
        "cgst_paise": sum(l.cgst_paise for l in document.lines),
        "sgst_paise": sum(l.sgst_paise for l in document.lines),
        "igst_paise": sum(l.igst_paise for l in document.lines),
    }
    for field_name, from_lines in sums.items():
        on_header = getattr(document, field_name)
        # A header left at zero is "not stated", not "stated as nothing" - the
        # importers fill only what their source carried.
        if on_header == 0 and from_lines != 0 and field_name != "taxable_paise":
            continue
        if on_header != from_lines:
            problems.append((field_name, from_lines, on_header))
    return problems


# ---------------------------------------------------------------- checks


def _check_identity(report: ValidationReport, identity: dict) -> None:
    """The shop's own details, without which nothing can be filed correctly."""
    if not identity.get("gstin"):
        report.add(
            code="NO_GSTIN", severity=BLOCKING, acknowledgeable=False,
            message="This shop has no GSTIN recorded. A return cannot be filed without one.",
            record_type="PHARMACY", record_id=identity.get("pharmacy_id"),
        )
    if not identity.get("state_code"):
        report.add(
            code="NO_STATE_CODE", severity=BLOCKING, acknowledgeable=False,
            message="This shop has no state code, so intra-state and inter-state "
                    "supplies cannot be told apart.",
            record_type="PHARMACY", record_id=identity.get("pharmacy_id"),
        )
    if not identity.get("filing_frequency"):
        report.add(
            code="NO_FILING_FREQUENCY", severity=BLOCKING, acknowledgeable=False,
            message="Nobody has said whether this shop files monthly or quarterly. "
                    "A QRMP shop files one GSTR-1 per quarter, so the period this "
                    "return covers is unknown until that is set.",
            record_type="PHARMACY", record_id=identity.get("pharmacy_id"),
        )
    if identity.get("aato_paise") is None and not identity.get("hsn_policy_is_declared"):
        report.add(
            code="NO_AATO", severity=WARNING,
            message="Aggregate turnover has not been declared, so HSN is being "
                    "reported at six digits to be safe. Declaring it may reduce "
                    "that to four.",
            record_type="PHARMACY", record_id=identity.get("pharmacy_id"),
        )


def _check_aato_against_our_own_sales(
    report: ValidationReport, identity: dict, own_sales_paise: Optional[int]
) -> None:
    """Whether the declared turnover is already contradicted by what we hold.

    AATO is PAN-wide and we see one GSTIN, so our own figure is a floor and
    never the answer. But a floor that is already above the declaration means
    the declaration is stale, and a stale declaration is what files four HSN
    digits when six were owed.
    """
    declared = identity.get("aato_paise")
    if declared is None or own_sales_paise is None:
        return
    if own_sales_paise > declared:
        report.add(
            code="AATO_BELOW_OWN_SALES", severity=WARNING,
            message=(
                f"Declared aggregate turnover is ₹{declared / 100:,.2f}, but this "
                f"workspace alone has recorded ₹{own_sales_paise / 100:,.2f} in the "
                "financial year. Aggregate turnover is PAN-wide, so it cannot be "
                "lower than one GSTIN's sales - the declaration looks out of date."
            ),
            record_type="PHARMACY", record_id=identity.get("pharmacy_id"),
            context={"declared_paise": declared, "own_sales_paise": own_sales_paise},
        )
    if (
        declared <= AATO_SIX_DIGIT_THRESHOLD_PAISE
        and own_sales_paise > AATO_SIX_DIGIT_THRESHOLD_PAISE
    ):
        report.add(
            code="AATO_CROSSES_HSN_THRESHOLD", severity=BLOCKING,
            message=(
                "This workspace's own sales have passed ₹5 crore while the declared "
                "aggregate turnover is still at or below it. HSN is being reported "
                "at four digits and six are owed. Update the declaration before "
                "filing."
            ),
            record_type="PHARMACY", record_id=identity.get("pharmacy_id"),
            context={"declared_paise": declared, "own_sales_paise": own_sales_paise},
        )


def _check_documents(report: ValidationReport, documents: Iterable, identity: dict) -> None:
    """Per-document and per-line checks."""
    hsn_digits = identity.get("hsn_digits", 6)
    b2c_hsn_is_mandatory = (identity.get("aato_paise") or 0) > AATO_SIX_DIGIT_THRESHOLD_PAISE

    for document in documents:
        if document.status == DocumentStatus.DRAFT:
            report.add(
                code="DRAFT_IN_PERIOD", severity=WARNING,
                message=f"Bill {document.bill_number or document.document_id} is still a "
                        "draft, so none of its figures are in this return.",
                record_type="SALE", record_id=document.document_id,
            )
            continue
        if not document.is_reportable:
            continue

        if not document.place_of_supply_state_code:
            report.add(
                code="NO_PLACE_OF_SUPPLY", severity=BLOCKING,
                message=f"Bill {document.bill_number or document.document_id} has no place "
                        "of supply, so it cannot be placed in a table and is currently "
                        "left out of the return entirely.",
                record_type="SALE", record_id=document.document_id,
            )

        for field_name, from_lines, on_header in reconcile_document(document):
            report.add(
                code="RATE_BLOCK_DOES_NOT_RECONCILE", severity=BLOCKING,
                message=(
                    f"Bill {document.bill_number or document.document_id}: its lines come "
                    f"to ₹{from_lines / 100:,.2f} of {field_name.replace('_paise', '')} but "
                    f"the bill's own total says ₹{on_header / 100:,.2f}. One of the two is "
                    "stale and there is no way to tell which from here."
                ),
                record_type="SALE", record_id=document.document_id,
                context={"field": field_name, "from_lines": from_lines, "on_header": on_header},
            )

        _check_document_class(report, document)

        for line in document.lines:
            _check_line(report, document, line, hsn_digits, b2c_hsn_is_mandatory)


def _check_document_class(report: ValidationReport, document: OutwardDocument) -> None:
    """Whether the document issued matches what was actually supplied.

    A tax invoice covers taxable supplies. The moment an exempt or nil-rated
    line appears on one, the shop needed Rule 46A's combined
    invoice-cum-bill-of-supply instead. This is a warning rather than a block:
    the document has already been issued and handed to a customer, so nothing
    about this return can fix it - but the shop's template can be fixed before
    it happens for a whole month.
    """
    if document.document_class != "TAX_INVOICE":
        return
    untaxed = [l for l in document.lines if l.supply_class in SupplyClass.UNTAXED]
    if not untaxed and not document.untaxed_paise:
        return
    report.add(
        code="EXEMPT_LINE_ON_TAX_INVOICE", severity=WARNING,
        message=(
            f"Bill {document.bill_number or document.document_id} is a tax invoice but "
            "carries exempt or nil-rated lines. A document covering both needs to be "
            "an invoice-cum-bill-of-supply under Rule 46A."
        ),
        record_type="SALE", record_id=document.document_id,
        context={"untaxed_line_count": len(untaxed)},
    )


def _check_line(
    report: ValidationReport,
    document: OutwardDocument,
    line,
    hsn_digits: int,
    b2c_hsn_is_mandatory: bool,
) -> None:
    """HSN, UQC and catalogue mapping on one line."""
    where = f"Bill {document.bill_number or document.document_id}, {line.product_name or 'a line'}"

    if not line.product_id:
        report.add(
            code="UNMAPPED_PRODUCT", severity=WARNING,
            message=f"{where} is not matched to a catalogue product, so its HSN and unit "
                    "cannot be checked against anything.",
            record_type="SALE_LINE", record_id=document.document_id, line_id=line.line_id,
        )

    if not line.hsn:
        # Mandatory for B2B whatever the turnover; for B2C only above ₹5 crore.
        severity = BLOCKING if (document.is_b2b or b2c_hsn_is_mandatory) else WARNING
        report.add(
            code="NO_HSN_B2B" if document.is_b2b else "NO_HSN_B2C",
            severity=severity,
            message=(
                f"{where} has no HSN code. "
                + ("HSN is mandatory on a B2B supply whatever the turnover."
                   if document.is_b2b else
                   "HSN is mandatory above ₹5 crore of turnover."
                   if b2c_hsn_is_mandatory else
                   "HSN is optional at this turnover, but Table 12 will be incomplete "
                   "without it.")
            ),
            record_type="SALE_LINE", record_id=document.document_id, line_id=line.line_id,
        )
    else:
        try:
            validate_hsn(line.hsn, hsn_digits)
        except HsnError as error:
            report.add(
                code="HSN_NOT_ACCEPTED", severity=BLOCKING,
                message=f"{where}: {error}",
                record_type="SALE_LINE", record_id=document.document_id,
                line_id=line.line_id, context={"hsn": line.hsn},
            )

        if not line.uqc:
            report.add(
                code="NO_UQC", severity=BLOCKING,
                message=f"{where} has no unit of measure, and Table 12 needs one per HSN.",
                record_type="SALE_LINE", record_id=document.document_id, line_id=line.line_id,
            )
        elif not is_valid_uqc(line.uqc):
            report.add(
                code="UQC_NOT_ACCEPTED", severity=BLOCKING,
                message=f"{where}: {line.uqc!r} is not a unit quantity code the portal "
                        "accepts.",
                record_type="SALE_LINE", record_id=document.document_id,
                line_id=line.line_id, context={"uqc": line.uqc},
            )

    if line.supply_class == SupplyClass.TAXABLE and line.rate_bp == 0 and line.taxable_paise:
        report.add(
            code="ZERO_RATE_MARKED_TAXABLE", severity=WARNING,
            message=f"{where} is marked taxable at 0%. A supply at nil rate belongs in "
                    "Table 8 as nil-rated, and is being left out of Table 7.",
            record_type="SALE_LINE", record_id=document.document_id, line_id=line.line_id,
        )


def _check_aggregates(report: ValidationReport, tables: dict) -> None:
    """Checks that only make sense once the tables exist."""
    for bucket in tables["b2cs"].negative_buckets:
        report.add(
            code="B2CS_NEGATIVE_BUCKET", severity=BLOCKING,
            message=(
                f"Returns have exceeded sales for {bucket.rate_bp / 100:g}% supplies to "
                f"state {bucket.place_of_supply} ({bucket.supply_type.lower()}-state): the "
                f"bucket comes to ₹{bucket.taxable_paise / 100:,.2f} of taxable value. The "
                "portal will not take a negative aggregate - the credit note belongs "
                "against the period the sale was in, as an amendment."
            ),
            record_type="B2CS_BUCKET",
            record_id=f"{bucket.place_of_supply}:{bucket.rate_bp}:{bucket.supply_type}",
            context={
                "taxable_paise": bucket.taxable_paise,
                "document_ids": bucket.document_ids,
            },
        )

    for entry in tables["b2cl"]:
        report.add(
            code="B2CL_NEEDS_REVIEW", severity=BLOCKING,
            message=(
                f"Bill {entry.bill_number or entry.document_id} is an inter-state supply to "
                f"an unregistered person of ₹{entry.invoice_value_paise / 100:,.2f}, which "
                "puts it in Table 5. An over-the-counter sale is supplied where the "
                "counter is, so this is usually a place of supply entered wrongly rather "
                "than a genuine inter-state sale. Check it before filing."
            ),
            record_type="SALE", record_id=entry.document_id,
            context={"invoice_value_paise": entry.invoice_value_paise,
                     "place_of_supply": entry.place_of_supply},
        )

    for series in tables["documents"].series:
        if series.duplicates:
            report.add(
                code="SERIES_DUPLICATE", severity=BLOCKING, acknowledgeable=False,
                message=(
                    f"Series {series.series_prefix} has more than one document numbered "
                    f"{', '.join(str(d) for d in series.duplicates[:10])}"
                    f"{'…' if len(series.duplicates) > 10 else ''}. Rule 46(b) makes a "
                    "serial unique within the financial year, and two bills sharing one "
                    "are indistinguishable in a return. Find out which is which before "
                    "filing."
                ),
                record_type="SERIES", record_id=series.series_prefix,
                context={"duplicates": series.duplicates},
            )
        if not series.gaps:
            continue
        report.add(
            code="SERIES_GAP", severity=BLOCKING,
            message=(
                f"Series {series.series_prefix} is missing "
                f"{'number' if len(series.gaps) == 1 else 'numbers'} "
                f"{', '.join(str(g) for g in series.gaps[:10])}"
                f"{'…' if len(series.gaps) > 10 else ''} between "
                f"{series.opening_number} and {series.closing_number}. Either a bill was "
                "issued on a device and never synced - in which case this return is "
                "missing its supplies - or the number was skipped."
            ),
            record_type="SERIES", record_id=series.series_prefix,
            context={"gaps": series.gaps},
        )

    for document in tables["b2b_credit_notes"]:
        report.add(
            code="CREDIT_NOTE_TO_REGISTERED_NOT_FILED", severity=BLOCKING,
            message=(
                f"Credit note {document.bill_number or document.document_id} is against a "
                f"registered person ({document.customer_gstin}). Those belong in Table 9B, "
                "which this engine does not yet build, so it is NOT in this payload. "
                "Filing without it understates the shop's credit notes."
            ),
            record_type="SALE", record_id=document.document_id,
            context={"customer_gstin": document.customer_gstin,
                     "value_paise": document.invoice_value_paise},
        )

    hsn = tables["hsn"]
    if hsn.documents_without_lines:
        report.add(
            code="HSN_SUMMARY_INCOMPLETE", severity=WARNING,
            message=(
                f"{len(hsn.documents_without_lines)} "
                f"{'document has' if len(hsn.documents_without_lines) == 1 else 'documents have'} "
                "no item lines - declared day totals, typically - so their supplies are in "
                "the return but not in the HSN summary."
            ),
            record_type="PERIOD",
            context={"document_ids": hsn.documents_without_lines},
        )

    for series_id in tables["documents"].documents_without_series:
        report.add(
            code="NO_BILL_SERIES", severity=WARNING,
            message="This bill has no serial number, so it cannot be counted in the "
                    "documents-issued table the portal cross-checks against.",
            record_type="SALE", record_id=series_id,
        )


def build_report(
    documents: Iterable[OutwardDocument],
    tables: dict,
    identity: dict,
    own_sales_paise: Optional[int] = None,
    acknowledged: Optional[set] = None,
) -> ValidationReport:
    """Everything that has to be looked at before this period can close."""
    report = ValidationReport(acknowledged=set(acknowledged or ()))
    _check_identity(report, identity)
    _check_aato_against_our_own_sales(report, identity, own_sales_paise)
    _check_documents(report, list(documents), identity)
    _check_aggregates(report, tables)
    # Blocking first, then by code, so the list reads as a worklist rather than
    # in whatever order the checks happened to run.
    report.items.sort(key=lambda i: (i.severity != BLOCKING, i.code, i.record_id or ""))
    return report
