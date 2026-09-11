"""The compliance calendar: what to do, when, and what was filed.

**This prepares and tracks. It does not file.** There is no GSP integration
here and no submission path, deliberately. Filing is a later milestone, it will
be gated behind an OTP and an explicit action, and nothing in this codebase
should ever be able to send a return without a person deciding to. Every write
endpoint here records something that has *already happened* on the portal.

`POST /compliance/filings` is the one that carries that weight: it is called
after filing, with the ARN in hand, and its whole job is to keep the evidence.
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status as http_status

from api.deps import current_user
from core.gst_calendar import GSTR1, GSTR3B, financial_year_of, obligations_for_month
from core.tax_periods import PeriodError, is_valid_period, period_of
from db.repositories import (
    compliance_repository,
    gstr1_repository,
    pharmacy_repository,
    sales_repository,
)
from services.compliance import reminders as reminder_service
from services.compliance import schedule as schedule_service
from services.compliance import stages as stage_service
from services.gstr1.engine import compute
from services.gstr1.periods import resolve_filing_period

router = APIRouter(prefix="/compliance", tags=["compliance"])

# Which return each stage's completion corresponds to, for the schedule.
_STAGE_FOR_KIND = {GSTR1: stage_service.GSTR1_FILED, GSTR3B: stage_service.GSTR3B_FILED}


def _today() -> date:
    return datetime.now().date()


def _identity() -> dict:
    return pharmacy_repository.tax_identity()


def _period_or_400(period: str) -> str:
    if not is_valid_period(period):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"{period!r} is not a tax period. Use MMYYYY, for example 092026.",
        )
    return period


def _timeline_for(period: str, identity: dict) -> tuple:
    """The eight stages for one period, and the pieces they were built from."""
    filing_period = resolve_filing_period(period, identity.get("effective_filing_frequency"))
    documents = gstr1_repository.documents_for_period(filing_period)
    result = compute(documents, identity, filing_period)

    period_state = sales_repository.get_period(period)
    built = stage_service.build(
        period_state=period_state,
        gstr1_validation={
            "blocking": [
                {"id": i.id, "code": i.code, "message": i.message,
                 "record_type": i.record_type, "record_id": i.record_id}
                for i in result.report.blocking
            ],
            "warnings": [
                {"id": i.id, "code": i.code, "message": i.message,
                 "record_type": i.record_type, "record_id": i.record_id}
                for i in result.report.warnings
            ],
        },
        sale_count=len(documents),
        draft_count=sum(1 for d in documents if d.status == "DRAFT"),
        gstr1_filing=compliance_repository.live_filing(period, GSTR1),
        gstr3b_filing=compliance_repository.live_filing(period, GSTR3B),
        is_nil_return=result.is_nil_return,
    )
    return built, filing_period, result


def _completion(periods: list, identity: dict) -> dict:
    """What is already done, keyed `(period, kind)` for the schedule.

    Filing evidence is read for every period in one go; the full timeline is
    not, because building a GSTR-1 for twelve periods to draw a calendar would
    make the calendar the most expensive screen in the app.
    """
    filings = compliance_repository.filings_for_periods(periods)
    done: dict = {}
    for filing in filings:
        done[(filing["period"], filing["return_type"])] = {
            "is_done": True,
            "done_at": filing.get("filed_at"),
            "arn": filing.get("arn"),
            "current_stage": _STAGE_FOR_KIND.get(filing["return_type"]),
            "link": "/compliance",
        }
    return done


@router.get("/next-action")
def next_action(_user: dict = Depends(current_user)) -> dict:
    """The one thing to do next. For the home screen.

    One answer rather than a list: a home screen showing five things due is one
    somebody skims, and the point of this endpoint is that it is actionable.
    """
    today = _today()
    identity = _identity()
    frequency = identity.get("effective_filing_frequency")
    state_code = identity.get("state_code")

    years = schedule_service.open_years(today)
    every = []
    for year in years:
        periods = [
            f"{m:02d}{y}" for m, y in
            [(month, year if month >= 4 else year + 1) for month in list(range(4, 13)) + list(range(1, 4))]
        ]
        every.extend(
            schedule_service.build_schedule(
                year, frequency, state_code, today, _completion(periods, identity)
            )
        )

    action = schedule_service.next_action(every, today)
    watch = schedule_service.time_barred_watch(every, today)
    return {
        "as_of": today.isoformat(),
        "filing_frequency": identity.get("filing_frequency"),
        "next_action": action,
        "time_bar": {
            "already_barred_count": watch["already_barred_count"],
            "closing_soon_count": watch["closing_soon_count"],
            "has_anything": watch["has_anything"],
        },
        "note": (
            None if action else
            "Nothing is outstanding. The next return will appear here when its "
            "period ends."
        ),
    }


@router.get("/calendar")
def calendar(
    financial_year: Optional[int] = Query(None, description="FY start year, e.g. 2026."),
    _user: dict = Depends(current_user),
) -> dict:
    """The year's schedule, branching on how this shop files."""
    today = _today()
    identity = _identity()
    year = financial_year if financial_year is not None else financial_year_of(today)
    frequency = identity.get("effective_filing_frequency")

    periods = [f"{m:02d}{year}" for m in range(4, 13)] + [f"{m:02d}{year + 1}" for m in range(1, 4)]
    items = schedule_service.build_schedule(
        year, frequency, identity.get("state_code"), today, _completion(periods, identity)
    )

    return {
        "as_of": today.isoformat(),
        "financial_year": year,
        "label": f"FY {year}-{str(year + 1)[-2:]}",
        "filing_frequency": identity.get("filing_frequency"),
        "effective_filing_frequency": frequency,
        "state_code": identity.get("state_code"),
        "frequency_is_set": bool(identity.get("filing_frequency")),
        "items": [item.to_dict(today) for item in items],
        "next_action": schedule_service.next_action(items, today),
        "open_years": schedule_service.open_years(today),
    }


