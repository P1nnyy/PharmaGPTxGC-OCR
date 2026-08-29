/**
 * The questions a reviewer would otherwise have to ask the invoice by hand.
 *
 * This replaces a single "Math" verdict that collapsed several unrelated
 * questions into one word. "Formula mismatch" told you something was wrong
 * and left you to find out which of five things it was; worse, one unanswerable
 * question — a subtotal the invoice never printed — made the whole row look
 * broken. Each check now answers one question and says which numbers it used,
 * so a glance is enough and a correction is visibly the thing that fixed it.
 *
 * Every check is a pure function of what is on screen, so the moment the
 * reviewer edits a figure the answer changes with it. Nothing is cached.
 *
 * On `unknown`: a check whose inputs are absent is not a failure. An invoice
 * that prints no subtotal cannot fail a subtotal reconciliation, and colouring
 * that red teaches the reviewer to ignore red.
 */

export type CheckStatus = 'pass' | 'fail' | 'warn' | 'unknown';

export interface InvoiceCheck {
  id: string;
  /** Short enough for a chip. */
  label: string;
  status: CheckStatus;
  /** One line naming the numbers, shown on hover and in the expanded list. */
  detail: string;
}

export interface CheckInputs {
  subtotal: number | null;
  /** Sum of the line-item amounts on screen. */
  lineTotal: number | null;
  discount: number | null;
  taxTotal: number | null;
  cgst: number | null;
  sgst: number | null;
  igst: number | null;
  roundoff: number | null;
  grandTotal: number | null;
  itemCount: number;
  /** Rows missing at least one field a pharmacist needs. */
  itemsWithGaps: number;
  /** Rows whose amount was worked out rather than read off the page. */
  derivedAmounts: number;
  /** Billed + free across every row, or null when a row has no quantity. */
  receivedQuantity: number | null;
  /** The quantity total printed in the invoice footer, when it printed one. */
  statedQuantity: number | null;
  /** Rows whose billed + free lands short of a whole pack. */
  partPackRows: number;
  sellerName: string | null;
  sellerGstin: string | null;
  invoiceNumber: string | null;
  invoiceDate: string | null;
}

/**
 * Rupees of slack. Indian pharmacy invoices round per line and again at the
 * foot, so an exact match is the exception; a tolerance below about a rupee
 * flags arithmetic that is actually correct.
 */
const TOLERANCE = 2.0;

// Tolerant of a value that arrived as text: these figures come from input
// boxes, and a chip that throws takes the whole review page down with it —
// a status indicator must never be the thing that breaks the screen.
const money = (value: number | null | undefined): string => {
  const num = typeof value === 'number' ? value : parseFloat(String(value ?? ''));
  return Number.isFinite(num) ? `₹${num.toFixed(2)}` : '—';
};

const isPresent = (value: string | null): boolean => !!(value && value.trim());

