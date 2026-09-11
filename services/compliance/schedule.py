"""The year's schedule, the next thing due, and the returns that are running out of time.

Three questions, in descending order of how often they are asked:

  What do I have to do next?     — one answer, with days remaining
  What is coming this year?      — the schedule, branching on filing frequency
  What have I left too long?     — the three-year bar

The last one is the one nobody asks and everybody should. A return more than
three years past its due date **cannot be filed at all** — the portal refuses
under Section 39(11) and Section 37(4). There is no penalty route back and no
condonation. Whatever credit and liability sit in that period are frozen where
they are, permanently. A shop with an old unfiled period generally does not
know this, which is exactly why it is surfaced rather than waited for.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from core.gst_calendar import (
    GSTR2B,
    Obligation,
    obligations_for_financial_year,
    financial_year_of,
)

# How close is close enough to be worth shouting about.
URGENT_DAYS = 3
SOON_DAYS = 7
# Inside this many days of the permanent bar, an unfiled period stops being a
# backlog item and becomes the most important thing on the screen.
BAR_WARNING_DAYS = 180


@dataclass
class ScheduledItem:
    """One obligation, with everything needed to decide whether to act on it."""

    obligation: Obligation
    is_done: bool = False
    done_at: Optional[str] = None
    arn: Optional[str] = None
    blocking_count: int = 0
    current_stage: Optional[str] = None
    current_stage_label: Optional[str] = None
    link: Optional[str] = None

    def days_remaining(self, today: date) -> int:
        return self.obligation.days_until(today)

    def urgency(self, today: date) -> str:
        if self.is_done:
            return "DONE"
        if not self.obligation.is_filing:
            return "INFORMATIONAL"
        days = self.days_remaining(today)
        if self.obligation.is_time_barred(today):
            return "TIME_BARRED"
        if days < 0:
            return "OVERDUE"
        if days <= URGENT_DAYS:
            return "URGENT"
        if days <= SOON_DAYS:
            return "SOON"
        return "SCHEDULED"

    def to_dict(self, today: date) -> dict:
        obligation = self.obligation
        days_to_bar = obligation.days_until_barred(today)
        return {
            "kind": obligation.kind,
            "label": obligation.label,
            "period": obligation.period,
            "covers_months": list(obligation.covers_months),
            "due_date": obligation.due_date.isoformat(),
            "days_remaining": self.days_remaining(today),
            "is_filing": obligation.is_filing,
            "is_optional": obligation.is_optional,
            "note": obligation.note,
            "is_done": self.is_done,
            "done_at": self.done_at,
            "arn": self.arn,
            "urgency": self.urgency(today),
            "blocking_count": self.blocking_count,
            "current_stage": self.current_stage,
            "current_stage_label": self.current_stage_label,
            "link": self.link,
            "barred_on": obligation.barred_on.isoformat() if obligation.barred_on else None,
            "days_until_barred": days_to_bar,
            "is_time_barred": obligation.is_time_barred(today),
            "bar_is_near": (
                days_to_bar is not None and 0 < days_to_bar <= BAR_WARNING_DAYS
                and not self.is_done
            ),
        }


def build_schedule(
    fy_start_year: int,
    frequency: str,
    state_code: Optional[str],
    today: date,
    completion: Optional[dict] = None,
) -> list:
    """The financial year's obligations, marked with what is already done.

    `completion` is keyed `(period, kind)` and carries whatever the timeline
    knows: whether it is filed, its ARN, and how much is blocking it.
    """
    completion = completion or {}
    items = []
    for obligation in obligations_for_financial_year(fy_start_year, frequency, state_code):
        done = completion.get((obligation.period, obligation.kind), {})
        items.append(
            ScheduledItem(
                obligation=obligation,
                is_done=bool(done.get("is_done")),
                done_at=done.get("done_at"),
                arn=done.get("arn"),
                blocking_count=int(done.get("blocking_count") or 0),
                current_stage=done.get("current_stage"),
                current_stage_label=done.get("current_stage_label"),
                link=done.get("link"),
            )
        )
    return items


def next_action(items: list, today: date) -> Optional[dict]:
    """The single thing to do next.

    One answer, not a list. A home screen that shows five things due is a home
    screen somebody skims; one that shows the next one is a home screen
    somebody acts on.

    Order of precedence, and each step is there for a reason:

      1. anything about to be **permanently time-barred** — the only deadline
         that cannot be recovered from
      2. anything **overdue** — late fees accrue daily
      3. otherwise the **soonest due**

    GSTR-2B is skipped: it arrives whether or not anybody does anything, so
    naming it as an action would be naming something with no action in it.
    """
    outstanding = [
        item for item in items
        if not item.is_done and item.obligation.is_filing
        and not item.obligation.is_time_barred(today)
    ]
    if not outstanding:
        return None

    near_bar = [
        item for item in outstanding
        if (item.obligation.days_until_barred(today) or 10**6) <= BAR_WARNING_DAYS
    ]
    overdue = [item for item in outstanding if item.days_remaining(today) < 0]

    if near_bar:
        chosen = min(near_bar, key=lambda i: i.obligation.days_until_barred(today) or 0)
        reason = "TIME_BAR"
    elif overdue:
        chosen = min(overdue, key=lambda i: i.obligation.due_date)
        reason = "OVERDUE"
    else:
        chosen = min(outstanding, key=lambda i: i.obligation.due_date)
        reason = "NEXT_DUE"

    payload = chosen.to_dict(today)
    payload["reason"] = reason
    payload["headline"] = _headline(chosen, today, reason)
    return payload


def _headline(item: ScheduledItem, today: date, reason: str) -> str:
    """One sentence a shopkeeper can act on without reading anything else."""
    days = item.days_remaining(today)
    label = item.obligation.label.split(" — ")[0]
    period = item.obligation.period
    pretty = f"{period[:2]}/{period[2:]}"

    if reason == "TIME_BAR":
        left = item.obligation.days_until_barred(today)
        return (
            f"{label} for {pretty} can only be filed for another {left} days. "
            "After that the portal refuses it permanently."
        )
    if days < 0:
        return f"{label} for {pretty} was due {abs(days)} days ago. Late fees are running."
    if days == 0:
        return f"{label} for {pretty} is due today."
    if days == 1:
        return f"{label} for {pretty} is due tomorrow."
    return f"{label} for {pretty} is due in {days} days."


def time_barred_watch(
    items: list, today: date, historic: Optional[list] = None
) -> dict:
    """Unfiled returns measured against the three-year bar.

    `historic` carries obligations from earlier years that are still open;
    those are where the bar actually bites, because this year's returns are
    nowhere near it.
    """
    every = list(items) + list(historic or [])
    unfiled = [i for i in every if not i.is_done and i.obligation.is_filing]

    barred = [i for i in unfiled if i.obligation.is_time_barred(today)]
    closing = sorted(
        (
            i for i in unfiled
            if not i.obligation.is_time_barred(today)
            and (i.obligation.days_until_barred(today) or 10**6) <= BAR_WARNING_DAYS
        ),
        key=lambda i: i.obligation.days_until_barred(today) or 0,
    )

    return {
        "rule": (
            "A return cannot be filed more than three years after its due date — "
            "Section 39(11) for GSTR-3B and Section 37(4) for GSTR-1. The portal "
            "refuses it. There is no late-fee route back and no condonation."
        ),
        "already_barred": [i.to_dict(today) for i in barred],
        "closing_soon": [i.to_dict(today) for i in closing],
        "already_barred_count": len(barred),
        "closing_soon_count": len(closing),
        "has_anything": bool(barred or closing),
    }


def open_years(today: date, earliest: Optional[int] = None) -> list:
    """Financial years a shop might still have open returns in.

    Bounded at four years back: anything older is past the bar in full and
    there is nothing to be done about it, so listing it would be a wall of
    rows with no action behind any of them.
    """
    current = financial_year_of(today)
    first = earliest if earliest is not None else current - 3
    return list(range(first, current + 1))
