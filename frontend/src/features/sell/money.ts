/**
 * Money is integer paise. Always.
 *
 * Floats cannot hold a rupee figure exactly - 0.1 + 0.2 is famously not 0.3 -
 * and these figures are summed into a GST return. A hundredth of a rupee lost
 * per line becomes a reconciliation failure at the document header, which the
 * house rules class as an error rather than something to absorb.
 *
 * The conversion to rupees happens here and only here, at the display edge.
 * Nothing upstream of `formatPaise` should ever hold a rupee float.
 */

/** Renders "not computed". Matches the reports feature, deliberately: a blank
 *  prompts a question, a fabricated 0 gets read as a fact. */
export const NOT_AVAILABLE = '—';

const RUPEES = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

/** Paise to a bare rupee string: `123456` to `1,234.56`. No symbol - thermal
 *  rolls print a bare figure in a right-aligned column. */
export function formatPaise(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || !Number.isFinite(paise)) return NOT_AVAILABLE;
  const negative = paise < 0;
  const text = RUPEES.format(Math.abs(paise) / 100);
  return negative ? `-${text}` : text;
}

/** Paise to a rupee string with the symbol, for screen use. */
export function formatRupees(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || !Number.isFinite(paise)) return NOT_AVAILABLE;
  return `₹${formatPaise(paise)}`;
}

/**
 * Reads typed rupee input into paise.
 *
 * Returns null for anything that is not a clean money figure rather than
 * coercing - `parseFloat("12abc")` is 12, and silently accepting that would
 * put a number nobody typed onto a bill. More than two decimal places is
 * likewise refused: a pharmacy cannot charge a fraction of a paisa, and
 * rounding it here would hide a typo.
 */
export function parseRupeesToPaise(input: string): number | null {
  const text = (input ?? '').trim().replace(/[₹,\s]/g, '');
  if (text === '') return null;
  if (!/^-?\d*\.?\d{0,2}$/.test(text)) return null;
  if (text === '.' || text === '-' || text === '-.') return null;
  const [whole, fraction = ''] = text.replace('-', '').split('.');
  const paise = Number(whole || '0') * 100 + Number(fraction.padEnd(2, '0'));
  if (!Number.isSafeInteger(paise)) return null;
  return text.startsWith('-') ? -paise : paise;
}

/**
 * `amount x numerator / denominator`, rounded half-up on the absolute value.
 *
 * Every proportional step in the tax engine goes through this one function so
 * that rounding behaviour is a single auditable decision rather than a
 * `Math.round` scattered across call sites. Half-up on the magnitude keeps a
 * credit note the exact mirror of the bill it reverses; banker's rounding
 * would not.
 */
export function applyRatio(amount: number, numerator: number, denominator: number): number {
  if (denominator === 0) throw new Error('applyRatio: zero denominator');
  const sign = amount < 0 ? -1 : 1;
  const scaled = (Math.abs(amount) * numerator) / denominator;
  return sign * Math.round(scaled);
}

/**
 * The rounding the document is allowed exactly one of.
 *
 * Returns the nearest whole rupee and the adjustment that gets there, so the
 * caller stores the adjustment in `round_off_paise` rather than folding it
 * into a taxable value. Half-up, matching how a printed bill reads.
 */
export function roundToRupee(paise: number): { rounded_paise: number; round_off_paise: number } {
  const sign = paise < 0 ? -1 : 1;
  const rounded = sign * Math.round(Math.abs(paise) / 100) * 100;
  return { rounded_paise: rounded, round_off_paise: rounded - paise };
}

/** Sums paise, treating an unresolved figure as unresolved rather than zero. */
export function sumPaise(values: (number | null)[]): number | null {
  let total = 0;
  for (const value of values) {
    if (value === null || !Number.isFinite(value)) return null;
    total += value;
  }
  return total;
}
