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
      detail: hit
        ? `${input.itemCount} rows total ${money(input.lineTotal)}, matching ${hit.label}.`
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
    checks.push({
      id: 'totals_vs_grand',
      label: 'Totals',
      status: Math.abs(gap) <= TOLERANCE ? 'pass' : 'fail',
      detail: Math.abs(gap) <= TOLERANCE
        ? `${money(input.subtotal)} − ${money(input.discount ?? 0)} + ${money(input.taxTotal ?? 0)} = ${money(input.grandTotal)}.`
        : `Subtotal, discount and tax come to ${money(expected)}, but the grand total says ${money(input.grandTotal)} — off by ${money(Math.abs(gap))}.`,
    });
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
