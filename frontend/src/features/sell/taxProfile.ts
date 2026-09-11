/**
 * The pharmacy's tax profile: the settings every figure on a bill depends on.
 *
 * Only one setting so far, and it is not a small one. Whether the shelf price
 * already contains the tax decides how the taxable value is derived, and
 * getting it backwards misstates the taxable value, both tax halves and the
 * grand total simultaneously - while still producing a bill that looks
 * entirely reasonable.
 *
 * Indian pharmacy retail sells at MRP, which Legal Metrology requires to be
 * inclusive of all taxes, so `inclusive` is what a counter almost always
 * wants. It is still `null` here rather than defaulted, for the same reason
 * the rate table ships empty: the house rules do not permit picking a
 * plausible interpretation of something that moves a tax figure. Set it once,
 * deliberately, and the screen prices normally from then on.
 */

import type { PricingMode } from './types';

export interface TaxProfile {
  /** Null until the pharmacy states it. Blocks pricing while unset. */
  pricing_mode: PricingMode | null;
  /** The seller's own state code, for the intra-state assumption below. */
  seller_state_code: string | null;
}

/**
 * UNCONFIGURED BY DESIGN. Set `pricing_mode` to 'inclusive' for MRP-inclusive
 * counter pricing, or 'exclusive' to add GST on top of the price entered.
 */
export const TAX_PROFILE: TaxProfile = {
  pricing_mode: null,
  seller_state_code: null
};

/**
 * A counter sale is treated as an intra-state supply, hence CGST + SGST and no
 * IGST anywhere in this feature. That holds because a walk-in customer takes
 * the goods across the counter: the place of supply is the shop. An
 * inter-state sale is a different document and does not go through this
 * screen.
 */
export const COUNTER_SUPPLY_IS_INTRA_STATE = true;

export const isPricingConfigured = (profile: TaxProfile = TAX_PROFILE): boolean =>
  profile.pricing_mode !== null;
