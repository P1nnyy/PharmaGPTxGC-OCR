/**
 * Reading the code on an Indian drug pack.
 *
 * Under the Schedule H2 mandate the code on a pack must hold the unique product
 * identification code, the generic and brand names, the manufacturer's name and
 * address, the batch number, the manufacturing and expiry dates and the
 * manufacturing licence number. What the mandate does *not* fix is the format —
 * each manufacturer chooses that under its own SOP. So there is no single layout
 * to parse, and a parser that assumed one would silently mis-read every pack
 * printed by someone else.
 *
 * The design that follows from that:
 *
 *   * Several formats are recognised, most specific first.
 *   * A field that could not be read is null. Never a guess, and never an empty
 *     string standing in for one.
 *   * `confidence` says how much of the payload was actually understood, so the
 *     UI can decide between "add the line" and "ask the user".
 *   * **The raw payload always survives**, whatever happened. It is stored on
 *     the SaleLine, which is what lets an unrecognised code be bound to a
 *     product later and resolve instantly from then on. That learning loop is
 *     the point of the feature, and it only works if nothing is thrown away.
 */

import { parseGs1Date } from './dates';
import { parseGs1ElementString } from './gs1';

export type ParseConfidence = 'high' | 'medium' | 'low' | 'none';
export type PayloadFormat = 'gs1' | 'gs1_digital_link' | 'url' | 'json' | 'ean' | 'unknown';

export interface ParsedDrugCode {
  /** Exactly what the scanner produced. Always present, never normalised. */
  raw: string;
  format: PayloadFormat;
  confidence: ParseConfidence;
  /** Normalised to GTIN-14, so one lookup serves every symbology. */
  gtin: string | null;
  batch: string | null;
  serial: string | null;
  /** ISO date. A month-precision expiry resolves to the last day of the month. */
  expiry: string | null;
  /** The expiry exactly as the pack printed it, kept beside the parsed date. */
  expiry_raw: string | null;
  manufactured_on: string | null;
  manufactured_on_raw: string | null;
  /** An http(s) payload, to offer the user as a manufacturer check. */
  authenticationUrl: string | null;
  /** Everything else recognised: brand, generic, manufacturer, licence, UPIC. */
  fields: Record<string, string>;
}

function empty(raw: string): ParsedDrugCode {
  return {
    raw,
    format: 'unknown',
    confidence: 'none',
    gtin: null,
    batch: null,
    serial: null,
    expiry: null,
    expiry_raw: null,
    manufactured_on: null,
    manufactured_on_raw: null,
    authenticationUrl: null,
    fields: {},
  };
}

/** GTIN-8/12/13 to GTIN-14, so lookups do not care which symbology it came from. */
function toGtin14(digits: string): string {
  return digits.padStart(14, '0');
}

/** The GS1 mod-10 check digit, the guard against a misread turning into a
 *  confident lookup against the wrong product. */
function hasValidCheckDigit(digits: string): boolean {
  if (!/^\d+$/.test(digits) || digits.length < 8) return false;
  const body = digits.slice(0, -1);
  const check = Number(digits[digits.length - 1]);
  let sum = 0;
  // Weights alternate 3 and 1 from the rightmost body digit leftwards.
  for (let i = body.length - 1, weight = 3; i >= 0; i -= 1, weight = weight === 3 ? 1 : 3) {
    sum += Number(body[i]) * weight;
  }
  return (10 - (sum % 10)) % 10 === check;
}

/**
 * A date from a URL or JSON payload, which unlike GS1 has no fixed shape.
 *
 * Month-precision forms resolve to the last day of the month, matching the
 * house rule and `core/dates.py` on the server: `11/2027` on a pack means good
 * through November.
 */
function parseLooseDate(value: string): string | null {
  const text = value.trim();
  if (!text) return null;

  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (iso) return isRealDate(+iso[1], +iso[2], +iso[3]) ? text : null;

  const isoMonth = /^(\d{4})-(\d{2})$/.exec(text);
  if (isoMonth) return lastDayOf(+isoMonth[1], +isoMonth[2]);

  // MM/YYYY, MM-YYYY, MM/YY
  const monthYear = /^(\d{1,2})[/\-.](\d{2}|\d{4})$/.exec(text);
  if (monthYear) {
    const month = Number(monthYear[1]);
    const year = monthYear[2].length === 2 ? 2000 + Number(monthYear[2]) : Number(monthYear[2]);
    return lastDayOf(year, month);
  }

  // DD/MM/YYYY — day-first, the Indian convention.
  const dayFirst = /^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$/.exec(text);
  if (dayFirst) {
    const [, d, m, y] = dayFirst;
    return isRealDate(+y, +m, +d)
      ? `${y}-${String(+m).padStart(2, '0')}-${String(+d).padStart(2, '0')}`
      : null;
  }

  // YYMMDD, the GS1 shape turning up in a query string.
  if (/^\d{6}$/.test(text)) return parseGs1Date(text);
  return null;
}

