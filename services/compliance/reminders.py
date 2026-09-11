"""Escalating reminders, off until somebody turns them on.

The design constraint is not technical. **Notification fatigue kills the
feature**: a calendar that sends something every day trains people to dismiss
it without reading, and then the one reminder that mattered — the return three
weeks from a permanent bar — arrives in a stream of fourteen that did not, and
gets dismissed with the rest.

So three rules:

1. **Off by default.** A shop that never opens settings never gets a
   notification from this. Nothing here fires until somebody asks for it.
2. **Escalating, not repeating.** Reminders get closer together and more
   insistent as a date approaches — seven days out is a note, the morning of is
   a warning. The same message four times is not escalation, it is nagging.
3. **One per obligation per step.** Each reminder is identified by what it is
   about and which step it is, so a caller that asks twice on the same day does
   not send twice. That key is the whole idempotency story.

This module *computes* which reminders are due. It does not send anything -
there is no mail or push transport here, and the caller decides what to do with
a due reminder. Keeping the decision and the delivery apart means the rule
above can be tested without a mailbox.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

# How loud each step is. The step that fires on the due date itself is the only
# one that calls itself urgent; escalation means nothing if everything shouts.
TONE_NOTE = "NOTE"
TONE_WARNING = "WARNING"
TONE_URGENT = "URGENT"
TONE_OVERDUE = "OVERDUE"
TONE_FINAL = "FINAL"


def _tone(days_before: int, days_remaining: int) -> str:
    if days_remaining < 0:
        return TONE_OVERDUE
    if days_remaining == 0:
        return TONE_URGENT
    if days_before <= 1:
        return TONE_URGENT
    if days_before <= 3:
        return TONE_WARNING
    return TONE_NOTE


@dataclass(frozen=True)
class Reminder:
    key: str
    kind: str
    period: str
    label: str
    due_date: str
    days_remaining: int
    tone: str
    message: str
    link: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "kind": self.kind,
            "period": self.period,
            "label": self.label,
            "due_date": self.due_date,
            "days_remaining": self.days_remaining,
            "tone": self.tone,
            "message": self.message,
            "link": self.link,
        }


def _message(item, days_remaining: int, tone: str) -> str:
    label = item.obligation.label.split(" — ")[0]
    period = item.obligation.period
    pretty = f"{period[:2]}/{period[2:]}"
    blocking = item.blocking_count

    if tone == TONE_FINAL:
        left = item.obligation.days_until_barred(date.today())
        return (
            f"{label} for {pretty} becomes impossible to file in {left} days. "
            "This is the last window."
        )
    if days_remaining < 0:
        base = f"{label} for {pretty} is {abs(days_remaining)} days late."
    elif days_remaining == 0:
        base = f"{label} for {pretty} is due today."
    elif days_remaining == 1:
        base = f"{label} for {pretty} is due tomorrow."
    else:
        base = f"{label} for {pretty} is due in {days_remaining} days."

    if blocking:
        return (
            f"{base} {blocking} item{'' if blocking == 1 else 's'} "
            f"{'is' if blocking == 1 else 'are'} still blocking it."
        )
    return base


def due_reminders(items: list, settings: dict, today: date) -> list:
    """Which reminders should fire today.

    Returns nothing at all when reminders are switched off — checked first and
    without looking at anything else, so a shop that has not opted in cannot
    receive one through some later branch.
    """
    if not settings or not settings.get("enabled"):
        return []

    offsets = sorted({int(d) for d in settings.get("days_before") or ()}, reverse=True)
    if not offsets:
        return []

    due = []
    for item in items:
        obligation = item.obligation
        if item.is_done or not obligation.is_filing:
            continue
        if obligation.is_time_barred(today):
            # Nothing to remind about: it can no longer be filed at all.
            continue

        days_remaining = obligation.days_until(today)

        # The permanent bar overrides the schedule. A return weeks from being
        # unfileable matters more than one due next Tuesday, and it fires
        # whatever offsets the shop chose.
        days_to_bar = obligation.days_until_barred(today)
        if days_to_bar is not None and 0 < days_to_bar <= 30:
            due.append(
                Reminder(
                    key=f"{obligation.period}:{obligation.kind}:BAR",
                    kind=obligation.kind, period=obligation.period,
                    label=obligation.label, due_date=obligation.due_date.isoformat(),
                    days_remaining=days_remaining, tone=TONE_FINAL,
                    message=_message(item, days_remaining, TONE_FINAL),
                    link=item.link,
                )
            )
            continue

        # An overdue return keeps reminding, because the late fee keeps
        # accruing - but only once a day, on the same key.
        if days_remaining < 0:
            due.append(
                Reminder(
                    key=f"{obligation.period}:{obligation.kind}:OVERDUE",
                    kind=obligation.kind, period=obligation.period,
                    label=obligation.label, due_date=obligation.due_date.isoformat(),
                    days_remaining=days_remaining, tone=TONE_OVERDUE,
                    message=_message(item, days_remaining, TONE_OVERDUE),
                    link=item.link,
                )
            )
            continue

        # Exactly one step fires: the one whose offset is today. Firing every
        # step whose offset has passed would mean four notifications on the
        # due date, which is the fatigue this design exists to avoid.
        if days_remaining in offsets:
            tone = _tone(days_remaining, days_remaining)
            due.append(
                Reminder(
                    key=f"{obligation.period}:{obligation.kind}:{days_remaining}",
                    kind=obligation.kind, period=obligation.period,
                    label=obligation.label, due_date=obligation.due_date.isoformat(),
                    days_remaining=days_remaining, tone=tone,
                    message=_message(item, days_remaining, tone),
                    link=item.link,
                )
            )

    # Most pressing first: the bar, then overdue, then by how little time is
    # left.
    rank = {TONE_FINAL: 0, TONE_OVERDUE: 1, TONE_URGENT: 2,
            TONE_WARNING: 3, TONE_NOTE: 4}
    due.sort(key=lambda r: (rank.get(r.tone, 9), r.days_remaining))
    return due


def preview(items: list, settings: dict, today: date, horizon_days: int = 45) -> list:
    """What would fire over the coming weeks, so a shop can see before enabling.

    Shown when reminders are still off, which is the moment somebody is
    deciding whether the feature will be useful or annoying. Letting them see
    the actual volume is a more honest answer than a description of it.
    """
    from datetime import timedelta

    enabled = {**(settings or {}), "enabled": True}
    upcoming = []
    for offset in range(horizon_days + 1):
        day = today + timedelta(days=offset)
        for reminder in due_reminders(items, enabled, day):
            upcoming.append({**reminder.to_dict(), "would_fire_on": day.isoformat()})
    return upcoming
