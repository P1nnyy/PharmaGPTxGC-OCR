# The statutory report pack

Seven reports over one filing period, at `/statutory-reports`. Every figure
drills through to the documents behind it.

The rule the whole thing is built around: **a number a user cannot explain to
an officer is worse than no number.** A wrong figure gets corrected. A figure
nobody can account for is the one that turns a routine scrutiny into an
assessment.

---

## The reports

| # | Report | Source |
|---|---|---|
| 1 | **GSTR-1 preview** | The C1 engine, table by table, with validation inline and the offline-utility JSON |
| 2 | **GSTR-3B worksheet** | 3.1 from GSTR-1; 4(A)(5) from an ITC source; 4(B)/(D) from the reversal ledger |
| 3 | **Purchase register** | Invoice-wise inward supplies, rate blocks, ITC eligibility, vendor |
| 4 | **Sales register** | Bill-wise outward supplies, filterable by rate, capture mode and payment method |
| 5 | **HSN summary** | Outward from Table 12, inward from purchase lines, both with UQC status |
| 6 | **Document series** | Table 13 with gaps and duplicates highlighted |
| 7 | **ITC reversal register** | Every reversal with trigger, provision, 3B table and source document |

They are built from **one load of the period**. The 3B worksheet reads the
GSTR-1 the same period produced, the cross-checks compare the return against
the register, and the HSN summary is Table 12 with validation attached.
Building them separately would let two reports disagree about the same
month — and catching your own drift with your own reconciliation checker is
not what the checker is for.

---

## Traceability

Every money value crosses the wire as a **figure**, not a number:

```json
{ "paise": 31040000, "value": 310400.00,
  "drill": { "kind": "SALES", "filters": {"periods": ["092026"]}, "count": 10 },
  "caveat": null }
```

`drill` is a **query, not a list of ids**. The obvious design — each figure
carries the ids behind it — works for a small shop and collapses for a busy
one: a single B2CS bucket in a month with three thousand bills would carry
three thousand ids, in every figure, in every report. So a drill describes
*how to find* the documents, and `POST /statutory/drill` resolves it when
somebody clicks. Small sets still pin exact ids by putting them in the filter.

The UI renders every figure through one `Amount` component, which becomes a
button whenever a drill is present. A figure with no drill renders as plain
text, which is itself the signal that it is a subtotal of other figures rather
than something with records behind it.

This is enforced by test, not by review. `TestEveryFigureIsTraceable` walks the
whole serialised pack, finds everything shaped like a figure, and fails if one
has no provenance. It caught a real omission on its first run.

---

## Cross-checks

Four reconciliations run **on every report load** and surface as a banner. One
you have to remember to run gets run the day before filing, which is when it is
least useful.

1. **GSTR-1 outward totals vs sales register.** The return aggregates into rate
   buckets; the register sums bill by bill. A difference means the aggregation
   lost or double-counted a document — most often a bill with no place of
   supply, which the return leaves out of every table.
2. **HSN summary vs transaction-level totals.** Compared against documents that
   *carry line items*, because day totals have none and cannot contribute to an
   HSN summary. That is a gap to know about, not a mismatch to fix.
3. **Rate block sums vs document headers.** The house rule — tax per line,
   summed per block, reconciled to the header — applied across a whole period.
   Both sides are the same documents, so any difference is a bill whose lines
   and total disagree.
4. **Declared turnover vs the payment split.** The one that catches unrecorded
   cash. A shortfall means either payments were not entered or sales were not
   rung up. A scrutiny officer runs this same comparison; better to find it
   here. Bills with no payment split are excluded and counted rather than
   failing the check — including them would fail every period and train people
   to ignore it.

---

## GSTR-3B

### The outward rows cannot be edited at the portal

Since January 2025, **Table 3 of GSTR-3B is auto-populated from GSTR-1 and
GSTR-1A and locked**. A wrong outward figure cannot be fixed in 3B. It has to
be corrected in **GSTR-1A, before 3B is filed** — and once 3B is filed for the
period, that route closes too.

This is the most expensive thing to not know, because the instinct on seeing a
wrong number is to edit it where you found it. Every outward row carries the
warning and a lock icon.

