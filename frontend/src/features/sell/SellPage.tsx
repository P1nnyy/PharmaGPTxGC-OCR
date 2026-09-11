/**
 * The counter billing screen.
 *
 * One component tree, two layouts. Every piece of state lives in this
 * component (or in `useCounterSale` beneath it) and both layouts render from
 * it, so the desktop table and the mobile cards cannot disagree about what is
 * on the bill. The layouts are chosen by Tailwind breakpoints rather than by
 * branching on a width in JavaScript: a rotated tablet then re-lays out
 * without remounting and losing the sale.
 *
 * The desktop interaction is one loop and nothing else: search, arrow, Enter,
 * quantity, Enter, back to search. Every shortcut it depends on is printed on
 * screen, because a keyboard-only flow that has to be memorised from
 * documentation is a flow that gets done with the mouse instead.
 */

import React from 'react';
import {
  AlertTriangle,
  IndianRupee,
  Loader2,
  Receipt,
  RefreshCw,
  ScanLine,
  Trash2
} from 'lucide-react';

import { issueBill, loadShop, NotImplementedError, type ShopProfile } from './api';
import { defaultBatch, expiryStanding } from './batches';
import { BatchPicker } from './components/BatchPicker';
import { BillPreview } from './components/BillPreview';
import { DiscountDialog } from './components/DiscountDialog';
import { BlockingNotice, Kbd } from './components/Primitives';
import { LineCards, LineRows } from './components/Lines';
import { NumericPad } from './components/NumericPad';
import { PaymentSheet } from './components/PaymentSheet';
import { PrescriptionCapture } from './components/PrescriptionCapture';
import { ProductSearch } from './components/ProductSearch';
import { TotalsPanel } from './components/TotalsPanel';
import { computeLine } from './totals';
import { consumeSerial, SerialUnavailableError } from './serial';
import { SyncStatusBar, createIndexedDbSerialStore } from '../../offline';
import { formatPaise } from './money';
import { isRateTableConfigured } from './gstRates';
import { TAX_PROFILE } from './taxProfile';
import { useCounterSale } from './useCounterSale';
import { BindCodeDialog, ScannerSheet, bindCode, resolveCode, unknownRead } from '../../scanning';
import type { ParsedDrugCode } from '../../scanning';
import { useProductSearch } from './useProductSearch';
import type { IssuedBill, PaymentSplit, SellableBatch, SellableProduct } from './types';

import './print.css';

/** The shortcut legend. Also the list the key handler is written against, so
 *  a shortcut cannot exist without an affordance for it. */
const SHORTCUTS = [
  { keys: ['F2'], label: 'Batch' },
  { keys: ['F4'], label: 'Discount' },
  { keys: ['F9'], label: 'Payment' },
  { keys: ['Esc'], label: 'Clear line' }
] as const;

type Modal = 'batch' | 'discount' | 'payment' | 'quantity' | null;

