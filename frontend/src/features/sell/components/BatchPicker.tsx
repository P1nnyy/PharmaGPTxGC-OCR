/**
 * The F2 batch picker.
 *
 * Opens on the FEFO default and is navigable with the arrow keys, so changing
 * a batch never requires the mouse. Expiry standing drives the colour, and an
 * expired batch cannot be chosen without a second, explicit confirmation - the
 * confirm exists because selling expired medicine is a different kind of
 * mistake from selling the wrong quantity, and should not be one keystroke away.
 */

import React from 'react';
import { AlertTriangle } from 'lucide-react';

import { byFefo, daysToExpiry, expiryStanding, nearExpiryExplanation } from '../batches';
import { formatPaise } from '../money';
import { Explained, Kbd, Modal } from './Primitives';
import type { SellableBatch } from '../types';

const TONE: Record<string, string> = {
  expired: 'border-red-300 bg-red-50',
  near: 'border-amber-300 bg-amber-50',
  ok: 'border-slate-200 bg-white',
  unknown: 'border-slate-300 bg-slate-50'
};

export const ExpiryLabel: React.FC<{ expiry: string | null; today: string }> = ({
  expiry,
  today
}) => {
  const standing = expiryStanding(expiry, today);
  const days = daysToExpiry(expiry, today);

  if (standing === 'unknown') {
    return <span className="text-[10px] text-gray-400 font-mono">expiry unknown</span>;
  }
  if (standing === 'expired') {
    return (
      <span className="text-[10px] font-bold text-red-600 font-mono">
        EXPIRED {expiry}
      </span>
    );
  }
  if (standing === 'near') {
    return (
      <Explained explanation={nearExpiryExplanation(days!)} className="decoration-amber-400">
        <span className="text-[10px] font-bold text-amber-700 font-mono">
          {expiry} · {days}d
        </span>
      </Explained>
    );
  }
  return <span className="text-[10px] text-gray-500 font-mono">{expiry}</span>;
};

export const BatchPicker: React.FC<{
  productName: string;
  batches: SellableBatch[];
  selectedId: string | null;
  today: string;
  onPick: (batch: SellableBatch) => void;
  onClose: () => void;
}> = ({ productName, batches: unsorted, selectedId, today, onPick, onClose }) => {
  // Sorted here, not assumed sorted. The list arrives in whatever order stock
  // came back in, and showing the longest-dated batch at the top while the
  // default selection is the shortest-dated one contradicts both the label on
  // this dialog and the batch the line actually used.
  const batches = React.useMemo(() => byFefo(unsorted), [unsorted]);
  const startIndex = Math.max(0, batches.findIndex((b) => b.batch_id === selectedId));
  const [cursor, setCursor] = React.useState(startIndex);
  const [confirming, setConfirming] = React.useState<SellableBatch | null>(null);

  const choose = React.useCallback(
    (batch: SellableBatch) => {
      if (expiryStanding(batch.expiry, today) === 'expired') {
        setConfirming(batch);
        return;
      }
      onPick(batch);
      onClose();
    },
    [onClose, onPick, today]
  );

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (confirming) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        setCursor((c) => (c + (event.key === 'ArrowDown' ? 1 : -1) + batches.length) % batches.length);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        const batch = batches[cursor];
        if (batch) choose(batch);
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [batches, choose, confirming, cursor]);

  if (confirming) {
    return (
      <Modal
        title="This batch has expired"
        onClose={() => setConfirming(null)}
        footer={
          <>
            <button
              onClick={() => setConfirming(null)}
              className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm cursor-pointer"
            >
              Pick another batch
            </button>
            <button
              onClick={() => {
                onPick(confirming);
                setConfirming(null);
                onClose();
              }}
              className="bg-red-600 hover:bg-red-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md cursor-pointer"
            >
              Sell it anyway
            </button>
          </>
        }
      >
        <div className="flex items-start gap-3">
          <div className="p-2 bg-red-50 text-red-600 rounded-xl shrink-0">
            <AlertTriangle size={20} />
          </div>
          <div className="space-y-1.5">
            <p className="text-xs text-gray-700 leading-normal">
              Batch <span className="font-mono font-bold">{confirming.batch_number ?? '—'}</span> of{' '}
              <span className="font-semibold">{productName}</span> expired on{' '}
              <span className="font-mono font-bold">{confirming.expiry}</span>.
            </p>
            <p className="text-[11px] text-gray-500 leading-normal">
              Selling expired medicine is an offence under the Drugs and Cosmetics Act. Continue
              only if you are certain the printed expiry is wrong.
            </p>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      title={`Batches — ${productName}`}
      onClose={onClose}
      wide
      footer={
        <span className="text-[10px] text-gray-400 flex items-center gap-2 mr-auto">
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd> move · <Kbd>Enter</Kbd> pick
        </span>
      }
    >
      {batches.length === 0 ? (
        <p className="text-xs text-gray-500">No batches of this product are in stock.</p>
      ) : (
        <div className="space-y-1.5">
          <p className="text-[10px] text-gray-400 mb-2">
            Sorted first-expiry-first. The soonest-expiring sellable batch is picked by default.
          </p>
          {batches.map((batch, index) => {
            const standing = expiryStanding(batch.expiry, today);
            const active = index === cursor;
            return (
              <button
                key={batch.batch_id}
                onClick={() => choose(batch)}
                onMouseEnter={() => setCursor(index)}
                className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-xl border transition-all cursor-pointer ${
                  TONE[standing]
                } ${active ? 'ring-2 ring-[#1b5dfc] ring-offset-1' : ''}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold text-[#0f172a] font-mono truncate">
                    {batch.batch_number ?? 'no batch number'}
                  </p>
                  <ExpiryLabel expiry={batch.expiry} today={today} />
                </div>
                <div className="text-right shrink-0">
                  <p className="text-xs font-mono tabular-nums text-[#0f172a]">
                    {formatPaise(batch.mrp_paise)}
                  </p>
                  <p className="text-[10px] text-gray-400 font-mono">
                    {batch.quantity_available} in stock
                  </p>
                </div>
              </button>
            );
          })}
          {/* Stock is derived from purchases until a dispensing feed exists;
              saying so here is cheaper than an operator trusting the figure. */}
          <p className="text-[9px] text-gray-400 pt-2 leading-snug">
            Quantities are what was received on verified purchase invoices. They do not yet come
            down as bills are issued.
          </p>
        </div>
      )}
    </Modal>
  );
};