export function buildInvoiceChecks(input: CheckInputs): InvoiceCheck[] {
  const checks: InvoiceCheck[] = [];

  // ---- 1. Do the rows add up to what the invoice says they add up to? ----
  //
  // Three targets are accepted, because formats disagree about what the
  // per-line "Amount" column means: some print it pre-tax, some after
  // discount, some tax-inclusive. Matching any one of them is a genuine
  // reconciliation, and insisting on a single formula fails correct invoices.
  if (input.lineTotal === null || input.subtotal === null) {
    checks.push({
      id: 'lines_vs_subtotal',
      label: 'Line items',
      status: 'unknown',
      detail: input.lineTotal === null
        ? 'Some rows have no amount yet, so they cannot be totalled.'
        : 'This invoice prints no subtotal to compare the rows against.',
    });
  } else {
    const discount = input.discount ?? 0;
    const roundoff = input.roundoff ?? 0;
    const candidates: { label: string; value: number }[] = [
      { label: 'the subtotal', value: input.subtotal },
      { label: 'the taxable value', value: input.subtotal - discount },
    ];
    if (input.grandTotal !== null) {
      candidates.push({ label: 'the grand total', value: input.grandTotal - roundoff });
    }
    const hit = candidates.find((c) => Math.abs(input.lineTotal! - c.value) <= TOLERANCE);
    checks.push({
      id: 'lines_vs_subtotal',
      label: 'Line items',
      status: hit ? 'pass' : 'fail',
      // A hit inside the tolerance is still a hit, but it is not necessarily
      // an exact match, and saying "matching" of a figure that is 20 paise out
      // is how a misread footer cell stays invisible. Name the gap when there
      // is one — the reviewer can then decide whether it is per-line rounding
      // or a digit read wrong.
      detail: hit
        ? (() => {
            const gap = Math.abs(input.lineTotal! - hit.value);
            return gap < 0.005
              ? `${input.itemCount} rows total ${money(input.lineTotal)}, matching ${hit.label} exactly.`
              : `${input.itemCount} rows total ${money(input.lineTotal)}, ${money(gap)} apart from ${hit.label} (${money(hit.value)}) — within rounding tolerance.`;
          })()
        : `${input.itemCount} rows total ${money(input.lineTotal)}, but the subtotal is ${money(input.subtotal)} — a gap of ${money(Math.abs(input.lineTotal - input.subtotal))}.`,
    });
  }

  // ---- 2. Does the totals block reach the grand total? ----
  if (input.subtotal === null || input.grandTotal === null) {
    checks.push({
      id: 'totals_vs_grand',
      label: 'Totals',
      status: 'unknown',
      detail: 'Needs both a subtotal and a grand total to check.',
    });
  } else {
    const expected =
      input.subtotal - (input.discount ?? 0) + (input.taxTotal ?? 0) + (input.roundoff ?? 0);
    const gap = expected - input.grandTotal;

    // A gap the invoice's own rounding explains is not an extraction fault,
    // and marking it red has a cost beyond noise: the only way a reviewer can
    // clear a red totals chip is to edit a figure until it goes green, which
    // on a correctly-read invoice means overwriting the amount payable. Grade
    // an explained gap amber and say what explains it, so the honest state of
    // the invoice is a state the reviewer can leave it in.
    const implied = deriveImpliedAdjustment(input);

    // The rupees of slack exist for per-line rounding drift on an invoice that
    // states no round-off of its own. Once one IS recorded, its entire job is
    // to close the total exactly, so any residue means it is wrong - and a
    // stale round-off must not hide behind the tolerance the drift needs.
    const reconciles = implied === null || (!implied.isStale && Math.abs(gap) <= TOLERANCE);
    const explained = implied !== null && implied.kind !== 'unexplained';

    checks.push({
      id: 'totals_vs_grand',
      label: 'Totals',
      status: reconciles ? 'pass' : explained ? 'warn' : 'fail',
      detail: reconciles
        ? `${money(input.subtotal)} − ${money(input.discount ?? 0)} + ${money(input.taxTotal ?? 0)}${input.roundoff ? ` + ${money(input.roundoff)}` : ''} = ${money(input.grandTotal)}.`
        : implied!.isStale
          ? `The recorded round-off of ${money(implied!.recordedRoundoff)} no longer reconciles — these figures need ${money(implied!.requiredRoundoff)} to reach ${money(input.grandTotal)}.`
          : explained
            ? `Subtotal, discount and tax come to ${money(expected)} against a grand total of ${money(input.grandTotal)} — a ${money(Math.abs(gap))} rounding the invoice applied without printing it.`
            : `Subtotal, discount and tax come to ${money(expected)}, but the grand total says ${money(input.grandTotal)} — off by ${money(Math.abs(gap))}.`,
    });
  }

  // ---- 2b. Does the quantity received add up? ----
  //
  // Its own question, and one the totals block cannot answer: every rupee
  // figure on this invoice reconciled while a free quantity was being read as
  // 0.20 instead of 0.25, because free goods carry no money. Quantity feeds
  // stock rather than the ledger, so nothing above would ever have caught it -
  // the footer's own quantity total is the only independent witness there is.
  {
    const quantity = (value: number | null): string =>
      value === null ? '—' : String(parseFloat(value.toFixed(2)));

    if (input.itemCount === 0) {
      checks.push({
        id: 'quantity',
        label: 'Quantity',
        status: 'unknown',
        detail: 'No line items on this invoice yet.',
      });
    } else if (input.receivedQuantity === null) {
      checks.push({
        id: 'quantity',
        label: 'Quantity',
        status: 'unknown',
        detail: 'Some rows have no quantity yet, so they cannot be totalled.',
      });
    } else if (input.statedQuantity !== null) {
      const gap = parseFloat((input.receivedQuantity - input.statedQuantity).toFixed(2));
      const matches = Math.abs(gap) < 0.005;
      // A matching total is not proof every row is right: two rows misread in
      // opposite directions cancel, and the sum alone would call that clean.
      // Rare, but it is the one way this check can be quietly wrong, so a
      // part pack still gets raised even when the arithmetic closes.
      const cancelsOut = matches && input.partPackRows > 0;
      checks.push({
        id: 'quantity',
        label: 'Quantity',
        status: matches ? (cancelsOut ? 'warn' : 'pass') : 'fail',
        detail: cancelsOut
          ? `${input.itemCount} rows total the ${quantity(input.statedQuantity)} the invoice states, but ${input.partPackRows} row(s) receive a part pack — the errors cancel, so check those rows individually.`
          : matches
          ? `${input.itemCount} rows receive ${quantity(input.receivedQuantity)} units, matching the ${quantity(input.statedQuantity)} the invoice states.`
          : `${input.itemCount} rows receive ${quantity(input.receivedQuantity)} units against the ${quantity(input.statedQuantity)} the invoice states — ${quantity(Math.abs(gap))} ${gap < 0 ? 'short' : 'over'}.`
            + (input.partPackRows > 0
              ? ` ${input.partPackRows} row(s) receive a part pack, which is where to look first.`
              : ''),
      });
    } else if (input.partPackRows > 0) {
      // Medicines are bought in whole packs. A part pack is nearly always a
      // free-quantity digit read wrong, but without the invoice's own total
      // there is nothing to prove it against, so it is raised rather than failed.
      checks.push({
        id: 'quantity',
        label: 'Quantity',
        status: 'warn',
        detail: `${input.partPackRows} of ${input.itemCount} rows receive a part pack (billed + free is not a whole number). This invoice states no quantity total to check against.`,
      });
    } else {
      checks.push({
        id: 'quantity',
        label: 'Quantity',
        status: 'pass',
        detail: `${input.itemCount} rows receive ${quantity(input.receivedQuantity)} units, every row a whole pack.`,
      });
    }
  }

  // ---- 3. Is every row complete enough to put into stock? ----
  checks.push({
    id: 'item_fields',
    label: 'Item details',
    status: input.itemCount === 0 ? 'unknown' : input.itemsWithGaps > 0 ? 'fail' : 'pass',
    detail:
      input.itemCount === 0
        ? 'No line items on this invoice yet.'
        : input.itemsWithGaps > 0
          ? `${input.itemsWithGaps} of ${input.itemCount} rows are missing a name, batch, HSN, quantity or amount.`
          : `All ${input.itemCount} rows have a name, batch, HSN, quantity and amount.`,
  });

  // ---- 4. Can this purchase be attributed and filed? ----
  //
  // The GSTIN carries the most weight: a purchase register is keyed on it, and
  // it is the field most recently seen to come back as the wrong party's.
  {
    const missing: string[] = [];
    if (!isPresent(input.sellerName)) missing.push('seller name');
    if (!isPresent(input.sellerGstin)) missing.push('GSTIN');
    if (!isPresent(input.invoiceNumber)) missing.push('invoice number');
    if (!isPresent(input.invoiceDate)) missing.push('invoice date');
    checks.push({
      id: 'vendor',
      label: 'Vendor details',
      status: missing.length === 0 ? 'pass' : 'fail',
      detail: missing.length === 0
        ? `${input.sellerName} · ${input.sellerGstin} · ${input.invoiceNumber}`
        : `Missing ${missing.join(', ')}.`,
    });
  }

  // ---- 5. Is the tax whole? ----
  //
  // A lone half is the specific failure worth catching: reading CGST but not
  // SGST halves the input tax credit, and the total still looks plausible.
  {
    const hasSplit = input.cgst !== null && input.sgst !== null;
    const hasIgst = input.igst !== null;
    if (!hasSplit && !hasIgst) {
      checks.push({
        id: 'tax',
        label: 'Tax',
        status: input.taxTotal ? 'warn' : 'fail',
        detail: 'No CGST/SGST or IGST captured for this invoice.',
      });
    } else if (hasSplit && Math.abs((input.cgst ?? 0) - (input.sgst ?? 0)) > 0.5) {
      checks.push({
        id: 'tax',
        label: 'Tax',
        status: 'fail',
        detail: `CGST ${money(input.cgst)} and SGST ${money(input.sgst)} should match on an intra-state bill.`,
      });
    } else {
      checks.push({
        id: 'tax',
        label: 'Tax',
        status: 'pass',
        detail: hasIgst && !hasSplit
          ? `IGST ${money(input.igst)} — inter-state.`
          : `CGST ${money(input.cgst)} + SGST ${money(input.sgst)} = ${money(input.taxTotal)}.`,
      });
    }
  }

  // ---- 6. Were the amounts read, or worked out? ----
  //
  // Not a fault — a derived amount is usually right — but it is the one class
  // of figure on the page that nobody has seen printed, so it is worth an
  // explicit look rather than being silently indistinguishable.
  if (input.derivedAmounts > 0) {
    checks.push({
      id: 'amount_source',
      label: 'Amounts',
      status: 'warn',
      detail: `${input.derivedAmounts} amount(s) were worked out from qty × rate, not read off the page.`,
    });
  } else if (input.itemCount > 0) {
    checks.push({
      id: 'amount_source',
      label: 'Amounts',
      status: 'pass',
      detail: 'Every amount was read from the invoice.',
    });
  }

  return checks;
}

