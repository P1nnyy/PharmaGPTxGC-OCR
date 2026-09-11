# The compliance calendar

What to do and when, at `/compliance`, with the single next action on the home
screen.

> **This prepares and tracks. It does not file.**
>
> There is no GSP integration and no submission path. Filing is a later
> milestone and will be gated behind an OTP and an explicit user action.
> Nothing in this codebase should ever be able to send a return without a
> person deciding to. `POST /compliance/filings` records a filing that has
> **already happened** on the portal — a test asserts the router has no other
> write endpoints.

---

## Everything branches on filing frequency

`Pharmacy.filing_frequency` decides the whole schedule, and a QRMP shop's
obligations are **not the monthly ones moved** — they are different obligations
in different months.

| | Monthly filer | QRMP filer |
|---|---|---|
| GSTR-1 | 11th of the next month | 13th of the month after the quarter |
| IFF *(optional)* | — | 13th, first two months of the quarter |
| GSTR-2B *(arrives)* | 14th, monthly | 14th, **quarterly** |
| GSTR-3B | 20th of the next month | **22nd or 24th**, by state |
| PMT-06 | — | 25th, first two months of the quarter |

Per financial year that is 36 obligations for a monthly filer and 28 for a QRMP
one. Building the QRMP schedule by adjusting monthly dates would get it wrong
in four separate ways, so it is generated from the frequency instead.

### The 22nd/24th split

QRMP GSTR-3B is due on the 22nd in one group of states and the 24th in the
other. Both groups are written out in full in `core/gst_calendar.py` — an
abbreviation there is a wrong due date for whichever state got left out.

**An unrecognised state code gets the earlier date.** Telling a shop it has
until the 24th when the real date was the 22nd creates a late filing; the
reverse costs two days of float. Only one of those is a problem.

---

## The three-year permanent bar

The part nobody expects, and the reason this feature earns its place.

Section 39(11) and Section 37(4), as amended by the Finance Act 2023 and
operative from July 2025, stop a return being filed **more than three years
after its due date**. The portal refuses it. There is no late-fee route back and
no condonation. Whatever input credit and liability sit in that period are
frozen exactly where they are, permanently.

A shop with an old unfiled period generally does not know this, so:

* every unfiled return carries `barred_on` and `days_until_barred`;
* anything within 180 days of the bar **outranks everything else** in the next
  action, above returns that are merely overdue;
* it **overrides whatever reminder offsets** were configured and always warns;
* the `/compliance/time-bar` tab separates what is already lost from what is
  still recoverable, and carries a count in the tab label so it does not need a
  click to discover.

Open years are bounded four back: anything older is past the bar in full, and
listing it would be a wall of rows with no action behind any of them.

---

## The eight-stage timeline

```
sales captured → period closed → GSTR-1 prepared → GSTR-1 filed
              → 2B reconciled → IMS actioned → 3B prepared → 3B filed
```

Exactly one stage is ever "the one to work on", which is what lets the home
screen name a single next action.

**Blocking items are distributed to the stage they belong to**, not listed once
at the top. A draft bill is a capture problem; a missing UQC is a preparation
problem. They are fixed by different people at different moments, and showing
them together makes both look like the same task. Every stage links to where
its work is done — "3 blocking items" that somebody then has to hunt for is a
worse answer than none.

### Two stages cannot be completed yet, and say so

**2B reconciled** and **IMS actioned** both need GSTR-2B, which this system does
not fetch. They are shown as `BLOCKED` with the reason, not as `PENDING` —
pending would imply somebody could go and do them today, and they would look for
the button. Neither stalls the stages after it, or every period would be stuck
on a step nobody can take.

### Closing is not filing

`close_period` used to set `filed_at` alongside `closed_at`, so every prepared
period claimed to have been filed. Closing prepares the return and locks the
records behind it; **nothing has gone to the portal**. `filed_at` now belongs
only to recorded filing evidence, which requires an ARN. The immutability lock
is unaffected — it keys off `status`, not `filed_at`.

---

## Filing evidence

