/**
 * The device's local store.
 *
 * A pharmacy's internet is not reliable, and a billing screen that stops when
 * the link drops is not a billing screen. So the counter reads from here and
 * writes to here, and the network is something that happens afterwards.
 *
 * What lives here, and why each is allowed to:
 *
 *   products / batches - a mirror of the master. A cache: nothing here feeds a
 *                        return, and it is rebuilt from the server on demand.
 *   serialBlock        - the range of invoice numbers this device owns.
 *   outbox             - bills issued but not yet acknowledged by the server.
 *   meta               - sync cursors and the device identity.
 *
 * The house rules put anything feeding a GST return in Neo4j and nowhere else,
 * with one carve-out: the offline outbox. That carve-out is exactly what this
 * is, and it is why the outbox is drained rather than treated as storage — a
 * bill lives here only until the server has it, and then the server is the
 * record.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb';

export const DB_NAME = 'pharmaflow-offline';
export const DB_VERSION = 1;

export interface MirroredProduct {
  product_id: string;
  name: string;
  pack: string | null;
  hsn: string | null;
  manufacturer: string | null;
  schedule: string | null;
  updated_at: string | null;
}

export interface MirroredBatch {
  batch_id: string;
  product_id: string;
  batch_number: string | null;
  expiry: string | null;
  /** Closing stock as the server last reported it, before local sales. */
  quantity_available: number;
  mrp_paise: number | null;
  source_invoice: string | null;
}

export interface StoredSerialBlock {
  id: string;
  prefix: string;
  financial_year: number;
  from_sequence: number;
  to_sequence: number;
  /** The next number this device will use. The only mutable field. */
  next_sequence: number;
  pad_to: number;
  device_id: string;
  allocated_at: string;
}

export type OutboxStatus = 'pending' | 'syncing' | 'failed' | 'synced';

export interface OutboxEntry {
  /** The bill's serial. Stable, unique per device, and already the server's
   *  idempotency key — so a retry cannot create a second entry either. */
  id: string;
  payload: unknown;
  status: OutboxStatus;
  attempts: number;
  /** Epoch ms. The backoff lives here rather than in a timer, so it survives
   *  the app being killed. */
  next_attempt_at: number;
  last_error: string | null;
  created_at: number;
  synced_at: number | null;
  /** Reconciliation tasks the server reported. Kept after a successful sync:
   *  they are the whole reason a shortfall is not a lost bill. */
  issues: { kind: string; line_id: string | null; detail: string }[] | null;
}

interface OfflineSchema extends DBSchema {
  products: { key: string; value: MirroredProduct };
  batches: { key: string; value: MirroredBatch; indexes: { by_product: string } };
  serialBlock: { key: string; value: StoredSerialBlock };
  outbox: {
    key: string;
    value: OutboxEntry;
    indexes: { by_status: string; by_created: number };
  };
  meta: { key: string; value: { key: string; value: unknown } };
}

let database: Promise<IDBPDatabase<OfflineSchema>> | null = null;

export function getDb(): Promise<IDBPDatabase<OfflineSchema>> {
  if (!database) {
    database = openDB<OfflineSchema>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('products')) {
          db.createObjectStore('products', { keyPath: 'product_id' });
        }
        if (!db.objectStoreNames.contains('batches')) {
          const batches = db.createObjectStore('batches', { keyPath: 'batch_id' });
          batches.createIndex('by_product', 'product_id');
        }
        if (!db.objectStoreNames.contains('serialBlock')) {
          db.createObjectStore('serialBlock', { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains('outbox')) {
          const outbox = db.createObjectStore('outbox', { keyPath: 'id' });
          outbox.createIndex('by_status', 'status');
          outbox.createIndex('by_created', 'created_at');
        }
        if (!db.objectStoreNames.contains('meta')) {
          db.createObjectStore('meta', { keyPath: 'key' });
        }
      },
    });
  }
  return database;
}

export async function getMeta<T>(key: string, fallback: T): Promise<T> {
  const db = await getDb();
  const row = await db.get('meta', key);
  return row === undefined ? fallback : (row.value as T);
}

export async function setMeta(key: string, value: unknown): Promise<void> {
  const db = await getDb();
  await db.put('meta', { key, value });
}

/**
 * This device's identity, minted once and kept.
 *
 * It is what a serial block is allocated against, so it has to survive
 * reloads. It is not returns data — the *block* is what matters, and that is
 * allocated and recorded server-side.
 */
export async function getDeviceId(): Promise<string> {
  const existing = await getMeta<string | null>('device_id', null);
  if (existing) return existing;
  const minted =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `dev-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  await setMeta('device_id', minted);
  return minted;
}

/** Wipes the mirror only. The outbox and the serial block are never cleared
 *  here — one holds bills that exist, the other holds numbers already used. */
export async function clearMirror(): Promise<void> {
  const db = await getDb();
  await db.clear('products');
  await db.clear('batches');
  await setMeta('products_cursor', null);
}
