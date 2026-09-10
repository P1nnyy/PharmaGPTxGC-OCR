# GSTR-1 — the outward-supply return

Turns a period's sales into GSTR-1 shaped data: a validated JSON payload in the
GSTN offline utility's schema, plus a review screen at `/gst-returns`.

**This does not file anything.** There is no GSP integration and no connection
to the portal. The output is a file a person downloads and uploads themselves.

---

## A nil return still has to be filed

A period with no sales is not a period with no obligation. A nil GSTR-1 is due
on the same date as any other, and a late fee accrues for every day it is not
filed — ₹20 per day for a nil return, against ₹50 otherwise, subject to a cap.
There is no relief for having had nothing to report.

So the engine produces a complete payload for an empty period rather than
refusing or returning nothing. `Gstr1Return.is_nil_return` says when that has
happened, and the review screen says so on the page. Tables 8, 12 and 13 are
still emitted — at zero — because those are statements about the whole period,
and omitting one claims something different from stating it as nothing.

---

## Filing frequency drives everything

Nothing in the engine assumes monthly. `Pharmacy.filing_frequency` is
`MONTHLY` or `QUARTERLY`, and `resolve_filing_period` turns "this shop, this
period" into the window one return covers — one month, or a QRMP quarter.

A quarterly filer aggregated by month would file three returns where one was
due, each missing two thirds of the quarter. So:

* every aggregation reads `FilingPeriod.months` rather than a single period;
* closing a QRMP period closes **all three months**, or records in the other
  two would stay editable after their figures had gone to the portal;
* `fp` in the payload is the month the window *ends* in, which is how the
  portal identifies a quarterly return.

The field is stored unset rather than defaulting silently, so "files monthly"
and "nobody has said" stay distinguishable. A period cannot be closed until it
is set — previewing works, closing does not.

---

## The tables

| Table | What it holds | Notes |
|---|---|---|
| **4A — B2B** | Supplies to registered persons, invoice-wise | Rare but real: expired stock returned to a distributor on the pharmacy's own outward tax invoice |
| **5 — B2CL** | Inter-state supplies to consumers above ₹2,50,000 | Implemented as a **guard**, see below |
| **7 — B2CS** | Supplies to unregistered persons, aggregated | Grouped by place of supply, rate and supply type; returns netted in |
| **8** | Nil rated, exempted, non-GST | Split intra/inter × registered/unregistered; all four rows always emitted |
| **12 — HSN** | HSN summary, B2B and B2C sections | Recomputed from line items; validated against the GSTN master |
| **13** | Documents issued, per bill series | Opening, closing, issued, cancelled, net, and gaps |

### Table 7 and the negative-bucket guard

Sale returns to unregistered customers net into the same buckets — that is what
a credit note to a walk-in customer does to a return.

A bucket that goes negative is **withheld, not emitted**. Returns exceeding
sales is a real thing that happens across a month boundary (a customer
returning in October what they bought in September), but the portal will not
accept a negative aggregate, and the correct fix is an amendment against the
period the original sale was in. So it stops and is raised for review. A
negative bucket does not suppress the healthy buckets beside it.

### Table 5 is a guard, not a path

This will almost never fire for a counter pharmacy, and the reason is worth
stating: **an over-the-counter sale is supplied where the counter stands.** A
customer who drove in from the next state and carried the medicine away has
made an intra-state purchase. Place of supply follows where the goods are
handed over, not where the customer lives.

So a bill that does qualify for Table 5 is far more likely to be a place of
supply entered wrongly than a genuine large inter-state consumer sale. It is
reported invoice-wise *and* raised as a blocking review item, and it is
excluded from the Table 7 aggregate so the supply is not reported twice.

### Table 12 and the HSN master

Every HSN is validated against `data/gstn/hsn_master.json`. The portal's
Table 12 is a dropdown: a code that is merely plausible is not rejected when it
is typed, it is rejected when the return is filed — after the month has closed.
Validating at entry moves that failure somewhere it is still cheap.

* **Digit length** comes from `Pharmacy.hsn_digit_policy`: 4 digits at AATO up
  to ₹5 crore, 6 above. A code shorter than the shop owes is refused; a longer
  one is fine.
* **HSN is mandatory for B2B** whatever the turnover, so a missing one blocks.
  For B2C it is optional at or below ₹5 crore, so a missing one warns — and
  blocks above that threshold.
* **UQC** must be one of GSTN's own unit codes. A pharmacy says "strip" and
  "vial"; `data/gstn/uqc.json` carries the mapping. An unmappable unit is
  refused rather than filed as `OTH`, which would turn a fixable data problem
  into a permanently vague return.
* The summary is **recomputed from line items**, never read off a stored
  aggregate. A stored total was correct when it was written, and a line
  corrected afterwards leaves it silently wrong — which the portal then
  cross-checks against the document-level tables and rejects.

The master ships as a **seed** covering what a pharmacy sells (chapter 30 in
depth, plus nutraceuticals, personal care, diagnostics, sanitary goods and
devices) at 4, 6 and 8 digits. Replacing it with the full GSTN list needs no
code change. Never add a code to make a bill pass — an unknown code means the
product is misclassified.

### Table 13 counts numbers, not supplies

The only table that does not filter to confirmed documents. A cancelled bill
consumed a number and is reported as issued-then-cancelled; deleting it would
show a gap the shop cannot account for, and the portal cross-checks these
counts against the document-level tables.

Gaps are surfaced as blocking. A missing number in the middle of a series is
either a bill issued on a device that never synced — in which case the return
is missing its supplies — or a number that was skipped.

