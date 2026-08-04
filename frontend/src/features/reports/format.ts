// Display formatting for report figures.
//
// The rule the whole feature turns on: null means "not computed", and it
// renders as an em dash, never as zero. A blank cell prompts a question; a
// fabricated 0 gets read as a fact.

export const NOT_AVAILABLE = '—';

const RUPEES = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

const RUPEES_COMPACT = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  notation: 'compact',
  maximumFractionDigits: 1
});

export function currency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NOT_AVAILABLE;
  return RUPEES.format(value);
}

/** For headline tiles, where a full-precision lakh figure would not fit. */
export function currencyCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NOT_AVAILABLE;
  return RUPEES_COMPACT.format(value);
}

export function percent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return NOT_AVAILABLE;
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function number(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NOT_AVAILABLE;
  return value.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** `2026-08` to `Aug 26`, for a compact axis label. */
export function monthLabel(month: string): string {
  const [year, monthNumber] = month.split('-');
  const date = new Date(Number(year), Number(monthNumber) - 1, 1);
  return `${date.toLocaleString('en-IN', { month: 'short' })} ${year.slice(-2)}`;
}

/** ISO date to `3 Aug 2026`. Dates are stored ISO, so no parsing guesswork. */
export function dateLabel(iso: string | null | undefined): string {
  if (!iso) return NOT_AVAILABLE;
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** Signed percentage for a rate movement, so a rise reads as a rise. */
export function signedPercent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return NOT_AVAILABLE;
  const sign = fraction > 0 ? '+' : '';
  return `${sign}${(fraction * 100).toFixed(1)}%`;
}

export function daysLabel(days: number): string {
  if (days < 0) return `${Math.abs(days)}d ago`;
  return `${days}d`;
}
