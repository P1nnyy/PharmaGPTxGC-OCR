"""Turning a period's sales into a checked return.

The order matters and is the whole content of this module. Tables are built
first, because several of the checks are about aggregates and cannot be made
until the aggregates exist - a bucket only goes negative once a month of credit
notes has been summed into it. The report is built second. The payload is built
last and only described as filable when nothing blocking is outstanding.

Nothing here decides whether to file. `compute` is safe to call at any time and
is what the review screen reads; `close_period` in the repository is the only
thing that changes state.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional

from services.gstr1.model import OutwardDocument
from services.gstr1.payload import build_payload
from services.gstr1.tables import (
    aggregate_b2b,
    aggregate_b2cl,
    aggregate_b2cs,
    aggregate_documents_issued,
    aggregate_hsn,
    aggregate_nil_exempt,
    credit_notes_to_registered,
    reportable,
)
from services.gstr1.validation import ValidationReport, build_report


@dataclass
class Gstr1Return:
    """Everything computed for one filing period."""

    filing_period: object
    identity: dict
    tables: dict
    report: ValidationReport
    payload: dict
    totals: dict = field(default_factory=dict)

    @property
    def can_close(self) -> bool:
        return self.report.can_close

    @property
    def is_nil_return(self) -> bool:
        """Whether this period has nothing to report.

        Worth naming rather than inferring from empty tables, because a nil
        return is not "no return". A period with no sales still has to be
        filed, and a shop that simply does not file because there was nothing
        to say accrues a late fee for every day it does not.
        """
        return self.totals.get("supplies_paise", 0) == 0 and not self.tables["b2b"]


def build_tables(documents: Iterable[OutwardDocument]) -> dict:
    """Every table, in dependency order.

    B2CL is computed before B2CS because a bill reported invoice-wise in
    Table 5 must not also be summed into the Table 7 aggregate - that would
    report the same supply twice.
    """
    documents = list(documents)
    b2cl = aggregate_b2cl(documents)
    b2cl_ids = {entry.document_id for entry in b2cl}
    return {
        "b2b": aggregate_b2b(documents),
        "b2b_credit_notes": credit_notes_to_registered(documents),
        "b2cl": b2cl,
        "b2cs": aggregate_b2cs(documents, b2cl_document_ids=b2cl_ids),
        "nil_exempt": aggregate_nil_exempt(documents),
        "hsn": aggregate_hsn(documents),
        "documents": aggregate_documents_issued(documents),
    }


def summarise(tables: dict, documents: Iterable[OutwardDocument]) -> dict:
    """Headline figures for the review screen.

    Summed from the tables rather than from the documents, so that what the
    screen shows is what the payload contains. A summary computed
    independently of the payload is a summary that can agree with the sales and
    still disagree with the return.
    """
    b2cs = tables["b2cs"].buckets
    taxable = sum(b.taxable_paise for b in b2cs)
    cgst = sum(b.cgst_paise for b in b2cs)
    sgst = sum(b.sgst_paise for b in b2cs)
    igst = sum(b.igst_paise for b in b2cs)
    cess = sum(b.cess_paise for b in b2cs)

    for entry in list(tables["b2b"]) + list(tables["b2cl"]):
        for block in entry.rate_blocks:
            taxable += block["taxable_paise"]
            cgst += block["cgst_paise"]
            sgst += block["sgst_paise"]
            igst += block["igst_paise"]
            cess += block["cess_paise"]

    untaxed = sum(row.total_paise for row in tables["nil_exempt"])
    counted = reportable(documents)
    return {
        "taxable_paise": taxable,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "igst_paise": igst,
        "cess_paise": cess,
        "tax_paise": cgst + sgst + igst + cess,
        "untaxed_paise": untaxed,
        "supplies_paise": taxable + untaxed,
        "document_count": len(counted),
        "b2b_count": len(tables["b2b"]),
        "b2cl_count": len(tables["b2cl"]),
        "b2cs_bucket_count": len(b2cs),
    }


def compute(
    documents: Iterable[OutwardDocument],
    identity: dict,
    filing_period,
    own_sales_paise: Optional[int] = None,
    acknowledged: Optional[set] = None,
) -> Gstr1Return:
    """Aggregate, validate and shape a period's return. Changes nothing."""
    documents = list(documents)
    tables = build_tables(documents)
    report = build_report(
        documents,
        tables,
        identity,
        own_sales_paise=own_sales_paise,
        acknowledged=acknowledged,
    )
    totals = summarise(tables, documents)
    payload = build_payload(
        tables,
        identity,
        filing_period,
        gross_turnover_paise=totals["supplies_paise"],
    )
    return Gstr1Return(
        filing_period=filing_period,
        identity=identity,
        tables=tables,
        report=report,
        payload=payload,
        totals=totals,
    )
