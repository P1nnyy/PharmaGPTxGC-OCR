// Shapes returned by /management/*.
//
// Money arrives as rupee numbers, already converted. Nothing here re-adds a
// figure: a total computed in the browser can disagree with the one the report
// computed, and afterwards nobody can tell which the shopkeeper acted on.

export interface Window { start: string; end: string }

export interface ExpiringRow {
  product_id: string;
  product_name: string | null;
  batch_number: string;
  expiry: string;
  days_left: number;
  bucket: string;
  quantity: number;
  value_at_mrp: number;
  value_at_cost: number;
  input_tax_at_risk: number;
  vendor_id: string | null;
  vendor_name: string | null;
  return_window_days: number | null;
  days_left_to_return: number | null;
  can_still_be_returned: boolean | null;
}

export interface ExpiryBucket {
  label: string;
  days: number | null;
  batch_count: number;
  quantity: number;
  value_at_mrp: number;
  value_at_cost: number;
  input_tax_at_risk: number;
  still_returnable_value_at_cost: number;
  return_window_unknown_count: number;
  rows: ExpiringRow[];
}

export interface ExpiryReport {
  as_of: string;
  horizon_days: number;
  buckets: ExpiryBucket[];
  expired: ExpiryBucket;
  totals: {
    batch_count: number;
    value_at_cost: number;
    value_at_mrp: number;
    input_tax_at_risk: number;
    still_returnable_value_at_cost: number;
    still_returnable_batch_count: number;
    return_window_unknown_count: number;
  };
  statutory_note: string;
  return_window_note: string | null;
}

export interface MarginRow {
  key: string;
  label: string;
  vendor_id: string | null;
  quantity: number;
  line_count: number;
  revenue: number;
  cost: number;
  margin: number;
  margin_percent: number | null;
  is_below_cost: boolean;
  confidence: 'BATCH' | 'PRODUCT' | 'NONE';
  estimated_line_count: number;
  uncosted_line_count: number;
  uncosted_revenue: number;
}

export interface MarginReport {
  window: Window;
  by_product: MarginRow[];
  by_vendor: MarginRow[];
  by_month: MarginRow[];
  below_cost: MarginRow[];
  totals: {
    revenue: number; cost: number; margin: number;
    product_count: number; below_cost_count: number; uncosted_line_count: number;
  };
  excluded: { day_total_count: number; note: string | null };
  empty_reason: string | null;
}

export interface LedgerRow {
  id: string;
  occurred_on: string;
  product_id: string;
  product_name: string | null;
  batch_number: string;
  expiry: string | null;
  reason: 'PURCHASE' | 'SALE';
  quantity_delta: number;
  balance: number;
  value: number;
  input_tax: number;
  source_type: string | null;
  source_id: string | null;
  flags: string[];
}

export interface LedgerReport {
  window: Window;
  filters: Record<string, string | null>;
  rows: LedgerRow[];
  row_count: number;
  negative_balance_count: number;
}

export interface MoverRow {
  product_id: string;
  product_name: string | null;
  units_sold: number;
  revenue: number;
  on_hand: number;
  stock_value: number;
  days_of_cover: number | null;
  never_sold: boolean;
  dead_stock: boolean;
}

export interface MoversReport {
  window: Window;
  days_observed: number;
  fast_by_units: MoverRow[];
  fast_by_value: MoverRow[];
  slow: MoverRow[];
  totals: {
    product_count: number; never_sold_count: number;
    dead_stock_count: number; stock_value: number;
  };
}

export interface DailySalesReport {
  window: Window;
  previous_window: Window;
  totals: { value: number; bill_count: number; average_bill_value: number };
  comparison: {
    previous_value: number;
    previous_bill_count: number;
    previous_average_bill_value: number;
    value_change_percent: number | null;
    bill_count_change_percent: number | null;
    average_bill_change_percent: number | null;
  };
  by_hour: Array<{ hour: number; label: string; bill_count: number; value: number }>;
  bills_without_a_time: number;
  by_day: Array<{ day: string; bill_count: number; value: number }>;
  payment_split: Array<{ method: string; amount: number; payment_count: number; share_percent: number | null }>;
  cash_vs_digital: {
    cash: number; digital: number; cash_share_percent: number | null;
    recorded_total: number; unrecorded: number;
  };
}

export interface TrendReport {
  window: Window;
  rows: Array<{ day: string; purchases: number; sales: number; net: number; cumulative_net: number }>;
  totals: { purchases: number; sales: number; net: number; purchase_invoice_count: number };
  note: string;
}

export interface VendorScoreRow {
  vendor_id: string;
  name: string;
  gstin: string | null;
  invoice_count: number;
  purchase_taxable: number;
  credit_from_this_supplier: number;
  return_window_days: number | null;
  filing: {
    available: boolean;
    on_time_rate: number | null;
    periods_expected: number;
    periods_filed_late: number;
    periods_not_filed: number;
    average_delay_days: number | null;
    blocked_credit: number;
  };
  summary: string | null;
}

export interface VendorScorecard {
  window: Window;
  rows: VendorScoreRow[];
  row_count: number;
  source: { name: string; has_filing_data: boolean; note: string | null };
  totals: { credit_at_stake: number; vendor_count: number; missing_return_window_count: number };
}

export interface DashboardCard {
  id: string;
  title: string;
  value: number;
  unit: 'currency' | 'count';
  detail: string;
  comparison_label?: string;
  comparison_percent?: number | null;
  comparison_value?: number;
  secondary?: { label: string; value: string | number } | null;
  note?: string | null;
  link: string;
  tone: 'neutral' | 'good' | 'warn' | 'bad';
}

export interface DashboardReport { as_of: string; cards: DashboardCard[] }

export interface VendorRow {
  vendor_id: string;
  name: string | null;
  gstin: string | null;
  return_window_days: number | null;
  return_window_note: string | null;
  invoice_count: number;
  last_invoice_date: string | null;
}
