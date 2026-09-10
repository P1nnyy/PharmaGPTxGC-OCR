// Typed access to /tax-periods/*.
//
// Three calls, and the split between them is the safety property: the preview
// computes and changes nothing, the payload is what would be (or was) filed,
// and the close is the only thing that locks anything. Nothing here posts a
// figure back - the close sends only the ids of blocking items a person has
// accepted, and the server recomputes everything else from the records.

import type { Gstr1Return } from './types';

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/tax-periods/${path}`, init);
  if (!response.ok) {
    let detail = `Request failed with ${response.status}`;
    try {
      const body = await response.json();
      // A refused close returns a structured detail carrying the outstanding
      // items; keep it whole so the screen can list them rather than
      // flattening it to a sentence.
      if (typeof body?.detail === 'string') detail = body.detail;
      else if (body?.detail?.message) {
        const error = new Error(body.detail.message) as Error & { outstanding?: unknown };
        error.outstanding = body.detail.outstanding;
        throw error;
      }
    } catch (error) {
      if (error instanceof Error && error.message !== detail) throw error;
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const gstr1Api = {
  /** The return as it currently stands. Safe to call as often as you like. */
  preview: (period: string) => call<Gstr1Return>(period),

  /** The GSTN offline-utility JSON. For a closed period, what was actually filed. */
  payload: (period: string) => call<Record<string, unknown>>(`${period}/payload`),

  /** Locks the period. `acknowledged` carries the blocking items a person accepted. */
  close: (period: string, acknowledged: string[]) =>
    call<Gstr1Return>(`${period}/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acknowledged })
    })
};
