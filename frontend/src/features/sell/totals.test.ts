/**
 * Tests for the counter-sale tax engine.
 *
 * Written before the engine, per the house rule on anything computing a tax
 * figure. Every rate used here is a FIXTURE declared in this file - the real
 * rate table ships empty on purpose, and these tests must not be read as a
 * statement about what any HSN actually carries.
 */

import { describe, expect, it } from 'vitest';

import { computeLine, computeTotals } from './totals';
import type { GstRateRow, SaleLineInput } from './types';

/** Fixture rates. Not real tax advice; shapes the arithmetic only. */
const FIXTURES: GstRateRow[] = [
  { hsn: 'TEST12', supply_kind: 'taxable', rate_bp: 1200, effective_from: '2020-01-01', effective_to: null, source: 'fixture' },
  { hsn: 'TEST05', supply_kind: 'taxable', rate_bp: 500, effective_from: '2020-01-01', effective_to: null, source: 'fixture' },
  { hsn: 'TESTEX', supply_kind: 'exempt', rate_bp: 0, effective_from: '2020-01-01', effective_to: null, source: 'fixture' },
  // A rate that changed, to prove resolution is dated.
  { hsn: 'TESTCH', supply_kind: 'taxable', rate_bp: 1800, effective_from: '2020-01-01', effective_to: '2022-03-31', source: 'fixture' },
  { hsn: 'TESTCH', supply_kind: 'taxable', rate_bp: 1200, effective_from: '2022-04-01', effective_to: null, source: 'fixture' }
];

const line = (over: Partial<SaleLineInput> = {}): SaleLineInput => ({
  line_id: 'l1',
  product_id: 'p1',
  product_name: 'Test Product',
  hsn: 'TEST12',
  batch_id: 'b1',
  batch_number: 'B1',
  expiry: '2027-12-31',
  quantity: 1,
  unit_price_paise: 11200,
  discount: { kind: 'none' },
  scanned_code_raw: null,
  scanned_code_format: null,
  ...over
});

const DATE = '2026-09-10';

describe('computeLine — exclusive pricing', () => {
  it('adds tax on top of the price', () => {
    const result = computeLine(
      line({ quantity: 2, unit_price_paise: 10000 }),
      DATE, 'exclusive', FIXTURES
    );
    expect(result.taxable_paise).toBe(20000);
    expect(result.cgst_paise).toBe(1200);
    expect(result.sgst_paise).toBe(1200);
    expect(result.line_total_paise).toBe(22400);
  });
});

describe('computeLine — inclusive pricing', () => {
  it('backs the taxable value out of an MRP that already contains the tax', () => {
    const result = computeLine(
      line({ quantity: 1, unit_price_paise: 11200 }),
      DATE, 'inclusive', FIXTURES
    );
    expect(result.taxable_paise).toBe(10000);
    expect(result.cgst_paise).toBe(600);
    expect(result.sgst_paise).toBe(600);
    // The whole point of inclusive pricing: the customer pays the MRP.
    expect(result.line_total_paise).toBe(11200);
  });

  it('never charges more than the MRP, whatever the rounding does', () => {
    // 99.99 at 12% does not divide cleanly; the line total must still be
    // exactly what is printed on the pack.
    const result = computeLine(
      line({ quantity: 3, unit_price_paise: 9999 }),
      DATE, 'inclusive', FIXTURES
    );
    expect(result.line_total_paise).toBe(29997);
    expect(result.taxable_paise! + result.cgst_paise! + result.sgst_paise!).toBe(29997);
  });
});

