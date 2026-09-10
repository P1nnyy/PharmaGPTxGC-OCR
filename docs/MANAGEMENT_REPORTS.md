# Management reports

Seven reports and a dashboard, at `/business-reports` and `/dashboard`. These
are what make a shopkeeper open the app daily rather than monthly.

Three of them are only possible because purchase cost, batch lineage and sales
sit in one graph. No spreadsheet a shop keeps can answer "what did the twelve
packs still on this shelf cost me" — that needs the invoice that delivered
them, the batch they arrived as, and the sales that took some away, joined.

---

## First, the thing that was missing

**The stock ledger only ever had sales in it.** `save_counter_sale` wrote
negative movements and nothing wrote positive ones, so a running balance could
only count down, and the cost basis every margin figure needs was not in the
graph at all.

Purchases are now recorded as movements when an invoice is **verified** — the
same trigger that already learns vendor item names, and for the same reason: an
unreviewed scan should not move stock or set a cost that every later margin
figure is computed against.

### Why generations, and why this matters

`update_invoice` deletes an invoice's line items and recreates them with fresh
ids whenever they are edited. Keying a movement to a line item id would leave
the previous movements orphaned *and still counted*, so stock and cost basis
would both **double on every correction** — the duplicate-ingestion failure the
house rules call the highest-severity class of bug here.

So each verification writes a **generation**, fingerprinted by what the lines
actually say:

* verifying again with nothing changed is a no-op;
* a correction supersedes the live generation and writes a new one;
* nothing is deleted, reads filter `superseded_by IS NULL`, and the superseded
  rows survive to explain why a figure moved;
* superseding happens *before* the new write, or there is a window in which
  both generations are live and stock reads double.

`backfill_purchase_movements()` covers invoices verified before this existed,
and is safe to run repeatedly for the same reason.

### Cost conventions

* **Received quantity is billed plus free.** A 10+2 scheme puts twelve packs on
  the shelf; costing them as ten overstates unit cost by a fifth. This matches
  what `inventory_repository` already counts as held.
* **Cost is stored as a line total and a quantity**, never a per-unit price, so
  the weighted average is taken once over sums instead of averaging figures
  that were each rounded.
* **Input tax is stored alongside**, because that is the credit that goes back
  under 17(5)(h) if the stock is written off rather than returned.

---

## 1. Gross margin

By product, by vendor, by month. Margin is sale taxable value less the weighted
average cost of the batch that was sold.

Two honesty rules:

* **A margin against the wrong cost is worse than none.** A sale naming a batch
  no purchase recorded — common on imported and photographed bills — is costed
  at the product's overall average and marked `PRODUCT` rather than `BATCH`.
  Where nothing is known the row is `NONE` and its revenue is **excluded from
  margin**, rather than shown as pure profit, which is what subtracting a zero
  cost produces.
* **Day totals are excluded, loudly.** A `DAY_TOTAL` declares a slab total and
  names no product. A shop billing mostly that way would otherwise see a margin
  covering a fraction of its sales with no way to know, so the count and the
  reason are always shown — and the empty state distinguishes "you have day
  totals" from "you have nothing".

Products selling below cost get their own section.

---

## 2. Expiry risk and ITC at risk

**The report the product is for**, and the first thing on the dashboard.

A pharmacy's expiry loss is two numbers, not one. The stock is worth what it
cost, **and** the input credit already claimed on it must be reversed
permanently under **Section 17(5)(h)** — "goods lost, stolen, destroyed or
written off" — because credit is only for inputs used in making taxable
supplies, and stock that expired on a shelf never made one. A ₹18,400 write-off
is really ₹18,400 plus ₹2,208 of credit going back, reported in GSTR-3B table
**4(B)(1)**, and never reclaimable.

And it is avoidable. Most distributors accept saleable returns up to some
window before expiry:

* inside the window the answer is **"send it back this week"**;
* outside it, **"this is a loss, and here is what it costs you in March"**.

`Vendor.return_window_days` is per-distributor, on no invoice, and derivable
from nothing we hold — so it is asked for and **reported as unknown until
somebody fills it in**. A guessed default that says "you have time" when you do
not is worse than silence. It is editable inline on the distributor scorecard.

Buckets are 30/60/90/180 days and **exclusive**: a batch 45 days out is in the
60 bucket and not the 30, so the totals add up. Stock already past expiry gets
its own row rather than being mixed into "30 days", where it would imply time
remains. Batches with nothing left on hand are excluded — sold stock carries no
expiry risk.

---

## 3. Vendor filing scorecard

What a shopkeeper wants to know about a distributor is not turnover. It is
**does this supplier's paperwork cost me money?** A distributor who files
GSTR-1 late holds up the buyer's credit, because credit is capped by GSTR-2B
and nothing appears there until the supplier files.

