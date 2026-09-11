/**
 * Which part of a scanned payload is worth remembering.
 *
 * This matters more than it looks. The DataMatrix on a Schedule H2 pack carries
 * the batch and often a per-pack serial, so the *raw payload is unique to that
 * single box* — bind that and it will never be scanned again, and the learning
 * loop quietly never learns anything. Every pack of the same medicine would
 * keep coming up unrecognised.
 *
 * The GTIN is the part that repeats: it identifies the product, not the pack.
 * So when the payload yields one, that is what a binding is filed under and
 * what a lookup asks for. Only when there is no GTIN at all — an in-house label,
 * an unparseable code — does the raw payload become the key, which is correct
 * there because for those the raw payload *is* the stable identifier.
 */

import type { ParsedDrugCode } from './parseDrugCode';

export interface BindingKey {
  value: string;
  /** What kind of thing `value` is, stored on the ProductCode for context. */
  type: string;
  /** True when the key repeats across packs, so binding it will pay off. */
  stable: boolean;
}

export function bindingKeyFor(parsed: ParsedDrugCode, symbology?: string): BindingKey {
  if (parsed.gtin) {
    return { value: parsed.gtin, type: 'gtin', stable: true };
  }
  return {
    value: parsed.raw,
    // The symbology the scanner reported, when it gave one — a Code 128 shelf
    // label and a QR code bound to the same product are different facts.
    type: symbology ? `raw:${symbology}` : `raw:${parsed.format}`,
    // A payload carrying a batch is per-pack, so binding it will not help the
    // next box. The UI uses this to say so rather than promising a shortcut
    // that will not arrive.
    stable: parsed.batch === null && parsed.serial === null,
  };
}

/** The lookups to try, in order, for a scanned payload. */
export function lookupCandidates(parsed: ParsedDrugCode): string[] {
  const candidates: string[] = [];
  if (parsed.gtin) candidates.push(parsed.gtin);
  if (parsed.raw && parsed.raw !== parsed.gtin) candidates.push(parsed.raw);
  return candidates;
}
