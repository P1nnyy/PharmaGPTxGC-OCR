/**
 * The counter sale itself: what is on the bill, and everything derived from it.
 *
 * One hook owns the whole sale so that the desktop and mobile layouts are two
 * renderings of one state rather than two implementations that drift. Nothing
 * below decides how anything looks.
 *
 * Totals recompute on every change rather than on a commit step. That is what
 * makes the running panel update per keystroke, and it is cheap: the engine is
 * integer arithmetic over the lines already on the bill.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { loadSellable } from './api';
import { defaultBatch } from './batches';
import { computeTotals } from './totals';
import { TAX_PROFILE } from './taxProfile';
import type {
  Discount,
  PaymentMethod,
  PaymentSplit,
  SaleLineInput,
  SellableBatch,
  SellableProduct
} from './types';

/** Per-device UI preference. Not a figure, not returns data - safe to keep in
 *  the browser, which is why this is the only sale-related key here. */
const PAYMENT_PREFERENCE_KEY = 'pharmaflow_sell_preferred_payment';
/** The in-progress bill, so a reload at the counter does not lose a basket.
 *  A draft is explicitly not a record: it is discarded the moment the bill
 *  issues, and nothing reads it back into a return. */
const DRAFT_KEY = 'pharmaflow_sell_draft';

const todayIso = (): string => new Date().toISOString().slice(0, 10);

let lineCounter = 0;
const nextLineId = (): string => `line-${Date.now()}-${lineCounter++}`;

function readPreferredMethod(): PaymentMethod {
  try {
    const stored = localStorage.getItem(PAYMENT_PREFERENCE_KEY);
    if (stored === 'cash' || stored === 'upi' || stored === 'card' || stored === 'credit') {
      return stored;
    }
  } catch {
    // A browser with storage blocked still has to be able to bill.
  }
  return 'cash';
}

export interface CounterSale {
  catalogue: SellableProduct[];
  catalogueError: string | null;
  loading: boolean;
  reloadCatalogue: () => void;

  lines: SaleLineInput[];
  addLine: (
    product: SellableProduct,
    batch: SellableBatch,
    quantity: number,
    scan?: { raw: string; format: string } | null,
  ) => string;
  updateQuantity: (lineId: string, quantity: number) => void;
  setLineDiscount: (lineId: string, discount: Discount) => void;
  setLineBatch: (lineId: string, batch: SellableBatch) => void;
  removeLine: (lineId: string) => void;
  clearSale: () => void;

  billDate: string;
  totals: ReturnType<typeof computeTotals>;
  /** True when the bill can legally be issued. Anything false here means the
   *  screen must say why rather than letting the operator press on. */
  canIssue: boolean;
  blockingReasons: string[];

  payments: PaymentSplit[];
  setPayments: (payments: PaymentSplit[]) => void;
  preferredMethod: PaymentMethod;
  rememberPreferredMethod: (method: PaymentMethod) => void;

  prescriptionRef: string | null;
  setPrescriptionRef: (ref: string | null) => void;
}

