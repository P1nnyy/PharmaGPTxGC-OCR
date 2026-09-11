/**
 * The F4 discount dialog.
 *
 * Percent and flat are captured as different things rather than one being
 * converted into the other, because the bill has to print which was given and
 * because a percentage re-derives correctly if the line quantity changes.
 *
 * A discount reduces the taxable value, so this is a tax-figure input: the
 * field refuses anything it cannot read exactly rather than coercing it.
 */

import React from 'react';

import { formatPaise, parseRupeesToPaise } from '../money';
import { Kbd, Modal } from './Primitives';
import type { Discount } from '../types';

export const DiscountDialog: React.FC<{
  current: Discount;
  lineGrossPaise: number | null;
  onApply: (discount: Discount) => void;
  onClose: () => void;
}> = ({ current, lineGrossPaise, onApply, onClose }) => {
  const [kind, setKind] = React.useState<'percent' | 'flat'>(
    current.kind === 'flat' ? 'flat' : 'percent'
  );
  const [text, setText] = React.useState(() => {
    if (current.kind === 'percent') return String(current.value_bp / 100);
    if (current.kind === 'flat') return (current.value_paise / 100).toFixed(2);
    return '';
  });
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [kind]);

  const parsed: Discount | null = React.useMemo(() => {
    const trimmed = text.trim();
    if (trimmed === '') return { kind: 'none' };
    if (kind === 'percent') {
      if (!/^\d{1,3}(\.\d{1,2})?$/.test(trimmed)) return null;
      const bp = Math.round(Number(trimmed) * 100);
      if (bp > 10000) return null;
      return { kind: 'percent', value_bp: bp };
    }
    const paise = parseRupeesToPaise(trimmed);
    if (paise === null || paise < 0) return null;
    if (lineGrossPaise !== null && paise > lineGrossPaise) return null;
    return { kind: 'flat', value_paise: paise };
  }, [kind, lineGrossPaise, text]);

  const preview =
    parsed === null || parsed.kind === 'none' || lineGrossPaise === null
      ? null
      : parsed.kind === 'percent'
        ? Math.round((lineGrossPaise * parsed.value_bp) / 10000)
        : parsed.value_paise;

  const apply = () => {
    if (parsed === null) return;
    onApply(parsed);
    onClose();
  };

  return (
    <Modal
      title="Discount on this line"
      onClose={onClose}
      footer={
        <>
          <span className="text-[10px] text-gray-400 mr-auto flex items-center gap-1.5">
            <Kbd>Enter</Kbd> apply
          </span>
          <button
            onClick={() => {
              onApply({ kind: 'none' });
              onClose();
            }}
            className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm cursor-pointer"
          >
            Remove
          </button>
          <button
            onClick={apply}
            disabled={parsed === null}
            className="bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Apply
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex gap-1.5" role="radiogroup" aria-label="Discount type">
          {(['percent', 'flat'] as const).map((option) => (
            <button
              key={option}
              role="radio"
              aria-checked={kind === option}
              onClick={() => setKind(option)}
              className={`flex-1 px-3 py-2 rounded-xl text-xs font-semibold border transition-colors cursor-pointer ${
                kind === option
                  ? 'bg-[#1b5dfc] text-white border-[#1b5dfc]'
                  : 'bg-white text-gray-600 border-gray-200 hover:bg-slate-50'
              }`}
            >
              {option === 'percent' ? 'Percentage' : 'Flat amount'}
            </button>
          ))}
        </div>

        <label className="block">
          <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
            {kind === 'percent' ? 'Percent off' : 'Rupees off'}
          </span>
          <input
            ref={inputRef}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                apply();
              }
            }}
            inputMode="decimal"
            placeholder={kind === 'percent' ? '10' : '25.00'}
            className={`mt-1 w-full bg-slate-50 border rounded-xl px-3 py-2.5 text-sm font-mono tabular-nums text-[#0f172a] focus:outline-none focus:bg-white transition-colors ${
              parsed === null ? 'border-red-300 focus:border-red-500' : 'border-gray-200 focus:border-[#1b5dfc]'
            }`}
          />
        </label>

        {parsed === null ? (
          <p className="text-[11px] text-red-600 leading-snug">
            {kind === 'percent'
              ? 'Enter a percentage between 0 and 100, to at most two decimal places.'
              : 'Enter an amount in rupees, to at most two decimal places, no larger than the line.'}
          </p>
        ) : (
          preview !== null && (
            <p className="text-[11px] text-gray-500">
              Takes <span className="font-mono font-bold text-[#0f172a]">{formatPaise(preview)}</span>{' '}
              off a line of {formatPaise(lineGrossPaise)}.
            </p>
          )
        )}

        <p className="text-[10px] text-gray-400 leading-snug border-t border-gray-100 pt-2">
          The discount comes off the taxable value, so the GST on this line is recomputed from the
          discounted figure.
        </p>
      </div>
    </Modal>
  );
};
