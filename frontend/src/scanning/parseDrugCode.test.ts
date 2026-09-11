/**
 * `parseDrugCode` covers every payload form a scanned Indian drug pack has
 * been seen to carry.
 *
 * The Schedule H2 mandate says what information the code must hold — unique
 * product identification code, generic and brand name, manufacturer name and
 * address, batch, manufacturing and expiry dates, licence number — but leaves
 * the *format* to each manufacturer's own SOP. So there is no single layout to
 * parse, and the only safe design is to recognise several and be honest when
 * none of them fits.
 *
 * Two invariants run through all of these: the raw payload always survives
 * untouched, and a field that could not be read is null rather than guessed.
 */

import { describe, expect, it } from 'vitest';

import { parseDrugCode } from './parseDrugCode';

const GS = '\x1D';
const TODAY = new Date('2026-09-10T00:00:00Z');
// 8901234567890 is a real EAN-13 check digit; 08901234567890 is it as a GTIN-14.
const EAN13 = '8901234567890';
const GTIN14 = '08901234567890';

describe('a. GS1 Application Identifier strings', () => {
  it('reads a parenthesised pack code', () => {
    const result = parseDrugCode(`(01)${GTIN14}(17)271130(10)AB1234(21)000000001`, TODAY);
    expect(result.format).toBe('gs1');
    expect(result.confidence).toBe('high');
    expect(result.gtin).toBe(GTIN14);
    expect(result.batch).toBe('AB1234');
    expect(result.serial).toBe('000000001');
    expect(result.expiry).toBe('2027-11-30');
  });

  it('reads an FNC1-delimited pack code', () => {
    const raw = `01${GTIN14}17271130` + `10AB1234` + GS + `21000000001`;
    const result = parseDrugCode(raw, TODAY);
    expect(result.format).toBe('gs1');
    expect(result.gtin).toBe(GTIN14);
    expect(result.batch).toBe('AB1234');
    expect(result.expiry).toBe('2027-11-30');
  });

  it('resolves a day-less expiry to the last day of the month', () => {
    // The house rule. 11/27 on the pack is good through all of November.
    const result = parseDrugCode(`(01)${GTIN14}(17)271100`, TODAY);
    expect(result.expiry).toBe('2027-11-30');
  });

  it('keeps the expiry exactly as it was printed', () => {
    // The house rule again: parse to a real date, and keep expiry_raw beside
    // it so the reading can always be checked against the pack.
    const result = parseDrugCode(`(01)${GTIN14}(17)271100`, TODAY);
    expect(result.expiry_raw).toBe('271100');
  });

  it('reads a manufacturing date', () => {
    const result = parseDrugCode(`(01)${GTIN14}(11)250115(17)271130`, TODAY);
    expect(result.manufactured_on).toBe('2025-01-15');
  });

  it('still reports the batch when the expiry is not a real date', () => {
    // A misread digit must not cost the batch number as well, but it does
    // cost the confidence: something on this pack was read wrongly.
    const result = parseDrugCode(`(01)${GTIN14}(17)271330(10)AB1234`, TODAY);
    expect(result.batch).toBe('AB1234');
    expect(result.expiry).toBeNull();
    expect(result.expiry_raw).toBe('271330');
    expect(result.confidence).toBe('medium');
  });

  it('keeps an AI it has no name for', () => {
    const result = parseDrugCode(`(01)${GTIN14}(91)SOMETHING`, TODAY);
    expect(result.fields['ai_91']).toBe('SOMETHING');
  });
});

describe('b. URL payloads', () => {
  it('extracts batch, expiry and GTIN from query parameters', () => {
    const result = parseDrugCode(
      `https://verify.example.in/c?gtin=${GTIN14}&batch=AB1234&exp=2027-11-30`, TODAY
    );
    expect(result.format).toBe('url');
    expect(result.gtin).toBe(GTIN14);
    expect(result.batch).toBe('AB1234');
    expect(result.expiry).toBe('2027-11-30');
  });

  it('recognises the other spellings manufacturers use', () => {
    const result = parseDrugCode(
      'https://x.in/v?b=LOT9&ed=11/2027&code=8901234567890', TODAY
    );
    expect(result.batch).toBe('LOT9');
    expect(result.gtin).toBe(GTIN14);
    // A month-precision expiry in a URL follows the same house rule.
    expect(result.expiry).toBe('2027-11-30');
  });

  it('reads a GS1 Digital Link path', () => {
    const result = parseDrugCode(
      `https://id.example.in/01/${GTIN14}/10/AB1234/17/271130`, TODAY
    );
    expect(result.format).toBe('gs1_digital_link');
    expect(result.confidence).toBe('high');
    expect(result.gtin).toBe(GTIN14);
    expect(result.batch).toBe('AB1234');
    expect(result.expiry).toBe('2027-11-30');
  });

  it('always surfaces the URL itself as an authentication link', () => {
    // The point of the code on an H2 pack is that a customer can check it.
    const url = 'https://verify.example.in/c?batch=AB1234';
    expect(parseDrugCode(url, TODAY).authenticationUrl).toBe(url);
  });

  it('is honest about a URL carrying nothing it understands', () => {
    const result = parseDrugCode('https://example.in/promo', TODAY);
    expect(result.format).toBe('url');
    expect(result.confidence).toBe('low');
    expect(result.batch).toBeNull();
    expect(result.authenticationUrl).toBe('https://example.in/promo');
  });

  it('does not treat a non-http scheme as an authentication link', () => {
    const result = parseDrugCode('javascript:alert(1)', TODAY);
    expect(result.authenticationUrl).toBeNull();
    expect(result.format).toBe('unknown');
  });
});

