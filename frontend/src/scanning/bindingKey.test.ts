import { describe, expect, it } from 'vitest';

import { bindingKeyFor, lookupCandidates } from './bindingKey';
import { parseDrugCode } from './parseDrugCode';

const GTIN14 = '08901234567890';
const TODAY = new Date('2026-09-10T00:00:00Z');

describe('bindingKeyFor', () => {
  it('binds a GS1 pack under its GTIN, not the whole payload', () => {
    // The payload holds the batch and serial, so it is unique to one box.
    // Binding it would mean the next box of the same medicine is unrecognised
    // all over again.
    const parsed = parseDrugCode(`(01)${GTIN14}(17)271130(10)AB1234(21)0001`, TODAY);
    const key = bindingKeyFor(parsed);
    expect(key.value).toBe(GTIN14);
    expect(key.type).toBe('gtin');
    expect(key.stable).toBe(true);
  });

  it('binds a plain EAN under its GTIN', () => {
    const key = bindingKeyFor(parseDrugCode('8901234567890', TODAY));
    expect(key.value).toBe(GTIN14);
    expect(key.stable).toBe(true);
  });

  it('falls back to the raw payload when there is no GTIN', () => {
    const parsed = parseDrugCode('SHELF-LABEL-123', TODAY);
    const key = bindingKeyFor(parsed, 'code_128');
    expect(key.value).toBe('SHELF-LABEL-123');
    expect(key.type).toBe('raw:code_128');
    expect(key.stable).toBe(true);
  });

  it('says a batch-bearing payload with no GTIN will not repeat', () => {
    // Honest rather than optimistic: binding this cannot help the next pack,
    // and the UI should not promise that it will.
    const parsed = parseDrugCode(JSON.stringify({ batch: 'AB1234' }), TODAY);
    const key = bindingKeyFor(parsed);
    expect(key.stable).toBe(false);
  });
});

describe('lookupCandidates', () => {
  it('tries the GTIN before the raw payload', () => {
    const parsed = parseDrugCode(`(01)${GTIN14}(10)AB1234`, TODAY);
    expect(lookupCandidates(parsed)).toEqual([GTIN14, parsed.raw]);
  });

  it('does not ask for the same value twice', () => {
    expect(lookupCandidates(parseDrugCode(GTIN14, TODAY))).toEqual([GTIN14]);
  });

  it('falls back to the raw payload alone', () => {
    expect(lookupCandidates(parseDrugCode('MYSTERY', TODAY))).toEqual(['MYSTERY']);
  });
});