@router.get("/time-bar")
def time_bar(_user: dict = Depends(current_user)) -> dict:
    """Unfiled returns measured against the three-year permanent bar."""
    today = _today()
    identity = _identity()
    frequency = identity.get("effective_filing_frequency")
    state_code = identity.get("state_code")

    every = []
    for year in schedule_service.open_years(today):
        periods = [f"{m:02d}{year}" for m in range(4, 13)] + [
            f"{m:02d}{year + 1}" for m in range(1, 4)
        ]
        every.extend(
            schedule_service.build_schedule(
                year, frequency, state_code, today, _completion(periods, identity)
            )
        )
    return {"as_of": today.isoformat(), **schedule_service.time_barred_watch(every, today)}


@router.get("/timeline/{period}")
def timeline(period: str, _user: dict = Depends(current_user)) -> dict:
    """The eight stages for one period, with what is blocking each."""
    _period_or_400(period)
    identity = _identity()
    try:
        built, filing_period, result = _timeline_for(period, identity)
    except PeriodError as error:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(error))

    current = stage_service.current_stage(built)
    obligations = obligations_for_month(
        period, identity.get("effective_filing_frequency"), identity.get("state_code")
    )
    today = _today()
    return {
        "period": period,
        "period_label": filing_period.label,
        "covers_months": list(filing_period.months),
        "filing_frequency": filing_period.frequency,
        "stages": [stage.to_dict() for stage in built],
        "current_stage": current.id if current else None,
        "is_nil_return": result.is_nil_return,
        "obligations": [
            {
                "kind": o.kind, "label": o.label,
                "due_date": o.due_date.isoformat(),
                "days_remaining": o.days_until(today),
                "is_filing": o.is_filing, "is_optional": o.is_optional,
                "note": o.note,
                "barred_on": o.barred_on.isoformat() if o.barred_on else None,
            }
            for o in obligations
        ],
    }


# ------------------------------------------------------------ the evidence


