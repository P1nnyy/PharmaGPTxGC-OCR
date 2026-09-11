import { describe, expect, it } from 'vitest';

import { byFefo, daysToExpiry, defaultBatch, expiryStanding } from './batches';
import type { SellableBatch } from './types';

const TODAY = '2026-09-10';

const batch = (over: Partial<SellableBatch> = {}): SellableBatch => ({
  batch_id: 'b1',
  batch_number: 'B1',
  expiry: '2027-01-31',
  quantity_available: 10,
  mrp_paise: 10000,
  source_invoice: 'INV-1',
  ...over
});

describe('daysToExpiry', () => {
  it('counts whole days forward', () => {
    expect(daysToExpiry('2026-09-20', TODAY)).toBe(10);
  });

  it('goes negative once the date has passed', () => {
    expect(daysToExpiry('2026-09-01', TODAY)).toBe(-9);
  });

  it('is null for an unreadable expiry', () => {
    expect(daysToExpiry(null, TODAY)).toBeNull();
    expect(daysToExpiry('not-a-date', TODAY)).toBeNull();
  });
});

describe('expiryStanding', () => {
  it('flags a batch inside the 90-day window as near', () => {
    expect(expiryStanding('2026-11-01', TODAY)).toBe('near');
  });

  it('leaves a batch beyond the window alone', () => {
    expect(expiryStanding('2027-06-30', TODAY)).toBe('ok');
  });

  it('calls a past date expired', () => {
    expect(expiryStanding('2026-08-31', TODAY)).toBe('expired');
  });

  it('never calls an unreadable expiry ok', () => {
    expect(expiryStanding(null, TODAY)).toBe('unknown');
  });
});

describe('byFefo', () => {
  it('puts the soonest expiry first', () => {
    const sorted = byFefo([
      batch({ batch_id: 'late', expiry: '2028-01-31' }),
      batch({ batch_id: 'soon', expiry: '2026-10-31' }),
      batch({ batch_id: 'mid', expiry: '2027-05-31' })
    ]);
    expect(sorted.map((b) => b.batch_id)).toEqual(['soon', 'mid', 'late']);
  });

  it('sorts an unknown expiry last, not first', () => {
    const sorted = byFefo([
      batch({ batch_id: 'unknown', expiry: null }),
      batch({ batch_id: 'dated', expiry: '2027-05-31' })
    ]);
    expect(sorted.map((b) => b.batch_id)).toEqual(['dated', 'unknown']);
  });
});

describe('defaultBatch', () => {
  it('picks the soonest-expiring batch that is still sellable', () => {
    const chosen = defaultBatch(
      [
        batch({ batch_id: 'later', expiry: '2027-12-31' }),
        batch({ batch_id: 'sooner', expiry: '2026-11-30' })
      ],
      TODAY
    );
    expect(chosen!.batch_id).toBe('sooner');
  });

  it('never auto-selects an expired batch', () => {
    const chosen = defaultBatch(
      [
        batch({ batch_id: 'expired', expiry: '2026-01-31' }),
        batch({ batch_id: 'good', expiry: '2027-12-31' })
      ],
      TODAY
    );
    expect(chosen!.batch_id).toBe('good');
  });

  it('skips a batch with nothing left', () => {
    const chosen = defaultBatch(
      [
        batch({ batch_id: 'empty', expiry: '2026-11-30', quantity_available: 0 }),
        batch({ batch_id: 'stocked', expiry: '2027-12-31' })
      ],
      TODAY
    );
    expect(chosen!.batch_id).toBe('stocked');
  });

  it('returns null rather than something unsuitable', () => {
    expect(defaultBatch([batch({ expiry: '2020-01-31' })], TODAY)).toBeNull();
    expect(defaultBatch([], TODAY)).toBeNull();
  });
});
