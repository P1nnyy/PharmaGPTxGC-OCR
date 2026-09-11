/**
 * What the counter can see about syncing.
 *
 * The brief was "do not hide failures", and that shapes everything here. A
 * pending count is shown even when it is healthy, a failure is shown in a
 * colour that means something is wrong, and "sync now" is always available
 * rather than appearing only once something has gone wrong — a person who
 * suspects a problem should be able to act on the suspicion.
 *
 * What it deliberately does not do is block. Nothing in this bar can stop a
 * sale being rung up, because the whole point of the offline design is that
 * the network is not on the critical path.
 */

import React from 'react';
import { AlertTriangle, Check, CloudOff, Loader2, RefreshCw, TicketX } from 'lucide-react';

import { useSyncStatus } from './useSyncStatus';

function ago(at: number | null): string {
  if (at === null) return 'never';
  const seconds = Math.round((Date.now() - at) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

export const SyncStatusBar: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const status = useSyncStatus();
  // Re-renders on a timer so "3 min ago" does not sit still while someone
  // watches it, which reads as a frozen screen.
  const [, tick] = React.useState(0);
  React.useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const trouble = status.failing > 0 || status.lastError !== null;
  const tone = !status.online
    ? 'bg-slate-100 border-slate-200 text-slate-600'
    : trouble
      ? 'bg-red-50 border-red-200 text-red-700'
      : status.pending > 0
        ? 'bg-amber-50 border-amber-200 text-amber-800'
        : 'bg-white border-[#e2e8f0] text-gray-500';

  return (
    <div className={`flex items-center gap-2 border rounded-xl px-3 py-2 ${tone}`}>
      {status.syncing ? (
        <Loader2 size={14} className="animate-spin shrink-0" />
      ) : !status.online ? (
        <CloudOff size={14} className="shrink-0" />
      ) : trouble ? (
        <AlertTriangle size={14} className="shrink-0" />
      ) : (
        <Check size={14} className="shrink-0" />
      )}

      <div className="min-w-0 flex-1 leading-tight">
        <p className="text-[11px] font-semibold truncate">
          {!status.online
            ? 'Offline — billing as normal'
            : status.pending > 0
              ? `${status.pending} bill${status.pending === 1 ? '' : 's'} waiting to sync`
              : 'All bills synced'}
        </p>
        {!compact && (
          <p className="text-[10px] opacity-80 truncate">
            Last sync {ago(status.lastSyncAt)}
            {status.failing > 0 && ` · ${status.failing} failing`}
            {status.lastError && ` · ${status.lastError}`}
          </p>
        )}
      </div>

      {/* Shown before the block runs out, while there is still a network to
          fetch another over. */}
      {status.serialsLow && (
        <span
          title={`${status.serialsRemaining} bill numbers left on this device. Connect to get more.`}
          className="shrink-0 flex items-center gap-1 text-[10px] font-bold text-amber-700 bg-amber-100 border border-amber-200 rounded-lg px-1.5 py-0.5"
        >
          <TicketX size={11} />
          {status.serialsRemaining}
        </span>
      )}

      <button
        onClick={status.syncNow}
        disabled={status.syncing}
        className="shrink-0 flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded-lg border border-current/20 hover:bg-black/5 cursor-pointer disabled:opacity-40"
      >
        <RefreshCw size={11} className={status.syncing ? 'animate-spin' : ''} />
        Sync now
      </button>
    </div>
  );
};
