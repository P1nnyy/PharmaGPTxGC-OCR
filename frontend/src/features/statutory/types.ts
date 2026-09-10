// Shapes returned by /statutory/*.
//
// The important one is `Figure`. Every money value in the pack arrives as a
// figure - an amount plus a `drill` describing how to find the documents
// behind it - and the UI renders it through one component that makes it
// clickable whenever a drill is present. That is what turns "every figure must
// be traceable" from a promise into a property of the rendering.
//
// Nothing here recomputes a total. If a number is needed that the API does not
// return, the fix belongs in services/statutory/, not in a reduce() on this
// side of the wire: a browser-computed total can disagree with the one that
// was exported, and there is no way to tell which the shop looked at.

export type DrillKind =
  | 'SALES' | 'SALE_LINES' | 'PURCHASES' | 'PURCHASE_LINES'
  | 'ITC_REVERSALS' | 'PAYMENTS';

export interface Drill {
  kind: DrillKind;
  filters: Record<string, unknown>;
  count: number | null;
}

export interface Figure {
  paise: number;
  value: number;
  drill: Drill | null;
  caveat: string | null;
}

export interface ReportRow {
  cells: Record<string, unknown>;
  drill: Drill | null;
  flags: string[];
}

export interface CrossCheck {
  code: string;
  label: string;
  agrees: boolean;
  difference: number;
  difference_paise: number;
  tolerance_paise: number;
  explanation: string;
  left: { label: string } & Figure;
  right: { label: string } & Figure;
}

export interface Gstr3bRow {
  code: string;
  label: string;
  taxable: Figure | null;
  igst: Figure | null;
  cgst: Figure | null;
  sgst: Figure | null;
  cess: Figure | null;
  auto_populated: boolean;
  note: string;
  caveats: string[];
}

export interface ItcSourceInfo {
  name: string;
  is_authoritative: boolean;
  caveats: string[];
  counted_invoices: number;
  excluded: Array<{ invoice_id: string; invoice_number: string; reason: string; tax_paise: number }>;
}

export interface Pack {
  period: {
    label: string;
    frequency: 'MONTHLY' | 'QUARTERLY';
    months: string[];
    start_date: string;
    end_date: string;
  };
  shop: {
    gstin: string | null;
    legal_name: string | null;
    trade_name: string | null;
    state_code: string | null;
    filing_frequency: string | null;
    hsn_digits: number;
  };
  checks_pass: boolean;
  failing_check_count: number;
  cross_checks: CrossCheck[];
  reports: {
    gstr1: {
      totals: Record<string, number>;
      tables: Record<string, any[]>;
      validation: { blocking: any[]; warnings: any[] };
      can_close: boolean;
      is_nil_return: boolean;
      payload: Record<string, unknown>;
    };
    gstr3b: {
      period_label: string;
      outward: Gstr3bRow[];
      itc: Gstr3bRow[];
      net_itc: Gstr3bRow | null;
      itc_source: ItcSourceInfo;
      auto_populated_warning: string;
    };
    purchase_register: { rows: ReportRow[]; row_count: number; totals: Record<string, Figure>; blocked_invoice_count: number };
    sales_register: {
      rows: ReportRow[];
      row_count: number;
      totals: Record<string, Figure>;
      filters_applied: Record<string, unknown>;
      available_filters: { rates: number[]; capture_modes: string[]; payment_methods: string[] };
    };
    hsn_summary: {
      outward: { b2b: ReportRow[]; b2c: ReportRow[]; unfilable_row_count: number; totals: Record<string, Figure> };
      inward: { rows: ReportRow[]; rows_without_uqc: number; rows_without_known_hsn: number; note: string; totals: Record<string, Figure> };
    };
    document_series: { rows: ReportRow[]; has_gaps: boolean; has_duplicates: boolean };
    itc_reversals: { rows: ReportRow[]; row_count: number; totals: Record<string, Figure>; note: string };
  };
}

export interface DrillResult {
  kind: DrillKind;
  rows: Array<Record<string, unknown>>;
  row_count: number;
  resolved_by: 'ids' | 'filters';
}

export type ReportId =
  | 'gstr1' | 'gstr3b' | 'purchase_register' | 'sales_register'
  | 'hsn_summary' | 'document_series' | 'itc_reversals';