**Today the filing columns are blank, not zero.** Filing dates come from
GSTR-2B, which is not connected. A zero would render as "filed on time every
month" — a claim about a supplier we have no evidence for, and one somebody
would repeat to them. What *is* real is the purchase exposure: how much credit
each distributor accounts for, which is exactly the measure of how much their
filing behaviour can cost. Rows are ranked by it.

The seam matches the statutory pack's: a `FilingSource`, a `has_filing_data`
flag, and phrasing that does not move when 2B lands. `Gstr2bFilingSource`
exists as a real class that raises rather than as a comment.

Output is phrased for a shopkeeper, not an accountant:

> Distributor X filed late in 4 of the last 6 months, delaying ₹42,000 of your
> credit by an average of 31 days.

---

## 4–7. The rest

**Stock ledger** — movement history per batch with a running balance, filterable
by product, batch and reason. The balance runs per `(product, batch)`, because
a ledger mixing batches answers no question anyone has: expiry, cost and recall
are all tracked by batch. A balance going below zero is **flagged, not hidden** —
it means stock left the shelf that no scanned purchase put there.

**Fast and slow movers** — units and value, with **days of cover** against
current stock. Cover turns a rate into a date, which is what makes slow stock
actionable. Products that sold nothing still appear: built from sales alone the
report would omit exactly the slow movers it exists to surface. Nothing sold is
reported as *no rate to project from*, not as infinite cover.

**Daily sales summary** — by hour, payment split, bill count, average bill
value, cash against digital, and the month before. The comparison is what earns
the daily open: a number alone is trivia, the same number against last month is
a fact. The gap between what bills say and what was recorded as taken is shown
here too — the same comparison a scrutiny officer makes.

**Purchase vs sales trend** — the working capital picture. Money leaves in lumps
and comes back over weeks. The **cumulative** line is the point: one day of
buying more than selling is a delivery, six weeks of it is working capital
draining, and only the running difference tells them apart.

---

## Dashboard

Four cards. The test each had to pass: **if this number moves, does the
shopkeeper do something differently today?**

| Card | Why it qualifies |
|---|---|
| Today's sales | Against the *same weekday* last week — a Monday against a Sunday says more about the calendar than the shop |
| Input credit at risk | The reason to open daily rather than monthly |
| Open compliance actions | What is blocking this period's return, while there is still time |
| Stock on hand | What is sitting on the shelf, at cost |

Lifetime scans, invoices processed and products in catalogue were removed. They
describe the software's activity rather than the shop's, and a dashboard made
of them gets opened once. A test asserts they do not creep back.

Each card links to its report. The dashboard still renders if the period's
return cannot be computed — one card reading zero beats a page that fails.

---

## Charts

**Hand-rolled inline SVG.** There is no charting library in this frontend and
the brief said not to add a second charting dependency, so rather than
introduce a first one these extend what the reports feature already does with
CSS magnitude bars.

They take values that are already final — nothing scales, aggregates or rounds
— because a chart that recomputes its own numbers can disagree with the table
beside it. One hue carries magnitude, a second is reserved for the comparison
series, status colours are never reused for data, and each chart has a text
alternative.

The hour histogram keeps the **quiet hours on the axis**. A chart drawn only
from hours that had a sale hides the shape somebody is looking for, and a
pharmacy has two humps.

---

## API

```
GET /management/dashboard
GET /management/expiry-risk?horizon_days=180
GET /management/margin?start=&end=
GET /management/stock-ledger?start=&end=&product_id=&batch_number=&reason=
GET /management/movers?start=&end=&limit=
GET /management/daily-sales?month=
GET /management/trend?start=&end=
GET /management/vendor-scorecard?start=&end=
GET /management/vendors
PUT /management/vendors/{vendor_id}/return-window
```

Costing is built **once per request** and shared by margin, expiry, movers and
stock value — building it four times would be four chances for two reports to
disagree about the same shelf. A test pins this.

## Layout

```
db/repositories/invoice_repository.py    purchase movements (generations)
db/repositories/management_repository.py movement and sales reads, in paise
db/repositories/vendor_repository.py     return windows

services/management/costing.py           weighted average batch positions
services/management/expiry.py            expiry risk + ITC at risk
services/management/margin.py            gross margin
services/management/vendors.py           scorecard + the GSTR-2B seam
services/management/stock.py             ledger, movers, stock value
services/management/sales.py             daily summary, trend
services/management/dashboard.py         the four cards

api/routers/management.py
frontend/src/features/management/        reports + hand-rolled charts
frontend/src/pages/DashboardPage.tsx     the four cards
```

## Tests

```bash
/Users/pranavgupta/PharmaGPTxGC-OCR/.venv/bin/python -m pytest tests/unit -q
```

* `test_purchase_movements.py` — the generation behaviour, including that a new
  line-item id alone is not a change and that superseding never deletes.
* `test_management_reports.py` — one synthetic shelf, every figure worked out by
  hand.
* `test_management_routes.py` — the endpoints, and that costing is shared.