Non-GST supplies get their own **3.1(e)** row rather than being folded into
3.1(c). Table 8 captures nil-rated, exempt and non-GST separately, and adding
non-GST to the exempt row would overstate it.

### 4(A)(5) is provisional until GSTR-2B is wired in

Since October 2022 the credit claimable in 3B is **capped by GSTR-2B** — what
suppliers actually filed — not by what the buyer holds. An invoice in a drawer
with perfect tax on it earns no credit until the supplier reports it.

Today 4(A)(5) is sourced from the purchase register, which is therefore an
**upper bound and usually wrong**. It says so on every figure it produces.

The seam is `services/statutory/itc_sources.py`. Everything downstream depends
on `ItcSource` and `ItcClaim` and never on where the number came from, and the
two things that actually differ are carried as data:

```python
is_authoritative   # purchase register: False.  GSTR-2B: True.
caveats            # what to know before filing. Empty once 2B lands.
```

Wiring 2B in means implementing `Gstr2bSource.claim_for` and changing
`default_source()`. The worksheet, the exports and the UI do not move — they
already render whatever caveats they are handed and mark the figure provisional
when told to. `Gstr2bSource` exists now as a real class that raises, rather
than as a comment, so the shape of the swap is fixed.

### 4(C) does not add the reclaim back

4(D)(1) is a *disclosure* of credit that came back. The credit itself already
sits inside 4(A)(5) for the period it was reclaimed in, so adding it to the net
would claim it twice.

---

## The ItcReversal ledger

Append-only, as the house rules require. No UPDATE and no DELETE: a wrong row is
**superseded** by a new one and both survive. If March's figure changes in June,
the March return stops matching its records and nothing explains the difference.

**Every row must name a source document.** The write refuses without one — a
reversal with no provenance cannot be explained to an officer.

A reversal is never just an amount. It carries a trigger, the provision behind
it, and the 3B row it lands in, and those resolved values are **stored on the
row** rather than looked up later: a return filed in March cited a particular
provision and has to keep saying so.

| Trigger | Provision | 3B | Reclaimable |
|---|---|---|---|
| `EXPIRED_STOCK` | Section 17(5)(h) | 4(B)(1) | no |
| `DAMAGED_STOCK`, `STOCK_WRITTEN_OFF` | Section 17(5)(h) | 4(B)(1) | no |
| `EXEMPT_SUPPLY_PROPORTION` | Rule 42 | 4(B)(1) | no |
| `CAPITAL_GOODS_EXEMPT` | Rule 43 | 4(B)(1) | no |
| `NON_PAYMENT_180_DAYS` | Rule 37 | 4(B)(2) | **yes** |
| `BLOCKED_CREDIT` | Section 17(5) | 4(B)(1) | no |
| `SUPPLIER_CREDIT_NOTE` | Section 16(2), Rule 37A | 4(B)(1) | no |
| `RECLAIM` | Rule 37 | 4(D)(1) | — |

Expired stock is the pharmacy's usual case by a wide margin, and it is
permanent — the goods are destroyed and the credit on them was never earned.
Rule 42 matters more than it used to now that the notified life-saving drugs
are nil rated: a shop selling both taxable and nil-rated stock cannot claim the
whole of its common input credit.

Getting the table wrong is not recoverable without an amendment. Reporting a
permanent reversal in 4(B)(2) understates a liability that will never be
reclaimed; reporting a temporary one in 4(B)(1) throws away credit the shop is
owed. So the mapping lives in one table in `core/itc_rules.py`, and a trigger
the catalogue does not know is refused at the write.

---

## Money: two representations, one boundary

The sales side stores **integer paise**. The purchase side (`Invoice`,
`LineItem`) predates that rule and stores **rupees as floats** — there is no
`_paise` field on it anywhere. The 3B worksheet has to add one to the other.

`db/repositories/statutory_repository.py` is where that stops. Every purchase
money column is converted once on the way out, via
`core.money.paise_from_legacy_rupees`, and the float is *dropped* rather than
kept alongside — two representations of one amount in a dict is an invitation
for the wrong one to be summed. Nothing above the repository sees a rupee.

