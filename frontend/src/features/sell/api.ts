/**
 * Typed access to what the counter needs.
 *
 * Reads are real. The sellable list is a join of two existing endpoints:
 * `/inventory/stock` knows what is physically held (batch, expiry, quantity,
 * MRP) and `/products` knows what it is (HSN, schedule, pack). Neither alone
 * can price a line - stock has no HSN, so it cannot resolve a GST rate - which
 * is why they are joined here rather than one being used on its own.
 *
 * Writes are STUBS. There is no sales domain in the backend yet: no Sale node,
 * no StockMovement ledger, no serial allocator endpoint. Each stub below states
 * the contract the real endpoint has to honour, and rejects rather than
 * pretending to have succeeded - a stub that silently "issues" a bill would be
 * far worse than one that refuses.
 *
 * The whole sellable list is fetched once and filtered in the browser, rather
 * than a request per keystroke. A counter search has to feel instant on the
 * second character, and the dataset is one pharmacy's stock.
 */

import type { IssuedBill, SellableBatch, SellableProduct } from './types';
import type { SerialBlock } from './serial';

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    let detail = `Request failed with ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // Non-JSON error body; the status-based message stands.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

interface StockRow {
  id: string;
  product: string | null;
  product_id: string | null;
  batch: string | null;
  expiry: string | null;
  quantity: number;
  mrp: number | null;
  source_invoice: string | null;
  is_expired: boolean;
}

interface CatalogueRow {
  id: string;
  canonical_name: string | null;
  hsn: string | null;
  manufacturer: string | null;
  pack_size: string | null;
  schedule: string | null;
}

/**
 * Everything sellable, with its batches.
 *
 * Stock rows that never resolved to a catalogue product still appear: the
 * pharmacy physically holds them, and hiding them would make the counter
 * unable to sell stock that is sitting on the shelf. They arrive with a null
 * HSN, which makes them unpriceable until the catalogue is filled in - and the
 * screen says exactly that rather than dropping them silently.
 */
export async function loadSellable(): Promise<SellableProduct[]> {
  // The device's mirror first. A counter must open and search at the same
  // speed whether or not the shop's line is up, so the network is a refresh
  // rather than a dependency.
  const { readSellable, hasMirror, refreshMirror } = await import('../../offline');
  if (await hasMirror()) {
    // Refreshed in the background; the screen does not wait for it.
    void refreshMirror().catch(() => undefined);
    return readSellable();
  }
  try {
    await refreshMirror();
    if (await hasMirror()) return readSellable();
  } catch {
    // First run with no network and no mirror. Fall through to the direct
    // read, which will surface its own error the screen already handles.
  }

  const [stock, catalogue] = await Promise.all([
    getJson<{ items: StockRow[] }>('/inventory/stock'),
    getJson<{ products: CatalogueRow[] }>('/products')
  ]);

  const byId = new Map(catalogue.products.map((p) => [p.id, p]));
  const grouped = new Map<string, SellableProduct>();

  for (const row of stock.items) {
    if (!row.product) continue;
    // Unmatched stock groups on its own id, which already encodes the raw
    // spelling, so two different unmatched spellings stay separate.
    const key = row.product_id ?? row.id;
    const catalogueRow = row.product_id ? byId.get(row.product_id) : undefined;

    const product = grouped.get(key) ?? {
      product_id: key,
      name: catalogueRow?.canonical_name || row.product,
      pack: catalogueRow?.pack_size ?? null,
      hsn: catalogueRow?.hsn ?? null,
      manufacturer: catalogueRow?.manufacturer ?? null,
      schedule: catalogueRow?.schedule ?? null,
      batches: [] as SellableBatch[]
    };

    product.batches.push({
      batch_id: row.id,
      batch_number: row.batch,
      expiry: row.expiry,
      quantity_available: row.quantity,
      // Stock reports MRP in rupees; paise is the only representation used
      // past this boundary.
      mrp_paise: row.mrp === null ? null : Math.round(row.mrp * 100),
      source_invoice: row.source_invoice
    });

    grouped.set(key, product);
  }

  return [...grouped.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** Raised by every write stub, so callers handle one type. */
export class NotImplementedError extends Error {
  constructor(what: string, contract: string) {
    super(`${what} is not built yet. ${contract}`);
    this.name = 'NotImplementedError';
  }
}

/**
 * Requests a block of serials for this device.
 *
 * Called when the counter opens and when a block runs low — never during a
 * sale, because a sale may have no network at all. The server allocates a
 * contiguous range under a write lock, so two devices can never be handed
 * overlapping numbers; that disjointness is what makes offline billing safe to
 * sync in any order.
 */
export async function requestSerialBlock(size?: number): Promise<SerialBlock> {
  const { getDeviceId } = await import('../../offline');
  const response = await fetch('/sales/serial-blocks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: await getDeviceId(), prefix: 'CTR-', ...(size ? { size } : {}) })
  });
  if (!response.ok) throw new Error(`Could not get bill numbers (${response.status}).`);
  const block = await response.json();
  return {
    prefix: block.prefix,
    financial_year: `${block.financial_year}-${String((block.financial_year + 1) % 100).padStart(2, '0')}`,
    from_sequence: block.from_sequence,
    to_sequence: block.to_sequence,
    next_sequence: block.next_sequence,
    pad_to: block.pad_to
  };
}

/**
 * Records an issued bill — locally first, and to the server whenever it can.
 *
 * This does **not** wait for the network, and that is the whole point. The bill
 * is written to the device's outbox and returns immediately, so the counter
 * prints and moves on to the next customer at the same speed whether the shop's
 * line is up, flapping or gone. A background pass drains the outbox to
 * `POST /sales`, which is idempotent on the serial, so retries are free.
 *
 * It also does not throw on a network error, because there is nothing useful
 * for the caller to do with one: the bill exists either way.
 */
export async function issueBill(bill: IssuedBill): Promise<{ queued: true; serial: string }> {
  const { enqueue, syncNow } = await import('../../offline');
  const { getDeviceId } = await import('../../offline');

  const payload = {
    serial: bill.serial,
    sale_date: bill.issued_at.slice(0, 10),
    issued_at: bill.issued_at,
    device_id: await getDeviceId(),
    lines: bill.lines.map((line, index) => {
      const computed = bill.computed[index];
      return {
        line_id: line.line_id,
        product_id: line.product_id,
        product_name: line.product_name,
        hsn: line.hsn,
        batch_number: line.batch_number,
        expiry: line.expiry,
        quantity: line.quantity,
        unit_price_paise: line.unit_price_paise,
        taxable_paise: computed?.taxable_paise ?? null,
        cgst_paise: computed?.cgst_paise ?? null,
        sgst_paise: computed?.sgst_paise ?? null,
        rate_bp: computed?.rate?.rate_bp ?? null,
        line_total_paise: computed?.line_total_paise ?? null,
        scanned_code_raw: line.scanned_code_raw
      };
    }),
    totals: {
      taxable_paise: bill.totals.taxable_paise,
      cgst_paise: bill.totals.cgst_paise,
      sgst_paise: bill.totals.sgst_paise,
      exempt_paise: bill.totals.exempt_paise,
      // The counter's rate table classifies a supply as taxable or exempt and
      // nothing finer, so nil-rated and non-GST are reported as zero rather
      // than guessed at. Splitting GSTR-1 Table 8 three ways needs the rate
      // table to say which of the three an HSN is; until it does, saying
      // "none" is the honest answer and "some" would be invented.
      nil_rated_paise: 0,
      non_gst_paise: 0,
      round_off_paise: bill.totals.round_off_paise,
      grand_total_paise: bill.totals.grand_total_paise,
      rate_blocks: bill.totals.blocks
    },
    payments: bill.payments,
    prescription_image_ref: bill.prescription_image_ref,
    customer_name: bill.customer_name,
    customer_phone: bill.customer_phone
  };

  await enqueue(bill.serial, payload);
  // Fire and forget: if there is a link the bill is gone in a moment, and if
  // there is not the outbox will carry it. Either way the counter does not wait.
  void syncNow();
  return { queued: true, serial: bill.serial };
}

/**
 * STUB. Uploads a prescription photo and returns its R2 reference.
 *
 * Contract for the real endpoint: store the image in R2 under the pharmacy's
 * prefix and return the object key, which the bill keeps as
 * `prescription_image_ref`. The image itself is never held in the browser
 * beyond the preview.
 */
export async function uploadPrescription(file: File): Promise<{ prescription_image_ref: string }> {
  throw new NotImplementedError(
    `Attaching ${file.name}`,
    'The backend needs POST /sales/prescriptions, storing to R2 and returning the object key.'
  );
}

/** The seller block a Rule 46A document has to carry. Real endpoint. */
export interface ShopProfile {
  legal_name: string | null;
  trade_name: string | null;
  gstin: string | null;
  drug_licence_number: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  pincode: string | null;
  phone: string | null;
  state: string | null;
  state_code: string | null;
}

export async function loadShop(): Promise<{ shop: ShopProfile | null; missing: string[] }> {
  return getJson<{ shop: ShopProfile | null; missing: string[] }>('/auth/shop');
}