export function useCounterSale(): CounterSale {
  const [catalogue, setCatalogue] = useState<SellableProduct[]>([]);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);

  const [lines, setLines] = useState<SaleLineInput[]>([]);
  const [payments, setPayments] = useState<PaymentSplit[]>([]);
  const [prescriptionRef, setPrescriptionRef] = useState<string | null>(null);
  const [preferredMethod, setPreferredMethod] = useState<PaymentMethod>(readPreferredMethod);

  // The bill date is fixed when the sale starts rather than read per render:
  // rate resolution depends on it, and a sale left open across midnight must
  // not silently reprice itself. It moves only when a new sale begins.
  const [billDate, setBillDate] = useState<string>(todayIso);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setCatalogueError(null);
    loadSellable()
      .then((products) => {
        if (active) setCatalogue(products);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setCatalogueError(error instanceof Error ? error.message : 'Could not load stock.');
        setCatalogue([]);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reloadToken]);

  // Restore an interrupted basket once, on mount.
  useEffect(() => {
    try {
      const stored = localStorage.getItem(DRAFT_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed?.lines) && parsed.date === billDate) {
          setLines(parsed.lines);
        }
      }
    } catch {
      // A corrupt draft is dropped rather than blocking the counter.
    }
    // Mount only: re-running when the bill date moves would restore a draft
    // into the fresh sale that just replaced it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try {
      if (lines.length === 0) localStorage.removeItem(DRAFT_KEY);
      else localStorage.setItem(DRAFT_KEY, JSON.stringify({ date: billDate, lines }));
    } catch {
      // Storage unavailable; the sale still works, it just will not survive a
      // reload. Not worth interrupting a customer over.
    }
  }, [billDate, lines]);

  const addLine = useCallback(
    (
      product: SellableProduct,
      batch: SellableBatch,
      quantity: number,
      scan: { raw: string; format: string } | null = null,
    ): string => {
      const lineId = nextLineId();
      setLines((current) => [
        ...current,
        {
          line_id: lineId,
          product_id: product.product_id,
          product_name: product.name,
          hsn: product.hsn,
          batch_id: batch.batch_id,
          batch_number: batch.batch_number,
          expiry: batch.expiry,
          quantity,
          unit_price_paise: batch.mrp_paise,
          discount: { kind: 'none' },
          scanned_code_raw: scan?.raw ?? null,
          scanned_code_format: scan?.format ?? null
        }
      ]);
      return lineId;
    },
    []
  );

  const updateQuantity = useCallback((lineId: string, quantity: number) => {
    setLines((current) =>
      current.map((line) => (line.line_id === lineId ? { ...line, quantity } : line))
    );
  }, []);

  const setLineDiscount = useCallback((lineId: string, discount: Discount) => {
    setLines((current) =>
      current.map((line) => (line.line_id === lineId ? { ...line, discount } : line))
    );
  }, []);

  const setLineBatch = useCallback((lineId: string, batch: SellableBatch) => {
    setLines((current) =>
      current.map((line) =>
        line.line_id === lineId
          ? {
              ...line,
              batch_id: batch.batch_id,
              batch_number: batch.batch_number,
              expiry: batch.expiry,
              unit_price_paise: batch.mrp_paise
            }
          : line
      )
    );
  }, []);

  const removeLine = useCallback((lineId: string) => {
    setLines((current) => current.filter((line) => line.line_id !== lineId));
  }, []);

  const clearSale = useCallback(() => {
    setLines([]);
    setPayments([]);
    setPrescriptionRef(null);
    setBillDate(todayIso());
  }, []);

  const rememberPreferredMethod = useCallback((method: PaymentMethod) => {
    setPreferredMethod(method);
    try {
      localStorage.setItem(PAYMENT_PREFERENCE_KEY, method);
    } catch {
      // Preference simply will not stick; nothing about the sale changes.
    }
  }, []);

  const totals = useMemo(
    () => computeTotals(lines, billDate, TAX_PROFILE.pricing_mode ?? 'exclusive'),
    [lines, billDate]
  );

  // Everything standing between this basket and a legally issuable bill,
  // gathered in one place so the screen can list them rather than disabling a
  // button with no explanation.
  const blockingReasons = useMemo(() => {
    const reasons: string[] = [];
    if (lines.length === 0) reasons.push('Nothing on the bill yet.');
    if (TAX_PROFILE.pricing_mode === null) {
      reasons.push('Pricing mode is not configured — the pharmacy has to state whether counter prices include GST.');
    }
    if (totals.unresolved_line_ids.length > 0) {
      reasons.push(
        `${totals.unresolved_line_ids.length} line${totals.unresolved_line_ids.length === 1 ? '' : 's'} cannot be priced.`
      );
    }
    if (totals.reconciliation_error) reasons.push(totals.reconciliation_error);
    return reasons;
  }, [lines.length, totals]);

  return {
    catalogue,
    catalogueError,
    loading,
    reloadCatalogue: () => setReloadToken((t) => t + 1),
    lines,
    addLine,
    updateQuantity,
    setLineDiscount,
    setLineBatch,
    removeLine,
    clearSale,
    billDate,
    totals,
    canIssue: blockingReasons.length === 0,
    blockingReasons,
    payments,
    setPayments,
    preferredMethod,
    rememberPreferredMethod,
    prescriptionRef,
    setPrescriptionRef
  };
}

/** Default batch for a product, exposed so the search can preselect one the
 *  same way the batch picker would. */
export const preselectBatch = (product: SellableProduct, onDate: string) =>
  defaultBatch(product.batches, onDate);
