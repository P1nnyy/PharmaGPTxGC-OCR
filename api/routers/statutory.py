"""The statutory report pack, its exports, and the drill-through behind it.

Three kinds of endpoint:

  GET  /statutory/{period}                     the whole pack, computed fresh
  GET  /statutory/{period}/export/{report}     the same pack as CSV or Excel
  POST /statutory/drill                        the documents behind a figure

The drill is a POST because it carries a filter object rather than a handful of
scalars, and a filter with a list of two hundred document ids does not belong
in a query string. It is a read and changes nothing.

Reversals get write endpoints here too, because the ledger is not much use
without a way to add to it and there is nowhere else it belongs. They append
only - there is no update or delete, by design.
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status as http_status

from api.deps import current_user
from core.itc_rules import ItcRuleError, ReversalTrigger, describe
from core.tax_periods import PeriodError, is_valid_period
from db.repositories import (
    gstr1_repository,
    itc_repository,
    pharmacy_repository,
    statutory_repository,
)
from services.gstr1.periods import resolve_filing_period
from services.statutory import exports, pack as pack_service
from services.statutory.model import DrillKind

router = APIRouter(prefix="/statutory", tags=["statutory"])

_CSV = "text/csv; charset=utf-8"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _period_or_400(period: str) -> str:
    if not is_valid_period(period):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"{period!r} is not a tax period. Use MMYYYY, for example 092026.",
        )
    return period


def _build(
    period: str,
    vendor: Optional[str] = None,
    sales_filters: Optional[dict] = None,
):
    """Loads the period once and builds every report from it."""
    identity = pharmacy_repository.tax_identity()
    filing_period = resolve_filing_period(period, identity.get("effective_filing_frequency"))
    start, end = filing_period.start_date, filing_period.end_date
    months = list(filing_period.months)

    return pack_service.build(
        identity=identity,
        filing_period=filing_period,
        documents=gstr1_repository.documents_for_period(filing_period),
        payments=statutory_repository.payments_for_window(start, end),
        purchase_invoices=statutory_repository.purchase_invoices(start, end, vendor=vendor),
        purchase_rate_blocks=statutory_repository.purchase_rate_blocks(start, end, vendor=vendor),
        purchase_hsn_lines=statutory_repository.purchase_hsn_lines(start, end),
        reversals=itc_repository.list_reversals(months),
        reversal_totals=itc_repository.totals_by_table(months),
        own_sales_paise=gstr1_repository.own_sales_for_financial_year(period),
        sales_filters=sales_filters or {},
    )


@router.post("/drill")
def drill(
    body: dict = Body(...),
    _user: dict = Depends(current_user),
) -> dict:
    """The documents behind a figure.

    Takes the `drill` object a figure carried, unchanged. The client does not
    have to understand it - it hands back what it was given, which is what
    makes every number clickable without the UI knowing how any report was
    built.
    """
    kind = body.get("kind")
    if kind not in DrillKind.ALL:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"{kind!r} is not something that can be drilled into.",
        )
    filters = body.get("filters") or {}

    ids = filters.get("ids")
    if ids:
        rows = statutory_repository.documents_by_id(kind, list(ids))
        return {"kind": kind, "rows": rows, "row_count": len(rows), "resolved_by": "ids"}

    # No explicit ids: the figure described a predicate over the period. Resolve
    # it the same way the report did, so what opens matches what was clicked.
    periods = filters.get("periods") or []
    if not periods:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="A drill needs either document ids or a period to resolve against.",
        )
    identity = pharmacy_repository.tax_identity()
    filing_period = resolve_filing_period(periods[0], identity.get("effective_filing_frequency"))
    start, end = filing_period.start_date, filing_period.end_date

    if kind == DrillKind.ITC_REVERSALS:
        rows = [
            r for r in itc_repository.list_reversals(list(filing_period.months))
            if not filters.get("gstr3b_table") or r.get("gstr3b_table") == filters["gstr3b_table"]
        ]
    elif kind in {DrillKind.PURCHASES, DrillKind.PURCHASE_LINES}:
        rows = statutory_repository.purchase_invoices(start, end)
        if filters.get("itc_eligible"):
            rows = [r for r in rows if r.get("seller_gstin")]
    else:
        documents = gstr1_repository.documents_for_period(filing_period)
        if filters.get("status"):
            documents = [d for d in documents if d.status == filters["status"]]
        if filters.get("untaxed"):
            documents = [d for d in documents if d.untaxed_paise]
        rows = statutory_repository.documents_by_id(
            DrillKind.SALES, [d.document_id for d in documents]
        )

    return {"kind": kind, "rows": rows, "row_count": len(rows), "resolved_by": "filters"}


# ------------------------------------------------------------- reversals


@router.get("/reversals/triggers")
def reversal_triggers(_user: dict = Depends(current_user)) -> dict:
    """What a reversal can be recorded against, with the rule behind each.

    Served rather than hard-coded in the UI so the form and the ledger cannot
    disagree about which provision a trigger cites.
    """
    return {"triggers": [describe(t) for t in sorted(ReversalTrigger.ALL)]}


@router.post("/reversals", status_code=http_status.HTTP_201_CREATED)
def record_reversal(body: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    """Appends a reversal to the ledger. Never updates one."""
    try:
        return itc_repository.record_reversal(
            trigger=body.get("trigger"),
            tax_period=body.get("tax_period"),
            cgst_paise=int(body.get("cgst_paise") or 0),
            sgst_paise=int(body.get("sgst_paise") or 0),
            igst_paise=int(body.get("igst_paise") or 0),
            cess_paise=int(body.get("cess_paise") or 0),
            source_type=body.get("source_type"),
            source_id=body.get("source_id"),
            note=body.get("note"),
            reclaims_id=body.get("reclaims_id"),
            recorded_by=user.get("id") or user.get("email"),
        )
    except (itc_repository.ItcLedgerError, ItcRuleError) as error:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Reversal amounts must be whole numbers of paise.",
        )


@router.get("/reversals/{period}")
def list_reversals(
    period: str,
    include_superseded: bool = Query(False),
    _user: dict = Depends(current_user),
) -> dict:
    """The ledger for a filing period, superseded rows on request."""
    _period_or_400(period)
    identity = pharmacy_repository.tax_identity()
    filing_period = resolve_filing_period(period, identity.get("effective_filing_frequency"))
    rows = itc_repository.list_reversals(
        list(filing_period.months), include_superseded=include_superseded
    )
    return {"period": filing_period.label, "rows": rows, "row_count": len(rows)}

# ---------------------------------------------------------- the pack
# Registered last on purpose: `/{period}` matches any single segment, so a
# static route added after it - `/statutory/reversals`, say - would be
# swallowed and answered with "that is not a tax period".

@router.get("/{period}")
def report_pack(
    period: str,
    vendor: Optional[str] = Query(None, description="Filter the purchase register by supplier name or GSTIN."),
    rate: Optional[float] = Query(None, description="Filter the sales register to one GST rate, as a percentage."),
    capture_mode: Optional[str] = Query(None),
    payment_method: Optional[str] = Query(None),
    _user: dict = Depends(current_user),
) -> dict:
    """Every report for the period, with the cross-checks already run.

    The cross-checks are in the response rather than behind their own call so
    the banner cannot be skipped: a client that renders the pack has already
    been told whether it reconciles.
    """
    _period_or_400(period)
    try:
        built = _build(
            period,
            vendor=vendor,
            sales_filters={
                # Rates cross the wire as percentages and are basis points
                # inside. Converting here keeps the API in the units a person
                # types and the engine in the units it computes with.
                "rate_bp": int(round(rate * 100)) if rate is not None else None,
                "capture_mode": capture_mode,
                "payment_method": payment_method,
            },
        )
    except PeriodError as error:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(error))
    return built.to_dict()


@router.get("/{period}/export/{report_id}")
def export(
    period: str,
    report_id: str,
    fmt: str = Query("csv", pattern="^(csv|xlsx)$"),
    vendor: Optional[str] = Query(None),
    _user: dict = Depends(current_user),
) -> Response:
    """One report as CSV or Excel, rendered from the same pack the screen reads."""
    _period_or_400(period)
    if not exports.is_exportable(report_id):
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"There is no report called {report_id!r} to export.",
        )

    built = _build(period, vendor=vendor).to_dict()

    if fmt == "xlsx":
        body = exports.to_xlsx(built, report_id)
        media_type = _XLSX
    else:
        body = exports.to_csv(built, report_id).encode("utf-8-sig")
        # utf-8-sig: Excel on Windows reads a plain UTF-8 CSV as latin-1 and
        # turns every rupee sign into mojibake. The BOM is what stops that.
        media_type = _CSV

    name = exports.filename(built, report_id, fmt)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
