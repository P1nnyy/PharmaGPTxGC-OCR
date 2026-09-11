/**
 * Counter-sale domain types.
 *
 * Naming follows the house rule: every stored monetary field is `*_paise` and
 * holds an integer. Rates are held in basis points (`*_bp`) for the same
 * reason - 12.5% as a float is not 12.5%, and a rate multiplied into a taxable
 * value has to be exact.
 */

/** 500 = 5.00%. Integer basis points, never a float percentage. */
export type BasisPoints = number;

/**
 * Whether a line carries tax at all.
 *
 * `exempt` is not "taxed at zero": Rule 46A requires the exempt value to be
 * shown as its own figure on a combined invoice-cum-bill-of-supply, and the
 * two collapse into the same number only by accident.
 */
export type SupplyKind = 'taxable' | 'exempt';

/**
 * Whether the price on the shelf already contains the tax.
 *
 * Indian pharmacy retail overwhelmingly sells at MRP, which Legal Metrology
 * requires to be inclusive of all taxes - so the taxable value is normally
 * back-computed out of the price rather than having tax added on top. Both
 * modes exist here because getting this backwards misstates every figure on
 * the bill, so it is a decision the tax profile has to state out loud rather
 * than something this module assumes.
 */
export type PricingMode = 'inclusive' | 'exclusive';

/** One row of the effective-dated rate table. */
export interface GstRateRow {
  /** HSN this rate applies to, as printed in the GSTN master. */
  hsn: string;
  supply_kind: SupplyKind;
  /** Total GST. The CGST/SGST halves are derived, never stored apart. */
  rate_bp: BasisPoints;
  /** ISO date, inclusive. */
  effective_from: string;
  /** ISO date, inclusive. Null means "still in force". */
  effective_to: string | null;
  /** Where the rate came from, so a figure on a bill can be traced back. */
  source: string;
}

/** A rate resolved for a specific line on a specific date. */
export interface ResolvedRate {
  hsn: string;
  supply_kind: SupplyKind;
  rate_bp: BasisPoints;
  source: string;
  effective_from: string;
}

/** A batch that can be sold, as read from stock on hand. */
export interface SellableBatch {
  batch_id: string;
  batch_number: string | null;
  /** ISO date. Month-precision expiries are already normalised to the last
   *  day of that month upstream, per the house rule. */
  expiry: string | null;
  /** Packs available. Received-minus-dispensed once a dispensing feed exists;
   *  today it is received, and the UI says so. */
  quantity_available: number;
  mrp_paise: number | null;
  source_invoice: string | null;
}

/** A product the counter can sell, with its batches. */
export interface SellableProduct {
  product_id: string;
  name: string;
  pack: string | null;
  hsn: string | null;
  manufacturer: string | null;
  schedule: string | null;
  batches: SellableBatch[];
}

/** A discount typed at the counter. Percent and flat are stored distinctly
 *  because a bill has to print which one was given. */
export type Discount =
  | { kind: 'none' }
  | { kind: 'percent'; value_bp: BasisPoints }
  | { kind: 'flat'; value_paise: number };

/** One line on the bill, before tax is computed. */
export interface SaleLineInput {
  line_id: string;
  product_id: string;
  product_name: string;
  hsn: string | null;
  batch_id: string | null;
  batch_number: string | null;
  expiry: string | null;
  quantity: number;
  /** The per-unit price charged. Inclusive or exclusive of tax per the
   *  pricing mode on the tax profile - the line does not decide that. */
  unit_price_paise: number | null;
  discount: Discount;
  /**
   * The scanned payload exactly as read, when this line came from a scan.
   *
   * Kept whatever the parser made of it - including when it made nothing of
   * it. An unrecognised code stored against the line it produced is what lets
   * it be bound to a product afterwards and resolve instantly from then on,
   * and it is the only record of what was physically on the pack.
   */
  scanned_code_raw: string | null;
  /** What the parser understood, for provenance on the line. */
  scanned_code_format: string | null;
}

/** A line with its tax worked out. Null figures mean "not computed". */
export interface ComputedLine {
  line_id: string;
  hsn: string | null;
  rate: ResolvedRate | null;
  /** Why this line could not be computed, for the UI to show verbatim. */
  unresolved_reason: string | null;
  gross_paise: number | null;
  discount_paise: number | null;
  taxable_paise: number | null;
  cgst_paise: number | null;
  sgst_paise: number | null;
  /** Exempt lines carry their value here and nothing in taxable. */
  exempt_paise: number | null;
  line_total_paise: number | null;
}

/** Per-rate-block subtotal. The bill prints one row per block, and the
 *  document header is reconciled against their sum. */
export interface RateBlock {
  rate_bp: BasisPoints;
  supply_kind: SupplyKind;
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  exempt_paise: number;
}

/** The whole document's figures. */
export interface SaleTotals {
  blocks: RateBlock[];
  taxable_paise: number | null;
  cgst_paise: number | null;
  sgst_paise: number | null;
  exempt_paise: number | null;
  /** The single document-level rounding, per the house rule. */
  round_off_paise: number | null;
  grand_total_paise: number | null;
  /** Lines that could not be computed. Non-empty means the bill cannot issue. */
  unresolved_line_ids: string[];
  /** Set when the per-block sums do not reconcile to the header. An error,
   *  never silently absorbed. */
  reconciliation_error: string | null;
}

export type PaymentMethod = 'cash' | 'upi' | 'card' | 'credit';

export interface PaymentSplit {
  method: PaymentMethod;
  amount_paise: number;
  /** UPI/card reference, where the operator captured one. */
  reference: string | null;
}

/** The bill as issued. Mirrors what the write path will persist to Neo4j. */
export interface IssuedBill {
  serial: string;
  issued_at: string;
  lines: SaleLineInput[];
  computed: ComputedLine[];
  totals: SaleTotals;
  payments: PaymentSplit[];
  /** R2 object key for an attached prescription photo, when captured. */
  prescription_image_ref: string | null;
  customer_name: string | null;
  customer_phone: string | null;
}
