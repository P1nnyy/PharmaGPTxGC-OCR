"""The eight stages a period goes through, and what is holding each one up.

A period is not "done" or "not done". It moves through a sequence, and at any
moment exactly one stage is the one to work on. The value of the timeline is
that it answers *which*, and then says what is in the way of it — with a link
to each offending record, because "3 blocking items" that a person then has to
go hunting for is a worse answer than none.

Validation items are distributed to the stage they actually belong to rather
than being listed once at the top. A draft bill is a capture problem; a missing
UQC is a preparation problem; they are fixed by different people at different
moments, and showing them together makes both look like the same task.

**Two stages cannot be completed yet, and say so.** Reconciling GSTR-2B and
actioning IMS both need 2B, which this system does not fetch. They are shown as
blocked on that rather than as pending — pending would imply somebody could go
and do them today, and they would look for the button.
"""

from dataclasses import dataclass, field
from typing import Optional

# Stage states. `BLOCKED` is distinct from `PENDING`: pending means its turn
# has not come, blocked means its turn has come and something is stopping it.
DONE = "DONE"
CURRENT = "CURRENT"
BLOCKED = "BLOCKED"
PENDING = "PENDING"
NOT_APPLICABLE = "NOT_APPLICABLE"

SALES_CAPTURED = "sales_captured"
PERIOD_CLOSED = "period_closed"
GSTR1_PREPARED = "gstr1_prepared"
GSTR1_FILED = "gstr1_filed"
RECONCILED_2B = "reconciled_2b"
IMS_ACTIONED = "ims_actioned"
GSTR3B_PREPARED = "gstr3b_prepared"
GSTR3B_FILED = "gstr3b_filed"

STAGE_ORDER = (
    SALES_CAPTURED, PERIOD_CLOSED, GSTR1_PREPARED, GSTR1_FILED,
    RECONCILED_2B, IMS_ACTIONED, GSTR3B_PREPARED, GSTR3B_FILED,
)

STAGE_LABELS = {
    SALES_CAPTURED: "Sales captured",
    PERIOD_CLOSED: "Period closed",
    GSTR1_PREPARED: "GSTR-1 prepared",
    GSTR1_FILED: "GSTR-1 filed",
    RECONCILED_2B: "GSTR-2B reconciled",
    IMS_ACTIONED: "IMS actioned",
    GSTR3B_PREPARED: "GSTR-3B prepared",
    GSTR3B_FILED: "GSTR-3B filed",
}

# Which stage each validation code is a problem for. A code not listed here
# falls to the close, which is where the engine refuses on it.
_CODE_STAGE = {
    "DRAFT_IN_PERIOD": SALES_CAPTURED,
    "NO_PLACE_OF_SUPPLY": SALES_CAPTURED,
    "UNMAPPED_PRODUCT": SALES_CAPTURED,
    "NO_BILL_SERIES": SALES_CAPTURED,
    "SERIES_GAP": SALES_CAPTURED,
    "SERIES_DUPLICATE": SALES_CAPTURED,
    "NO_HSN_B2B": GSTR1_PREPARED,
    "NO_HSN_B2C": GSTR1_PREPARED,
    "HSN_NOT_ACCEPTED": GSTR1_PREPARED,
    "NO_UQC": GSTR1_PREPARED,
    "UQC_NOT_ACCEPTED": GSTR1_PREPARED,
    "HSN_SUMMARY_INCOMPLETE": GSTR1_PREPARED,
    "NO_GSTIN": PERIOD_CLOSED,
    "NO_STATE_CODE": PERIOD_CLOSED,
    "NO_FILING_FREQUENCY": PERIOD_CLOSED,
    "CREDIT_NOTE_TO_REGISTERED_NOT_FILED": GSTR3B_PREPARED,
    "AATO_CROSSES_HSN_THRESHOLD": GSTR1_PREPARED,
    "AATO_BELOW_OWN_SALES": GSTR1_PREPARED,
}

# Where a stage's work is actually done.
_STAGE_LINK = {
    SALES_CAPTURED: "/business-reports",
    PERIOD_CLOSED: "/gst-returns",
    GSTR1_PREPARED: "/statutory-reports",
    GSTR1_FILED: "/compliance",
    RECONCILED_2B: "/statutory-reports",
    IMS_ACTIONED: "/statutory-reports",
    GSTR3B_PREPARED: "/statutory-reports",
    GSTR3B_FILED: "/compliance",
}

NOT_CONNECTED_2B = (
    "GSTR-2B is not connected yet, so this cannot be completed here. Download "
    "the statement from the portal and reconcile it there before filing 3B — "
    "the credit you may claim is capped by what is in it."
)


@dataclass
class Stage:
    id: str
    label: str
    state: str
    detail: str = ""
    link: Optional[str] = None
    blocking: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    completed_at: Optional[str] = None
    evidence: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "state": self.state,
            "detail": self.detail,
            "link": self.link,
            "blocking": list(self.blocking),
            "warnings": list(self.warnings),
            "blocking_count": len(self.blocking),
            "completed_at": self.completed_at,
            "evidence": self.evidence,
        }


def _split_by_stage(items: list) -> dict:
    buckets: dict = {stage: [] for stage in STAGE_ORDER}
    for item in items:
        buckets[_CODE_STAGE.get(item.get("code"), PERIOD_CLOSED)].append(item)
    return buckets