**Duplicates** are surfaced too, and cannot be acknowledged away. Two documents
sharing a serial are indistinguishable in a return, Rule 46(b) makes a serial
unique within the financial year, and the offline serial-block design has no
conflict resolver downstream to catch it — the atomic block allocation is the
only thing preventing it, so a duplicate reaching here means that guarantee has
already failed and somebody has to look.

---

## Aggregate turnover is declared, never derived

AATO decides HSN digit length, and it is **PAN-wide across every GSTIN on the
PAN**. This workspace holds the sales of exactly one of them.

So it is asked for and stored with the year it covers and where the figure came
from (`aato_paise`, `aato_financial_year`, `aato_source`). Deriving it from our
own sales would understate any multi-GSTIN business and quietly file four
digits where six were owed.

What the engine *does* do is cross-check: our own recorded sales are a floor
under AATO, so if they already exceed the declaration, the declaration is
stale. That warns — and blocks when our own sales have crossed ₹5 crore while
the declaration has not, because that is the case where the digit length is
actively wrong.

`Pharmacy.pan` already exists, so a sibling-GSTIN registry is an easy later
extension.

---

## Period close and immutability

`POST /tax-periods/{period}/close` runs every validation, produces the payload,
and sets `TaxPeriod.status` to `CLOSED` for every month the return covers.

It **recomputes from the records** rather than trusting anything in the
request. The body carries only the ids of blocking items a person has
consciously accepted, and those are matched against freshly computed items — an
acknowledgement of something that is no longer a problem simply does not apply.

After close, sales in that period are immutable, **enforced in the repository**
(`sales_repository.assert_period_open`) rather than only in the UI. Every write
path calls it. Corrections become new documents — a credit note or an
amendment — never edits.

### The one exception, and why

A bill issued on a device offline and syncing late is **recorded and flagged**,
not refused. It was printed and handed to a customer before the sync; nothing
the server discovers can un-issue it, and refusing it would lose it. It is
stored with an issue noting that it needs an amendment. That is the only caller
of `upsert_sale(allow_filed_period=True)`.

### Reproducibility

The payload is stored on the `TaxPeriod` at close. A return that cannot be
revised has to be reproducible: when the portal disagrees six months later, the
question is what was actually sent, and recomputing it from records that have
moved on since answers a different question. `GET /tax-periods/{period}/payload`
returns the stored payload for a closed period and a fresh computation for an
open one.

---

## Validation report

Produced before close, every item carrying a route back to the offending
record. The blocking/warning split is not about how serious something sounds —
it is about whether filing makes it worse.

**Blocking** — the return would be rejected, or would state a wrong figure:
negative B2CS bucket, series gap, duplicate serial, missing B2B HSN, HSN not in the master,
missing or invalid UQC, a document with no place of supply, rate blocks that do
not reconcile to the header, a B2CL bill needing review, a B2B credit note
(Table 9B, which this engine does not build, so it is excluded and said so),
filing frequency unset, no GSTIN or state code.

**Warning** — filable, but worth looking at: missing B2C HSN below the
threshold, unmapped products, exempt lines on a document classed as a tax
invoice (Rule 46A wanted an invoice-cum-bill-of-supply), drafts still in the
period, day totals leaving the HSN summary incomplete, a stale AATO
declaration, a 0% slab recorded as taxable rather than nil-rated.

Blocking items can be acknowledged. Some are facts about a real month rather
than mistakes, and a check nobody can override is a check people work around.
The acknowledgement is recorded against the period with who made it.

---

## What this does not do

* **No filing and no GSP integration.** Download the JSON and upload it.
* **No Table 9B (CDNR/CDNUR).** Credit notes to *unregistered* persons net into
  Table 7 as specified. Credit notes to *registered* persons are excluded from
  Table 4A and raised as blocking, so the gap is visible rather than silent.
* **No amendment tables** (9A, 10, 11).
* **No e-commerce supplies**; every B2CS row is filed as `OE`.
* **No cess** beyond carrying the field through at zero.

---

## Layout

```
core/hsn.py                          HSN + UQC validation, digit policy
data/gstn/hsn_master.json            the stored GSTN master (seed)
data/gstn/uqc.json                   GSTN unit codes + pharmacy aliases

services/gstr1/model.py              the input contract - frozen, no database
services/gstr1/periods.py            filing frequency -> filing window
services/gstr1/tables.py             the six aggregators, pure integer paise
services/gstr1/validation.py         blocking/warning report
services/gstr1/payload.py            GSTN offline-utility JSON (the only rupees)
services/gstr1/engine.py             aggregate -> validate -> shape

db/repositories/gstr1_repository.py  Sale nodes -> outward documents
db/repositories/sales_repository.py  the filing lock, close, cancel
api/routers/tax_periods.py           preview, payload, close
frontend/src/features/gstr1/         the review screen
```

The engine never opens a database. That is partly testability — a month of
mixed sales can be built in a fixture and asserted to the paise — and partly
that `.env` here points at production Neo4j, so an engine that read the graph
would be an engine whose tests read production.

## Tests

```bash
docker run --rm -u app -v "$PWD":/w -w /w --entrypoint bash deploy-backend \
  -lc "pip install --quiet --user pytest anyio >/dev/null 2>&1; python -m pytest tests/unit -q"
```

`tests/unit/test_gstr1_synthetic_month.py` is one synthetic September asserted
to the paise: two rates, nil-rated and exempt lines, a day total with no lines,
a customer return, a cancelled bill, a series gap, both a small inter-state
delivery and a large one either side of the Table 5 threshold, a B2B invoice
for expired stock, and a draft that must not appear. Every expected figure is
worked out by hand in the test rather than recomputed by it.