describe('computeLine — the CGST/SGST halves', () => {
  it('splits an odd paisa without losing it', () => {
    // Chosen so total tax is odd and cannot halve evenly.
    const result = computeLine(
      line({ hsn: 'TEST05', quantity: 1, unit_price_paise: 12345 }),
      DATE, 'exclusive', FIXTURES
    );
    const tax = result.cgst_paise! + result.sgst_paise!;
    expect(tax).toBe(617); // 12345 * 5% = 617.25, half-up on the line
    // Halves differ by at most a paisa, and the odd one goes to SGST.
    expect(result.sgst_paise! - result.cgst_paise!).toBe(1);
    expect(result.cgst_paise).toBe(308);
    expect(result.sgst_paise).toBe(309);
  });
});

describe('computeLine — discounts', () => {
  it('reduces the taxable value, not the tax directly', () => {
    const result = computeLine(
      line({ quantity: 1, unit_price_paise: 20000, discount: { kind: 'percent', value_bp: 1000 } }),
      DATE, 'exclusive', FIXTURES
    );
    expect(result.discount_paise).toBe(2000);
    expect(result.taxable_paise).toBe(18000);
    expect(result.cgst_paise).toBe(1080);
    expect(result.sgst_paise).toBe(1080);
  });

  it('applies a flat discount in paise', () => {
    const result = computeLine(
      line({ quantity: 1, unit_price_paise: 20000, discount: { kind: 'flat', value_paise: 2500 } }),
      DATE, 'exclusive', FIXTURES
    );
    expect(result.taxable_paise).toBe(17500);
  });
});

describe('computeLine — exempt supply', () => {
  it('carries the value as exempt and charges no tax', () => {
    const result = computeLine(
      line({ hsn: 'TESTEX', quantity: 2, unit_price_paise: 5000 }),
      DATE, 'inclusive', FIXTURES
    );
    expect(result.exempt_paise).toBe(10000);
    expect(result.taxable_paise).toBe(0);
    expect(result.cgst_paise).toBe(0);
    expect(result.sgst_paise).toBe(0);
    expect(result.line_total_paise).toBe(10000);
  });
});

describe('computeLine — rates are resolved against the document date', () => {
  it('uses the rate in force on the bill date, not the newest row', () => {
    const before = computeLine(line({ hsn: 'TESTCH' }), '2021-06-01', 'exclusive', FIXTURES);
    const after = computeLine(line({ hsn: 'TESTCH' }), '2023-06-01', 'exclusive', FIXTURES);
    expect(before.rate!.rate_bp).toBe(1800);
    expect(after.rate!.rate_bp).toBe(1200);
  });
});

describe('computeLine — an unresolvable rate', () => {
  it('computes nothing rather than assuming zero', () => {
    const result = computeLine(line({ hsn: 'NOT_IN_TABLE' }), DATE, 'exclusive', FIXTURES);
    expect(result.rate).toBeNull();
    expect(result.taxable_paise).toBeNull();
    expect(result.cgst_paise).toBeNull();
    expect(result.line_total_paise).toBeNull();
    expect(result.unresolved_reason).toBeTruthy();
  });

  it('treats a missing HSN the same way', () => {
    const result = computeLine(line({ hsn: null }), DATE, 'exclusive', FIXTURES);
    expect(result.taxable_paise).toBeNull();
  });

  it('treats a missing price the same way', () => {
    const result = computeLine(line({ unit_price_paise: null }), DATE, 'exclusive', FIXTURES);
    expect(result.taxable_paise).toBeNull();
    expect(result.unresolved_reason).toMatch(/price/i);
  });
});

