import { useCallback, useEffect, useState } from 'react';

import type { PeriodQuery } from './types';

export interface ReportState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Fetches one report and tracks its request state.
 *
 * Stale responses are discarded rather than rendered: changing the period
 * fires a new request while the previous one is still open, and without the
 * cancellation flag a slow first response can land after a fast second one and
 * overwrite the newer data with older figures.
 */
export function useReport<T>(
  fetcher: () => Promise<T>,
  deps: unknown[]
): ReportState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    fetcher()
      .then((result) => {
        if (!active) return;
        setData(result);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : 'Could not load this report.');
        // The previous report's data is cleared on failure: leaving it on
        // screen under a new period label would misattribute the figures.
        setData(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken]);

  return { data, loading, error, reload };
}

/** Serialises a period into a stable dependency key for `useReport`. */
export function periodKey(query: PeriodQuery): string {
  return [query.kind, query.fy, query.quarter, query.month, query.start, query.end, query.statuses]
    .map((part) => part ?? '')
    .join('|');
}
