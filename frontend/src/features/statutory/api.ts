// Typed access to /statutory/*.
//
// Exports are downloaded by navigating to the endpoint rather than by building
// a file here: the server already renders CSV and Excel from the same pack the
// screen is showing, and generating either in the browser would be a second
// implementation of the arithmetic that could disagree with the first.

import type { DrillResult, Pack, ReportId } from './types';
import type { Drill } from './types';
import { getToken } from '../../api/session';

export interface PackQuery {
  vendor?: string;
  rate?: number;
  capture_mode?: string;
  payment_method?: string;
}

function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : '';
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/statutory/${path}`, init);
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

export const statutoryApi = {
  pack: (period: string, query: PackQuery = {}) =>
    call<Pack>(`${period}${queryString(query as Record<string, unknown>)}`),

  drill: (drill: Drill) =>
    call<DrillResult>('drill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(drill)
    }),

  /** Downloads a report. The blob is fetched rather than linked so the
   *  Authorization header goes with it - a bare <a href> carries no token. */
  download: async (period: string, reportId: ReportId | 'hsn_inward', fmt: 'csv' | 'xlsx', query: PackQuery = {}) => {
    const token = getToken();
    const response = await fetch(
      `/statutory/${period}/export/${reportId}${queryString({ ...query, fmt })}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : undefined }
    );
    if (!response.ok) throw new Error(`Export failed with ${response.status}`);

    const disposition = response.headers.get('content-disposition') || '';
    const match = /filename="([^"]+)"/.exec(disposition);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = match ? match[1] : `${reportId}-${period}.${fmt}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
};