describe('computeTotals — rate blocks', () => {
  it('groups lines into one block per rate and sums each', () => {
    const totals = computeTotals(
      [
        line({ line_id: 'a', hsn: 'TEST12', quantity: 1, unit_price_paise: 10000 }),
        line({ line_id: 'b', hsn: 'TEST12', quantity: 1, unit_price_paise: 20000 }),
        line({ line_id: 'c', hsn: 'TEST05', quantity: 1, unit_price_paise: 10000 })
      ],
      DATE, 'exclusive', FIXTURES
    );
    expect(totals.blocks).toHaveLength(2);
    const twelve = totals.blocks.find((b) => b.rate_bp === 1200)!;
    expect(twelve.taxable_paise).toBe(30000);
    expect(twelve.cgst_paise).toBe(1800);
    const five = totals.blocks.find((b) => b.rate_bp === 500)!;
    expect(five.taxable_paise).toBe(10000);
    expect(five.cgst_paise).toBe(250);
  });

  it('reconciles the header to the sum of the blocks', () => {
    const totals = computeTotals(
      [
        line({ line_id: 'a', hsn: 'TEST12', quantity: 3, unit_price_paise: 13337 }),
        line({ line_id: 'b', hsn: 'TEST05', quantity: 7, unit_price_paise: 4321 })
      ],
      DATE, 'exclusive', FIXTURES
    );
    expect(totals.reconciliation_error).toBeNull();
    const blockTaxable = totals.blocks.reduce((s, b) => s + b.taxable_paise, 0);
    expect(totals.taxable_paise).toBe(blockTaxable);
  });
});

describe('computeTotals — Rule 46A mixed supply', () => {
  it('keeps the exempt value out of the taxable value', () => {
    const totals = computeTotals(
      [
        line({ line_id: 'a', hsn: 'TEST12', quantity: 1, unit_price_paise: 10000 }),
        line({ line_id: 'b', hsn: 'TESTEX', quantity: 1, unit_price_paise: 7000 })
      ],
      DATE, 'exclusive', FIXTURES
    );
    expect(totals.taxable_paise).toBe(10000);
    expect(totals.exempt_paise).toBe(7000);
    expect(totals.cgst_paise).toBe(600);
    // Grand total covers both halves of the document.
    expect(totals.grand_total_paise).toBe(18200);
  });
});

describe('computeTotals — rounding', () => {
  it('rounds once, at the document, into round_off_paise', () => {
    const totals = computeTotals(
      [line({ hsn: 'TEST05', quantity: 1, unit_price_paise: 12345 })],
      DATE, 'exclusive', FIXTURES
    );
    // 12345 taxable + 617 tax = 12962, which rounds up to 13000.
    expect(totals.taxable_paise).toBe(12345);
    expect(totals.round_off_paise).toBe(38);
    expect(totals.grand_total_paise).toBe(13000);
    // The rounding must not have been folded into the taxable value.
    expect(totals.taxable_paise! + totals.cgst_paise! + totals.sgst_paise! + totals.round_off_paise!)
      .toBe(totals.grand_total_paise);
  });

  it('always lands on a whole rupee', () => {
    const totals = computeTotals(
      [
        line({ line_id: 'a', hsn: 'TEST12', quantity: 3, unit_price_paise: 9991 }),
        line({ line_id: 'b', hsn: 'TEST05', quantity: 2, unit_price_paise: 3337 })
      ],
      DATE, 'exclusive', FIXTURES
    );
    expect(totals.grand_total_paise! % 100).toBe(0);
    expect(Math.abs(totals.round_off_paise!)).toBeLessThanOrEqual(50);
  });
});

describe('computeTotals — an unresolved line poisons the document', () => {
  it('reports no totals at all rather than a partial figure', () => {
    const totals = computeTotals(
      [
        line({ line_id: 'good', hsn: 'TEST12' }),
        line({ line_id: 'bad', hsn: 'NOT_IN_TABLE' })
      ],
      DATE, 'exclusive', FIXTURES
    );
    expect(totals.unresolved_line_ids).toEqual(['bad']);
    expect(totals.grand_total_paise).toBeNull();
    expect(totals.taxable_paise).toBeNull();
  });
});

describe('computeTotals — an empty bill', () => {
  it('is zero rather than unresolved', () => {
    const totals = computeTotals([], DATE, 'exclusive', FIXTURES);
    expect(totals.grand_total_paise).toBe(0);
    expect(totals.unresolved_line_ids).toEqual([]);
    expect(totals.reconciliation_error).toBeNull();
  });
});
