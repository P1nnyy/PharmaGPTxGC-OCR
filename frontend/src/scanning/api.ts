/**
 * Resolving and binding scanned codes.
 *
 * A 404 from `resolveCode` is not an error — it is the ordinary answer for a
 * pack nobody has bound yet, and it is what makes the counter offer to bind it.
 * So it comes back as null rather than throwing.
 */

import type { ParsedDrugCode } from './parseDrugCode';
import { bindingKeyFor, lookupCandidates } from './bindingKey';

export interface BoundProduct {
  product: { id: string; canonical_name: string | null; hsn: string | null };
  code: { value: string; type: string | null; first_seen_at: string | null };
}

/** The product a scanned payload is bound to, or null if none is. */
export async function resolveCode(parsed: ParsedDrugCode): Promise<BoundProduct | null> {
  for (const candidate of lookupCandidates(parsed)) {
    const response = await fetch(`/products/by-code?value=${encodeURIComponent(candidate)}`);
    if (response.status === 404) continue;
    if (!response.ok) throw new Error(`Code lookup failed with ${response.status}`);
    return (await response.json()) as BoundProduct;
  }
  return null;
}

/** Binds a scanned payload to a product, under whichever part of it repeats. */
export async function bindCode(
  productId: string,
  parsed: ParsedDrugCode,
  symbology?: string,
): Promise<BoundProduct> {
  const key = bindingKeyFor(parsed, symbology);
  const response = await fetch(`/products/${encodeURIComponent(productId)}/codes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: key.value, type: key.type }),
  });
  if (!response.ok) {
    let detail = `Could not bind that code (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // Non-JSON error body; the status-based message stands.
    }
    throw new Error(detail);
  }
  return (await response.json()) as BoundProduct;
}
