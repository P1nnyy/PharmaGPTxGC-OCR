/**
 * The counter-sale tax engine.
 *
 * The shape the house rules require: tax is computed per line, summed per rate
 * block, and then reconciled to the document header. A mismatch between the
 * two is returned as an error, never quietly absorbed into a figure.
 *
 * Every value in and out is integer paise. Rates are integer basis points.
 * Nothing here touches a float except through `applyRatio`, which rounds
 * deterministically and is the single place rounding is allowed to happen at
 * line level. The document gets exactly one further rounding, into
 * `round_off_paise`.
 *
 * The other rule this module enforces structurally: a line whose rate or price
 * cannot be resolved computes to `null`, and one null line makes the whole
 * document null. A bill that cannot be priced correctly must not print a
 * plausible-looking total.
 */

import { applyRatio, roundToRupee } from './money';
import { RATE_TABLE, resolveRate, unresolvedRateReason } from './gstRates';
import type {
  ComputedLine,
  Discount,
  GstRateRow,
  PricingMode,
  RateBlock,
  SaleLineInput,
  SaleTotals
} from './types';

const BP_DENOMINATOR = 10000;

/** The discount in paise, given the gross the discount applies to. */
function discountPaise(discount: Discount, gross: number): number {
  switch (discount.kind) {
    case 'none':
      return 0;
    case 'percent':
      return applyRatio(gross, discount.value_bp, BP_DENOMINATOR);
    case 'flat':
      return discount.value_paise;
  }
}

/** An uncomputed line carrying the reason, so the UI can say why verbatim. */
function unresolved(input: SaleLineInput, reason: string): ComputedLine {
  return {
    line_id: input.line_id,
    hsn: input.hsn,
    rate: null,
    unresolved_reason: reason,
    gross_paise: null,
    discount_paise: null,
    taxable_paise: null,
    cgst_paise: null,
    sgst_paise: null,
    exempt_paise: null,
    line_total_paise: null
  };
}

/**
 * One line's figures.
 *
 * `onDate` is the document date, not today: the rate that applies is the one
 * in force when the supply was made.
 */
export function computeLine(
  input: SaleLineInput,
  onDate: string,
  mode: PricingMode,
  table: GstRateRow[] = RATE_TABLE
): ComputedLine {
  if (input.unit_price_paise === null || !Number.isFinite(input.unit_price_paise)) {
    return unresolved(input, 'No price on this line.');
  }
  if (!Number.isFinite(input.quantity) || input.quantity <= 0) {
    return unresolved(input, 'Quantity must be more than zero.');
  }

  const rate = resolveRate(input.hsn, onDate, table);
  if (rate === null) {
    return unresolved(input, unresolvedRateReason(input.hsn));
  }

  const gross = input.unit_price_paise * input.quantity;
  const discount = discountPaise(input.discount, gross);
  if (discount > gross) {
    return unresolved(input, 'Discount is larger than the line value.');
  }
  const net = gross - discount;

  // An exempt supply carries its whole value as exempt. It is not a taxable
  // line that happens to compute to zero tax, and Rule 46A needs the two
  // reported separately, so they never share a bucket here.
  if (rate.supply_kind === 'exempt') {
    return {
      line_id: input.line_id,
      hsn: input.hsn,
      rate,
      unresolved_reason: null,
      gross_paise: gross,
      discount_paise: discount,
      taxable_paise: 0,
      cgst_paise: 0,
      sgst_paise: 0,
      exempt_paise: net,
      line_total_paise: net
    };
  }

  // Inclusive pricing backs the taxable value out of the price; exclusive adds
  // the tax on top. Deriving the tax by subtraction in the inclusive case is
  // what guarantees the customer pays exactly the MRP - computing both figures
  // independently would leave a stray paisa on a third of all lines.
  let taxable: number;
  let tax: number;
  if (mode === 'inclusive') {
    taxable = applyRatio(net, BP_DENOMINATOR, BP_DENOMINATOR + rate.rate_bp);
    tax = net - taxable;
  } else {
    taxable = net;
    tax = applyRatio(net, rate.rate_bp, BP_DENOMINATOR);
  }

  // An intra-state supply is exactly half CGST and half SGST. The odd paisa
  // goes to SGST rather than being dropped, matching `pages/taxSplit.ts` so
  // that a sale and a purchase reviewed by hand break the same way.
  const cgst = Math.floor(tax / 2);
  const sgst = tax - cgst;

  return {
    line_id: input.line_id,
    hsn: input.hsn,
    rate,
    unresolved_reason: null,
    gross_paise: gross,
    discount_paise: discount,
    taxable_paise: taxable,
    cgst_paise: cgst,
    sgst_paise: sgst,
    exempt_paise: 0,
    line_total_paise: taxable + tax
  };
}

