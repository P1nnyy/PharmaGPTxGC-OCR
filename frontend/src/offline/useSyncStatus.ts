import { useCallback, useEffect, useState } from 'react';

import { readStatus, startSync, subscribe, syncNow, type SyncStatus } from './sync';

const IDLE: SyncStatus = {
  online: true,
  syncing: false,
  pending: 0,
  failing: 0,
  needingReconciliation: 0,
  lastSyncAt: null,
  lastError: null,
  serialsRemaining: 0,
  serialsLow: false,
};

/** Live sync state, plus an explicit way to force a pass. */
export function useSyncStatus(): SyncStatus & { syncNow: () => void } {
  const [status, setStatus] = useState<SyncStatus>(IDLE);

  useEffect(() => {
    const unsubscribe = subscribe(setStatus);
    const stopSync = startSync();
    return () => {
      unsubscribe();
      stopSync();
    };
  }, []);

  // The browser's online event is not always trustworthy, so the status is
  // also re-read whenever the tab comes back to the foreground — which is
  // exactly when someone is about to look at it.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') void readStatus().then(setStatus);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  return { ...status, syncNow: useCallback(() => void syncNow(), []) };
}
