// Typed access to /compliance/*.
//
// There is no file() call here, and there is not going to be one in this
// milestone. Every write records something that already happened on the
// portal; filing itself will be a separate, OTP-gated action.

import type {
  CalendarReport, FilingRow, NextAction, ReminderSettings,
  RemindersReport, TimeBarReport, TimelineReport
} from './types';

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/compliance/${path}`, init);
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

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body)
});

export const complianceApi = {
  nextAction: () => call<NextAction>('next-action'),
  calendar: (financialYear?: number) =>
    call<CalendarReport>(`calendar${financialYear ? `?financial_year=${financialYear}` : ''}`),
  timeBar: () => call<TimeBarReport>('time-bar'),
  timeline: (period: string) => call<TimelineReport>(`timeline/${period}`),

  filings: (periods?: string[]) =>
    call<{ rows: FilingRow[]; row_count: number }>(
      `filings${periods?.length ? `?periods=${periods.join(',')}` : ''}`
    ),
  filingPayload: (filingId: string) =>
    call<{ arn: string; filed_at: string; period: string; return_type: string;
           payload: unknown; payload_missing: boolean }>(`filings/${filingId}/payload`),

  /** Records a filing that has already happened on the portal. Never files. */
  recordFiling: (body: {
    period: string; return_type: string; arn: string; filed_at: string;
    covers_months?: string[]; note?: string;
  }) => call<FilingRow>('filings', json(body)),

  reminders: (preview = false) =>
    call<RemindersReport>(`reminders${preview ? '?preview=true' : ''}`),
  setReminders: (body: { enabled: boolean; days_before?: number[]; channel?: string }) =>
    call<ReminderSettings>('reminders', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
};
