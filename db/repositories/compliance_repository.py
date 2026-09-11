"""Filing evidence, and when to be reminded.

**The evidence is the point.** When a notice arrives asking why a return says
what it says, the answer has to be three things together: the ARN the portal
gave back, the moment it was filed, and the exact JSON that was submitted. Any
two of those without the third is an assertion. All three is a record.

So a `ReturnFiling` row is append-only, like the other ledgers here. A filing
that turns out to have been recorded wrongly is **superseded** by a new row and
both survive, because the question somebody eventually asks is not "what does
it say now" but "what did it say in March, and when did that change".

This module records that a filing happened. **It does not file.** There is no
GSP integration and no submission path here, by design - filing is a later
milestone, it will be OTP-gated behind an explicit action, and nothing in this
codebase should ever be able to file a return without a person deciding to.
`record_filing` is what you call *after* filing on the portal, with the ARN in
your hand.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.gst_calendar import GSTR1, GSTR3B, IFF, PMT06
from core.tax_periods import is_valid_period
from core.tenancy import current_tenant
from db.graph_db import get_driver

# What can carry an ARN. GSTR-2B is absent on purpose: it is generated for you
# and is never filed, so there is nothing to acknowledge.
FILEABLE = {GSTR1, GSTR3B, PMT06, IFF}

# An ARN is 15 characters: AA + state + MM + YYYY + six digits + a check. The
# shape is checked rather than the checksum - a typo caught here is worth more
# than a false refusal of a number the portal actually issued.
_ARN_LENGTH = 15

# Escalating reminder offsets, in days before the due date. Off unless the shop
# turns them on: a compliance calendar that nags becomes a compliance calendar
# nobody reads, and the one reminder that mattered arrives in a stream of
# fourteen that did not.
DEFAULT_REMINDER_DAYS = (7, 3, 1, 0)


class ComplianceError(ValueError):
    """Raised when filing evidence or a reminder setting cannot be accepted."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_write(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: [r.data() for r in tx.run(query, **params)])


def _run_read(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _normalise_arn(arn: Optional[str]) -> str:
    text = "".join((arn or "").split()).upper()
    if not text:
        raise ComplianceError(
            "A filing has no evidence without its ARN. Copy the acknowledgement "
            "number from the portal."
        )
    if len(text) != _ARN_LENGTH or not text.isalnum():
        raise ComplianceError(
            f"{arn!r} does not look like an ARN. They are {_ARN_LENGTH} characters, "
            "letters and digits only."
        )
    return text


# ------------------------------------------------------------- the evidence


def record_filing(
    period: str,
    return_type: str,
    arn: str,
    filed_at: str,
    payload: Optional[dict] = None,
    covers_months: Optional[list] = None,
    filed_by: Optional[str] = None,
    note: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> dict:
    """Records that a return was filed, with the proof.

    Called after filing on the portal, never instead of it.

    The payload is stored verbatim as JSON. Not a summary of it and not a
    reference to something that can be recomputed - the whole value of this row
    is that it says what was *actually sent*, and a figure regenerated from
    records that have moved on since answers a different question.
    """
    pharmacy_id = pharmacy_id or current_tenant()

    if not is_valid_period(period):
        raise ComplianceError(f"{period!r} is not a tax period. Use MMYYYY.")
    if return_type not in FILEABLE:
        raise ComplianceError(
            f"{return_type!r} is not something that gets filed. "
            f"Expected one of {', '.join(sorted(FILEABLE))}."
        )
    if not filed_at:
        raise ComplianceError("A filing needs the date and time it was filed.")

    normalised = _normalise_arn(arn)

    existing = live_filing(period, return_type, pharmacy_id)
    if existing and existing.get("arn") == normalised:
        # Recording the same ARN twice is somebody pressing save again, not a
        # second filing. Returned unchanged rather than duplicated.
        return existing

    rows = _run_write(
        """
        MATCH (ph:Pharmacy {id: $pharmacy_id})
        CREATE (f:ReturnFiling {
            id: $id,
            pharmacy_id: $pharmacy_id,
            period: $period,
            return_type: $return_type,
            arn: $arn,
            filed_at: $filed_at,
            covers_months: $covers_months,
            payload_json: $payload_json,
            filed_by: $filed_by,
            note: $note,
            recorded_at: $now,
            superseded_by: null
        })
        CREATE (f)-[:BELONGS_TO]->(ph)
        WITH f
        OPTIONAL MATCH (p:TaxPeriod {key: $period_key})
        FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
            CREATE (f)-[:FILED_FOR]->(p)
            SET p.filed_at = coalesce(p.filed_at, $filed_at)
        )
        RETURN f {.*} AS filing
        """,
        id=str(uuid.uuid4()),
        pharmacy_id=pharmacy_id,
        period=period,
        return_type=return_type,
        arn=normalised,
        filed_at=filed_at,
        covers_months=list(covers_months or [period]),
        payload_json=json.dumps(payload) if payload is not None else None,
        filed_by=filed_by,
        note=note,
        now=_now(),
        period_key=f"{pharmacy_id}::{period}",
    )
    if not rows:
        raise ComplianceError("That workspace no longer exists.")

    new_row = rows[0]["filing"]
    if existing:
        # A different ARN for the same return: the first record was wrong.
        # Superseded rather than overwritten, so the history explains itself.
        _run_write(
            """
            MATCH (f:ReturnFiling {id: $id})
            SET f.superseded_by = $new_id, f.superseded_at = $now
            """,
            id=existing["id"], new_id=new_row["id"], now=_now(),
        )
    return new_row


def live_filing(
    period: str, return_type: str, pharmacy_id: Optional[str] = None
) -> Optional[dict]:
    """The filing that currently stands for this period and return."""
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (f:ReturnFiling {pharmacy_id: $pid, period: $period, return_type: $rt})
        WHERE f.superseded_by IS NULL
        RETURN f {.*} AS filing
        ORDER BY filing.recorded_at DESC
        LIMIT 1
        """,
        pid=pharmacy_id, period=period, rt=return_type,
    )
    return rows[0]["filing"] if rows else None


def filings_for_periods(
    periods: list, include_superseded: bool = False, pharmacy_id: Optional[str] = None
) -> list:
    """Every filing recorded against these periods."""
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (f:ReturnFiling {pharmacy_id: $pid})
        WHERE f.period IN $periods
          AND ($include_superseded OR f.superseded_by IS NULL)
        RETURN f {.*} AS filing
        ORDER BY filing.period, filing.return_type, filing.recorded_at
        """,
        pid=pharmacy_id, periods=list(periods), include_superseded=include_superseded,
    )
    return [row["filing"] for row in rows]


def filing_payload(filing_id: str, pharmacy_id: Optional[str] = None) -> Optional[dict]:
    """The exact JSON that was submitted, parsed.

    Read on demand rather than returned with every listing: these are whole
    returns, and shipping one on each row of a calendar would be megabytes to
    show a date.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (f:ReturnFiling {id: $id, pharmacy_id: $pid})
        RETURN f.payload_json AS payload_json, f.arn AS arn,
               f.filed_at AS filed_at, f.period AS period,
               f.return_type AS return_type
        """,
        id=filing_id, pid=pharmacy_id,
    )
    if not rows:
        return None
    row = rows[0]
    parsed = None
    if row.get("payload_json"):
        try:
            parsed = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            parsed = None
    return {
        "arn": row.get("arn"),
        "filed_at": row.get("filed_at"),
        "period": row.get("period"),
        "return_type": row.get("return_type"),
        "payload": parsed,
        # Said plainly rather than left as a null somebody has to interpret.
        "payload_missing": parsed is None,
    }


