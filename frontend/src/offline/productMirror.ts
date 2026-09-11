/**
 * The catalogue, mirrored onto the device.
 *
 * The counter searches this, not the network, so a dropped link changes
 * nothing about typing a medicine name. It is a cache and nothing more —
 * no figure here feeds a return, and it can be thrown away and rebuilt.
 *
 * The refresh is delta-based: `/products/delta` takes the `server_time` from
 * the last successful sync and returns only what changed. On a bad line the
 * difference between sending a few rows and re-downloading a catalogue of
 * thousands is the difference between reconnecting in a second and in a
 * minute — and a shop on a weak connection is exactly the shop that
 * reconnects most often.
 *
 * Batch stock is refreshed wholesale rather than by delta. It is a derived
 * figure that moves whenever any invoice is verified, so "what changed" is
 * close to "everything"; a cursor there would cost a query and save nothing.
 */

import { getDb, getMeta, setMeta, type MirroredBatch, type MirroredProduct } from './db';
import type { SellableBatch, SellableProduct } from '../features/sell/types';

const CURSOR_KEY = 'products_cursor';

interface DeltaResponse {
  products: {
    id: string;
    canonical_name: string | null;
    hsn: string | null;
    manufacturer: string | null;
    pack_size: string | null;
    schedule: string | null;
    updated_at: string | null;
    created_at: string | null;
  }[];
  server_time: string;
  full: boolean;
}

interface StockResponse {
  items: {
    id: string;
    product: string | null;
    product_id: string | null;
    batch: string | null;
    expiry: string | null;
    quantity: number;
    mrp: number | null;
    source_invoice: string | null;
  }[];
}

/** Pulls what changed since the last sync into the local mirror. */
export async function refreshMirror(): Promise<{ products: number; batches: number; full: boolean }> {
  const db = await getDb();
  const cursor = await getMeta<string | null>(CURSOR_KEY, null);

  const query = cursor ? `?since=${encodeURIComponent(cursor)}` : '';
  const deltaResponse = await fetch(`/products/delta${query}`);
  if (!deltaResponse.ok) throw new Error(`Catalogue refresh failed with ${deltaResponse.status}`);
  const delta = (await deltaResponse.json()) as DeltaResponse;

  // A full response replaces the mirror; a delta merges into it. Merging a
  // full response would leave behind products the server has since removed.
  if (delta.full) await db.clear('products');

  const productTx = db.transaction('products', 'readwrite');
  for (const product of delta.products) {
    const row: MirroredProduct = {
      product_id: product.id,
      name: product.canonical_name ?? '',
      pack: product.pack_size ?? null,
      hsn: product.hsn ?? null,
      manufacturer: product.manufacturer ?? null,
      schedule: product.schedule ?? null,
      updated_at: product.updated_at ?? product.created_at ?? null,
    };
    await productTx.store.put(row);
  }
  await productTx.done;

  const stockResponse = await fetch('/inventory/stock');
  if (!stockResponse.ok) throw new Error(`Stock refresh failed with ${stockResponse.status}`);
  const stock = (await stockResponse.json()) as StockResponse;

  await db.clear('batches');
  const batchTx = db.transaction('batches', 'readwrite');
  for (const item of stock.items) {
    if (!item.product) continue;
    const row: MirroredBatch = {
      batch_id: item.id,
      product_id: item.product_id ?? item.id,
      batch_number: item.batch,
      expiry: item.expiry,
      quantity_available: item.quantity,
      // Rupees on the wire, paise everywhere past this boundary.
      mrp_paise: item.mrp === null ? null : Math.round(item.mrp * 100),
      source_invoice: item.source_invoice,
    };
    await batchTx.store.put(row);
  }
  await batchTx.done;

  // Written only after both halves landed. A cursor advanced past a refresh
  // that then failed would skip those changes forever.
  await setMeta(CURSOR_KEY, delta.server_time);

  return { products: delta.products.length, batches: stock.items.length, full: delta.full };
}

/**
 * The catalogue as the counter screen wants it, read entirely from the device.
 *
 * Falls back to the raw stock name for a holding whose product never resolved,
 * matching what the online path does — the pharmacy physically holds it, and
 * hiding it would make stock on the shelf unsellable.
 */
export async function readSellable(): Promise<SellableProduct[]> {
  const db = await getDb();
  const [products, batches] = await Promise.all([db.getAll('products'), db.getAll('batches')]);
  const byId = new Map(products.map((product) => [product.product_id, product]));

  const grouped = new Map<string, SellableProduct>();
  for (const batch of batches) {
    const product = byId.get(batch.product_id);
    const existing = grouped.get(batch.product_id) ?? {
      product_id: batch.product_id,
      name: product?.name || batch.product_id,
      pack: product?.pack ?? null,
      hsn: product?.hsn ?? null,
      manufacturer: product?.manufacturer ?? null,
      schedule: product?.schedule ?? null,
      batches: [] as SellableBatch[],
    };
    existing.batches.push({
      batch_id: batch.batch_id,
      batch_number: batch.batch_number,
      expiry: batch.expiry,
      quantity_available: batch.quantity_available,
      mrp_paise: batch.mrp_paise,
      source_invoice: batch.source_invoice,
    });
    grouped.set(batch.product_id, existing);
  }

  return [...grouped.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export async function hasMirror(): Promise<boolean> {
  const db = await getDb();
  return (await db.count('batches')) > 0;
}
