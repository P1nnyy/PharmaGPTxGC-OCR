"""The management reports and the dashboard.

Lives under `/management/` for the same reason the other report subtrees do -
the SPA owns the bare paths as page routes and the edge forwards the subtree.

Costing is loaded once per request and shared. Margin, expiry, movers and stock
value all need the same batch positions, and building them four times would be
four chances for two reports to disagree about how much stock is on a shelf.
"""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status as http_status

from api.deps import current_user
from core.tax_periods import PeriodError, is_valid_period, period_of
from db.repositories import (
    gstr1_repository,
    management_repository,
    pharmacy_repository,
    vendor_repository,
)
from services.gstr1.engine import compute
from services.gstr1.periods import resolve_filing_period
from services.management import costing, dashboard, expiry, margin, sales, stock, vendors

router = APIRouter(prefix="/management", tags=["management"])


def _today() -> date:
    return datetime.now().date()


def _window(start: Optional[str], end: Optional[str]) -> tuple:
    """Defaults to the last 30 days, which is what "recently" means here."""
    finish = end or _today().isoformat()
    begin = start or (date.fromisoformat(finish) - timedelta(days=29)).isoformat()
    if begin > finish:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="The start of the window is after its end.",
        )
    return begin, finish


def _product_names(rows: list) -> dict:
    return {
        row["product_id"]: row.get("product_name")
        for row in rows
        if row.get("product_id") and row.get("product_name")
    }


def _costing():
    """Batch positions, built once and shared by every report that needs them."""
    costs = management_repository.batch_costs()
    sold = management_repository.batch_sales()
    # Names come off the movement read, which already joins Product.
    names = _product_names(management_repository.movements(reason="PURCHASE"))
    return costing.build(costs, sold, names)


def _vendor_lookup() -> tuple:
    rows = vendor_repository.list_vendors()
    windows = {
        r["vendor_id"]: r["return_window_days"]
        for r in rows if r.get("return_window_days") is not None
    }
    names = {r["vendor_id"]: r.get("name") for r in rows}
    return windows, names


@router.get("/dashboard")
def dashboard_cards(_user: dict = Depends(current_user)) -> dict:
    """The four cards. Every one of them changes what somebody does today."""
    today = _today()
    priced = _costing()
    windows, names = _vendor_lookup()

    todays = management_repository.sales_by_day(today.isoformat(), today.isoformat())
    comparison_day = dashboard.comparison_day(today)
    previous = management_repository.sales_by_day(comparison_day, comparison_day)

    identity = pharmacy_repository.tax_identity()
    period = period_of(today.isoformat())
    validation = {"blocking": [], "warnings": []}
    period_label = ""
    try:
        filing_period = resolve_filing_period(
            period, identity.get("effective_filing_frequency")
        )
        period_label = filing_period.label
        result = compute(
            gstr1_repository.documents_for_period(filing_period), identity, filing_period
        )
        validation = {
            "blocking": [{"id": i.id, "code": i.code} for i in result.report.blocking],
            "warnings": [{"id": i.id, "code": i.code} for i in result.report.warnings],
        }
    except PeriodError:
        # A dashboard that fails to render because a return could not be
        # computed is worse than one card reading zero.
        pass

    return dashboard.build(
        today=today,
        todays_sales_paise=sum(int(d.get("value_paise") or 0) for d in todays),
        todays_bill_count=sum(int(d.get("bill_count") or 0) for d in todays),
        comparison_sales_paise=sum(int(d.get("value_paise") or 0) for d in previous),
        expiry_report=expiry.build(priced, today, windows, names),
        stock=stock.stock_value(priced),
        validation=validation,
        period_label=period_label,
    )


@router.get("/expiry-risk")
def expiry_risk(
    horizon_days: int = Query(180, ge=1, le=730),
    _user: dict = Depends(current_user),
) -> dict:
    windows, names = _vendor_lookup()
    return expiry.build(_costing(), _today(), windows, names, horizon_days=horizon_days)