# ------------------------------------------------------------- reminders


def reminder_settings(pharmacy_id: Optional[str] = None) -> dict:
    """When this shop wants to be reminded, if at all.

    Off by default and stored as an explicit boolean rather than inferred from
    an empty list, so "never turned on" and "turned on and then silenced" stay
    distinguishable.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (ph:Pharmacy {id: $pid})
        RETURN ph.reminders_enabled AS enabled,
               ph.reminder_days_before AS days_before,
               ph.reminder_channel AS channel
        """,
        pid=pharmacy_id,
    )
    stored = rows[0] if rows else {}
    days = stored.get("days_before")
    return {
        "enabled": bool(stored.get("enabled")),
        "days_before": sorted(
            (int(d) for d in days), reverse=True
        ) if days else list(DEFAULT_REMINDER_DAYS),
        "channel": stored.get("channel") or "IN_APP",
        "is_default": not days,
    }


def set_reminder_settings(
    enabled: bool,
    days_before: Optional[list] = None,
    channel: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> dict:
    """Turns reminders on or off, and sets how far ahead they start."""
    pharmacy_id = pharmacy_id or current_tenant()

    cleaned = None
    if days_before is not None:
        try:
            cleaned = sorted({int(d) for d in days_before}, reverse=True)
        except (TypeError, ValueError):
            raise ComplianceError("Reminder offsets are whole numbers of days.")
        if any(d < 0 or d > 60 for d in cleaned):
            raise ComplianceError(
                "Reminder offsets are between 0 and 60 days before the due date."
            )
        if len(cleaned) > 6:
            raise ComplianceError(
                "Six reminders before one due date is already more than anybody "
                "reads. Pick fewer."
            )

    _run_write(
        """
        MATCH (ph:Pharmacy {id: $pid})
        SET ph.reminders_enabled = $enabled,
            ph.reminder_days_before = $days,
            ph.reminder_channel = $channel
        """,
        pid=pharmacy_id, enabled=bool(enabled), days=cleaned,
        channel=(channel or "IN_APP"),
    )
    return reminder_settings(pharmacy_id)
