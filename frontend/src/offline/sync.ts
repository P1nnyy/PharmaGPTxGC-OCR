/**
 * Draining the outbox, and keeping the device stocked to work without a link.
 *
 * Three jobs, in this order of importance:
 *
 *   1. get issued bills to the server,
 *   2. keep a serial block in hand so billing can continue offline,
 *   3. refresh the catalogue mirror.
 *
 * The order is deliberate. A bill that has not synced is the only one of the
 * three where something can be lost, so it goes first and the other two never
 * block it.
 *
 * Nothing here resolves conflicts, because none can arise. A bill's serial
 * comes from a block only this device owns, and the server treats that serial
 * as its idempotency key — so the outbox can be replayed in any order, any
 * number of times, from any number of devices, and converge.
 */

import { counts, due, markFailed, markSynced, markSyncing, prune, type SyncIssue } from './outbox';
import { currentBlock, isRunningLow, storeBlock } from './serialBlock';
import { getDeviceId, getMeta, setMeta } from './db';
import { refreshMirror } from './productMirror';

/** Series prefix for this pharmacy's counter bills. */
const DEFAULT_PREFIX = 'CTR-';
const LAST_SYNC_KEY = 'last_sync_at';

export interface SyncStatus {
  online: boolean;
  syncing: boolean;
  pending: number;
  failing: number;
  needingReconciliation: number;
  lastSyncAt: number | null;
  lastError: string | null;
  serialsRemaining: number;
  serialsLow: boolean;
}

type Listener = (status: SyncStatus) => void;

const listeners = new Set<Listener>();
let syncing = false;
let lastError: string | null = null;
let timer: number | null = null;

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  void readStatus().then(listener);
  return () => listeners.delete(listener);
}

async function announce(): Promise<void> {
  const status = await readStatus();
  listeners.forEach((listener) => listener(status));
}

export async function readStatus(): Promise<SyncStatus> {
  const [outbox, block, low, lastSyncAt] = await Promise.all([
    counts(),
    currentBlock(),
    isRunningLow(),
    getMeta<number | null>(LAST_SYNC_KEY, null),
  ]);
  const remaining = block ? Math.max(0, block.to_sequence - block.next_sequence + 1) : 0;
  return {
    online: typeof navigator === 'undefined' ? true : navigator.onLine,
    syncing,
    pending: outbox.pending,
    failing: outbox.failing,
    needingReconciliation: outbox.needingReconciliation,
    lastSyncAt,
    lastError,
    serialsRemaining: remaining,
    serialsLow: low,
  };
}

/** POSTs one bill. Separated so tests can drive the outbox without a network. */
async function postSale(payload: unknown): Promise<{ issues: SyncIssue[] }> {
  const response = await fetch('/sales', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let detail = `Sync failed with ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // Non-JSON error body; the status-based message stands.
    }
    // A 4xx is not retried into oblivion, but neither is it discarded — the
    // entry keeps its place in the outbox and surfaces as a failure a person
    // can see and act on.
    throw new Error(detail);
  }
  const body = await response.json();
  return { issues: (body?.issues ?? []) as SyncIssue[] };
}

/** Sends everything whose backoff has elapsed. */
export async function drainOutbox(post = postSale): Promise<{ sent: number; failed: number }> {
  let sent = 0;
  let failed = 0;
  for (const entry of await due()) {
    await markSyncing(entry.id);
    try {
      const { issues } = await post(entry.payload);
      await markSynced(entry.id, issues);
      sent += 1;
    } catch (error) {
      await markFailed(entry.id, error instanceof Error ? error.message : String(error));
      failed += 1;
    }
  }
  return { sent, failed };
}

/** Asks for another block while there is still a network to ask over. */
export async function topUpSerials(prefix: string = DEFAULT_PREFIX): Promise<boolean> {
  if (!(await isRunningLow())) return false;
  const device_id = await getDeviceId();
  const response = await fetch('/sales/serial-blocks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id, prefix }),
  });
  if (!response.ok) throw new Error(`Could not get more bill numbers (${response.status}).`);
  const block = await response.json();
  await storeBlock({
    id: block.id,
    prefix: block.prefix,
    financial_year: block.financial_year,
    from_sequence: block.from_sequence,
    to_sequence: block.to_sequence,
    next_sequence: block.next_sequence,
    pad_to: block.pad_to,
    device_id: block.device_id,
    allocated_at: block.allocated_at,
  });
  return true;
}

/**
 * One full pass. Safe to call at any time, including with no network.
 *
 * Each step is attempted independently: a catalogue refresh that fails must
 * not stop bills from syncing, and vice versa.
 */
export async function syncNow(): Promise<SyncStatus> {
  if (syncing) return readStatus();
  syncing = true;
  lastError = null;
  await announce();

  let anythingWorked = false;
  try {
    const drained = await drainOutbox();
    anythingWorked = drained.failed === 0;
  } catch (error) {
    lastError = error instanceof Error ? error.message : String(error);
  }

  for (const step of [topUpSerials, refreshMirror]) {
    try {
      await step();
      anythingWorked = true;
    } catch (error) {
      // Recorded, not thrown: the outbox drain above is the part that matters
      // and it has already happened.
      lastError = error instanceof Error ? error.message : String(error);
    }
  }

  if (anythingWorked) await setMeta(LAST_SYNC_KEY, Date.now());
  await prune().catch(() => 0);

  syncing = false;
  await announce();
  return readStatus();
}

/**
 * Starts syncing in the background.
 *
 * Wakes on reconnect and on a slow interval. The interval matters as much as
 * the event: `online` fires when the OS thinks there is a link, which is not
 * the same as the shop's connection actually working, so a periodic retry is
 * what eventually gets a bill through after a flaky reconnect.
 */
export function startSync(intervalMs = 30_000): () => void {
  const onOnline = () => {
    void syncNow();
  };
  const onOffline = () => {
    void announce();
  };
  window.addEventListener('online', onOnline);
  window.addEventListener('offline', onOffline);
  timer = window.setInterval(() => {
    if (navigator.onLine) void syncNow();
  }, intervalMs);

  if (navigator.onLine) void syncNow();

  return () => {
    window.removeEventListener('online', onOnline);
    window.removeEventListener('offline', onOffline);
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  };
}