`paise_from_legacy_rupees` is deliberately more forgiving than
`parse_rupees_to_paise`. The strict parser refuses a third decimal because a
person typing one has made a typo; a stored float has a third decimal as the
ordinary residue of binary arithmetic, and refusing `1234.5600000000001` would
refuse a real invoice. It rounds to the nearest paisa instead.

**Stored data is not migrated.** That is a separate job. What this guarantees is
that no *computation* uses a float, and that purchase-derived figures carry a
caveat saying they were rounded from stored decimals.

---

## Exports

Every report exports as **CSV and Excel**, and every screen prints.

All three render from the **same pack dictionary the screen reads**, through
one column specification per report in `services/statutory/exports.py`. A
figure cannot differ between the screen, the CSV and the spreadsheet because
there is only one figure and one list of columns. An export built by a second
query — or assembled in the browser — is one that can disagree with what
somebody checked before downloading it.

* Every export carries a header block: shop, GSTIN, period, generation time.
* A pack that **failed its cross-checks says so inside the file**, because
  whoever opens it in three weeks will not remember the banner.
* Money is written as a **number**, not `"₹1,234.56"`. The first thing anyone
  does to a column of money is sum it, and a currency string sums to zero. The
  rupee sign lives in the Excel cell format.
* CSV goes out as **utf-8-sig**. Excel on Windows reads plain UTF-8 as latin-1
  and turns every rupee sign into mojibake; the BOM stops that.

---

## Records do not live in the browser

GST records must be retained for **72 months**. A store that a cache clear
destroys cannot hold them, and the house rules say so directly: anything that
feeds a GST return lives in Neo4j, and browser storage is for UI state and the
offline outbox only.

`ReportsPage` and `InventoryPage` were already server-backed before this task.
The remaining violation was `InvoiceReviewPage`, which built a
`pharmaflow_inventory` array in the browser on every Verify — written and, since
the Inventory page moved to `/inventory/stock`, never read. It is gone. The
invoice is the record, it is saved to the server, and stock is composed from
invoices.

The "clear local data" prompts still look for the old key, so a browser
carrying a stale copy can be cleaned out.

---

## API

```
GET  /statutory/{period}                     the pack, cross-checks included
     ?vendor= &rate= &capture_mode= &payment_method=
GET  /statutory/{period}/export/{report}?fmt=csv|xlsx
POST /statutory/drill                        {kind, filters} -> documents
GET  /statutory/reversals/triggers           the catalogue, with its rules
POST /statutory/reversals                    append one (never updates)
GET  /statutory/reversals/{period}           the ledger, superseded on request
```

`/{period}` is registered **last**: it matches any single segment, so a static
route added after it would be swallowed and answered with "that is not a tax
period".

The trigger catalogue is served rather than hard-coded in the UI, so the form
and the ledger cannot disagree about which provision a trigger cites.

---

## Layout

```
core/itc_rules.py                       triggers -> provision -> 3B table
core/money.py                           + paise_from_legacy_rupees

db/repositories/itc_repository.py       the append-only ItcReversal ledger
db/repositories/statutory_repository.py the paise boundary over legacy floats

services/statutory/model.py             Figure, Drill, CrossCheck, ReportRow
services/statutory/itc_sources.py       the 4(A)(5) seam (2B swap point)
services/statutory/gstr3b.py            the worksheet
services/statutory/registers.py         purchase and sales registers
services/statutory/hsn.py               outward and inward HSN + UQC status
services/statutory/crosschecks.py       the four reconciliations
services/statutory/exports.py           CSV + Excel, one column spec each
services/statutory/pack.py              one load, seven projections

api/routers/statutory.py                pack, exports, drill, reversals
frontend/src/features/statutory/        the screen + print stylesheet
```

## Tests

```bash
/Users/pranavgupta/PharmaGPTxGC-OCR/.venv/bin/python -m pytest tests/unit -q
```

* `test_statutory_foundations.py` — the money boundary, the reversal catalogue,
  figure provenance, the ITC source seam.
* `test_statutory_pack.py` — the seven reports over the same synthetic
  September the GSTR-1 tests pin to the paise, plus the structural
  traceability check.
* `test_statutory_routes.py` — the endpoints, exports in both formats, the
  drill, and the ledger's refusals.
