import React from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2 } from 'lucide-react';

import type { Severity } from '../types';

// Matches the reports feature's visual language deliberately - same card, same
// tile, same status hues - without importing its internals, which are private
// to that folder. Two of these hues sit below 3:1 on white, so each is always
// paired with an icon and a word: colour never carries the meaning alone.
export const STATUS: Record<Severity, { dot: string; tint: string; ink: string; label: string }> = {
  BLOCKING: { dot: '#d03b3b', tint: '#fdecec', ink: '#8f1d1d', label: 'Blocking' },
  WARNING: { dot: '#fab219', tint: '#fdf3e0', ink: '#7a5205', label: 'Warning' }
};

const SEVERITY_ICON: Record<Severity, React.ElementType> = {
  BLOCKING: AlertCircle,
  WARNING: AlertTriangle
};

const rupees = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

/** Indian grouping, two decimals, always. A tax figure shown as ₹1,234.5 reads
 *  as a different number from the one that was filed. */
export const Money: React.FC<{ value: number | null | undefined; muted?: boolean }> = ({
  value,
  muted
}) => {
  if (value === null || value === undefined) return <span className="text-gray-300">—</span>;
  return (
    <span
      className={`tabular-nums ${muted && value === 0 ? 'text-gray-300' : 'text-[#0f172a]'}`}
      // Negative figures matter here: a bucket that went negative is the whole
      // reason the close is refused, so it is coloured as well as signed.
      style={value < 0 ? { color: STATUS.BLOCKING.ink, fontWeight: 600 } : undefined}
    >
      {rupees.format(value)}
    </span>
  );
};

export const Card: React.FC<{
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}> = ({ title, subtitle, action, children, className = '' }) => (
  <section className={`bg-white rounded-2xl border border-[#e2e8f0] shadow-sm ${className}`}>
    {(title || action) && (
      <header className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-gray-100">
        <div>
          {title && <h3 className="text-sm font-bold text-[#0f172a]">{title}</h3>}
          {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
        </div>
        {action}
      </header>
    )}
    <div className="p-6">{children}</div>
  </section>
);

export const StatTile: React.FC<{
  label: string;
  value: string;
  hint?: string;
  tone?: 'default' | Severity;
}> = ({ label, value, hint, tone = 'default' }) => {
  const accent = tone === 'default' ? undefined : STATUS[tone];
  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{label}</span>
      <strong
        className="text-2xl font-bold text-[#0f172a] leading-tight tabular-nums"
        style={accent ? { color: accent.ink } : undefined}
      >
        {value}
      </strong>
      {hint && <p className="text-[11px] text-gray-500 leading-snug">{hint}</p>}
    </div>
  );
};

export const SeverityChip: React.FC<{ severity: Severity; label?: string }> = ({ severity, label }) => {
  const status = STATUS[severity];
  const Icon = SEVERITY_ICON[severity];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold"
      style={{ background: status.tint, color: status.ink }}
    >
      <Icon size={12} aria-hidden />
      {label ?? status.label}
    </span>
  );
};

export const AllClear: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="flex items-center gap-2 text-sm text-gray-600">
    <CheckCircle2 size={16} className="text-emerald-600" aria-hidden />
    {children}
  </p>
);

/** A table that scrolls inside its own box rather than widening the page. */
export const Table: React.FC<{ head: React.ReactNode; children: React.ReactNode }> = ({
  head,
  children
}) => (
  <div className="overflow-x-auto -mx-2 px-2">
    <table className="w-full text-sm border-collapse">
      <thead>
        <tr className="text-[11px] uppercase tracking-wide text-gray-400 text-left">{head}</tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  </div>
);

export const Th: React.FC<{ children?: React.ReactNode; right?: boolean }> = ({ children, right }) => (
  <th className={`font-semibold py-2 pr-4 whitespace-nowrap ${right ? 'text-right' : ''}`}>{children}</th>
);

export const Td: React.FC<{ children?: React.ReactNode; right?: boolean; className?: string }> = ({
  children,
  right,
  className = ''
}) => (
  <td className={`py-2 pr-4 border-t border-gray-100 ${right ? 'text-right' : ''} ${className}`}>
    {children}
  </td>
);

export const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="text-sm text-gray-500">{children}</p>
);