/** Groups computed lines into one block per rate, the way the bill prints. */
function toBlocks(lines: ComputedLine[]): RateBlock[] {
  const blocks = new Map<string, RateBlock>();
  for (const line of lines) {
    if (line.rate === null) continue;
    const key = `${line.rate.supply_kind}:${line.rate.rate_bp}`;
    const block = blocks.get(key) ?? {
      rate_bp: line.rate.rate_bp,
      supply_kind: line.rate.supply_kind,
      taxable_paise: 0,
      cgst_paise: 0,
      sgst_paise: 0,
      exempt_paise: 0
    };
    block.taxable_paise += line.taxable_paise ?? 0;
    block.cgst_paise += line.cgst_paise ?? 0;
    block.sgst_paise += line.sgst_paise ?? 0;
    block.exempt_paise += line.exempt_paise ?? 0;
    blocks.set(key, block);
  }
  // Exempt first, then ascending rate - the order a bill reads in.
  return [...blocks.values()].sort((a, b) => a.rate_bp - b.rate_bp);
}

/**
 * The whole document.
 *
 * Returns null figures - not zeroes - whenever any line is unresolved, so that
 * a partially-priced bill cannot be mistaken for a complete one.
 */
export function computeTotals(
  inputs: SaleLineInput[],
  onDate: string,
  mode: PricingMode,
  table: GstRateRow[] = RATE_TABLE
): SaleTotals {
  const computed = inputs.map((input) => computeLine(input, onDate, mode, table));
  const unresolvedIds = computed.filter((l) => l.unresolved_reason !== null).map((l) => l.line_id);
  const blocks = toBlocks(computed);

  if (unresolvedIds.length > 0) {
    return {
      blocks,
      taxable_paise: null,
      cgst_paise: null,
      sgst_paise: null,
      exempt_paise: null,
      round_off_paise: null,
      grand_total_paise: null,
      unresolved_line_ids: unresolvedIds,
      reconciliation_error: null
    };
  }

  const header = blocks.reduce(
    (acc, block) => ({
      taxable: acc.taxable + block.taxable_paise,
      cgst: acc.cgst + block.cgst_paise,
      sgst: acc.sgst + block.sgst_paise,
      exempt: acc.exempt + block.exempt_paise
    }),
    { taxable: 0, cgst: 0, sgst: 0, exempt: 0 }
  );

  // The reconciliation the house rules ask for: the blocks are a regrouping of
  // the lines, so their sums must equal the lines' own sums exactly. If they
  // ever diverge, something upstream is wrong and the figure is not to be
  // trusted - so it is reported rather than rendered.
  const fromLines = computed.reduce(
    (acc, line) => ({
      taxable: acc.taxable + (line.taxable_paise ?? 0),
      cgst: acc.cgst + (line.cgst_paise ?? 0),
      sgst: acc.sgst + (line.sgst_paise ?? 0),
      exempt: acc.exempt + (line.exempt_paise ?? 0)
    }),
    { taxable: 0, cgst: 0, sgst: 0, exempt: 0 }
  );

  const mismatches: string[] = [];
  if (fromLines.taxable !== header.taxable) mismatches.push('taxable value');
  if (fromLines.cgst !== header.cgst) mismatches.push('CGST');
  if (fromLines.sgst !== header.sgst) mismatches.push('SGST');
  if (fromLines.exempt !== header.exempt) mismatches.push('exempt value');

  if (mismatches.length > 0) {
    return {
      blocks,
      taxable_paise: null,
      cgst_paise: null,
      sgst_paise: null,
      exempt_paise: null,
      round_off_paise: null,
      grand_total_paise: null,
      unresolved_line_ids: [],
      reconciliation_error: `Rate-block totals do not reconcile to the bill: ${mismatches.join(', ')}.`
    };
  }

  // The document's one and only rounding.
  const beforeRounding = header.taxable + header.cgst + header.sgst + header.exempt;
  const { rounded_paise, round_off_paise } = roundToRupee(beforeRounding);

  return {
    blocks,
    taxable_paise: header.taxable,
    cgst_paise: header.cgst,
    sgst_paise: header.sgst,
    exempt_paise: header.exempt,
    round_off_paise,
    grand_total_paise: rounded_paise,
    unresolved_line_ids: [],
    reconciliation_error: null
  };
}