function lastDayOf(year: number, month: number): string | null {
  if (month < 1 || month > 12) return null;
  const day = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function isRealDate(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12 || day < 1) return false;
  return day <= new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Key spellings seen across manufacturers, normalised for comparison. */
const KEY_ALIASES: Record<string, string[]> = {
  gtin: ['gtin', 'gtin14', 'ean', 'barcode', 'code', 'pid', 'productcode', 'upic', 'uid'],
  batch: ['batch', 'batchno', 'batchnumber', 'b', 'lot', 'lotno', 'lotnumber', 'bn'],
  expiry: ['exp', 'expiry', 'expirydate', 'expdate', 'ed', 'expdt', 'usebefore', 'bestbefore'],
  mfg: ['mfg', 'mfgdate', 'manufacturingdate', 'manufactureddate', 'mfd', 'md', 'pd'],
  serial: ['serial', 'serialno', 'serialnumber', 'sn', 'sr'],
  brand: ['brand', 'brandname', 'tradename', 'product', 'productname', 'name'],
  generic: ['generic', 'genericname', 'composition', 'salt', 'molecule'],
  manufacturer: ['manufacturer', 'mfr', 'mfrname', 'manufacturername', 'company', 'marketedby'],
  manufacturer_address: ['address', 'mfraddress', 'manufactureraddress', 'addr'],
  licence: ['licence', 'license', 'licenceno', 'licenseno', 'mfglic', 'mfglicence', 'dl', 'dlno'],
  upic: ['upic', 'upicode', 'uniqueproductcode'],
};

const normaliseKey = (key: string): string => key.toLowerCase().replace(/[^a-z0-9]/g, '');

/** Pulls the known fields out of a flat key/value bag (JSON object or query). */
function readBag(bag: Record<string, string>, into: ParsedDrugCode): number {
  const byNormalised = new Map<string, string>();
  for (const [key, value] of Object.entries(bag)) {
    if (value === null || value === undefined) continue;
    byNormalised.set(normaliseKey(key), String(value));
  }

  const take = (canonical: string): string | null => {
    for (const alias of KEY_ALIASES[canonical] ?? []) {
      const found = byNormalised.get(alias);
      if (found !== undefined && found !== '') return found;
    }
    return null;
  };

  let recognised = 0;

  const gtin = take('gtin');
  if (gtin && /^\d{8,14}$/.test(gtin) && hasValidCheckDigit(gtin)) {
    into.gtin = toGtin14(gtin);
    recognised += 1;
  }

  const batch = take('batch');
  if (batch) {
    into.batch = batch;
    recognised += 1;
  }

  const serial = take('serial');
  if (serial) {
    into.serial = serial;
    recognised += 1;
  }

  const expiry = take('expiry');
  if (expiry) {
    into.expiry_raw = expiry;
    into.expiry = parseLooseDate(expiry);
    recognised += 1;
  }

  const mfg = take('mfg');
  if (mfg) {
    into.manufactured_on_raw = mfg;
    into.manufactured_on = parseLooseDate(mfg);
    recognised += 1;
  }

  for (const canonical of ['brand', 'generic', 'manufacturer', 'manufacturer_address', 'licence', 'upic']) {
    const value = take(canonical);
    if (value) {
      into.fields[canonical] = value;
      recognised += 1;
    }
  }

  return recognised;
}

/** GS1 element string — the DataMatrix on a compliant pack. */
function tryGs1(raw: string, today: Date): ParsedDrugCode | null {
  const parsed = parseGs1ElementString(raw);
  if (parsed === null) return null;

  const result = empty(raw);
  result.format = 'gs1';

  const { ais } = parsed;
  let misread = false;

  if (ais['01'] && /^\d{14}$/.test(ais['01'])) result.gtin = ais['01'];
  else if (ais['01']) misread = true;

  if (ais['10'] !== undefined) result.batch = ais['10'] || null;
  if (ais['21'] !== undefined) result.serial = ais['21'] || null;

  if (ais['17']) {
    result.expiry_raw = ais['17'];
    result.expiry = parseGs1Date(ais['17'], today);
    if (result.expiry === null) misread = true;
  }
  if (ais['11']) {
    result.manufactured_on_raw = ais['11'];
    result.manufactured_on = parseGs1Date(ais['11'], today);
    if (result.manufactured_on === null) misread = true;
  }

  // Anything else the pack carried is kept rather than dropped: a manufacturer
  // AI we have no name for may still be the only copy of something on screen.
  for (const [ai, value] of Object.entries(ais)) {
    if (['01', '10', '17', '11', '21'].includes(ai)) continue;
    result.fields[`ai_${ai}`] = value;
  }

  // Something on this pack did not read cleanly, so the whole read is suspect
  // even though most fields came through.
  result.confidence = misread || parsed.unparsed ? 'medium' : 'high';
  return result;
}

/** GS1 Digital Link: the AIs expressed as URL path segments. */
function tryDigitalLink(url: URL, raw: string, today: Date): ParsedDrugCode | null {
  const segments = url.pathname.split('/').filter(Boolean);
  const ais: Record<string, string> = {};
  for (let i = 0; i + 1 < segments.length; i += 2) {
    if (/^\d{2,4}$/.test(segments[i])) ais[segments[i]] = decodeURIComponent(segments[i + 1]);
  }
  if (!ais['01']) return null;

  const result = empty(raw);
  result.format = 'gs1_digital_link';
  result.authenticationUrl = url.href;

  const gtin = ais['01'];
  if (/^\d{8,14}$/.test(gtin) && hasValidCheckDigit(gtin)) result.gtin = toGtin14(gtin);
  if (ais['10']) result.batch = ais['10'];
  if (ais['21']) result.serial = ais['21'];
  if (ais['17']) {
    result.expiry_raw = ais['17'];
    result.expiry = parseGs1Date(ais['17'], today);
  }
  if (ais['11']) {
    result.manufactured_on_raw = ais['11'];
    result.manufactured_on = parseGs1Date(ais['11'], today);
  }

  result.confidence = result.gtin ? 'high' : 'medium';
  return result;
}

function tryUrl(raw: string, today: Date): ParsedDrugCode | null {
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  // Only http(s) is an authentication link. A javascript: or data: payload is
  // not something to offer the user as a manufacturer check.
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;

  const digitalLink = tryDigitalLink(url, raw, today);
  if (digitalLink) return digitalLink;

  const result = empty(raw);
  result.format = 'url';
  result.authenticationUrl = url.href;

  const bag: Record<string, string> = {};
  url.searchParams.forEach((value, key) => {
    bag[key] = value;
  });
  const recognised = readBag(bag, result);

  // A URL is always worth surfacing even when none of its parameters are
  // recognisable — the customer can still follow it to the manufacturer.
  result.confidence = recognised >= 2 ? 'high' : recognised === 1 ? 'medium' : 'low';
  return result;
}

function tryJson(raw: string): ParsedDrugCode | null {
  const text = raw.trim();
  if (!text.startsWith('{')) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;

  const result = empty(raw);
  result.format = 'json';
  const recognised = readBag(parsed as Record<string, string>, result);
  result.confidence = recognised >= 2 ? 'high' : recognised === 1 ? 'medium' : 'low';
  return result;
}

function tryEan(raw: string): ParsedDrugCode | null {
  const digits = raw.trim();
  if (!/^\d{8}$|^\d{12}$|^\d{13}$|^\d{14}$/.test(digits)) return null;
  if (!hasValidCheckDigit(digits)) return null;

  const result = empty(raw);
  result.format = 'ean';
  result.gtin = toGtin14(digits);
  // Identity only. The majority of non-H2 stock carries nothing more, and
  // pretending otherwise would invent a batch.
  result.confidence = 'high';
  return result;
}

/**
 * Reads a scanned payload.
 *
 * Order matters, and EAN comes first for a reason worth stating. A bare
 * `12345670` is a valid EAN-8 — and it is *also* readable as GS1 AI `12` (due
 * date) carrying `345670`, because `12` is a fixed-length AI. Trying GS1 first
 * turns a product barcode into a due date and loses the identity entirely.
 *
 * The check digit is what makes putting EAN first safe. `tryEan` accepts only a
 * bare numeric payload of exactly GTIN-8/12/13/14 length whose mod-10 check
 * digit agrees, and a genuine GS1 element string is both longer than that and
 * vanishingly unlikely to satisfy the check by accident. Anything that is not
 * unambiguously a barcode falls through to the structured readers.
 */
export function parseDrugCode(raw: string, today: Date = new Date()): ParsedDrugCode {
  // Detector output is not ours to trust — a non-string here is a bug
  // somewhere else, and it must not take the counter down with it.
  if (typeof raw !== 'string') return empty(raw === null || raw === undefined ? '' : String(raw));
  if (!raw.trim()) return empty(raw);

  // Written out rather than looped so each reader takes only what it needs —
  // an EAN has no date in it to resolve a century against.
  return tryEan(raw) ?? tryGs1(raw, today) ?? tryUrl(raw, today) ?? tryJson(raw) ?? empty(raw);
}
