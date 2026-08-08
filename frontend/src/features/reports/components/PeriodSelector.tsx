import React from 'react';
import { Calendar } from 'lucide-react';

import type { PeriodKind, PeriodQuery } from '../types';

interface Props {
  value: PeriodQuery;
  onChange: (next: PeriodQuery) => void;
  /** Label resolved by the server, so the UI never re-derives period bounds. */
  resolvedLabel?: string;
}

/** Financial years offered in the picker, newest first. */
function financialYears(count = 4): number[] {
  const today = new Date();
  const currentFy = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
  return Array.from({ length: count }, (_, index) => currentFy - index);
}

const KINDS: { value: PeriodKind; label: string }[] = [
  { value: 'fy', label: 'Financial year' },
  { value: 'quarter', label: 'Quarter' },
  { value: 'month', label: 'Month' }
];

const SELECT_CLASS =
  'text-xs font-medium text-[#0f172a] bg-white border border-[#e2e8f0] rounded-lg px-2.5 py-1.5 ' +
  'focus:outline-none focus:ring-2 focus:ring-[#1b5dfc]/30 focus:border-[#1b5dfc] cursor-pointer';

/**
 * Period picker built around the Indian financial year.
 *
 * Calendar-year ranges are deliberately not offered: nothing downstream — GST
 * returns, ITC claims, an audit — is pulled on one, so offering it would only
 * produce totals that reconcile against nothing.
 */
export const PeriodSelector: React.FC<Props> = ({ value, onChange, resolvedLabel }) => {
  const years = financialYears();
  const kind = value.kind ?? 'fy';
  const fy = value.fy ?? years[0];

  const setKind = (nextKind: PeriodKind) => {
    // Each kind needs its own parameters; carrying the previous kind's over
    // would send a quarter with a month, or a month with no month set.
    if (nextKind === 'month') {
      const today = new Date();
      onChange({
        ...value,
        kind: 'month',
        month: `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`,
        quarter: undefined
      });
      return;
    }
    onChange({
      ...value,
      kind: nextKind,
      fy,
      quarter: nextKind === 'quarter' ? (value.quarter ?? 1) : undefined,
      month: undefined
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="flex items-center gap-1.5 text-xs text-gray-500">
        <Calendar size={13} aria-hidden="true" />
        <span className="sr-only">Reporting period</span>
      </span>

      <select
        className={SELECT_CLASS}
        value={kind}
        onChange={(e) => setKind(e.target.value as PeriodKind)}
        aria-label="Period type"
      >
        {KINDS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      {kind === 'month' ? (
        <input
          type="month"
          className={SELECT_CLASS}
          value={value.month ?? ''}
          onChange={(e) => onChange({ ...value, month: e.target.value })}
          aria-label="Month"
        />
      ) : (
        <select
          className={SELECT_CLASS}
          value={fy}
          onChange={(e) => onChange({ ...value, fy: Number(e.target.value) })}
          aria-label="Financial year"
        >
          {years.map((year) => (
            <option key={year} value={year}>
              FY {year}-{String(year + 1).slice(-2)}
            </option>
          ))}
        </select>
      )}

      {kind === 'quarter' && (
        <select
          className={SELECT_CLASS}
          value={value.quarter ?? 1}
          onChange={(e) => onChange({ ...value, quarter: Number(e.target.value) })}
          aria-label="Quarter"
        >
          {[1, 2, 3, 4].map((quarter) => (
            <option key={quarter} value={quarter}>
              Q{quarter}
            </option>
          ))}
        </select>
      )}

      <select
        className={SELECT_CLASS}
        value={value.statuses ?? 'verified'}
        onChange={(e) => onChange({ ...value, statuses: e.target.value })}
        aria-label="Invoice status"
      >
        <option value="verified">Verified only</option>
        <option value="all">All invoices</option>
      </select>

      {resolvedLabel && (
        <span className="text-[11px] text-gray-400 ml-1 hidden sm:inline">{resolvedLabel}</span>
      )}
    </div>
  );
};
