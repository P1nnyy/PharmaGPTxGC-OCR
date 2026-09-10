"""The outward return: previewing a period, and closing it.

Lives under `/tax-periods/` for the same reason `/inventory/` does - the SPA
owns the bare path as a page route and the edge forwards the subtree.

Two shapes of endpoint, and the difference between them is the point:

  GET  computes and changes nothing. Safe to call as often as the review
       screen likes, on an open period or a closed one.
  POST closes, once. Everything it needs was already computed by the GET, and
       it recomputes rather than trusting anything the client sends back -
       a period must not be closable on figures a browser assembled.

Money crosses this boundary as rupees, per the house rule that paise are for
storage and computation. Everything below `services/gstr1/` is integer paise;
`_rupees` is where that stops.
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status as http_status

from api.deps import current_user
from core.tax_periods import PeriodError, is_valid_period
from db.repositories import gstr1_repository, pharmacy_repository, sales_repository
from services.gstr1.engine import compute
from services.gstr1.periods import resolve_filing_period

router = APIRouter(prefix="/tax-periods", tags=["tax-periods"])


def _rupees(paise: Optional[int]) -> Optional[float]:
    return None if paise is None else round((paise or 0) / 100, 2)


def _period_or_400(period: str) -> str:
    if not is_valid_period(period):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"{period!r} is not a tax period. Use MMYYYY, for example 092026.",
        )
    return period


def _load(period: str, acknowledged: Optional[set] = None):
    """Everything the screen and the close both need.

    Shared so that what the review screen shows and what the close acts on are
    computed by the same code from the same records. Two paths that agree
    today and drift tomorrow is how a period gets closed on figures nobody
    reviewed.
    """
    identity = pharmacy_repository.tax_identity()
    filing_period = resolve_filing_period(period, identity.get("effective_filing_frequency"))
    documents = gstr1_repository.documents_for_period(filing_period)
    own_sales = gstr1_repository.own_sales_for_financial_year(period)
    result = compute(
        documents,
        identity,
        filing_period,
        own_sales_paise=own_sales,
        acknowledged=acknowledged,
    )
    return identity, filing_period, result


def _item(item) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "severity": item.severity,
        "message": item.message,
        "record_type": item.record_type,
        "record_id": item.record_id,
        "line_id": item.line_id,
        "acknowledgeable": item.acknowledgeable,
        "context": item.context,
    }


def _serialise(identity: dict, filing_period, result) -> dict:
    """The return as the review screen reads it."""
    months = list(filing_period.months)
    period_states = [sales_repository.get_period(month) for month in months]
    closed = any(p.get("status") == sales_repository.PERIOD_CLOSED for p in period_states)

    tables = result.tables
    return {
        "period": {
            "label": filing_period.label,
            "frequency": filing_period.frequency,
            "months": months,
            "start_date": filing_period.start_date,
            "end_date": filing_period.end_date,
            "quarter": filing_period.quarter,
            "financial_year": filing_period.financial_year,
            "status": sales_repository.PERIOD_CLOSED if closed else sales_repository.PERIOD_OPEN,
            "closed_at": next((p.get("closed_at") for p in period_states if p.get("closed_at")), None),
            "closed_by": next((p.get("closed_by") for p in period_states if p.get("closed_by")), None),
        },
        "shop": {
            "gstin": identity.get("gstin"),
            "legal_name": identity.get("legal_name"),
            "trade_name": identity.get("trade_name"),
            "state_code": identity.get("state_code"),
            "filing_frequency": identity.get("filing_frequency"),
            "hsn_digits": identity.get("hsn_digits"),
            "aato": _rupees(identity.get("aato_paise")),
        },
        "totals": {
            "taxable": _rupees(result.totals["taxable_paise"]),
            "cgst": _rupees(result.totals["cgst_paise"]),
            "sgst": _rupees(result.totals["sgst_paise"]),
            "igst": _rupees(result.totals["igst_paise"]),
            "cess": _rupees(result.totals["cess_paise"]),
            "tax": _rupees(result.totals["tax_paise"]),
            "untaxed": _rupees(result.totals["untaxed_paise"]),
            "supplies": _rupees(result.totals["supplies_paise"]),
            "document_count": result.totals["document_count"],
        },
        "is_nil_return": result.is_nil_return,
        "can_close": result.can_close,
        "validation": {
            "blocking": [_item(i) for i in result.report.blocking],
            "warnings": [_item(i) for i in result.report.warnings],
            "outstanding": [_item(i) for i in result.report.unacknowledged_blocking],
        },
        "tables": {
            "b2cs": [
                {
                    "place_of_supply": b.place_of_supply,
                    "rate": b.rate_bp / 100,
                    "supply_type": b.supply_type,
                    "taxable": _rupees(b.taxable_paise),
                    "cgst": _rupees(b.cgst_paise),
                    "sgst": _rupees(b.sgst_paise),
                    "igst": _rupees(b.igst_paise),
                    "document_ids": b.document_ids,
                }
                for b in tables["b2cs"].buckets
            ],
            "b2cs_negative": [
                {
                    "place_of_supply": b.place_of_supply,
                    "rate": b.rate_bp / 100,
                    "supply_type": b.supply_type,
                    "taxable": _rupees(b.taxable_paise),
                    "document_ids": b.document_ids,
                }
                for b in tables["b2cs"].negative_buckets
            ],
            "b2cl": [
                {
                    "document_id": e.document_id,
                    "bill_number": e.bill_number,
                    "sale_date": e.sale_date,
                    "place_of_supply": e.place_of_supply,
                    "invoice_value": _rupees(e.invoice_value_paise),
                }
                for e in tables["b2cl"]
            ],
            "b2b": [
                {
                    "document_id": e.document_id,
                    "customer_gstin": e.customer_gstin,
                    "customer_name": e.customer_name,
                    "bill_number": e.bill_number,
                    "sale_date": e.sale_date,
                    "place_of_supply": e.place_of_supply,
                    "supply_type": e.supply_type,
                    "invoice_value": _rupees(e.invoice_value_paise),
                }
                for e in tables["b2b"]
            ],
            "nil_exempt": [
                {
                    "code": r.code,
                    "description": r.description,
                    "nil_rated": _rupees(r.nil_rated_paise),
                    "exempted": _rupees(r.exempted_paise),
                    "non_gst": _rupees(r.non_gst_paise),
                    "total": _rupees(r.total_paise),
                }
                for r in tables["nil_exempt"]
            ],
            "hsn": {
                section: [
                    {
                        "hsn": r.hsn,
                        "uqc": r.uqc,
                        "rate": r.rate_bp / 100,
                        "quantity": float(r.quantity),
                        "taxable": _rupees(r.taxable_paise),
                        "cgst": _rupees(r.cgst_paise),
                        "sgst": _rupees(r.sgst_paise),
                        "igst": _rupees(r.igst_paise),
                        "total_value": _rupees(r.total_value_paise),
                        "document_ids": r.document_ids,
                    }
                    for r in rows
                ]
                for section, rows in (("b2b", tables["hsn"].b2b), ("b2c", tables["hsn"].b2c))
            },
            "documents_issued": [
                {
                    "series_prefix": s.series_prefix,
                    "opening_number": s.opening_number,
                    "closing_number": s.closing_number,
                    "total_issued": s.total_issued,
                    "cancelled": s.cancelled,
                    "net_issued": s.net_issued,
                    "gaps": s.gaps,
                    "duplicates": s.duplicates,
                }
                for s in tables["documents"].series
            ],
        },
    }


@router.get("/{period}")
def preview(period: str, _user: dict = Depends(current_user)) -> dict:
    """The return as it currently stands. Computes; changes nothing."""
    _period_or_400(period)
    try:
        identity, filing_period, result = _load(period)
    except PeriodError as error:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(error))
    return _serialise(identity, filing_period, result)


@router.get("/{period}/payload")
def payload(period: str, _user: dict = Depends(current_user)) -> dict:
    """The GSTR-1 JSON in the offline utility's schema.

    For a closed period this is the payload that was stored at close rather
    than a fresh computation. A filed return has to be reproducible: when the
    portal disagrees months later the question is what was actually sent, and
    recomputing from records that have moved on answers a different question.
    """
    _period_or_400(period)
    stored = sales_repository.get_period(period)
    if stored.get("status") == sales_repository.PERIOD_CLOSED and stored.get("payload_json"):
        import json

        return json.loads(stored["payload_json"])

    _identity, _filing_period, result = _load(period)
    return result.payload


@router.post("/{period}/close")
def close(
    period: str,
    body: dict = Body(default_factory=dict),
    user: dict = Depends(current_user),
) -> dict:
    """Runs every validation, produces the return, and locks the period.

    Recomputes from the records rather than trusting anything in the request.
    The only thing the body carries is the set of blocking items a person has
    consciously accepted, and even those are matched against freshly computed
    items - an acknowledgement of something that is no longer a problem simply
    does not apply.

    Closing a QRMP shop's period closes all three months of the quarter. The
    return covers the quarter, so leaving the other two open would leave
    records editable after their figures had gone to the portal.
    """
    _period_or_400(period)
    acknowledged = set(body.get("acknowledged") or [])

    try:
        identity, filing_period, result = _load(period, acknowledged=acknowledged)
    except PeriodError as error:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(error))

    already = [
        month for month in filing_period.months
        if sales_repository.get_period(month).get("status") == sales_repository.PERIOD_CLOSED
    ]
    if already:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                f"{filing_period.label} has already been closed. Reopening a filed period "
                "is a deliberate act - a correction is normally a credit note or an "
                "amendment."
            ),
        )

    if not result.can_close:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": (
                    f"{filing_period.label} cannot be closed yet: "
                    f"{len(result.report.unacknowledged_blocking)} "
                    f"{'item needs' if len(result.report.unacknowledged_blocking) == 1 else 'items need'} "
                    "attention."
                ),
                "outstanding": [_item(i) for i in result.report.unacknowledged_blocking],
            },
        )

    sales_repository.close_period(
        months=list(filing_period.months),
        payload=result.payload,
        summary=result.totals,
        closed_by=user.get("id") or user.get("email"),
        acknowledged=sorted(acknowledged),
    )

    body_out = _serialise(identity, filing_period, result)
    body_out["closed"] = True
    return body_out
