/**
 * The symbologies worth looking for on a pharmacy counter.
 *
 * Kept short on purpose. Every extra format is more work per frame for the
 * decoder, and the ones left out (PDF417, ITF, Codabar, Aztec…) do not appear
 * on Indian drug packs or retail cartons.
 *
 *   qr_code, data_matrix  - what a Schedule H2 pack carries
 *   ean_13, ean_8         - ordinary retail barcodes, the majority of stock
 *   code_128, code_39     - wholesaler and in-house labels
 */
export const SCAN_FORMATS = [
  'qr_code',
  'data_matrix',
  'ean_13',
  'ean_8',
  'code_128',
  'code_39',
] as const;

export type ScanFormat = (typeof SCAN_FORMATS)[number];