/** Worst status present, for the one-line summary. */
export function overallCheckStatus(checks: InvoiceCheck[]): CheckStatus {
  if (checks.some((c) => c.status === 'fail')) return 'fail';
  if (checks.some((c) => c.status === 'warn')) return 'warn';
  if (checks.every((c) => c.status === 'unknown')) return 'unknown';
  return 'pass';
}

/**
 * Rupees of drift a nearest-rupee round-off can account for. Per-line rounding
 * across a long invoice, plus a final round to the rupee, lands inside a
 * rupee. Past that, the difference is not rounding and should not be dressed
 * up as it.
 */
const ROUNDING_LIMIT = 1.0;

/**
 * Steps suppliers round the payable to, coarsest first. Rounding the amount
 * due to a whole ₹5 or ₹10 is common on cash-counter pharma bills and is
 * almost never printed as a line — it just appears as a grand total that is
 * several rupees above what the figures above it come to.
 */
const COARSE_STEPS = [10, 5];

export type ImpliedAdjustmentKind = 'rounding' | 'coarse_rounding' | 'unexplained';

export interface ImpliedAdjustmentInput {
  subtotal: number | null;
  discount: number | null;
  taxTotal: number | null;
  /** The round-off currently recorded, whether printed or entered by a reviewer. */
  roundoff: number | null;
  /**
   * The round-off the invoice itself printed, when it printed one. Only affects
   * wording: a printed round-off that no longer reconciles is evidence that
   * something else on the page was misread, while one a reviewer entered is
   * merely stale. Optional, so callers that do not track provenance still get
   * the right arithmetic.
   */
  printedRoundoff?: number | null;
  grandTotal: number | null;
}

