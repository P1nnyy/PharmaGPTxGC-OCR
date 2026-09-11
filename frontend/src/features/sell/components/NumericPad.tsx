/**
 * The mobile quantity pad.
 *
 * A dedicated pad rather than `inputMode="numeric"` because the OS keyboard on
 * a phone covers the bill, takes a moment to appear, and puts the digits in a
 * different place on every handset. Counter staff enter quantities all day
 * with one hand; the keys need to be in the same place every time and big
 * enough to hit without looking.
 */

import React from 'react';
import { Check, Delete } from 'lucide-react';

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back'] as const;

export const NumericPad: React.FC<{
  value: string;
  label: string;
  /**
   * Takes an updater rather than a value, deliberately.
   *
   * Two taps landing in the same render pass would otherwise both read the
   * same stale `value` prop and the first digit would be lost - typing "12"
   * gives "22". Counter staff enter quantities faster than React re-renders,
   * so the append has to be computed from the current state, not from a prop
   * captured when the pad last drew.
   */
  onChange: (update: (current: string) => string) => void;
  onCommit: () => void;
  onCancel: () => void;
}> = ({ value, label, onChange, onCommit, onCancel }) => {
  const press = (key: (typeof KEYS)[number]) => {
    if (key === 'clear') return onChange(() => '');
    if (key === 'back') return onChange((current) => current.slice(0, -1));
    onChange((current) => {
      // Leading zeros are meaningless in a pack count and read as a typo.
      if (current === '0') return key;
      if (current.length >= 4) return current;
      return current + key;
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end bg-black/50 backdrop-blur-xs">
      <button
        aria-label="Cancel"
        onClick={onCancel}
        className="flex-1 w-full cursor-pointer"
        tabIndex={-1}
      />
      <div className="bg-white rounded-t-3xl border-t border-gray-200 shadow-2xl p-4 pb-6 space-y-3 animate-in slide-in-from-bottom duration-200">
        <div className="text-center">
          <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">{label}</p>
          <p className="text-4xl font-bold font-mono tabular-nums text-[#0f172a] mt-1 min-h-[2.75rem]">
            {value || '0'}
          </p>
        </div>

        <div className="grid grid-cols-3 gap-2">
          {KEYS.map((key) => (
            <button
              key={key}
              onClick={() => press(key)}
              className={`h-14 rounded-2xl text-xl font-bold transition-colors cursor-pointer active:scale-95 ${
                key === 'clear' || key === 'back'
                  ? 'bg-slate-100 text-gray-500 hover:bg-slate-200'
                  : 'bg-slate-50 text-[#0f172a] hover:bg-slate-100'
              }`}
              aria-label={key === 'back' ? 'Backspace' : key === 'clear' ? 'Clear' : key}
            >
              {key === 'back' ? (
                <Delete size={20} className="mx-auto" />
              ) : key === 'clear' ? (
                <span className="text-xs font-bold uppercase tracking-wide">Clear</span>
              ) : (
                key
              )}
            </button>
          ))}
        </div>

        <button
          onClick={onCommit}
          disabled={value === '' || Number(value) <= 0}
          className="w-full h-14 rounded-2xl bg-[#1b5dfc] hover:bg-blue-700 text-white text-base font-bold flex items-center justify-center gap-2 shadow-lg shadow-blue-500/20 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Check size={20} />
          Done
        </button>
      </div>
    </div>
  );
};
