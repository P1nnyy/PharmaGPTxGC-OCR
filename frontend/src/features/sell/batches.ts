/**
 * Choosing which batch to sell, and how near its expiry is.
 *
 * FEFO - first expiry, first out - is the default because it is what a
 * pharmacy actually does: the pack that dies soonest leaves first, or it stops
 * being stock and becomes a write-off. A write-off is not merely lost margin.
 * Input tax credit was claimed on that stock when it was bought, and stock
 * written off has to have that credit reversed under s.17(5)(h). Selling a
 * short-dated batch before it expires is what avoids the reversal, which is
 * why the near-expiry warning is worth a colour and a sentence of explanation
 * on the line rather than being left to the operator to remember.
 */

import type { SellableBatch } from './types';

/**
 * The warning horizon.
 *
 * Distinct from the 180 days `inventory_repository.EXPIRING_WITHIN_DAYS` uses,
 * and deliberately so: that figure answers "can this still be returned to the
 * wholesaler", this one answers "can this still realistically be sold across
 * the counter". Same data, different decisions, so they are different numbers
 * rather than one number doing two jobs badly.
 */
export const NEAR_EXPIRY_DAYS = 90;

export type ExpiryStanding = 'expired' | 'near' | 'ok' | 'unknown';

/** Whole days from `today` to `expiry`. Negative once it has passed. */
export function daysToExpiry(expiry: string | null, today: string): number | null {
  if (!expiry) return null;
  const end = Date.parse(`${expiry.slice(0, 10)}T00:00:00Z`);
  const start = Date.parse(`${today.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(end) || Number.isNaN(start)) return null;
  return Math.round((end - start) / 86_400_000);
}

/**
 * How a batch stands against the calendar.
 *
 * An unreadable expiry is `unknown`, never `ok`: defaulting it to fine would
 * let an expired pack be sold without anyone being asked.
 */
export function expiryStanding(expiry: string | null, today: string): ExpiryStanding {
  const days = daysToExpiry(expiry, today);
  if (days === null) return 'unknown';
  if (days < 0) return 'expired';
  if (days <= NEAR_EXPIRY_DAYS) return 'near';
  return 'ok';
}

/** The sentence shown against a short-dated batch. Explains the consequence
 *  rather than just flagging the date, because the consequence is the reason
 *  the operator should pick this batch first. */
export function nearExpiryExplanation(days: number): string {
  return `Expires in ${days} day${days === 1 ? '' : 's'}. Sell this batch before it expires — stock written off after expiry means the input tax credit claimed on it has to be reversed.`;
}

/**
 * FEFO order: soonest expiry first.
 *
 * Batches with no readable expiry sort last rather than first. Sorting them
 * first would have the counter default to the one batch nobody can vouch for.
 */
export function byFefo(batches: SellableBatch[]): SellableBatch[] {
  return [...batches].sort((a, b) => {
    if (a.expiry === b.expiry) return (a.batch_number ?? '').localeCompare(b.batch_number ?? '');
    if (!a.expiry) return 1;
    if (!b.expiry) return -1;
    return a.expiry < b.expiry ? -1 : 1;
  });
}

/**
 * The batch the counter should reach for.
 *
 * Expired batches are never chosen automatically - selling one is a decision
 * someone has to make explicitly - and neither is a batch with nothing left.
 * Returns null when nothing qualifies, which the screen shows as "no sellable
 * batch" rather than quietly selecting something unsuitable.
 */
export function defaultBatch(batches: SellableBatch[], today: string): SellableBatch | null {
  const sellable = byFefo(batches).filter(
    (batch) => batch.quantity_available > 0 && expiryStanding(batch.expiry, today) !== 'expired'
  );
  return sellable[0] ?? null;
}
