"""Purchase analytics endpoints.

Every report accepts the same period parameters, resolved once by
`_period()`. Aggregation happens in Cypher and composition in
`services.reports` — this module only parses the request, maps domain errors
onto status codes, and returns.

`statuses` defaults to verified-only. Pass `statuses=all` to include invoices
still in review; every response reports what the filter excluded either way.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db.repositories import reports_repository
from db.repositories import scan_repository
from services.reports import expiry, gst, overview, procurement, quality
from services.reports.periods import Period, PeriodError, resolve

router = APIRouter(prefix="/reports", tags=["reports"])


def _period(
    kind: Optional[str],
    fy: Optional[int],
    quarter: Optional[int],
    month: Optional[str],
    start: Optional[str],
    end: Optional[str],
) -> Period:
    """Resolves period parameters, turning a bad request into a 400.

    `PeriodError` carries a message written for the user, so it is surfaced
    verbatim rather than replaced with a generic validation string.
    """
    try:
        return resolve(kind=kind, fy=fy, quarter=quarter, month=month, start=start, end=end)
    except PeriodError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _statuses(statuses: Optional[str]) -> Optional[list[str]]:
    """`all` widens the report to every status; anything else is a filter list.

    None (the default) is not the same as `all`: it means verified-only, which
    is what the repository applies when no explicit list is given.
    """
    if statuses is None:
        return reports_repository.DEFAULT_STATUSES
    if statuses.strip().lower() == "all":
        return None
    return [s.strip() for s in statuses.split(",") if s.strip()]


# Shared across the period-scoped endpoints so the query contract stays
# identical everywhere and the UI can pass one period object to all of them.
_KIND = Query(None, description="fy, quarter, month or custom. Defaults to the current FY.")
_FY = Query(None, description="Financial year start year, e.g. 2026 for FY 2026-27.")
_QUARTER = Query(None, ge=1, le=4, description="Quarter within the FY. Q1 is April to June.")
_MONTH = Query(None, description="Month as YYYY-MM, when kind=month.")
_START = Query(None, description="Start date, when kind=custom.")
_END = Query(None, description="End date, when kind=custom.")
_STATUSES = Query(None, description="Comma-separated statuses, or 'all'. Defaults to verified only.")


@router.get("/summary")
def summary(
    kind: Optional[str] = _KIND,
    fy: Optional[int] = _FY,
    quarter: Optional[int] = _QUARTER,
    month: Optional[str] = _MONTH,
    start: Optional[str] = _START,
    end: Optional[str] = _END,
    statuses: Optional[str] = _STATUSES,
):
    """Headline totals for the period, with what the status filter excluded."""
    return overview.build(_period(kind, fy, quarter, month, start, end), _statuses(statuses))


@router.get("/spend-trend")
def spend_trend(
    kind: Optional[str] = _KIND,
    fy: Optional[int] = _FY,
    quarter: Optional[int] = _QUARTER,
    month: Optional[str] = _MONTH,
    start: Optional[str] = _START,
    end: Optional[str] = _END,
    statuses: Optional[str] = _STATUSES,
):
    """Spend per month across the period, including months with no purchases."""
    return overview.spend_trend(_period(kind, fy, quarter, month, start, end), _statuses(statuses))


@router.get("/gst-register")
def gst_register(
    kind: Optional[str] = _KIND,
    fy: Optional[int] = _FY,
    quarter: Optional[int] = _QUARTER,
    month: Optional[str] = _MONTH,
    start: Optional[str] = _START,
    end: Optional[str] = _END,
    statuses: Optional[str] = _STATUSES,
):
    """Invoice-level purchase register for the ITC claim and GSTR-2B matching."""
    return gst.register(_period(kind, fy, quarter, month, start, end), _statuses(statuses))


@router.get("/hsn-summary")
def hsn_summary(
    kind: Optional[str] = _KIND,
    fy: Optional[int] = _FY,
    quarter: Optional[int] = _QUARTER,
    month: Optional[str] = _MONTH,
    start: Optional[str] = _START,
    end: Optional[str] = _END,
    statuses: Optional[str] = _STATUSES,
):
    """Taxable value by HSN code and GST slab, with slab conflicts flagged."""
    return gst.hsn_summary(_period(kind, fy, quarter, month, start, end), _statuses(statuses))


@router.get("/vendors")
def vendors(
    kind: Optional[str] = _KIND,
    fy: Optional[int] = _FY,
    quarter: Optional[int] = _QUARTER,
    month: Optional[str] = _MONTH,
    start: Optional[str] = _START,
    end: Optional[str] = _END,
    statuses: Optional[str] = _STATUSES,
):
    """Per-vendor spend, share, scheme volume and effective discount."""
    return procurement.vendor_scorecard(
        _period(kind, fy, quarter, month, start, end), _statuses(statuses)
    )


@router.get("/price-variance")
def price_variance(
    kind: Optional[str] = _KIND,
    fy: Optional[int] = _FY,
    quarter: Optional[int] = _QUARTER,
    month: Optional[str] = _MONTH,
    start: Optional[str] = _START,
    end: Optional[str] = _END,
    statuses: Optional[str] = _STATUSES,
):
    """Rate movement per product, and the same item bought at two prices."""
    return procurement.price_variance(
        _period(kind, fy, quarter, month, start, end), _statuses(statuses)
    )


@router.get("/expiry")
def expiry_exposure(
    horizon_days: int = Query(180, ge=1, le=730),
    as_of: Optional[str] = Query(None, description="Defaults to today. ISO date."),
    statuses: Optional[str] = _STATUSES,
):
    """Batches bucketed by time to expiry, valued at purchase cost.

    Deliberately not period-scoped: stock bought in March can expire in
    September, and a period filter would hide the batches worth acting on.
    """
    as_of_date = date.today()
    if as_of:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Could not read {as_of!r} as a date.")

    return expiry.build(_statuses(statuses), as_of=as_of_date, horizon_days=horizon_days)


@router.get("/data-quality")
def data_quality(
    kind: Optional[str] = _KIND,
    fy: Optional[int] = _FY,
    quarter: Optional[int] = _QUARTER,
    month: Optional[str] = _MONTH,
    start: Optional[str] = _START,
    end: Optional[str] = _END,
):
    """Ledger problems and what each one costs.

    Runs across every status, not just verified — an invoice with a missing
    GSTIN is exactly the one to catch before somebody verifies it.
    """
    return quality.build(_period(kind, fy, quarter, month, start, end))


@router.get("/scans")
def scans(granularity: str = "month", limit: int = 24):
    """How many scans have been run, bucketed by day, month or year.

    Deliberately not filtered by the period selector the other reports share.
    Those answer "what did this financial year cost"; this answers "how much
    work has gone through the system", which is a lifetime figure and must not
    move when someone changes the period dropdown.
    """
    if granularity not in scan_repository.GRANULARITIES:
        raise HTTPException(
            status_code=400,
            detail=f"granularity must be one of {', '.join(scan_repository.GRANULARITIES)}.",
        )
    return scan_repository.scan_activity(granularity=granularity, limit=max(1, min(limit, 120)))
