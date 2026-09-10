// The shapes the /tax-periods/* endpoints return.
//
// Every money field is a rupee number, already converted server-side. Nothing
// on this side of the wire adds up a tax figure: if a total is needed that the
// API does not return, the fix belongs in services/gstr1/, not in a reduce()
// here. A number computed in the browser can disagree with the payload that
// was filed, and there is no way to tell which one the shop looked at.

export type Severity = 'BLOCKING' | 'WARNING';
export type PeriodStatus = 'OPEN' | 'CLOSED';
export type SupplyType = 'INTRA' | 'INTER';

export interface ValidationItem {
  id: string;
  code: string;
  severity: Severity;
  message: string;
  record_type: string;
  record_id: string | null;
  line_id: string | null;
  acknowledgeable: boolean;
  context: Record<string, unknown>;
}

export interface PeriodInfo {
  label: string;
  frequency: 'MONTHLY' | 'QUARTERLY';
  months: string[];
  start_date: string;
  end_date: string;
  quarter: number | null;
  financial_year: number | null;
  status: PeriodStatus;
  closed_at: string | null;
  closed_by: string | null;
}

export interface ShopInfo {
  gstin: string | null;
  legal_name: string | null;
  trade_name: string | null;
  state_code: string | null;
  filing_frequency: string | null;
  hsn_digits: number;
  aato: number | null;
}

export interface Totals {
  taxable: number;
  cgst: number;
  sgst: number;
  igst: number;
  cess: number;
  tax: number;
  untaxed: number;
  supplies: number;
  document_count: number;
}

export interface B2csRow {
  place_of_supply: string;
  rate: number;
  supply_type: SupplyType;
  taxable: number;
  cgst: number;
  sgst: number;
  igst: number;
  document_ids: string[];
}

export interface InvoiceRow {
  document_id: string;
  bill_number: string | null;
  sale_date: string;
  place_of_supply: string;
  invoice_value: number;
  customer_gstin?: string;
  customer_name?: string | null;
  supply_type?: SupplyType | null;
}

export interface NilExemptRow {
  code: string;
  description: string;
  nil_rated: number;
  exempted: number;
  non_gst: number;
  total: number;
}

export interface HsnRow {
  hsn: string;
  uqc: string | null;
  rate: number;
  quantity: number;
  taxable: number;
  cgst: number;
  sgst: number;
  igst: number;
  total_value: number;
  document_ids: string[];
}

export interface SeriesRow {
  series_prefix: string;
  opening_number: string | null;
  closing_number: string | null;
  total_issued: number;
  cancelled: number;
  net_issued: number;
  gaps: number[];
  duplicates: number[];
}

export interface Gstr1Return {
  period: PeriodInfo;
  shop: ShopInfo;
  totals: Totals;
  is_nil_return: boolean;
  can_close: boolean;
  closed?: boolean;
  validation: {
    blocking: ValidationItem[];
    warnings: ValidationItem[];
    outstanding: ValidationItem[];
  };
  tables: {
    b2cs: B2csRow[];
    b2cs_negative: B2csRow[];
    b2cl: InvoiceRow[];
    b2b: InvoiceRow[];
    nil_exempt: NilExemptRow[];
    hsn: { b2b: HsnRow[]; b2c: HsnRow[] };
    documents_issued: SeriesRow[];
  };
}