export interface ImpliedAdjustment {
  kind: ImpliedAdjustmentKind;
  /**
   * The round-off these figures need in order to reach the stated grand total.
   * This — not the leftover gap — is the number to put in the box, and the
   * distinction is the whole point: once any round-off is recorded, the
   * leftover gap is only the *error* in it, and offering that as the value to
   * record replaces a nearly-right figure with a badly wrong one.
   */
  requiredRoundoff: number;
  /** Stated total minus what the figures currently come to. */
  residual: number;
  /** What is in the round-off box right now, if anything. */
  recordedRoundoff: number | null;
  /** Subtotal − discount + tax + whatever round-off is recorded. */
  computedTotal: number;
  /** What the invoice itself says is payable. */
  statedTotal: number;
  /** The rounding step this is consistent with, when it is one. */
  step: number | null;
  /** True when a round-off is recorded but no longer reconciles. */
  isStale: boolean;
  /** Row label for the summary. */
  label: string;
  /** One line of interpretation, in the reviewer's language. */
  note: string;
}

const round2 = (value: number): number => parseFloat(value.toFixed(2));

/**
 * The gap between what an invoice's own figures come to and what it says is
 * payable.
 *
 * Suppliers routinely round the amount due and print no round-off line for it,
 * which leaves a grand total that reconciles with nothing on the page. Left
 * unexplained that reads as an extraction fault; stated plainly it is just a
 * fact about the invoice. Returns null when the figures already close, or when
 * there are not enough of them to ask the question.
 *
 * Deliberately does not decide that a large gap is a rounding. A difference
 * bigger than a rupee that does not land on a ₹5/₹10 step is reported as
 * unexplained, because presenting it as a round-off would launder a genuine
 * extraction error into a tidy-looking number.
 */
