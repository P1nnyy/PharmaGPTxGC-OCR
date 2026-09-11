/**
 * GS1 element strings — the format behind the DataMatrix on a drug pack.
 *
 * A payload is a run of Application Identifiers, each a 2-4 digit code followed
 * by its data. Two forms exist in the wild and both turn up on Indian packs:
 *
 *   parenthesised   (01)08901234567890(17)271130(10)AB1234
 *   FNC1-delimited  0108901234567890172711301 0AB1234<GS>21000000001
 *
 * The second is the one that needs care. AIs with a fixed data length end
 * without any separator — `01` is always fourteen digits, `17` always six — so
 * the parser has to know those lengths to find where the next AI begins.
 * Variable-length AIs run to the next FNC1 (ASCII 29) or to the end of the
 * payload. Get that wrong and every field after the first variable one is
 * misaligned, which is worse than failing: a batch number sliced at the wrong
 * offset still looks like a batch number.
 *
 * So when alignment is lost, this stops. Whatever was read before that point is
 * returned and the remainder is handed back untouched in `unparsed`, rather
 * than guessed at.
 */

/**
 * Fixed data lengths, by AI. An AI absent from this table is variable-length
 * and runs to the next separator.
 *
 * Only the AIs a pharmacy might actually meet are listed. An unknown AI is
 * still captured (see below) — this table decides termination, not whether a
 * field is worth keeping.
 */
const FIXED_LENGTH: Record<string, number> = {
  '00': 18, // SSCC
  '01': 14, // GTIN
  '02': 14, // GTIN of contained trade items
  '03': 14,
  '04': 16,
  '11': 6,  // production date
  '12': 6,  // due date
  '13': 6,  // packaging date
  '15': 6,  // best before
  '16': 6,  // sell by
  '17': 6,  // expiry
  '20': 2,  // variant
  '41': 13,
  '7003': 10, // expiry to the hour
};

/** AIs that are variable-length but known, so they are read as fields. */
const KNOWN_VARIABLE = new Set([
  '10', // batch / lot
  '21', // serial
  '22',
  '30',
  '37',
  '240', '241', '242', '243',
  '250', '251', '253', '254',
  '400', '401', '402', '403',
  '410', '411', '412', '413', '414', '415', '416', '417',
  '710', '711', '712', '713', '714', // national healthcare reimbursement
  '7001', '7002', '7004', '7005', '7006', '7007', '7008', '7009', '7010',
  '8001', '8002', '8003', '8004', '8005', '8006', '8017', '8018', '8020',
  '90', '91', '92', '93', '94', '95', '96', '97', '98', '99', // internal use
]);

const GS = '\x1D';
/** Symbology identifiers a scanner prefixes: DataMatrix, GS1-128, QR, DataBar. */
const SYMBOLOGY_PREFIX = /^\](?:d2|C1|Q3|e0|E0|d1|Q1)/;

export interface Gs1ParseResult {
  ais: Record<string, string>;
  /** Whatever could not be read, if alignment was lost partway. */
  unparsed: string | null;
}

/** The longest known AI at this position, or null. */
function readAi(payload: string, at: number): string | null {
  // Longest first: `240` must not be read as `24` and `0`.
  for (const width of [4, 3, 2]) {
    const candidate = payload.slice(at, at + width);
    if (candidate.length < width) continue;
    if (!/^\d+$/.test(candidate)) continue;
    if (candidate in FIXED_LENGTH || KNOWN_VARIABLE.has(candidate)) return candidate;
  }
  return null;
}

export function parseGs1ElementString(raw: string): Gs1ParseResult | null {
  if (!raw) return null;
  let payload = raw.trim().replace(SYMBOLOGY_PREFIX, '');
  // A leading FNC1 carries no data; it only marks the symbol as GS1.
  while (payload.startsWith(GS)) payload = payload.slice(1);
  if (!payload) return null;

  if (payload.includes('(')) return parseParenthesised(payload);

  const ais: Record<string, string> = {};
  let at = 0;
  let unparsed: string | null = null;

  while (at < payload.length) {
    if (payload[at] === GS) {
      at += 1;
      continue;
    }

    const ai = readAi(payload, at);
    if (ai === null) {
      unparsed = payload.slice(at);
      break;
    }
    at += ai.length;

    const fixed = FIXED_LENGTH[ai];
    if (fixed !== undefined) {
      const value = payload.slice(at, at + fixed);
      // A fixed-length field that ran short means the payload is truncated.
      // Everything after it would be misaligned, so nothing after it is read.
      if (value.length < fixed) return Object.keys(ais).length ? { ais, unparsed: payload.slice(at - ai.length) } : null;
      ais[ai] = value;
      at += fixed;
      continue;
    }

    const separator = payload.indexOf(GS, at);
    const end = separator === -1 ? payload.length : separator;
    ais[ai] = payload.slice(at, end);
    at = end;
  }

  if (Object.keys(ais).length === 0) return null;
  return { ais, unparsed };
}

/** `(01)0890...(10)AB1234` — the human-readable rendering. */
function parseParenthesised(payload: string): Gs1ParseResult | null {
  const pattern = /\((\d{2,4})\)([^(]*)/g;
  const ais: Record<string, string> = {};
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(payload)) !== null) {
    // Whitespace between elements is presentation, not data.
    ais[match[1]] = match[2].trim();
  }
  if (Object.keys(ais).length === 0) return null;
  return { ais, unparsed: null };
}
