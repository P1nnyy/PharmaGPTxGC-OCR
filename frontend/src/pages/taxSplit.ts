/**
 * Distributing a combined tax figure across CGST / SGST / IGST.
 *
 * Mirrors `split_combined_tax` in the extraction normalizer, deliberately:
 * a reviewer typing the tax by hand should get the same breakdown the
 * pipeline would have produced from the same invoice, or the two disagree
 * for no reason the reviewer can see.
 *
 * The split is derived from GST law rather than guessed - an intra-state
 * supply is exactly half CGST and half SGST, an inter-state one is entirely
 * IGST - which is why typing a single figure is enough for the common case.
 */

export interface TaxSplit {
  cgst: number | null;
  sgst: number | null;
  igst: number | null;
}

/** The GST state code, or null when the value does not carry a readable one. */
export const stateCodeOf = (gstin: string | null | undefined): string | null => {
  const value = (gstin || '').replace(/\s+/g, '').toUpperCase();
  const code = value.slice(0, 2);
  // Two digits, not merely two characters: a garbled read like "GA" is an
  // unreadable state, not a different one, and treating it as different
  // would silently reclassify an intra-state purchase as inter-state.
  return /^\d{2}$/.test(code) ? code : null;
};

/**
 * True for intra-state, false for inter-state, null when it cannot be told.
 * The three answers are distinct because they lead to different tax fields.
 */
export const sameState = (
  a: string | null | undefined,
  b: string | null | undefined
): boolean | null => {
  const codeA = stateCodeOf(a);
  const codeB = stateCodeOf(b);
  if (codeA === null || codeB === null) return null;
  return codeA === codeB;
};

export const splitCombinedTax = (
  combined: number | null,
  sellerGstin: string | null | undefined,
  buyerGstin: string | null | undefined
): TaxSplit => {
  if (combined === null || !Number.isFinite(combined)) {
    return { cgst: null, sgst: null, igst: null };
  }

  const intra = sameState(sellerGstin, buyerGstin);
  if (intra === true) {
    const half = Math.round((combined / 2) * 100) / 100;
    // The odd paisa goes to SGST rather than being dropped, so the halves
    // still add back to the figure the reviewer typed.
    return { cgst: half, sgst: Math.round((combined - half) * 100) / 100, igst: null };
  }
  if (intra === false) {
    return { cgst: null, sgst: null, igst: combined };
  }
  // Supply type unknown, so the figure stays whole rather than being split
  // into a breakdown nobody can vouch for. The total is still right.
  return { cgst: combined, sgst: null, igst: null };
};
