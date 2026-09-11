import { describe, expect, it } from 'vitest';

import { parseGs1ElementString } from './gs1';

const GS = '\x1D';

describe('parseGs1ElementString — parenthesised form', () => {
  it('reads the four AIs a drug pack carries', () => {
    const result = parseGs1ElementString('(01)08901234567890(17)271130(10)AB1234(21)000000001');
    expect(result).not.toBeNull();
    expect(result!.ais['01']).toBe('08901234567890');
    expect(result!.ais['17']).toBe('271130');
    expect(result!.ais['10']).toBe('AB1234');
    expect(result!.ais['21']).toBe('000000001');
  });

  it('tolerates whitespace between elements', () => {
    const result = parseGs1ElementString('(01)08901234567890 (10)AB1234');
    expect(result!.ais['10']).toBe('AB1234');
  });

  it('records an AI it does not know rather than discarding it', () => {
    // Manufacturers add their own AIs. Dropping one silently loses data the
    // user can still see on the pack.
    const result = parseGs1ElementString('(01)08901234567890(91)VENDORDATA');
    expect(result!.ais['91']).toBe('VENDORDATA');
  });
});

describe('parseGs1ElementString — FNC1 delimited form', () => {
  it('terminates a fixed-length AI without needing a separator', () => {
    // 01 is 14 digits and 17 is 6, so neither needs a GS after it.
    const result = parseGs1ElementString('010890123456789017271130');
    expect(result!.ais['01']).toBe('08901234567890');
    expect(result!.ais['17']).toBe('271130');
  });

  it('runs a variable-length AI to the separator', () => {
    const raw = `010890123456789017271130` + `10AB1234` + GS + `21000000001`;
    const result = parseGs1ElementString(raw);
    expect(result!.ais['10']).toBe('AB1234');
    expect(result!.ais['21']).toBe('000000001');
  });

  it('runs a trailing variable-length AI to the end of the payload', () => {
    const result = parseGs1ElementString('010890123456789010AB1234');
    expect(result!.ais['10']).toBe('AB1234');
  });

  it('strips a symbology identifier prefix', () => {
    // ]d2 is DataMatrix, ]C1 GS1-128, ]Q3 QR, ]e0 DataBar. Scanners emit them.
    for (const prefix of [']d2', ']C1', ']Q3', ']e0']) {
      const result = parseGs1ElementString(`${prefix}010890123456789017271130`);
      expect(result!.ais['01']).toBe('08901234567890');
    }
  });

  it('tolerates a leading FNC1 separator', () => {
    const result = parseGs1ElementString(`${GS}010890123456789017271130`);
    expect(result!.ais['01']).toBe('08901234567890');
  });

  it('reads a four-digit AI', () => {
    // 7003 is expiry to the hour: 10 characters, fixed.
    const result = parseGs1ElementString('01089012345678907003' + '2611301200');
    expect(result!.ais['7003']).toBe('2611301200');
  });
});

describe('parseGs1ElementString — refusals', () => {
  it('returns null for something that is not a GS1 string', () => {
    for (const bad of ['', '   ', 'HELLO WORLD', 'https://example.com', '{"a":1}']) {
      expect(parseGs1ElementString(bad)).toBeNull();
    }
  });

  it('returns null when a plain EAN-13 is offered', () => {
    // 13 digits is not an element string, and reading it as AI 89 plus data
    // would invent fields that are not there.
    expect(parseGs1ElementString('8901234567890')).toBeNull();
  });

  it('stops at a fixed-length AI whose data is truncated', () => {
    // The payload claims a 14-digit GTIN and supplies eight. Anything read
    // after that point would be misaligned, so nothing is.
    const result = parseGs1ElementString('0108901234');
    expect(result).toBeNull();
  });

  it('stops cleanly when an unreadable AI follows good data', () => {
    // The GTIN was read correctly before the payload became unparseable; it
    // is kept, and the leftover is reported rather than guessed at.
    const result = parseGs1ElementString('0108901234567890' + 'XX' + 'garbage');
    expect(result!.ais['01']).toBe('08901234567890');
    expect(result!.unparsed).toContain('XX');
  });

  it('does not loop forever on an empty variable-length field', () => {
    const result = parseGs1ElementString(`0108901234567890` + `10` + GS + `21ABC`);
    expect(result!.ais['10']).toBe('');
    expect(result!.ais['21']).toBe('ABC');
  });
});
