/**
 * The bill's lines, in the two shapes the two layouts need.
 *
 * Both read the same computed lines, so a figure cannot differ between the
 * desktop table and the mobile cards. What differs is only what fits: the
 * table shows every column, the card shows what a thumb needs and hides the
 * rest behind the tap targets.
 */

import React from 'react';
import { AlertCircle, Layers, Percent, Trash2 } from 'lucide-react';

import { formatPaise } from '../money';
import { ExpiryLabel } from './BatchPicker';
import type { ComputedLine, SaleLineInput } from '../types';

const discountLabel = (line: SaleLineInput): string | null => {
  if (line.discount.kind === 'percent') return `${line.discount.value_bp / 100}%`;
  if (line.discount.kind === 'flat') return formatPaise(line.discount.value_paise);
  return null;
};

/** The reason a line cannot be priced, shown on the line rather than as a
 *  page-level error - the operator has to know which line to fix. */
const Unresolved: React.FC<{ reason: string }> = ({ reason }) => (
  <span className="inline-flex items-start gap-1 text-[10px] text-red-600 font-semibold leading-snug">
    <AlertCircle size={11} className="shrink-0 mt-px" />
    {reason}
  </span>
);

export const LineRows: React.FC<{
  lines: SaleLineInput[];
  computed: ComputedLine[];
  today: string;
  activeLineId: string | null;
  onEditBatch: (lineId: string) => void;
  onEditDiscount: (lineId: string) => void;
  onRemove: (lineId: string) => void;
  onQuantity: (lineId: string, quantity: number) => void;
}> = ({ lines, computed, today, activeLineId, onEditBatch, onEditDiscount, onRemove, onQuantity }) => (
  <table className="w-full">
    <thead className="sticky top-0 bg-[#f8fafc] z-10">
      <tr className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
        <th className="text-left px-3 py-2 w-8">#</th>
        <th className="text-left px-3 py-2">Item</th>
        <th className="text-right px-3 py-2 w-20">Qty</th>
        <th className="text-right px-3 py-2 w-24">Rate</th>
        <th className="text-right px-3 py-2 w-20">Disc</th>
        <th className="text-right px-3 py-2 w-24">Taxable</th>
        <th className="text-right px-3 py-2 w-24">GST</th>
        <th className="text-right px-3 py-2 w-28">Amount</th>
        <th className="w-10" />
      </tr>
    </thead>
    <tbody>
      {lines.map((line, index) => {
        const result = computed[index];
        const active = line.line_id === activeLineId;
        return (
          <tr
            key={line.line_id}
            className={`border-t border-gray-100 transition-colors ${
              active ? 'bg-blue-50/60' : 'hover:bg-slate-50/60'
            }`}
          >
            <td className="px-3 py-2 text-[11px] font-mono text-gray-400">{index + 1}</td>
            <td className="px-3 py-2 min-w-0">
              <p className="text-xs font-semibold text-[#0f172a] truncate">{line.product_name}</p>
              <div className="flex items-center gap-2 flex-wrap mt-0.5">
                <span className="text-[10px] text-gray-400 font-mono">
                  HSN {line.hsn || '—'}
                </span>
                <button
                  onClick={() => onEditBatch(line.line_id)}
                  title="Change batch (F2)"
                  className="text-[10px] text-gray-500 font-mono hover:text-[#1b5dfc] inline-flex items-center gap-1 cursor-pointer"
                >
                  <Layers size={10} />
                  {line.batch_number || 'no batch'}
                </button>
                <ExpiryLabel expiry={line.expiry} today={today} />
              </div>
              {result?.unresolved_reason && <Unresolved reason={result.unresolved_reason} />}
            </td>
            <td className="px-3 py-2 text-right">
              <input
                value={line.quantity}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  if (Number.isFinite(next) && next >= 0) onQuantity(line.line_id, next);
                }}
                inputMode="numeric"
                aria-label={`Quantity for ${line.product_name}`}
                className="w-14 bg-transparent border border-transparent hover:border-gray-200 focus:border-[#1b5dfc] focus:bg-white rounded-lg px-1.5 py-1 text-xs font-mono tabular-nums text-right text-[#0f172a] focus:outline-none"
              />
            </td>
            <td className="px-3 py-2 text-right text-xs font-mono tabular-nums text-gray-600">
              {formatPaise(line.unit_price_paise)}
            </td>
            <td className="px-3 py-2 text-right">
              <button
                onClick={() => onEditDiscount(line.line_id)}
                title="Discount (F4)"
                className={`text-[11px] font-mono inline-flex items-center gap-0.5 cursor-pointer ${
                  discountLabel(line) ? 'text-[#1b5dfc] font-bold' : 'text-gray-300 hover:text-gray-500'
                }`}
              >
                {discountLabel(line) ?? <Percent size={11} />}
              </button>
            </td>
            <td className="px-3 py-2 text-right text-xs font-mono tabular-nums text-gray-600">
              {formatPaise(result?.taxable_paise ?? null)}
            </td>
            <td className="px-3 py-2 text-right text-xs font-mono tabular-nums text-gray-600">
              {result?.rate === null || result === undefined
                ? '—'
                : result.rate.supply_kind === 'exempt'
                  ? 'exempt'
                  : formatPaise((result.cgst_paise ?? 0) + (result.sgst_paise ?? 0))}
            </td>
            <td className="px-3 py-2 text-right text-xs font-mono tabular-nums font-bold text-[#0f172a]">
              {formatPaise(result?.line_total_paise ?? null)}
            </td>
            <td className="px-2 py-2">
              <button
                onClick={() => onRemove(line.line_id)}
                aria-label={`Remove ${line.product_name}`}
                className="p-1 text-gray-300 hover:text-red-500 rounded transition-colors cursor-pointer"
              >
                <Trash2 size={13} />
              </button>
            </td>
          </tr>
        );
      })}
    </tbody>
  </table>
);

