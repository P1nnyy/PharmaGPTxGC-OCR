/**
 * The outbox, against a real IndexedDB implementation.
 *
 * These are the tests that matter most in the whole offline design, because
 * this is the only place a bill can be lost. A bill in the outbox has been
 * printed and handed to a customer; every property below is a restatement of
 * "and therefore it must still be here afterwards".
 */

import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getDb } from './db';
import {
  allEntries,
  counts,
  due,
  enqueue,
  markFailed,
  markSynced,
  prune,
  reconciliationTasks,
  unsynced,
} from './outbox';
import { drainOutbox } from './sync';

async function wipe() {
  const db = await getDb();
  await db.clear('outbox');
  await db.clear('meta');
}

const aBill = (serial: string) => ({ serial, grand_total_paise: 11200 });

beforeEach(wipe);

describe('enqueue', () => {
  it('stores a bill immediately', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    const entries = await allEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].status).toBe('pending');
    expect(entries[0].attempts).toBe(0);
  });

  it('is keyed on the serial, so a double submit does not queue twice', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    await enqueue('CTR-000001', aBill('CTR-000001'));
    expect(await allEntries()).toHaveLength(1);
  });

  it('does not resurrect a bill the server already has', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    await markSynced('CTR-000001', null);
    await enqueue('CTR-000001', aBill('CTR-000001'));
    const entries = await allEntries();
    expect(entries[0].status).toBe('synced');
  });
});

describe('failure never loses a bill', () => {
  it('keeps the entry after a failed attempt', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    await markFailed('CTR-000001', 'network down');
    const entries = await allEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].last_error).toBe('network down');
    expect(entries[0].attempts).toBe(1);
  });

  it('keeps it after many failures', async () => {
    // There is no attempt count at which discarding becomes right.
    await enqueue('CTR-000001', aBill('CTR-000001'));
    for (let i = 0; i < 50; i += 1) await markFailed('CTR-000001', 'still down');
    const entries = await unsynced();
    expect(entries).toHaveLength(1);
    expect(entries[0].attempts).toBe(50);
  });

  it('backs off further with each failure', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    await markFailed('CTR-000001', 'down');
    const first = (await allEntries())[0].next_attempt_at;
    await markFailed('CTR-000001', 'down');
    const second = (await allEntries())[0].next_attempt_at;
    expect(second).toBeGreaterThan(first);
  });

  it('holds an entry back until its backoff has elapsed', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    await markFailed('CTR-000001', 'down');
    expect(await due(Date.now())).toHaveLength(0);
    expect(await due(Date.now() + 60 * 60_000)).toHaveLength(1);
  });

  it('never prunes anything unsynced, however old', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    const db = await getDb();
    const entry = (await allEntries())[0];
    await db.put('outbox', { ...entry, created_at: 0 });
    await prune(1);
    expect(await allEntries()).toHaveLength(1);
  });
});

describe('draining', () => {
  it('marks a bill synced when the server takes it', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    const result = await drainOutbox(async () => ({ issues: [] }));
    expect(result).toEqual({ sent: 1, failed: 0 });
    expect((await allEntries())[0].status).toBe('synced');
  });

  it('leaves a bill queued when the server refuses it', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    const result = await drainOutbox(async () => {
      throw new Error('500');
    });
    expect(result).toEqual({ sent: 0, failed: 1 });
    expect((await unsynced())).toHaveLength(1);
  });

  it('drains a full outbox in one pass', async () => {
    // The "app killed and reopened with a full outbox" case.
    for (let i = 1; i <= 25; i += 1) await enqueue(`CTR-${String(i).padStart(6, '0')}`, aBill('x'));
    const result = await drainOutbox(async () => ({ issues: [] }));
    expect(result.sent).toBe(25);
    expect(await unsynced()).toHaveLength(0);
  });

  it('does not let one bad bill block the rest', async () => {
    await enqueue('CTR-000001', aBill('a'));
    await enqueue('CTR-000002', aBill('b'));
    await enqueue('CTR-000003', aBill('c'));
    const post = vi.fn(async (payload: unknown) => {
      if ((payload as { serial: string }).serial === 'b') throw new Error('rejected');
      return { issues: [] };
    });
    const result = await drainOutbox(post);
    expect(result).toEqual({ sent: 2, failed: 1 });
  });

  it('replays safely — sending the same bill twice is harmless', async () => {
    // The server dedupes on the serial, so the outbox is free to retry a bill
    // it never saw the answer for.
    await enqueue('CTR-000001', aBill('CTR-000001'));
    const post = vi.fn(async () => ({ issues: [] }));
    await drainOutbox(post);
    await drainOutbox(post);
    // Second pass has nothing due: the entry is already synced.
    expect(post).toHaveBeenCalledTimes(1);
  });
});

describe('reconciliation tasks', () => {
  it('keeps what the server flagged after a successful sync', async () => {
    // The bill is in the customer's hand. A stock shortfall is a task, and
    // dropping it here would lose the only record of it.
    await enqueue('CTR-000001', aBill('CTR-000001'));
    await drainOutbox(async () => ({
      issues: [{ kind: 'insufficient_stock', line_id: 'l1', detail: 'sold 2, stock showed 1' }],
    }));
    const tasks = await reconciliationTasks();
    expect(tasks).toHaveLength(1);
    expect(tasks[0].status).toBe('synced');
    expect(tasks[0].issues![0].kind).toBe('insufficient_stock');
  });

  it('never prunes a synced bill that still has a task on it', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    await drainOutbox(async () => ({
      issues: [{ kind: 'insufficient_stock', line_id: 'l1', detail: 'short' }],
    }));
    const db = await getDb();
    const entry = (await allEntries())[0];
    await db.put('outbox', { ...entry, synced_at: 0 });
    await prune(1);
    expect(await allEntries()).toHaveLength(1);
  });

  it('does prune a synced bill with nothing outstanding', async () => {
    await enqueue('CTR-000001', aBill('CTR-000001'));
    await drainOutbox(async () => ({ issues: [] }));
    const db = await getDb();
    const entry = (await allEntries())[0];
    await db.put('outbox', { ...entry, synced_at: 0 });
    await prune(1);
    expect(await allEntries()).toHaveLength(0);
  });
});

describe('counts', () => {
  it('reports what the status bar shows', async () => {
    await enqueue('CTR-000001', aBill('a'));
    await enqueue('CTR-000002', aBill('b'));
    await markSynced('CTR-000002', [{ kind: 'insufficient_stock', line_id: null, detail: 'x' }]);
    for (let i = 0; i < 5; i += 1) await markFailed('CTR-000001', 'down');

    const summary = await counts();
    expect(summary.pending).toBe(1);
    expect(summary.failing).toBe(1);
    expect(summary.synced).toBe(1);
    expect(summary.needingReconciliation).toBe(1);
  });
});