describe('c. JSON payloads', () => {
  it('maps the obvious key spellings', () => {
    const result = parseDrugCode(
      JSON.stringify({ gtin: GTIN14, batch: 'AB1234', exp: '2027-11-30' }), TODAY
    );
    expect(result.format).toBe('json');
    expect(result.gtin).toBe(GTIN14);
    expect(result.batch).toBe('AB1234');
    expect(result.expiry).toBe('2027-11-30');
  });

  it('maps the less obvious ones', () => {
    const result = parseDrugCode(
      JSON.stringify({
        batchNo: 'LOT-9', expiryDate: '11/2027', mfgDate: '01/2025',
        upic: 'UPIC-123', brandName: 'CALPOL', genericName: 'PARACETAMOL',
        manufacturer: 'GSK', licenceNo: 'MH-1234',
      }), TODAY
    );
    expect(result.batch).toBe('LOT-9');
    expect(result.expiry).toBe('2027-11-30');
    expect(result.fields.upic).toBe('UPIC-123');
    expect(result.fields.brand).toBe('CALPOL');
    expect(result.fields.generic).toBe('PARACETAMOL');
    expect(result.fields.manufacturer).toBe('GSK');
    expect(result.fields.licence).toBe('MH-1234');
  });

  it('is not fooled by JSON that is not an object', () => {
    for (const payload of ['[1,2,3]', '"a string"', '42', 'null', 'true']) {
      expect(parseDrugCode(payload, TODAY).format).not.toBe('json');
    }
  });

  it('reports low confidence for an object with nothing useful in it', () => {
    const result = parseDrugCode(JSON.stringify({ hello: 'world' }), TODAY);
    expect(result.format).toBe('json');
    expect(result.confidence).toBe('low');
  });
});

describe('d. plain EAN-13 — the majority case', () => {
  it('reads a valid EAN-13 as product identity only', () => {
    const result = parseDrugCode(EAN13, TODAY);
    expect(result.format).toBe('ean');
    expect(result.confidence).toBe('high');
    // Normalised to a GTIN-14 so one lookup serves every symbology.
    expect(result.gtin).toBe(GTIN14);
    expect(result.batch).toBeNull();
    expect(result.expiry).toBeNull();
  });

  it('reads a valid EAN-8', () => {
    const result = parseDrugCode('12345670', TODAY);
    expect(result.format).toBe('ean');
    expect(result.gtin).toBe('00000012345670');
  });

  it('refuses a barcode whose check digit does not agree', () => {
    // A misread digit must not become a confident lookup against the wrong
    // product. The check digit is exactly the guard against that.
    const result = parseDrugCode('8901234567891', TODAY);
    expect(result.format).toBe('unknown');
    expect(result.gtin).toBeNull();
  });

  it('reads a 14-digit GTIN as given', () => {
    expect(parseDrugCode(GTIN14, TODAY).gtin).toBe(GTIN14);
  });
});

describe('e. unrecognised payloads', () => {
  it('returns the raw payload with no confidence', () => {
    const result = parseDrugCode('SOME RANDOM TEXT', TODAY);
    expect(result.format).toBe('unknown');
    expect(result.confidence).toBe('none');
    expect(result.raw).toBe('SOME RANDOM TEXT');
    expect(result.gtin).toBeNull();
  });
});

describe('malformed input', () => {
  it('survives an empty or blank payload', () => {
    for (const payload of ['', '   ', '\n\t']) {
      const result = parseDrugCode(payload, TODAY);
      expect(result.format).toBe('unknown');
      expect(result.confidence).toBe('none');
      expect(result.raw).toBe(payload);
    }
  });

  it('survives a value that is not a string at all', () => {
    // Detector output is not ours to trust.
    for (const payload of [null, undefined, 42, {}, []] as unknown[]) {
      const result = parseDrugCode(payload as string, TODAY);
      expect(result.confidence).toBe('none');
      expect(typeof result.raw).toBe('string');
    }
  });

  it('survives broken JSON that looks like JSON', () => {
    const result = parseDrugCode('{"batch": "AB1234"', TODAY);
    expect(result.confidence).toBe('none');
    expect(result.raw).toBe('{"batch": "AB1234"');
  });

  it('survives a truncated GS1 string', () => {
    const result = parseDrugCode('0108901234', TODAY);
    expect(result.gtin).toBeNull();
    expect(result.raw).toBe('0108901234');
  });

  it('survives control characters and very long input', () => {
    const long = 'A'.repeat(10_000);
    expect(parseDrugCode(long, TODAY).raw).toBe(long);
    expect(parseDrugCode('\x00\x01\x02', TODAY).confidence).toBe('none');
  });

  it('never loses the raw payload, whatever the outcome', () => {
    const payloads = [
      `(01)${GTIN14}(10)AB1234`, EAN13, 'https://x.in/a?b=1',
      '{"batch":"X"}', 'nonsense', '', '\x1D\x1D',
    ];
    for (const payload of payloads) {
      expect(parseDrugCode(payload, TODAY).raw).toBe(payload);
    }
  });
});