@router.get("/filings")
def list_filings(
    periods: Optional[str] = Query(None, description="Comma-separated MMYYYY."),
    include_superseded: bool = Query(False),
    _user: dict = Depends(current_user),
) -> dict:
    """Filing evidence: what was filed, when, and under which ARN."""
    today = _today()
    if periods:
        wanted = [p.strip() for p in periods.split(",") if p.strip()]
    else:
        year = financial_year_of(today)
        wanted = [f"{m:02d}{year}" for m in range(4, 13)] + [
            f"{m:02d}{year + 1}" for m in range(1, 4)
        ]

    rows = compliance_repository.filings_for_periods(
        wanted, include_superseded=include_superseded
    )
    return {
        "rows": [
            {
                "id": r.get("id"), "period": r.get("period"),
                "return_type": r.get("return_type"), "arn": r.get("arn"),
                "filed_at": r.get("filed_at"), "filed_by": r.get("filed_by"),
                "covers_months": r.get("covers_months") or [],
                "note": r.get("note"),
                "recorded_at": r.get("recorded_at"),
                "superseded_by": r.get("superseded_by"),
                # The payload is fetched on demand: these are whole returns,
                # and shipping one per row would be megabytes to show a date.
                "has_payload": bool(r.get("payload_json")),
            }
            for r in rows
        ],
        "row_count": len(rows),
    }


@router.get("/filings/{filing_id}/payload")
def filing_payload(filing_id: str, _user: dict = Depends(current_user)) -> dict:
    """The exact JSON that was submitted. The audit trail."""
    found = compliance_repository.filing_payload(filing_id)
    if found is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No filing recorded under that reference.",
        )
    return found


@router.post("/filings", status_code=http_status.HTTP_201_CREATED)
def record_filing(body: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    """Records a filing that has **already happened** on the portal.

    This does not file. It takes the ARN the portal gave back and keeps it with
    the payload that was sent, so the return can be explained later.

    When no payload is supplied, the one stored at period close is used - that
    is what the offline utility was given, so it is what was filed.
    """
    period = body.get("period")
    _period_or_400(period or "")

    payload = body.get("payload")
    if payload is None:
        stored = sales_repository.get_period(period)
        if stored.get("payload_json"):
            import json
            try:
                payload = json.loads(stored["payload_json"])
            except (TypeError, ValueError):
                payload = None

    try:
        return compliance_repository.record_filing(
            period=period,
            return_type=body.get("return_type"),
            arn=body.get("arn"),
            filed_at=body.get("filed_at"),
            payload=payload,
            covers_months=body.get("covers_months"),
            filed_by=user.get("id") or user.get("email"),
            note=body.get("note"),
        )
    except compliance_repository.ComplianceError as error:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        )


# ------------------------------------------------------------- reminders


@router.get("/reminders")
def reminders(
    preview: bool = Query(False, description="Show what would fire if enabled."),
    _user: dict = Depends(current_user),
) -> dict:
    """What should be reminded about today, and the settings behind it."""
    today = _today()
    identity = _identity()
    settings = compliance_repository.reminder_settings()

    year = financial_year_of(today)
    periods = [f"{m:02d}{year}" for m in range(4, 13)] + [
        f"{m:02d}{year + 1}" for m in range(1, 4)
    ]
    items = schedule_service.build_schedule(
        year, identity.get("effective_filing_frequency"),
        identity.get("state_code"), today, _completion(periods, identity),
    )

    return {
        "as_of": today.isoformat(),
        "settings": settings,
        "due": [r.to_dict() for r in reminder_service.due_reminders(items, settings, today)],
        "preview": (
            reminder_service.preview(items, settings, today) if preview else None
        ),
        "note": (
            "Reminders are off. Nothing will be sent until you turn them on."
            if not settings["enabled"] else None
        ),
    }


@router.put("/reminders")
def set_reminders(body: dict = Body(...), _user: dict = Depends(current_user)) -> dict:
    """Turns reminders on or off and sets how far ahead they start."""
    try:
        return compliance_repository.set_reminder_settings(
            enabled=bool(body.get("enabled")),
            days_before=body.get("days_before"),
            channel=body.get("channel"),
        )
    except compliance_repository.ComplianceError as error:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        )
