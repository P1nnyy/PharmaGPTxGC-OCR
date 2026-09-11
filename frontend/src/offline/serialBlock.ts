/**
 * The device's own range of invoice numbers, held locally.
 *
 * This is what makes billing work with no network at all. The serial is not
 * asked for at sale time — it comes from a block this device was handed in
 * advance and which no other device shares. That disjointness is the reason
 * sync has no ordering requirement and no merge conflicts: two bills cannot
 * claim one number, so there is nothing to reconcile.
 *
 * The cursor is persisted *before* a serial is handed out. Handing out a
 * number and then failing to record that it was used is the one ordering that
 * can duplicate a serial across two bills, so it is not the ordering used.
 *
 * This implements `SerialBlockStore` from `features/sell/serial.ts`, which was
 * left as an interface precisely so this decision could be made later.
 */

import { getDb, getDeviceId, getMeta, setMeta, type StoredSerialBlock } from './db';
import type { SerialBlock, SerialBlockStore } from '../features/sell/serial';

/** Warn the counter once four fifths of the block is gone. */
export const LOW_BLOCK_THRESHOLD = 0.8;

const CURRENT_BLOCK_KEY = 'current_block_id';

export async function currentBlock(): Promise<StoredSerialBlock | null> {
  const db = await getDb();
  const id = await getMeta<string | null>(CURRENT_BLOCK_KEY, null);
  if (id) {
    const found = await db.get('serialBlock', id);
    if (found && found.next_sequence <= found.to_sequence) return found;
  }
  // Either nothing recorded or the recorded one is exhausted: fall back to any
  // block with numbers left, oldest first so the series stays consecutive.
  const blocks = (await db.getAll('serialBlock'))
    .filter((block) => block.next_sequence <= block.to_sequence)
    .sort((a, b) => a.from_sequence - b.from_sequence);
  const next = blocks[0] ?? null;
  if (next) await setMeta(CURRENT_BLOCK_KEY, next.id);
  return next;
}

export async function storeBlock(block: StoredSerialBlock): Promise<void> {
  const db = await getDb();
  await db.put('serialBlock', block);
  const current = await currentBlock();
  if (!current) await setMeta(CURRENT_BLOCK_KEY, block.id);
}

/** How much of the block is gone, 0 to 1. */
export function consumption(block: StoredSerialBlock): number {
  const size = block.to_sequence - block.from_sequence + 1;
  if (size <= 0) return 1;
  return (block.next_sequence - block.from_sequence) / size;
}

export async function remaining(): Promise<number> {
  const db = await getDb();
  const blocks = await db.getAll('serialBlock');
  return blocks.reduce(
    (total, block) => total + Math.max(0, block.to_sequence - block.next_sequence + 1),
    0,
  );
}

/** True when the device should ask for another block while it still can. */
export async function isRunningLow(): Promise<boolean> {
  const block = await currentBlock();
  if (!block) return true;
  const db = await getDb();
  const spare = (await db.getAll('serialBlock')).filter(
    (other) => other.id !== block.id && other.next_sequence <= other.to_sequence,
  );
  // A spare block already in hand means there is nothing to be low on.
  if (spare.length > 0) return false;
  return consumption(block) >= LOW_BLOCK_THRESHOLD;
}

/**
 * The `SerialBlockStore` the counter screen consumes.
 *
 * `write` persists the advanced cursor synchronously with respect to the
 * caller — the counter awaits it before showing a bill as issued.
 */
export function createIndexedDbSerialStore(): SerialBlockStore {
  return {
    async read(): Promise<SerialBlock | null> {
      const block = await currentBlock();
      if (!block) return null;
      return {
        prefix: block.prefix,
        financial_year: `${block.financial_year}-${String((block.financial_year + 1) % 100).padStart(2, '0')}`,
        from_sequence: block.from_sequence,
        to_sequence: block.to_sequence,
        next_sequence: block.next_sequence,
        pad_to: block.pad_to,
      };
    },
    async write(block: SerialBlock): Promise<void> {
      const db = await getDb();
      const stored = await currentBlock();
      if (!stored) throw new Error('No serial block to advance.');
      await db.put('serialBlock', { ...stored, next_sequence: block.next_sequence });
    },
  };
}

/** Identity for a block request. */
export async function deviceId(): Promise<string> {
  return getDeviceId();
}
