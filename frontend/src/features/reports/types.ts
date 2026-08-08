// Response shapes from /reports/*.
//
// Numbers are `number | null` throughout rather than defaulting to 0. The
// backend reports a figure it cannot compute as missing, and collapsing that
// to zero here would put the fabricated value back — a margin of "unknown"
// rendering as "0%" is exactly the failure the API was written to avoid.

export type PeriodKind = 'fy' | 'quarter' | 'month' | 'custom';

export interface Period {
  kind: PeriodKind;
  start: string;
  end: string;
  label: string;
  fy_start_year: number | null;
}

/** Query parameters shared by every period-scoped report. */
export interface PeriodQuery {
  kind?: PeriodKind;
  fy?: number;
  quarter?: number;
  month?: string;
  start?: string;
  end?: string;
  statuses?: string;
}

export interface ExcludedBlock {
  invoice_count: number;
  gross_total: number;
  reason: string | null;
}

export interface Summary {
  period: Period;
  invoice_count: number;
  vendor_count: number;
  gross_total: number;
  taxable_total: number;
  discount_total: number;
  cgst_total: number;
  sgst_total: number;
  igst_total: number;
  tax_total: number;
  effective_discount_rate: number | null;
  estimated_line_count: number;
  excluded: ExcludedBlock;
}

export interface TrendPoint {
  month: string;
  gross_total: number;
  taxable_total: number;
  invoice_count: number;
}

export interface SpendTrend {
  period: Period;
  series: TrendPoint[];
  total: number;
  average_active_month: number | null;
  active_month_count: number;
  peak_month: string | null;
}

export interface RegisterRow {
  invoice_id: string;
  invoice_date: string | null;
  invoice_number: string | null;
  seller_name: string | null;
  seller_gstin: string | null;
  taxable_value: number | null;
  discount: number | null;
  cgst: number | null;
  sgst: number | null;
  igst: number | null;
  roundoff: number | null;
  grand_total: number | null;
  status: string | null;
  tax_total: number | null;
  supply_type: 'intra_state' | 'inter_state' | 'mixed' | null;
  itc_eligible: boolean;
  itc_blocked_reason: string | null;
}

export interface GstRegister {
  period: Period;
  rows: RegisterRow[];
  row_count: number;
  claimable_tax: number;
  blocked_tax: number;
  blocked_invoice_count: number;
}

export interface HsnRow {
  hsn: string;
  gst_percent: number | null;
  line_count: number;
  taxable_value: number;
  quantity: number;
  batch_count: number;
  share: number | null;
  slab_is_expected: boolean | null;
}

export interface SlabRow {
  gst_percent: number | null;
  taxable_value: number;
  line_count: number;
  hsn_count: number;
  share: number | null;
}

export interface HsnSummary {
  period: Period;
  rows: HsnRow[];
  slabs: SlabRow[];
  taxable_total: number;
  unclassified_line_count: number;
  slab_conflicts: { hsn: string; slabs: number[] }[];
}

export interface VendorRow {
  vendor_name: string;
  gstin: string | null;
  invoice_count: number;
  gross_total: number;
  taxable_total: number;
  share: number | null;
  billed_units: number;
  free_units: number;
  free_unit_share: number | null;
  effective_discount_rate: number | null;
  last_purchase_date: string | null;
  identified: boolean;
}

export interface VendorScorecard {
  period: Period;
  vendors: VendorRow[];
  vendor_count: number;
  total_spend: number;
  top_three_share: number | null;
  unidentified_vendor_count: number;
}

export type ExpiryBucketKey =
  | 'expired'
  | '0_30'
  | '31_60'
  | '61_90'
  | '91_180'
  | 'beyond_180';

export interface ExpiryBucket {
  bucket: ExpiryBucketKey;
  label: string;
  batch_count: number;
  value_at_risk: number;
  units: number;
}

export interface ExpiryRow {
  expiry_date: string;
  days_remaining: number;
  bucket: ExpiryBucketKey;
  batch_number: string | null;
  product_name: string | null;
  pack: string | null;
  quantity: number | null;
  units: number;
  rate: number | null;
  mrp: number | null;
  value_at_risk: number;
  vendor_name: string | null;
  invoice_id: string;
  invoice_number: string | null;
  invoice_date: string | null;
}

export interface ExpiryExposure {
  as_of: string;
  horizon_days: number;
  buckets: ExpiryBucket[];
  rows: ExpiryRow[];
  total_value_at_risk: number;
  actionable_value: number;
  batches_with_unreadable_expiry: number;
  basis: string;
  basis_note: string;
}

export interface PurchasePoint {
  invoice_date: string | null;
  invoice_id: string;
  invoice_number: string | null;
  vendor_name: string | null;
  rate: number | null;
  mrp: number | null;
  gst_percent: number | null;
  quantity: number | null;
  free_quantity: number | null;
  effective_unit_cost: number | null;
  margin_at_purchase: number | null;
}

export interface ProductVariance {
  product_id: string;
  product_name: string | null;
  pack: string | null;
  purchase_count: number;
  vendor_count: number;
  first_unit_cost: number | null;
  latest_unit_cost: number | null;
  min_unit_cost: number;
  max_unit_cost: number;
  rate_change: number | null;
  rate_increased: boolean;
  cross_vendor_spread: number | null;
  cheapest_vendor: string | null;
  latest_margin: number | null;
  purchases: PurchasePoint[];
}

export interface PriceVariance {
  period: Period;
  products: ProductVariance[];
  product_count: number;
  increased_count: number;
  multi_vendor_count: number;
}

export type Severity = 'blocking' | 'warning' | 'info';

export interface QualityIssue {
  code: string;
  severity: Severity;
  title: string;
  detail: string;
  value_at_stake: number | null;
  invoice_id?: string;
  invoice_number?: string | null;
  invoice_date?: string | null;
  seller_name?: string | null;
  grand_total?: number | null;
  status?: string | null;
  seller_gstin?: string | null;
  occurrences?: { invoice_id: string; grand_total: number | null }[];
}

export interface DataQuality {
  period: Period;
  issues: QualityIssue[];
  issue_count: number;
  blocking_count: number;
  itc_at_risk: number;
  duplicate_group_count: number;
  invoices_checked: number;
}

/** Bucket sizes the scan-activity panel offers. Mirrors GRANULARITIES on the server. */
export type ScanGranularity = 'day' | 'month' | 'year' | 'all';

export interface ScanBucket {
  bucket: string;
  scans: number;
  pages: number;
}

/**
 * Scanning activity, read from an append-only ledger rather than counted from
 * invoices — so a scan whose invoice was deleted still counts as work done.
 */
export interface ScanActivity {
  granularity: ScanGranularity;
  total_scans: number;
  total_pages: number;
  scans_with_invoice: number;
  scans_without_invoice: number;
  first_scan: string | null;
  last_scan: string | null;
  series: ScanBucket[];
}
