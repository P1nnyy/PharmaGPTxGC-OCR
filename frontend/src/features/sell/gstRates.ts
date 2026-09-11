/**
 * The effective-dated GST rate table, and resolving a rate against a date.
 *
 * House rule: "GST rates are never hardcoded. They come from an effective-dated
 * rate table and are resolved against the document date." Two consequences the
 * rest of this feature is built around:
 *
 *  1. `RATE_TABLE` below ships EMPTY. Nobody on this side of the wire knows
 *     what rate an HSN carries, and inventing one - even a rate that happens
 *     to be right today - would put an unsourced figure onto a filed return.
 *     It is seeded from the GSTN master; see `docs` note at the bottom.
 *
 *  2. An HSN with no row for the bill's date resolves to `null`, not to zero
 *     and not to a guess. A null rate makes the line uncomputable, which makes
 *     the bill unissuable. That is the intended behaviour: a counter that
 *     cannot price a line correctly must not print a bill for it.
 *
 * Rates are dated because they change. Resolving against the *document* date
 * rather than today is what stops a rate revision silently rewriting the tax
 * on a bill that was issued before it.
 */

import type { GstRateRow, ResolvedRate } from './types';

/**
 * The rate table.
 *
 * EMPTY BY DESIGN - see the module note. Seed it from the GSTN master list
 * with rows like:
 *
 *   { hsn: '3004', supply_kind: 'taxable', rate_bp: 1200,
 *     effective_from: '2017-07-01', effective_to: null, source: 'GSTN 2017 Sch II' }
 *
 * Add rows; do not edit or delete them. A rate that changed gets a new row and
 * an `effective_to` on the old one, so a bill issued last year still resolves
 * to the rate it was actually charged at.
 */
export const RATE_TABLE: GstRateRow[] = [];

/** ISO date comparison. Dates are stored `YYYY-MM-DD`, so string order is
 *  chronological order and there is no parsing to get wrong. */
const onOrBefore = (a: string, b: string): boolean => a <= b;

/**
 * The rate in force for an HSN on a date, or null when nothing covers it.
 *
 * When more than one row matches - which should not happen in a well-formed
 * table, but can while it is being seeded - the latest `effective_from` wins,
 * since that is the most recent statement about that HSN.
 */
export function resolveRate(
  hsn: string | null | undefined,
  onDate: string,
  table: GstRateRow[] = RATE_TABLE
): ResolvedRate | null {
  const code = (hsn ?? '').trim();
  if (!code) return null;

  const candidates = table.filter(
    (row) =>
      row.hsn === code &&
      onOrBefore(row.effective_from, onDate) &&
      (row.effective_to === null || onOrBefore(onDate, row.effective_to))
  );
  if (candidates.length === 0) return null;

  const winner = candidates.reduce((best, row) =>
    row.effective_from > best.effective_from ? row : best
  );

  return {
    hsn: winner.hsn,
    supply_kind: winner.supply_kind,
    rate_bp: winner.rate_bp,
    source: winner.source,
    effective_from: winner.effective_from
  };
}

/** Why a line has no rate, phrased for the counter operator rather than for a
 *  developer. The operator's next action differs by case, so the cases differ. */
export function unresolvedRateReason(hsn: string | null | undefined): string {
  const code = (hsn ?? '').trim();
  if (!code) return 'No HSN on this product — set one in the catalogue before selling it.';
  if (RATE_TABLE.length === 0) return 'GST rate table is not configured yet.';
  return `No GST rate on file for HSN ${code} on this date.`;
}

/** True when the table has usable rows at all. The screen uses this to explain
 *  itself once at the top rather than repeating the reason on every line. */
export const isRateTableConfigured = (table: GstRateRow[] = RATE_TABLE): boolean =>
  table.length > 0;
