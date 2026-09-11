/**
 * The F9 payment sheet: how the bill was paid, possibly across several methods.
 *
 * Opens with the whole amount on the device's most-used method, because that
 * is the answer most of the time and it should take zero keystrokes. Splitting
 * is there when it is needed and out of the way when it is not.
 *
 * The sheet will not settle for less or more than the bill. A payment split
 * that does not add up to the total is a cash-drawer discrepancy tomorrow, so
 * it is caught while the customer is still standing there.
 */

import React from 'react';
import { Banknote, CreditCard, Smartphone, UserRound } from 'lucide-react';

import { formatPaise, parseRupeesToPaise } from '../money';
import { Kbd, Modal } from './Primitives';
import type { PaymentMethod, PaymentSplit } from '../types';

const METHODS: { id: PaymentMethod; label: string; icon: React.ElementType; needsReference: boolean }[] = [
  { id: 'cash', label: 'Cash', icon: Banknote, needsReference: false },
  { id: 'upi', label: 'UPI', icon: Smartphone, needsReference: true },
  { id: 'card', label: 'Card', icon: CreditCard, needsReference: true },
  { id: 'credit', label: 'Credit', icon: UserRound, needsReference: false }
];

export const PaymentSheet: React.FC<{
  totalPaise: number;
  preferred: PaymentMethod;
  initial: PaymentSplit[];
  onRememberPreferred: (method: PaymentMethod) => void;
  onConfirm: (payments: PaymentSplit[]) => void;
  onClose: () => void;
}> = ({ totalPaise, preferred, initial, onRememberPreferred, onConfirm, onClose }) => {
  const [splits, setSplits] = React.useState<PaymentSplit[]>(() =>
    initial.length > 0
      ? initial
      : [{ method: preferred, amount_paise: totalPaise, reference: null }]
  );

  const allocated = splits.reduce((sum, split) => sum + split.amount_paise, 0);
  const remaining = totalPaise - allocated;
  const balanced = remaining === 0;

  const setAmount = (index: number, text: string) => {
    const paise = text.trim() === '' ? 0 : parseRupeesToPaise(text);
    if (paise === null) return;
    setSplits((current) =>
      current.map((split, i) => (i === index ? { ...split, amount_paise: paise } : split))
    );
  };

  const addMethod = (method: PaymentMethod) => {
    if (splits.some((split) => split.method === method)) return;
    setSplits((current) => [
      ...current,
      // A new row takes whatever is still unpaid, which is the amount it is
      // being added for in almost every case.
      { method, amount_paise: Math.max(0, remaining), reference: null }
    ]);
  };

  const confirm = () => {
    if (!balanced) return;
    const used = splits.filter((split) => split.amount_paise > 0);
    // The method that took the largest share is the one worth remembering.
    const dominant = [...used].sort((a, b) => b.amount_paise - a.amount_paise)[0];
    if (dominant) onRememberPreferred(dominant.method);
    onConfirm(used);
    onClose();
  };

  return (
    <Modal
      title="Payment"
      onClose={onClose}
      footer={
        <>
          <span className="text-[10px] text-gray-400 mr-auto flex items-center gap-1.5">
            <Kbd>Enter</Kbd> confirm
          </span>
          <button
            onClick={onClose}
            className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={confirm}
            disabled={!balanced}
            className="bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-5 py-2 rounded-xl text-xs shadow-md cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Confirm {formatPaise(totalPaise)}
          </button>
        </>
      }
    >
      <div
        className="space-y-3"
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            confirm();
          }
        }}
      >
        <div className="flex items-baseline justify-between bg-slate-50 border border-slate-200 rounded-xl px-3 py-2.5">
          <span className="text-[11px] font-semibold text-gray-600">Bill total</span>
          <span className="text-lg font-bold font-mono tabular-nums text-[#0f172a]">
            {formatPaise(totalPaise)}
          </span>
        </div>

        <div className="space-y-2">
          {splits.map((split, index) => {
            const meta = METHODS.find((m) => m.id === split.method)!;
            const Icon = meta.icon;
            return (
              <div
                key={split.method}
                className="flex items-center gap-2 border border-gray-200 rounded-xl px-3 py-2"
              >
                <Icon size={16} className="text-gray-500 shrink-0" />
                <span className="text-xs font-semibold text-[#0f172a] w-14 shrink-0">
                  {meta.label}
                </span>
                <input
                  autoFocus={index === 0}
                  defaultValue={(split.amount_paise / 100).toFixed(2)}
                  onChange={(event) => setAmount(index, event.target.value)}
                  inputMode="decimal"
                  aria-label={`${meta.label} amount`}
                  className="flex-1 min-w-0 bg-slate-50 border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm font-mono tabular-nums text-right text-[#0f172a] focus:outline-none focus:bg-white focus:border-[#1b5dfc]"
                />
                {meta.needsReference && (
                  <input
                    placeholder="Ref"
                    aria-label={`${meta.label} reference`}
                    onChange={(event) =>
                      setSplits((current) =>
                        current.map((s, i) =>
                          i === index ? { ...s, reference: event.target.value || null } : s
                        )
                      )
                    }
                    className="w-20 shrink-0 bg-slate-50 border border-gray-200 rounded-lg px-2 py-1.5 text-[11px] font-mono text-[#0f172a] focus:outline-none focus:bg-white focus:border-[#1b5dfc]"
                  />
                )}
                {splits.length > 1 && (
                  <button
                    onClick={() => setSplits((current) => current.filter((_, i) => i !== index))}
                    aria-label={`Remove ${meta.label}`}
                    className="text-gray-400 hover:text-red-500 text-xs px-1 cursor-pointer shrink-0"
                  >
                    ✕
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {METHODS.filter((m) => !splits.some((s) => s.method === m.id)).map((method) => (
            <button
              key={method.id}
              onClick={() => addMethod(method.id)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-semibold border border-gray-200 text-gray-600 bg-white hover:bg-slate-50 cursor-pointer"
            >
              <method.icon size={13} />+ {method.label}
            </button>
          ))}
        </div>

        {!balanced && (
          <p
            className={`text-[11px] font-semibold ${remaining > 0 ? 'text-amber-700' : 'text-red-600'}`}
          >
            {remaining > 0
              ? `${formatPaise(remaining)} still unpaid.`
              : `${formatPaise(-remaining)} more than the bill.`}
          </p>
        )}

        <p className="text-[10px] text-gray-400 leading-snug border-t border-gray-100 pt-2">
          The method taking the largest share becomes this device's default for the next bill.
        </p>
      </div>
    </Modal>
  );
};
