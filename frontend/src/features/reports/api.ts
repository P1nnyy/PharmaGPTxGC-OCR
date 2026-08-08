// Typed access to the /reports/* endpoints.
//
// All aggregation happens server-side; nothing here sums anything. If a number
// is needed that the API does not return, the fix belongs in
// services/reports/, not in a reduce() on this side of the wire.

import type {
  DataQuality,
  ExpiryExposure,
  GstRegister,
  HsnSummary,
  PeriodQuery,
  PriceVariance,
  SpendTrend,
  ScanActivity,
  ScanGranularity,
  Summary,
  VendorScorecard
} from './types';

/** Drops undefined entries so an unset period field is absent, not "undefined". */
function toQueryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return query ? `?${query}` : '';
}

async function getReport<T>(path: string, params: Record<string, string | number | undefined>): Promise<T> {
  const response = await fetch(`/reports/${path}${toQueryString(params)}`);
  if (!response.ok) {
    // The API returns a user-facing message for bad periods; surface it rather
    // than replacing it with a generic failure string.
    let detail = `Request failed with ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // Non-JSON error body; the status-based message stands.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

function periodParams(query: PeriodQuery): Record<string, string | number | undefined> {
  return {
    kind: query.kind,
    fy: query.fy,
    quarter: query.quarter,
    month: query.month,
    start: query.start,
    end: query.end,
    statuses: query.statuses
  };
}

export const reportsApi = {
  summary: (query: PeriodQuery) => getReport<Summary>('summary', periodParams(query)),
  spendTrend: (query: PeriodQuery) => getReport<SpendTrend>('spend-trend', periodParams(query)),
  gstRegister: (query: PeriodQuery) => getReport<GstRegister>('gst-register', periodParams(query)),
  hsnSummary: (query: PeriodQuery) => getReport<HsnSummary>('hsn-summary', periodParams(query)),
  vendors: (query: PeriodQuery) => getReport<VendorScorecard>('vendors', periodParams(query)),
  priceVariance: (query: PeriodQuery) => getReport<PriceVariance>('price-variance', periodParams(query)),
  dataQuality: (query: PeriodQuery) => getReport<DataQuality>('data-quality', periodParams(query)),

  // Not period-scoped: stock bought in March can expire in September, so a
  // period filter would hide the batches worth acting on.
  expiry: (horizonDays = 180, statuses?: string) =>
    getReport<ExpiryExposure>('expiry', { horizon_days: horizonDays, statuses })
};

/**
 * Scanning activity. Takes no period: this is a lifetime figure, and tying it
 * to the page's period selector would make "total scans" change meaning
 * depending on a dropdown intended for the GST register.
 */
export function getScanActivity(granularity: ScanGranularity, limit: number): Promise<ScanActivity> {
  return getReport<ScanActivity>('scans', { granularity, limit });
}