export const SellPage: React.FC = () => {
  const sale = useCounterSale();
  const search = useProductSearch(sale.catalogue);

  // One ref per layout, not one shared between them. Both layouts stay
  // mounted so that rotating a tablet does not remount the sale, which means a
  // single ref would be claimed by whichever input mounted last - in practice
  // the hidden one - and focusing it would silently do nothing.
  const desktopSearchRef = React.useRef<HTMLInputElement>(null);
  const mobileSearchRef = React.useRef<HTMLInputElement>(null);
  const quantityRef = React.useRef<HTMLInputElement>(null);
  // The device's serial block, held in IndexedDB. This is the decision
  // `serial.ts` left as an interface: the cursor lives on the device, because
  // a counter with no network still has to number a bill, and it is advanced
  // and persisted before a serial is handed out.
  const serialStore = React.useRef(createIndexedDbSerialStore());

  const [draft, setDraft] = React.useState<{ product: SellableProduct; batch: SellableBatch } | null>(null);
  const [quantityText, setQuantityText] = React.useState('1');
  const [activeLineId, setActiveLineId] = React.useState<string | null>(null);
  const [modal, setModal] = React.useState<Modal>(null);
  const [editingLineId, setEditingLineId] = React.useState<string | null>(null);
  const [shop, setShop] = React.useState<ShopProfile | null>(null);
  const [issued, setIssued] = React.useState<IssuedBill | null>(null);
  const [issueError, setIssueError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [scannerOpen, setScannerOpen] = React.useState(false);
  const [scanMessage, setScanMessage] = React.useState<string | null>(null);
  const [pendingCode, setPendingCode] = React.useState<
    { parsed: ParsedDrugCode; symbology: string } | null
  >(null);

  React.useEffect(() => {
    loadShop()
      .then((result) => setShop(result.shop))
      .catch(() => setShop(null));
  }, []);

  const focusSearch = React.useCallback(() => {
    // Deferred a frame: focusing while a modal is still unmounting hands focus
    // straight back to the element being removed.
    requestAnimationFrame(() => {
      // Whichever layout is actually on screen. A hidden input reports zero
      // width, and calling focus() on it does nothing at all.
      const visible = [desktopSearchRef.current, mobileSearchRef.current].find(
        (input) => input !== null && input.getBoundingClientRect().width > 0
      );
      visible?.focus();
    });
  }, []);

  // Focus lands in the search on load, which is the whole premise of the
  // desktop flow - the operator should be able to start typing a medicine
  // without touching anything first.
  React.useEffect(() => {
    if (!sale.loading && !issued) focusSearch();
  }, [focusSearch, issued, sale.loading]);

  const flash = (message: string) => {
    setNotice(message);
    setTimeout(() => setNotice(null), 2600);
  };

  /** Picking a product from the results: preselect FEFO and jump to quantity. */
  const selectProduct = React.useCallback(
    (product: SellableProduct) => {
      const batch = defaultBatch(product.batches, sale.billDate);
      if (batch === null) {
        // Nothing sellable: the picker opens so an expired batch can be
        // chosen deliberately, rather than the selection silently failing.
        setDraft({ product, batch: product.batches[0] ?? { batch_id: '', batch_number: null, expiry: null, quantity_available: 0, mrp_paise: null, source_invoice: null } });
        setModal('batch');
        flash(`No sellable batch of ${product.name} — every batch is expired or empty.`);
        return;
      }
      setDraft({ product, batch });
      setQuantityText('1');
      // The result list has done its job; leaving it open would cover the
      // line being built, which is the thing the operator now needs to see.
      search.reset();
    },
    [sale.billDate, search]
  );

  // Focus follows the draft into existence.
  //
  // Deliberately an effect rather than a requestAnimationFrame scheduled from
  // the selection handler: rAF is not ordered against React's commit, so the
  // callback can run while the quantity input still does not exist, silently
  // leaving focus in the search box and breaking the one loop the whole
  // desktop flow is built on.
  React.useEffect(() => {
    if (!draft) return;
    quantityRef.current?.focus();
    quantityRef.current?.select();
  }, [draft]);

  /** Commits the line under construction and returns to the search. */
  const commitDraft = React.useCallback(() => {
    if (!draft) return;
    const quantity = Number(quantityText);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      flash('Enter a quantity above zero.');
      return;
    }
    const lineId = sale.addLine(draft.product, draft.batch, quantity);
    setActiveLineId(lineId);
    setDraft(null);
    setQuantityText('1');
    focusSearch();
  }, [draft, focusSearch, quantityText, sale]);

  /** Esc: abandons the line being built, or clears a stale search. */
  const clearCurrentLine = React.useCallback(() => {
    if (draft) {
      setDraft(null);
      setQuantityText('1');
    }
    search.reset();
    focusSearch();
  }, [draft, focusSearch, search]);

  // The global shortcuts. Registered once, and deliberately inert while a
  // modal is open so that F-keys cannot stack dialogs on top of each other.
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (issued) return;
      if (event.key === 'Escape') {
        if (modal === null) {
          event.preventDefault();
          clearCurrentLine();
        }
        return;
      }
      if (modal !== null) return;

      if (event.key === 'F2') {
        event.preventDefault();
        if (draft) setModal('batch');
        else if (activeLineId) {
          setEditingLineId(activeLineId);
          setModal('batch');
        } else flash('Add a line first, then F2 changes its batch.');
      } else if (event.key === 'F4') {
        event.preventDefault();
        if (activeLineId) {
          setEditingLineId(activeLineId);
          setModal('discount');
        } else flash('Add a line first, then F4 discounts it.');
      } else if (event.key === 'F9') {
        event.preventDefault();
        if (sale.canIssue) setModal('payment');
        else flash(sale.blockingReasons[0] ?? 'Nothing to pay for yet.');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeLineId, clearCurrentLine, draft, issued, modal, sale.blockingReasons, sale.canIssue]);

  const onSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      search.moveHighlight(1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      search.moveHighlight(-1);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const product = search.results[search.highlight];
      if (product) selectProduct(product);
    }
  };

  /**
   * Adds a line from a scanned pack.
   *
   * The batch the pack itself declares is preferred over the FEFO default,
   * because the pack in the customer's hand is the one leaving the shelf — but
   * only when we actually hold that batch. A code naming a batch we have no
   * record of is a discrepancy worth showing rather than quietly overriding.
   */
  const addScannedLine = React.useCallback(
    (product: SellableProduct, parsed: ParsedDrugCode) => {
      const scan = { raw: parsed.raw, format: parsed.format };
      const declared = parsed.batch?.trim().toLowerCase();
      const matched = declared
        ? product.batches.find((b) => (b.batch_number ?? '').trim().toLowerCase() === declared)
        : undefined;

      if (matched) {
        const lineId = sale.addLine(product, matched, 1, scan);
        setActiveLineId(lineId);
        setScanMessage(`${product.name} · batch ${matched.batch_number}`);
        return;
      }

      const fallback = defaultBatch(product.batches, sale.billDate);
      if (!fallback) {
        setScannerOpen(false);
        flash(`${product.name} has no sellable batch in stock.`);
        return;
      }

      const lineId = sale.addLine(product, fallback, 1, scan);
      setActiveLineId(lineId);
      // No batch on the code, or one we do not hold: the operator picks.
      setScannerOpen(false);
      setEditingLineId(lineId);
      setModal('batch');
      flash(
        declared
          ? `Pack says batch ${parsed.batch}, which is not in stock — pick the batch being sold.`
          : `${product.name} added — pick the batch.`,
      );
    },
    [sale],
  );

  /** A code came off the camera. Three outcomes, per the scanning spec. */
  const handleScan = React.useCallback(
    async (parsed: ParsedDrugCode, symbology: string) => {
      setScanMessage(null);
      let bound;
      try {
        bound = await resolveCode(parsed);
      } catch {
        setScannerOpen(false);
        flash('Could not look that code up. Search for the medicine instead.');
        return;
      }

      if (!bound) {
        // Never seen. Offer to bind it — once — and remember it after that.
        unknownRead();
        setScannerOpen(false);
        setPendingCode({ parsed, symbology });
        return;
      }

      const product = sale.catalogue.find((p) => p.product_id === bound.product.id);
      if (!product) {
        setScannerOpen(false);
        flash(
          `${bound.product.canonical_name ?? 'That product'} is bound to this code but has no stock.`,
        );
        return;
      }
      addScannedLine(product, parsed);
    },
    [addScannedLine, sale.catalogue],
  );

  /** Issues the bill: takes a serial, then writes. Both are still stubs. */
  const finishSale = async (payments: PaymentSplit[]) => {
    sale.setPayments(payments);
    setIssueError(null);
    const bill: IssuedBill = {
      serial: '',
      issued_at: new Date().toISOString(),
      lines: sale.lines,
      computed: sale.lines.map((line) =>
        computeLine(line, sale.billDate, TAX_PROFILE.pricing_mode ?? 'exclusive')
      ),
      totals: sale.totals,
      payments,
      prescription_image_ref: sale.prescriptionRef,
      customer_name: null,
      customer_phone: null
    };

    try {
      bill.serial = await consumeSerial(serialStore.current, sale.billDate);
      await issueBill(bill);
      setIssued(bill);
      sale.clearSale();
    } catch (error) {
      const message =
        error instanceof SerialUnavailableError || error instanceof NotImplementedError
          ? error.message
          : error instanceof Error
            ? error.message
            : 'Could not issue the bill.';
      setIssueError(message);
      // The bill is still shown, marked unmistakably as not issued, so the
      // print and share paths are usable while the write path is being built.
      setIssued({ ...bill, serial: 'PREVIEW — NOT ISSUED' });
    }
  };

  const startNewBill = () => {
    setIssued(null);
    setIssueError(null);
    sale.clearSale();
    search.reset();
    focusSearch();
  };

  const editingLine = sale.lines.find((line) => line.line_id === editingLineId) ?? null;
  const computed = sale.lines.map((line) =>
    computeLine(line, sale.billDate, TAX_PROFILE.pricing_mode ?? 'exclusive')
  );

  // ---------------------------------------------------------------- issued
  if (issued) {
    return (
      <div className="space-y-3">
        {issueError && (
          <div className="bill-no-print bg-red-50 border border-red-200 rounded-2xl p-4 flex items-start gap-3">
            <AlertTriangle size={18} className="text-red-600 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="text-sm font-bold text-red-800">This bill has no number.</p>
              <p className="text-xs text-red-700 leading-normal">{issueError}</p>
              <p className="text-[11px] text-red-600/90 leading-normal">
                A bill cannot be issued without a serial from this device's block. What you
                see below is a layout preview only — it is not a valid tax invoice, so do not
                give it to a customer. Connect once to collect more numbers.
              </p>
            </div>
          </div>
        )}
        <BillPreview bill={issued} shop={shop} onNewBill={startNewBill} />
      </div>
    );
  }

  // ------------------------------------------------------------- the sale
  const configWarnings: string[] = [];
  if (!isRateTableConfigured()) {
    configWarnings.push(
      'The GST rate table is empty, so no line can be priced. Seed it from the GSTN master before billing.'
    );
  }
  if (TAX_PROFILE.pricing_mode === null) {
    configWarnings.push(
      'Counter pricing mode is not set — state whether shelf prices include GST.'
    );
  }

  return (
    <div className="space-y-3">
      {notice && (
        <div className="fixed top-20 left-1/2 -translate-x-1/2 z-50 bg-[#0f172a] text-white px-4 py-2.5 rounded-xl text-xs font-semibold shadow-xl animate-in slide-in-from-top duration-200 max-w-[90vw] text-center">
          {notice}
        </div>
      )}

      {configWarnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-3.5 flex items-start gap-3">
          <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
          <div className="space-y-0.5 min-w-0">
            <p className="text-xs font-bold text-amber-800">Counter is not ready to bill</p>
            {configWarnings.map((warning) => (
              <p key={warning} className="text-[11px] text-amber-700 leading-normal">
                {warning}
              </p>
            ))}
          </div>
        </div>
      )}

      {sale.catalogueError && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-3.5 flex items-center gap-3">
          <AlertTriangle size={16} className="text-red-600 shrink-0" />
          <p className="text-xs text-red-700 flex-1">{sale.catalogueError}</p>
          <button
            onClick={sale.reloadCatalogue}
            className="flex items-center gap-1.5 text-xs font-semibold text-red-700 hover:text-red-800 cursor-pointer"
          >
            <RefreshCw size={13} /> Retry
          </button>
        </div>
      )}

      {/* =============================== DESKTOP =============================== */}
      <div className="hidden md:grid grid-cols-[1fr_20rem] gap-4 items-start">
        <div className="space-y-3 min-w-0">
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-4 space-y-3">
            <ProductSearch
              inputRef={desktopSearchRef}
              query={search.query}
              onQueryChange={search.setQuery}
              results={search.results}
              highlight={search.highlight}
              onHighlight={search.setHighlight}
              onSelect={selectProduct}
              onKeyDown={onSearchKeyDown}
              today={sale.billDate}
              variant="desktop"
              disabled={sale.loading}
            />

            {/* The line under construction. Present only between selecting a
                product and committing it, which is the only moment the
                quantity field is the right place for focus. */}
            {draft && (
              <div className="flex items-center gap-3 bg-blue-50/70 border border-blue-200 rounded-xl px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold text-[#0f172a] truncate">{draft.product.name}</p>
                  <p className="text-[10px] text-gray-500 font-mono">
                    Batch {draft.batch.batch_number || '—'} · exp {draft.batch.expiry || '—'} ·{' '}
                    {formatPaise(draft.batch.mrp_paise)}
                    {expiryStanding(draft.batch.expiry, sale.billDate) === 'near' && (
                      <span className="text-amber-700 font-bold"> · expiring soon</span>
                    )}
                  </p>
                </div>
                <label className="flex items-center gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
                    Qty
                  </span>
                  <input
                    ref={quantityRef}
                    value={quantityText}
                    onChange={(event) => setQuantityText(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        commitDraft();
                      }
                    }}
                    inputMode="numeric"
                    aria-label="Quantity"
                    className="w-20 bg-white border-2 border-[#1b5dfc] rounded-lg px-2.5 py-1.5 text-sm font-mono tabular-nums text-right text-[#0f172a] focus:outline-none"
                  />
                </label>
                <span className="text-[10px] text-gray-400 flex items-center gap-1 shrink-0">
                  <Kbd>↵</Kbd> add
                </span>
              </div>
            )}
          </div>

          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden">
            {sale.lines.length === 0 ? (
              <div className="px-4 py-12 text-center">
                {sale.loading ? (
                  <Loader2 size={20} className="animate-spin text-gray-300 mx-auto" />
                ) : (
                  <>
                    <Receipt size={22} className="text-gray-300 mx-auto mb-2" />
                    <p className="text-xs text-gray-400">
                      Start typing a medicine name. Nothing has been added yet.
                    </p>
                  </>
                )}
              </div>
            ) : (
              <div className="max-h-[52vh] overflow-y-auto">
                <LineRows
                  lines={sale.lines}
                  computed={computed}
                  today={sale.billDate}
                  activeLineId={activeLineId}
                  onEditBatch={(id) => {
                    setEditingLineId(id);
                    setModal('batch');
                  }}
                  onEditDiscount={(id) => {
                    setEditingLineId(id);
                    setModal('discount');
                  }}
                  onRemove={sale.removeLine}
                  onQuantity={sale.updateQuantity}
                />
              </div>
            )}
          </div>
        </div>

        {/* Totals stay put while the list scrolls: they are what the operator
            reads out to the customer, and they should never be scrolled away. */}
        <aside className="sticky top-0 space-y-3">
          <SyncStatusBar />

          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-4">
            <TotalsPanel totals={sale.totals} lineCount={sale.lines.length} />
          </div>

          <BlockingNotice reasons={sale.blockingReasons} />

          <button
            onClick={() => sale.canIssue && setModal('payment')}
            disabled={!sale.canIssue}
            className="w-full bg-[#1b5dfc] hover:bg-blue-700 text-white py-3 rounded-2xl text-sm font-bold shadow-md shadow-blue-500/20 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            <IndianRupee size={15} />
            Payment
            <Kbd tone="dark">F9</Kbd>
          </button>

          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-3 space-y-2">
            <PrescriptionCapture
              imageRef={sale.prescriptionRef}
              onCaptured={sale.setPrescriptionRef}
            />
            <button
              onClick={() => {
                sale.clearSale();
                search.reset();
                setDraft(null);
                setActiveLineId(null);
                focusSearch();
              }}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-[11px] font-semibold border border-gray-200 text-gray-500 hover:bg-slate-50 cursor-pointer"
            >
              <Trash2 size={13} /> Clear bill
            </button>
          </div>

          {/* Every shortcut the screen listens for, always visible. */}
          <div className="bg-[#0f172a] rounded-2xl p-3">
            <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400 mb-2">
              Shortcuts
            </p>
            <div className="space-y-1.5">
              {SHORTCUTS.map((shortcut) => (
                <div key={shortcut.label} className="flex items-center justify-between">
                  <span className="text-[11px] text-slate-300">{shortcut.label}</span>
                  <div className="flex gap-1">
                    {shortcut.keys.map((key) => (
                      <Kbd key={key} tone="dark">
                        {key}
                      </Kbd>
                    ))}
                  </div>
                </div>
              ))}
              <div className="flex items-center justify-between pt-1.5 border-t border-white/10">
                <span className="text-[11px] text-slate-300">Add line</span>
                <div className="flex gap-1">
                  <Kbd tone="dark">↑</Kbd>
                  <Kbd tone="dark">↓</Kbd>
                  <Kbd tone="dark">↵</Kbd>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {/* ================================ MOBILE ================================ */}
      <div className="md:hidden">
        {/* Lines scroll between the header and the pinned controls; the padding
            reserves the space the fixed bar occupies. */}
        <div className="pb-56 space-y-2">
          {sale.lines.length === 0 ? (
            <div className="bg-white rounded-2xl border border-[#e2e8f0] px-4 py-10 text-center">
              <Receipt size={22} className="text-gray-300 mx-auto mb-2" />
              <p className="text-xs text-gray-400">
                Search or scan to add the first item.
              </p>
            </div>
          ) : (
            <>
              <LineCards
                lines={sale.lines}
                computed={computed}
                today={sale.billDate}
                onRemove={sale.removeLine}
                onEditQuantity={(id) => {
                  setEditingLineId(id);
                  const line = sale.lines.find((l) => l.line_id === id);
                  setQuantityText(String(line?.quantity ?? 1));
                  setModal('quantity');
                }}
                onEditBatch={(id) => {
                  setEditingLineId(id);
                  setModal('batch');
                }}
              />
              <p className="text-[10px] text-gray-400 text-center pt-1">
                Swipe a line left to remove it.
              </p>
            </>
          )}
        </div>

        <div className="fixed bottom-0 left-0 right-0 z-30 bg-white border-t border-[#e2e8f0] shadow-[0_-4px_16px_rgba(15,23,42,0.06)]">
          <div className="px-3 pt-2">
            <SyncStatusBar compact />
          </div>

          {/* Sticky total bar. The grand total is the one figure a customer
              asks for, so it is the largest thing on the phone screen. */}
          <div className="px-4 py-2.5 flex items-baseline justify-between border-b border-gray-100">
            <div className="flex items-baseline gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
                Total
              </span>
              <span className="text-[10px] text-gray-400 font-mono">
                {sale.lines.length} line{sale.lines.length === 1 ? '' : 's'}
              </span>
            </div>
            <span className="text-2xl font-bold font-mono tabular-nums text-[#0f172a]">
              {formatPaise(sale.totals.grand_total_paise)}
            </span>
          </div>

          {sale.blockingReasons.length > 0 && sale.lines.length > 0 && (
            <div className="px-4 pt-2">
              <BlockingNotice reasons={sale.blockingReasons} />
            </div>
          )}

          <div className="px-4 py-2.5 space-y-2">
            <button
              onClick={() => sale.canIssue && setModal('payment')}
              disabled={!sale.canIssue}
              className="w-full bg-[#1b5dfc] hover:bg-blue-700 text-white py-3.5 rounded-2xl text-base font-bold shadow-lg shadow-blue-500/20 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              <IndianRupee size={17} />
              {sale.totals.grand_total_paise === null
                ? 'Payment'
                : `Take ${formatPaise(sale.totals.grand_total_paise)}`}
            </button>

            {/* Search sits above the keyboard rather than at the top of the
                screen: on a phone the keyboard covers the top half, and a
                search field up there is a field you cannot see while typing
                into it. */}
            <div className="flex items-end gap-2">
              <div className="flex-1 min-w-0">
                <ProductSearch
                  inputRef={mobileSearchRef}
                  query={search.query}
                  onQueryChange={search.setQuery}
                  results={search.results}
                  highlight={search.highlight}
                  onHighlight={search.setHighlight}
                  onSelect={(product) => {
                    const batch = defaultBatch(product.batches, sale.billDate);
                    if (batch) {
                      const lineId = sale.addLine(product, batch, 1);
                      setActiveLineId(lineId);
                      search.reset();
                    } else {
                      selectProduct(product);
                    }
                  }}
                  onKeyDown={onSearchKeyDown}
                  today={sale.billDate}
                  variant="mobile"
                  disabled={sale.loading}
                />
              </div>

              {/* Scanning is a shortcut, never a requirement: the search
                  field beside this does the same job by hand. */}
              <button
                onClick={() => {
                  setScanMessage(null);
                  setScannerOpen(true);
                }}
                aria-label="Scan a pack"
                className="shrink-0 w-14 h-14 rounded-2xl bg-[#0f172a] text-white flex items-center justify-center shadow-lg cursor-pointer active:scale-95 transition-transform"
              >
                <ScanLine size={22} />
              </button>

              <div className="shrink-0">
                <PrescriptionCapture
                  imageRef={sale.prescriptionRef}
                  onCaptured={sale.setPrescriptionRef}
                  compact
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ================================ MODALS ================================ */}
      {modal === 'batch' && (draft || editingLine) && (
        <BatchPicker
          productName={draft?.product.name ?? editingLine?.product_name ?? ''}
          batches={
            draft?.product.batches ??
            sale.catalogue.find((p) => p.product_id === editingLine?.product_id)?.batches ??
            []
          }
          selectedId={draft?.batch.batch_id ?? editingLine?.batch_id ?? null}
          today={sale.billDate}
          onPick={(batch) => {
            if (draft) setDraft({ ...draft, batch });
            else if (editingLine) sale.setLineBatch(editingLine.line_id, batch);
          }}
          onClose={() => {
            setModal(null);
            setEditingLineId(null);
            if (draft) requestAnimationFrame(() => quantityRef.current?.focus());
            else focusSearch();
          }}
        />
      )}

      {modal === 'discount' && editingLine && (
        <DiscountDialog
          current={editingLine.discount}
          lineGrossPaise={
            editingLine.unit_price_paise === null
              ? null
              : editingLine.unit_price_paise * editingLine.quantity
          }
          onApply={(discount) => sale.setLineDiscount(editingLine.line_id, discount)}
          onClose={() => {
            setModal(null);
            setEditingLineId(null);
            focusSearch();
          }}
        />
      )}

      {modal === 'payment' && sale.totals.grand_total_paise !== null && (
        <PaymentSheet
          totalPaise={sale.totals.grand_total_paise}
          preferred={sale.preferredMethod}
          initial={sale.payments}
          onRememberPreferred={sale.rememberPreferredMethod}
          onConfirm={finishSale}
          onClose={() => {
            setModal(null);
            focusSearch();
          }}
        />
      )}

      {scannerOpen && (
        <ScannerSheet
          onRead={handleScan}
          onClose={() => setScannerOpen(false)}
          lastMessage={scanMessage}
        />
      )}

      {pendingCode && (
        <BindCodeDialog
          parsed={pendingCode.parsed}
          symbology={pendingCode.symbology}
          catalogue={sale.catalogue}
          onBind={async (product) => {
            await bindCode(product.product_id, pendingCode.parsed, pendingCode.symbology);
            addScannedLine(product, pendingCode.parsed);
            setPendingCode(null);
          }}
          onSkip={(product) => {
            // Added without binding: the queue does not wait while someone
            // decides what a code belongs to.
            if (product) addScannedLine(product, pendingCode.parsed);
            setPendingCode(null);
          }}
          onClose={() => {
            setPendingCode(null);
            focusSearch();
          }}
        />
      )}

      {modal === 'quantity' && editingLine && (
        <NumericPad
          value={quantityText}
          label={editingLine.product_name}
          onChange={setQuantityText}
          onCommit={() => {
            const quantity = Number(quantityText);
            if (Number.isFinite(quantity) && quantity > 0) {
              sale.updateQuantity(editingLine.line_id, quantity);
            }
            setModal(null);
            setEditingLineId(null);
          }}
          onCancel={() => {
            setModal(null);
            setEditingLineId(null);
          }}
        />
      )}
    </div>
  );
};

export default SellPage;