A `ReturnFiling` row is **ARN + filing timestamp + the exact JSON submitted**.
Any two of those without the third is an assertion; all three is a record. When
a notice arrives asking why a return says what it says, this is the answer.

* **Append-only.** A filing recorded wrongly is superseded by a new row and both
  survive, because the question is not "what does it say now" but "what did it
  say in March, and when did that change".
* Recording the **same ARN twice** is somebody pressing save again — returned
  unchanged rather than duplicated. A **different ARN** supersedes.
* The payload defaults to the one stored at period close: that is what the
  offline utility was given, so it is what was filed.
* Payloads are fetched **on demand**, never with a listing — these are whole
  returns, and shipping one per row would be megabytes to show a date.

An ARN is validated on shape (15 alphanumeric characters) rather than checksum:
a typo caught here is worth more than a false refusal of a number the portal
actually issued.

---

## Reminders

**Off by default**, and the reason is the whole design:

> Notification fatigue kills the feature. A calendar that sends something every
> day trains people to dismiss it without reading, and then the one reminder
> that mattered — the return three weeks from a permanent bar — arrives in a
> stream of fourteen that did not, and gets dismissed with the rest.

Four rules follow:

1. **Nothing fires unless switched on.** Checked before anything else, so a shop
   that has not opted in cannot receive one through some later branch.
2. **One step fires, not every step whose day has passed.** Otherwise the due
   date itself produces four notifications.
3. **The tone escalates** — seven days out is a `NOTE`, the morning of is
   `URGENT`. The same message four times is nagging, not escalation.
4. **Overdue reminders back off**: daily for the first week, then weekly.

That fourth rule exists because the preview caught the original one. The preview
shows a shop the real volume before it opts in, and for a shop with eight late
returns the obvious daily-forever rule produced **381 reminders over 45 days** —
exactly the fatigue the design is built to avoid. It is 85 now, and a test
guards the volume rather than just the rule.

A return approaching the three-year bar ignores the configured offsets entirely
and always warns.

This module *computes* which reminders are due. It sends nothing — there is no
mail or push transport here, so the rule can be tested without a mailbox.

---

## Home screen

One thing: **the next action due, with days remaining.** Not the calendar and
not a list — a home screen showing five things due is one somebody skims.

Precedence, each step there for a reason:

1. anything about to be **permanently time-barred** — the only deadline with no
   way back
2. anything **overdue** — late fees accrue daily
3. otherwise the **soonest due**

GSTR-2B is never offered as an action: it arrives whether or not anybody does
anything, so naming it would be naming something with no action in it.

It is fetched separately from the dashboard cards, so a calendar failure cannot
take the whole home screen down.

---

## API

```
GET  /compliance/next-action              the one thing, for the home screen
GET  /compliance/calendar?financial_year= the year's schedule
GET  /compliance/time-bar                 unfiled returns against the 3-year limit
GET  /compliance/timeline/{period}        the eight stages
GET  /compliance/filings                  filing evidence
GET  /compliance/filings/{id}/payload     the exact JSON submitted
POST /compliance/filings                  record a filing that already happened
GET  /compliance/reminders?preview=       what would fire, and the settings
PUT  /compliance/reminders                turn them on or off
```

Only two write endpoints, and neither files anything.

## Layout

```
core/gst_calendar.py                      statutory due dates, state groups, the bar
db/repositories/compliance_repository.py  ReturnFiling evidence, reminder settings
services/compliance/stages.py             the eight-stage timeline
services/compliance/schedule.py           the year, the next action, the time bar
services/compliance/reminders.py          escalation and back-off
api/routers/compliance.py
frontend/src/features/compliance/         calendar, timeline, evidence, reminders
frontend/src/pages/DashboardPage.tsx      the next-action banner
```

## Tests

```bash
/Users/pranavgupta/PharmaGPTxGC-OCR/.venv/bin/python -m pytest tests/unit -q
```

* `test_gst_calendar.py` — every statutory date, both state groups, the bar.
* `test_compliance_calendar.py` — the schedule, next-action precedence, the
  timeline's stage distribution, and the reminder rules including the volume
  guard.
* `test_compliance_routes.py` — the endpoints, and that **nothing files**.
