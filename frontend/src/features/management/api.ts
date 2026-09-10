// Typed access to /management/*.

import type {
  DailySalesReport, DashboardReport, ExpiryReport, LedgerReport,
  MarginReport, MoversReport, TrendReport, VendorRow, VendorScorecard
} from './types';

function queryString(params: Record<string, unknown> | object): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : '';
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/management/${path}`, init);
  if (!response.ok) {
    let detail = `Request failed with ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // Non-JSON body; the status message stands.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export interface WindowQuery { start?: string; end?: string }

export const managementApi = {
  dashboard: () => call<DashboardReport>('dashboard'),
  expiryRisk: (horizonDays = 180) =>
    call<ExpiryReport>(`expiry-risk${queryString({ horizon_days: horizonDays })}`),
  margin: (q: WindowQuery = {}) => call<MarginReport>(`margin${queryString(q)}`),
  stockLedger: (q: WindowQuery & { product_id?: string; batch_number?: string; reason?: string } = {}) =>
    call<LedgerReport>(`stock-ledger${queryString(q)}`),
  movers: (q: WindowQuery & { limit?: number } = {}) =>
    call<MoversReport>(`movers${queryString(q)}`),
  dailySales: (month?: string) =>
    call<DailySalesReport>(`daily-sales${queryString({ month })}`),
  trend: (q: WindowQuery = {}) => call<TrendReport>(`trend${queryString(q)}`),
  vendorScorecard: (q: WindowQuery = {}) =>
    call<VendorScorecard>(`vendor-scorecard${queryString(q)}`),

  vendors: () => call<{ rows: VendorRow[]; missing_return_window_count: number; note: string }>('vendors'),
  setReturnWindow: (vendorId: string, days: number | null, note?: string) =>
    call<VendorRow>(`vendors/${vendorId}/return-window`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ return_window_days: days, return_window_note: note })
    })
};
