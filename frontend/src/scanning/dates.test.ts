import { describe, expect, it } from 'vitest';

import { parseGs1Date } from './dates';

/**
 * GS1 dates are YYMMDD. Two things about them matter here and both are house
 * rules as much as GS1 rules: a day of `00` means "no day given", which for an
 * expiry means the last day of that month; and the century has to be inferred.
 */
describe('parseGs1Date', () => {
  const TODAY = new Date('2026-09-10T00:00:00Z');

  it('reads a full date', () => {
    expect(parseGs1Date('261231', TODAY)).toBe('2026-12-31');
  });

  it('treats a day of 00 as the last day of that month', () => {
    // The house rule: a pack marked 12/26 is good through the whole of
    // December, and resolving to the 1st would write stock off 30 days early.
    expect(parseGs1Date('261200', TODAY)).toBe('2026-12-31');
  });

  it('gets February right in a leap year', () => {
    expect(parseGs1Date('280200', TODAY)).toBe('2028-02-29');
    expect(parseGs1Date('260200', TODAY)).toBe('2026-02-28');
  });

  it('reads a near-future year as this century', () => {
    expect(parseGs1Date('300101', TODAY)).toBe('2030-01-01');
  });

  it('reads a year far in the future as the previous century', () => {
    // GS1's sliding window: 51+ years ahead is the past, not the future.
    // A pack cannot expire in 2085; that code means 1985.
    expect(parseGs1Date('850101', TODAY)).toBe('1985-01-01');
  });

  it('reads a year far in the past as the next century', () => {
    expect(parseGs1Date('750101', new Date('2060-01-01T00:00:00Z'))).toBe('2075-01-01');
  });

  it('refuses a month outside 1-12', () => {
    expect(parseGs1Date('261301', TODAY)).toBeNull();
    expect(parseGs1Date('260001', TODAY)).toBeNull();
  });

  it('refuses a day that month does not have', () => {
    expect(parseGs1Date('260231', TODAY)).toBeNull();
    expect(parseGs1Date('260431', TODAY)).toBeNull();
  });

  it('refuses anything that is not six digits', () => {
    for (const bad of ['', '2612', '2612311', 'abcdef', '26-12-31', '26123a']) {
      expect(parseGs1Date(bad, TODAY)).toBeNull();
    }
  });
});