export function deriveImpliedAdjustment(input: ImpliedAdjustmentInput): ImpliedAdjustment | null {
  const { subtotal, grandTotal } = input;
  if (subtotal === null || grandTotal === null) return null;
  if (!Number.isFinite(subtotal) || !Number.isFinite(grandTotal)) return null;

  const recordedRoundoff = input.roundoff;
  const base = round2(subtotal - (input.discount ?? 0) + (input.taxTotal ?? 0));
  const computedTotal = round2(base + (recordedRoundoff ?? 0));
  const residual = round2(grandTotal - computedTotal);
  if (Math.abs(residual) < 0.005) return null;

  // Everything below is judged on the round-off the invoice NEEDS, not on how
  // far the current entry is from it. A recorded 3.81 against a required 3.61
  // is a 20-paise error in a legitimate ₹10 rounding — classifying on the 20
  // paise would call it an ordinary rupee round-off and lose the explanation.
  const requiredRoundoff = round2(grandTotal - base);
  const isStale = recordedRoundoff !== null;
  const wasPrinted =
    input.printedRoundoff !== null &&
    input.printedRoundoff !== undefined &&
    recordedRoundoff !== null &&
    Math.abs(input.printedRoundoff - recordedRoundoff) < 0.005;

  const shared = {
    requiredRoundoff,
    residual,
    recordedRoundoff,
    computedTotal,
    statedTotal: grandTotal,
    isStale,
  };

  const staleNote = wasPrinted
    ? `The invoice prints a round-off of ${money(recordedRoundoff)}, but these figures need ${money(requiredRoundoff)} to reach its ${money(grandTotal)}. Check the subtotal, discount and tax against the scan.`
    : `${money(recordedRoundoff)} is recorded, but these figures now need ${money(requiredRoundoff)} to reach the invoice's ${money(grandTotal)} — something above changed after the round-off was entered.`;

  const classify = (): { kind: ImpliedAdjustmentKind; step: number | null; freshNote: string } => {
    if (Math.abs(requiredRoundoff) <= ROUNDING_LIMIT) {
      return {
        kind: 'rounding',
        step: 1,
        freshNote:
          'Not printed on this invoice — implied by its own grand total, and small enough to be an ordinary round-off to the rupee.',
      };
    }
    const step = COARSE_STEPS.find(
      (candidate) =>
        Math.abs(grandTotal - Math.round(grandTotal / candidate) * candidate) < 0.005 &&
        Math.abs(requiredRoundoff) < candidate,
    );
    if (step) {
      return {
        kind: 'coarse_rounding',
        step,
        freshNote: `Not printed on this invoice. The grand total is an exact ₹${step} figure, so the supplier appears to have rounded the amount due to the nearest ₹${step}.`,
      };
    }
    return {
      kind: 'unexplained',
      step: null,
      freshNote:
        'Not printed on this invoice, and too large to be a round-off. Check the subtotal, discount and tax against the scan before verifying.',
    };
  };

  const { kind, step, freshNote } = classify();

  return {
    ...shared,
    kind,
    step,
    label: isStale
      ? 'Round Off needs updating'
      : kind === 'unexplained'
        ? 'Unexplained difference'
        : 'Round Off',
    note: isStale ? staleNote : freshNote,
  };
}
