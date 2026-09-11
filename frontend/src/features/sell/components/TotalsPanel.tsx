/**
 * The running totals, fixed beside the lines on desktop.
 *
 * Every figure renders through `formatPaise`, which shows an em dash for a
 * value that could not be computed. That is the whole contract of this panel:
 * a number here is a number the bill will carry, and anything uncertain is
 * visibly absent rather than shown as zero.
 */

import React from 'react';

import { formatPaise } from '../money';
import type { SaleTotals } from '../types';

const Row: React.FC<{
  label: string;
  paise: number | null;
  strong?: boolean;
  muted?: boolean;
}> = ({ label, paise, strong = false, muted = false }) => (
  <div className={`flex items-baseline justify-between gap-4 ${strong ? 'pt-2' : ''}`}>
    <span
      className={`${
        strong ? 'text-xs font-bold text-[#0f172a]' : 'text-[11px] text-gray-500'
      } ${muted ? 'text-gray-400' : ''}`}
    >
      {label}
    </span>
    <span
      className={`font-mono tabular-nums ${
        strong ? 'text-lg font-bold text-[#0f172a]' : 'text-xs text-[#0f172a]'
      } ${muted ? 'text-gray-400' : ''}`}
    >
      {formatPaise(paise)}
    </span>
  </div>
);

export const TotalsPanel: React.FC<{ totals: SaleTotals; lineCount: number }> = ({
  totals,
  lineCount
}) => (
  <div className="space-y-1.5">
    <div className="flex items-center justify-between">
      <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Bill total</span>
      <span className="text-[10px] text-gray-400 font-mono">
        {lineCount} line{lineCount === 1 ? '' : 's'}
      </span>
    </div>

    <div className="space-y-1 pt-1">
      <Row label="Taxable value" paise={totals.taxable_paise} />
      <Row label="CGST" paise={totals.cgst_paise} />
      <Row label="SGST" paise={totals.sgst_paise} />
      <Row label="Exempt value" paise={totals.exempt_paise} muted={totals.exempt_paise === 0} />
      <Row label="Round off" paise={totals.round_off_paise} muted={totals.round_off_paise === 0} />
    </div>

    <div className="border-t border-gray-200 mt-1">
      <Row label="Grand total" paise={totals.grand_total_paise} strong />
    </div>

    {/* The per-rate breakdown the bill prints. Shown live so a wrong rate on a
        line is noticed at the counter rather than on the printed bill. */}
    {totals.blocks.length > 0 && (
      <div className="pt-2 mt-1 border-t border-dashed border-gray-200 space-y-1">
        <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400">
          Rate blocks
        </span>
        {totals.blocks.map((block) => (
          <div
            key={`${block.supply_kind}-${block.rate_bp}`}
            className="flex items-baseline justify-between gap-3 text-[10px]"
          >
            <span className="text-gray-500 font-mono">
              {block.supply_kind === 'exempt' ? 'Exempt' : `${block.rate_bp / 100}%`}
            </span>
            <span className="font-mono tabular-nums text-gray-600">
              {formatPaise(
                block.supply_kind === 'exempt' ? block.exempt_paise : block.taxable_paise
              )}
            </span>
          </div>
        ))}
      </div>
    )}

    {totals.reconciliation_error && (
      <p className="text-[10px] text-red-600 leading-snug pt-2 font-semibold">
        {totals.reconciliation_error}
      </p>
    )}
  </div>
);