/**
 * One mobile card, swipeable left to delete.
 *
 * The threshold is deliberately most of the card's width: a bill line removed
 * by an accidental thumb drag is a customer charged for something they did not
 * get, so the gesture has to be plainly intentional. Under the threshold the
 * card springs back.
 */
const SwipeCard: React.FC<{
  line: SaleLineInput;
  result: ComputedLine | undefined;
  index: number;
  today: string;
  onRemove: () => void;
  onEditQuantity: () => void;
  onEditBatch: () => void;
}> = ({ line, result, index, today, onRemove, onEditQuantity, onEditBatch }) => {
  const [offset, setOffset] = React.useState(0);
  const startX = React.useRef<number | null>(null);
  const THRESHOLD = 120;

  return (
    <div className="relative overflow-hidden rounded-2xl">
      <div className="absolute inset-0 bg-red-500 flex items-center justify-end pr-5">
        <Trash2 size={18} className="text-white" />
      </div>
      <div
        onTouchStart={(event) => {
          startX.current = event.touches[0].clientX;
        }}
        onTouchMove={(event) => {
          if (startX.current === null) return;
          const delta = event.touches[0].clientX - startX.current;
          setOffset(Math.min(0, delta));
        }}
        onTouchEnd={() => {
          if (offset < -THRESHOLD) onRemove();
          else setOffset(0);
          startX.current = null;
        }}
        style={{ transform: `translateX(${offset}px)` }}
        className={`relative bg-white border border-[#e2e8f0] p-3 ${
          offset === 0 ? 'transition-transform duration-200' : ''
        }`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-[#0f172a] leading-tight">
              <span className="text-gray-300 font-mono text-xs mr-1.5">{index + 1}</span>
              {line.product_name}
            </p>
            <button
              onClick={onEditBatch}
              className="flex items-center gap-1.5 mt-1 cursor-pointer"
            >
              <Layers size={11} className="text-gray-400" />
              <span className="text-[10px] text-gray-500 font-mono">
                {line.batch_number || 'no batch'}
              </span>
              <ExpiryLabel expiry={line.expiry} today={today} />
            </button>
          </div>
          <span className="text-sm font-bold font-mono tabular-nums text-[#0f172a] shrink-0">
            {formatPaise(result?.line_total_paise ?? null)}
          </span>
        </div>

        {result?.unresolved_reason && (
          <div className="mt-1.5">
            <Unresolved reason={result.unresolved_reason} />
          </div>
        )}

        <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-100">
          {/* The quantity is the field edited most on a phone, so it is a
              button-sized target rather than a text input. */}
          <button
            onClick={onEditQuantity}
            className="flex items-baseline gap-1.5 bg-slate-50 hover:bg-slate-100 border border-gray-200 rounded-xl px-3 py-1.5 cursor-pointer"
          >
            <span className="text-[10px] text-gray-500 font-semibold">Qty</span>
            <span className="text-base font-bold font-mono tabular-nums text-[#0f172a]">
              {line.quantity}
            </span>
          </button>
          <span className="text-[10px] text-gray-400 font-mono">
            {formatPaise(line.unit_price_paise)} each
          </span>
        </div>
      </div>
    </div>
  );
};

export const LineCards: React.FC<{
  lines: SaleLineInput[];
  computed: ComputedLine[];
  today: string;
  onRemove: (lineId: string) => void;
  onEditQuantity: (lineId: string) => void;
  onEditBatch: (lineId: string) => void;
}> = ({ lines, computed, today, onRemove, onEditQuantity, onEditBatch }) => (
  <div className="space-y-2">
    {lines.map((line, index) => (
      <SwipeCard
        key={line.line_id}
        line={line}
        result={computed[index]}
        index={index}
        today={today}
        onRemove={() => onRemove(line.line_id)}
        onEditQuantity={() => onEditQuantity(line.line_id)}
        onEditBatch={() => onEditBatch(line.line_id)}
      />
    ))}
  </div>
);