@router.get("/margin")
def gross_margin(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    _user: dict = Depends(current_user),
) -> dict:
    begin, finish = _window(start, end)
    _windows, names = _vendor_lookup()
    return {
        "window": {"start": begin, "end": finish},
        **margin.build(
            management_repository.sold_lines(begin, finish),
            _costing(),
            day_total_count=management_repository.day_total_count(begin, finish),
            vendor_names=names,
        ),
    }


@router.get("/stock-ledger")
def stock_ledger(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    batch_number: Optional[str] = Query(None),
    reason: Optional[str] = Query(None, pattern="^(PURCHASE|SALE)$"),
    _user: dict = Depends(current_user),
) -> dict:
    begin, finish = _window(start, end)
    return {
        "window": {"start": begin, "end": finish},
        "filters": {
            "product_id": product_id, "batch_number": batch_number, "reason": reason,
        },
        **stock.ledger(
            management_repository.movements(
                begin, finish, product_id=product_id,
                batch_number=batch_number, reason=reason,
            )
        ),
    }


@router.get("/movers")
def movers(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=200),
    _user: dict = Depends(current_user),
) -> dict:
    begin, finish = _window(start, end)
    days = (date.fromisoformat(finish) - date.fromisoformat(begin)).days + 1
    return {
        "window": {"start": begin, "end": finish},
        **stock.movers(
            management_repository.sold_lines(begin, finish), _costing(), days, limit=limit
        ),
    }


@router.get("/daily-sales")
def daily_sales(
    month: Optional[str] = Query(None, description="Any date in the month, ISO."),
    _user: dict = Depends(current_user),
) -> dict:
    anchor = date.fromisoformat(month) if month else _today()
    begin, finish = sales.month_bounds(anchor)
    previous_begin, previous_end = sales.previous_month_bounds(anchor)
    return {
        "window": {"start": begin, "end": finish},
        "previous_window": {"start": previous_begin, "end": previous_end},
        **sales.daily_summary(
            by_hour=management_repository.sales_by_hour(begin, finish),
            by_day=management_repository.sales_by_day(begin, finish),
            payments=management_repository.payment_split(begin, finish),
            previous_by_day=management_repository.sales_by_day(previous_begin, previous_end),
            previous_payments=management_repository.payment_split(previous_begin, previous_end),
        ),
    }


@router.get("/trend")
def purchase_vs_sales(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    _user: dict = Depends(current_user),
) -> dict:
    begin, finish = _window(start, end)
    return {
        "window": {"start": begin, "end": finish},
        **sales.trend(
            management_repository.purchases_by_day(begin, finish),
            management_repository.sales_by_day(begin, finish),
        ),
    }


@router.get("/vendor-scorecard")
def vendor_scorecard(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    _user: dict = Depends(current_user),
) -> dict:
    begin, finish = _window(start, end)
    months = sorted({period_of(d) for d in (begin, finish) if is_valid_period(period_of(d))})
    return {
        "window": {"start": begin, "end": finish},
        **vendors.build(
            management_repository.vendor_purchase_totals(begin, finish), months
        ),
    }


# ---------------------------------------------------------------- vendors


@router.get("/vendors")
def list_vendors(_user: dict = Depends(current_user)) -> dict:
    """Distributors, so their return windows can be filled in."""
    rows = vendor_repository.list_vendors()
    return {
        "rows": rows,
        "row_count": len(rows),
        "missing_return_window_count": sum(
            1 for r in rows if r.get("return_window_days") is None
        ),
        "note": (
            "A return window is how many days before expiry this distributor stops "
            "accepting stock back. It is on no invoice and cannot be derived, so the "
            "expiry report reports it as unknown until it is filled in here."
        ),
    }


@router.put("/vendors/{vendor_id}/return-window")
def set_return_window(
    vendor_id: str,
    body: dict = Body(...),
    _user: dict = Depends(current_user),
) -> dict:
    """Records, or clears, how long before expiry this distributor takes returns."""
    try:
        return vendor_repository.set_return_window(
            vendor_id,
            days=body.get("return_window_days"),
            note=body.get("return_window_note"),
        )
    except vendor_repository.VendorError as error:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        )