def build(
    period_state: dict,
    gstr1_validation: dict,
    sale_count: int,
    draft_count: int,
    gstr1_filing: Optional[dict],
    gstr3b_filing: Optional[dict],
    is_nil_return: bool = False,
) -> list:
    """The eight stages for one filing period, with the current one marked.

    The first stage that is not done becomes `CURRENT` unless something is
    blocking it, in which case it is `BLOCKED`. Everything after it is
    `PENDING`. Exactly one stage is ever the one to work on, which is what
    makes the home screen able to name a single next action.
    """
    blocking = _split_by_stage(gstr1_validation.get("blocking") or [])
    warnings = _split_by_stage(gstr1_validation.get("warnings") or [])

    is_closed = period_state.get("status") == "CLOSED"
    has_payload = bool(period_state.get("payload_json"))

    stages = [
        Stage(
            id=SALES_CAPTURED, label=STAGE_LABELS[SALES_CAPTURED],
            state=DONE if (sale_count or is_nil_return) else BLOCKED,
            detail=(
                "Nothing was sold in this period — a nil return is still due."
                if is_nil_return and not sale_count else
                f"{sale_count} document{'' if sale_count == 1 else 's'}"
                + (f", {draft_count} still in draft" if draft_count else "")
            ),
            completed_at=None,
        ),
        Stage(
            id=PERIOD_CLOSED, label=STAGE_LABELS[PERIOD_CLOSED],
            state=DONE if is_closed else PENDING,
            detail=(
                "Records for this period are locked; corrections need a credit "
                "note or an amendment."
                if is_closed else
                "Closing locks the records behind the return so the figures "
                "cannot move after they are filed."
            ),
            completed_at=period_state.get("closed_at"),
        ),
        Stage(
            id=GSTR1_PREPARED, label=STAGE_LABELS[GSTR1_PREPARED],
            state=DONE if has_payload else PENDING,
            detail=(
                "The JSON is ready to upload to the offline utility."
                if has_payload else
                "Produced when the period is closed."
            ),
            completed_at=period_state.get("closed_at") if has_payload else None,
        ),
        Stage(
            id=GSTR1_FILED, label=STAGE_LABELS[GSTR1_FILED],
            state=DONE if gstr1_filing else PENDING,
            detail=(
                f"ARN {gstr1_filing['arn']}"
                if gstr1_filing else
                "File on the portal, then record the ARN here. This app does not "
                "file for you."
            ),
            completed_at=(gstr1_filing or {}).get("filed_at"),
            evidence=_evidence(gstr1_filing),
        ),
        Stage(
            id=RECONCILED_2B, label=STAGE_LABELS[RECONCILED_2B],
            state=BLOCKED, detail=NOT_CONNECTED_2B,
        ),
        Stage(
            id=IMS_ACTIONED, label=STAGE_LABELS[IMS_ACTIONED],
            state=BLOCKED,
            detail=(
                "Accepting, rejecting or holding supplier invoices happens in the "
                "portal's Invoice Management System, and what it acts on comes "
                "from 2B. Until 2B is connected this cannot be tracked here."
            ),
        ),
        Stage(
            id=GSTR3B_PREPARED, label=STAGE_LABELS[GSTR3B_PREPARED],
            state=DONE if has_payload else PENDING,
            detail=(
                "The worksheet is ready. Its input credit figure is provisional "
                "until 2B is reconciled."
                if has_payload else
                "Available once the period is closed."
            ),
        ),
        Stage(
            id=GSTR3B_FILED, label=STAGE_LABELS[GSTR3B_FILED],
            state=DONE if gstr3b_filing else PENDING,
            detail=(
                f"ARN {gstr3b_filing['arn']}"
                if gstr3b_filing else
                "File on the portal, then record the ARN here."
            ),
            completed_at=(gstr3b_filing or {}).get("filed_at"),
            evidence=_evidence(gstr3b_filing),
        ),
    ]

    for stage in stages:
        stage.link = _STAGE_LINK.get(stage.id)
        stage.blocking = blocking.get(stage.id, [])
        stage.warnings = warnings.get(stage.id, [])

    _mark_current(stages)
    return stages


def _evidence(filing: Optional[dict]) -> Optional[dict]:
    if not filing:
        return None
    return {
        "id": filing.get("id"),
        "arn": filing.get("arn"),
        "filed_at": filing.get("filed_at"),
        "filed_by": filing.get("filed_by"),
        "has_payload": bool(filing.get("payload_json")),
    }


def _mark_current(stages: list) -> None:
    """Marks the first unfinished stage, and pends everything after it.

    A blocked stage that is not the current one stays blocked but does not
    stop the sequence: 2B reconciliation cannot be done at all yet, and letting
    it hold up the 3B stages would leave the timeline permanently stuck on a
    step nobody can take.
    """
    found = False
    for stage in stages:
        if stage.state == DONE:
            continue
        if stage.state == BLOCKED and not found:
            # Blocked stages that are waiting on something external do not
            # become "the" current step - the work moves past them.
            continue
        if not found:
            stage.state = BLOCKED if stage.blocking else CURRENT
            found = True
        elif stage.state == PENDING:
            stage.state = PENDING


def current_stage(stages: list) -> Optional[Stage]:
    for stage in stages:
        if stage.state in (CURRENT, BLOCKED) and stage.id not in (RECONCILED_2B, IMS_ACTIONED):
            return stage
    return None
