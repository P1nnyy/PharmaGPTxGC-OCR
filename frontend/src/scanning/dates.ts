/**
 * GS1 date fields: `YYMMDD`.
 *
 * Two rules decide what one of these means, and both matter for stock.
 *
 * **Day `00` means no day was given.** GS1 fills the field with two zeros when
 * only a month is significant, which is the norm on a drug pack. The house rule
 * says a month-precision expiry means the *last* day of that month — `12/26` is
 * good through all of December — so that is what this resolves to. Resolving to
 * the 1st would write stock off thirty days early and would disagree with what
 * a pharmacist reading the same pack would say.
 *
 * **The century is inferred by a sliding window.** Two digits cannot say it. GS1
 * puts the boundary at roughly fifty years either side of today: a code reading
 * `85` scanned in 2026 is 1985, not 2085, because no pack expires sixty years
 * out. Anchoring on the current date rather than a hardcoded pivot year is what
 * keeps that true after 2050.
 */

/** `YYMMDD` to an ISO date, or null if it is not a date. */
export function parseGs1Date(value: string, today: Date = new Date()): string | null {
  if (!/^\d{6}$/.test(value)) return null;

  const yy = Number(value.slice(0, 2));
  const month = Number(value.slice(2, 4));
  const day = Number(value.slice(4, 6));

  if (month < 1 || month > 12) return null;

  const year = expandYear(yy, today);
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();

  // `00` is GS1 for "no day given". Anything else must be a real day of that
  // month — 31 April is a misread, not a date to round into range.
  const resolvedDay = day === 0 ? lastDay : day;
  if (day !== 0 && (day < 1 || day > lastDay)) return null;

  return `${year}-${String(month).padStart(2, '0')}-${String(resolvedDay).padStart(2, '0')}`;
}

/** The four-digit year a two-digit one means, relative to today. */
function expandYear(yy: number, today: Date): number {
  const currentYear = today.getUTCFullYear();
  let candidate = Math.floor(currentYear / 100) * 100 + yy;
  // Slide by a century until the result is within fifty years either way.
  if (candidate - currentYear > 50) candidate -= 100;
  else if (currentYear - candidate > 50) candidate += 100;
  return candidate;
}
