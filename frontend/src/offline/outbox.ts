/**
 * Bills that exist but the server has not acknowledged yet.
 *
 * The rule the whole module is built around: **an entry is never discarded.**
 * A bill in here was printed and handed to a customer. There is no error, no
 * attempt count and no server response that makes deleting it the right answer
 * — the worst case is a bill the books do not know about, and that is precisely
 * what this exists to prevent.
 *
 * So failures accumulate state rather than removing rows. An entry moves to
 * `synced` only when the server has confirmed it, and even then it is kept if
 * it came back with reconciliation tasks attached.
 *
 * There is no conflict resolution here and none is needed. The entry's id is
 * the bill's serial, which came from a block only this device owns and which
 * the server treats as its idempotency key. Replaying the whole outbox in any
 * order, any number of times, converges on the same records.
 */

import { getDb, type OutboxEntry } from './db';
import { isVisiblyFailing, nextAttemptAt } from './backoff';

export interface SyncIssue {
  kind: string;
  line_id: string | null;
  detail: string;
}

/**
 * Adds a bill to the outbox.
 *
 * Keyed on the serial, so an accidental double-submit of the same bill
 * overwrites rather than queueing twice. `put` rather than `add` deliberately:
 * failing here would leave the counter unable to record a sale it had already
 * printed.
 */
export async function enqueue(serial: string, payload: unknown): Promise<OutboxEntry> {
  const db = await getDb();
  const existing = await db.get('outbox', serial);
  if (existing && existing.status === 'synced') return existing;

  const entry: OutboxEntry = existing ?? {
    id: serial,
    payload,
    status: 'pending',
    attempts: 0,
    next_attempt_at: Date.now(),
    last_error: null,
    created_at: Date.now(),
    synced_at: null,
    issues: null,
  };
  entry.payload = payload;
  await db.put('outbox', entry);
  return entry;
}

export async function allEntries(): Promise<OutboxEntry[]> {
  const db = await getDb();
  const entries = await db.getAll('outbox');
  return entries.sort((a, b) => a.created_at - b.created_at);
}

/** Entries still owed to the server, oldest first. */
export async function unsynced(): Promise<OutboxEntry[]> {
  return (await allEntries()).filter((entry) => entry.status !== 'synced');
}

/** Entries whose backoff has elapsed. */
export async function due(now: number = Date.now()): Promise<OutboxEntry[]> {
  return (await unsynced()).filter((entry) => entry.next_attempt_at <= now);
}

export interface OutboxCounts {
  pending: number;
  failing: number;
  synced: number;
  /** Entries the server accepted but flagged — stock shortfalls and the like. */
  needingReconciliation: number;
}

export async function counts(): Promise<OutboxCounts> {
  const entries = await allEntries();
  return {
    pending: entries.filter((e) => e.status !== 'synced').length,
    failing: entries.filter((e) => e.status !== 'synced' && isVisiblyFailing(e.attempts)).length,
    synced: entries.filter((e) => e.status === 'synced').length,
    needingReconciliation: entries.filter((e) => (e.issues?.length ?? 0) > 0).length,
  };
}

export async function markSyncing(id: string): Promise<void> {
  const db = await getDb();
  const entry = await db.get('outbox', id);
  if (!entry) return;
  await db.put('outbox', { ...entry, status: 'syncing' });
}

export async function markSynced(id: string, issues: SyncIssue[] | null): Promise<void> {
  const db = await getDb();
  const entry = await db.get('outbox', id);
  if (!entry) return;
  await db.put('outbox', {
    ...entry,
    status: 'synced',
    synced_at: Date.now(),
    last_error: null,
    // Kept, not cleared: a shortfall the server reported is a task for a
    // person, and dropping it here would lose the only record of it.
    issues: issues && issues.length > 0 ? issues : null,
  });
}

export async function markFailed(id: string, error: string): Promise<void> {
  const db = await getDb();
  const entry = await db.get('outbox', id);
  if (!entry) return;
  const attempts = entry.attempts + 1;
  await db.put('outbox', {
    ...entry,
    // Never 'discarded'. The bill exists; it simply has not landed yet.
    status: 'failed',
    attempts,
    last_error: error,
    next_attempt_at: nextAttemptAt(attempts),
  });
}

/** Entries the server accepted but flagged for someone to sort out. */
export async function reconciliationTasks(): Promise<OutboxEntry[]> {
  return (await allEntries()).filter((entry) => (entry.issues?.length ?? 0) > 0);
}

export async function clearReconciliation(id: string): Promise<void> {
  const db = await getDb();
  const entry = await db.get('outbox', id);
  if (!entry) return;
  await db.put('outbox', { ...entry, issues: null });
}

/**
 * Removes synced entries that have nothing outstanding.
 *
 * Only ever synced-and-clean rows, and only once they are old enough that the
 * shift they belong to is over. Anything unsynced, and anything carrying a
 * reconciliation task, stays regardless of age.
 */
export async function prune(olderThanMs: number = 7 * 24 * 60 * 60_000): Promise<number> {
  const db = await getDb();
  const cutoff = Date.now() - olderThanMs;
  let removed = 0;
  for (const entry of await allEntries()) {
    if (entry.status !== 'synced') continue;
    if ((entry.issues?.length ?? 0) > 0) continue;
    if ((entry.synced_at ?? entry.created_at) > cutoff) continue;
    await db.delete('outbox', entry.id);
    removed += 1;
  }
  return removed;
}
