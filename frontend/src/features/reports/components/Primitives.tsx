import React from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, Info, Loader2 } from 'lucide-react';

import type { Severity } from '../types';

// One hue carries every magnitude bar in this feature. Each chart plots a
// single series, so colour never has to encode identity — position and the row
// label do that — and a categorical palette would only invite hue cycling.
export const SERIES = '#1b5dfc';

// Reserved status colours, never reused for a series. Each is paired with an
// icon and a text label wherever it appears: two of these sit below 3:1 on
// white, so hue alone must never carry the meaning. Chip text uses its own
// darker ink for legibility; the status hue rides on the dot and the tint.
export const STATUS: Record<Severity, { dot: string; tint: string; ink: string; label: string }> = {
  blocking: { dot: '#d03b3b', tint: '#fdecec', ink: '#8f1d1d', label: 'Blocking' },
  warning: { dot: '#fab219', tint: '#fdf3e0', ink: '#7a5205', label: 'Warning' },
  info: { dot: '#1b5dfc', tint: '#eaf0ff', ink: '#123c9e', label: 'Info' }
};

const SEVERITY_ICON: Record<Severity, React.ElementType> = {
  blocking: AlertCircle,
  warning: AlertTriangle,
  info: Info
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
  tone?: 'default' | 'blocking' | 'warning';
}> = ({ label, value, hint, tone = 'default' }) => {
  const accent = tone === 'default' ? undefined : STATUS[tone === 'blocking' ? 'blocking' : 'warning'];
  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{label}</span>
      <strong
        className="text-2xl font-bold text-[#0f172a] leading-tight"
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
      className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide whitespace-nowrap"
      style={{ background: status.tint, color: status.ink }}
    >
      <Icon size={11} aria-hidden="true" />
      {label ?? status.label}
    </span>
  );
};

/** A share-of-total bar. Single hue: the row label carries identity. */
export const ShareBar: React.FC<{ share: number | null; title?: string }> = ({ share, title }) => (
  <div className="w-full h-1.5 rounded-full bg-[#eef2f7] overflow-hidden" title={title}>
    <div
      className="h-full rounded-full transition-[width] duration-300"
      style={{ width: `${Math.max(0, Math.min(1, share ?? 0)) * 100}%`, background: SERIES }}
    />
  </div>
);

export const LoadingState: React.FC<{ label?: string }> = ({ label = 'Loading report…' }) => (
  <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-500">
    <Loader2 size={16} className="animate-spin" aria-hidden="true" />
    <span>{label}</span>
  </div>
);

export const ErrorState: React.FC<{ message: string; onRetry?: () => void }> = ({ message, onRetry }) => (
  <div className="flex flex-col items-center gap-3 py-12 text-center">
    <AlertCircle size={28} style={{ color: STATUS.blocking.dot }} aria-hidden="true" />
    <p className="text-sm font-semibold text-[#0f172a]">{message}</p>
    {onRetry && (
      <button
        onClick={onRetry}
        className="text-xs font-semibold text-[#1b5dfc] hover:text-[#154ecb] cursor-pointer"
      >
        Try again
      </button>
    )}
  </div>
);

export const EmptyState: React.FC<{ title: string; detail?: string; icon?: React.ReactNode }> = ({
  title,
  detail,
  icon
}) => (
  <div className="flex flex-col items-center gap-2 py-12 text-center">
    {icon ?? <CheckCircle2 size={28} className="text-gray-300" aria-hidden="true" />}
    <p className="text-sm font-semibold text-[#0f172a]">{title}</p>
    {detail && <p className="text-xs text-gray-500 max-w-sm">{detail}</p>}
  </div>
);

/** Wide tables scroll inside their own container so the page never does. */
export const TableScroll: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="overflow-x-auto -mx-6 px-6">{children}</div>
);

export const Th: React.FC<{ children: React.ReactNode; align?: 'left' | 'right' }> = ({
  children,
  align = 'left'
}) => (
  <th
    className={`text-[10px] font-semibold text-gray-400 uppercase tracking-wider pb-2 px-3 whitespace-nowrap ${
      align === 'right' ? 'text-right' : 'text-left'
    }`}
  >
    {children}
  </th>
);

export const Td: React.FC<{
  children: React.ReactNode;
  align?: 'left' | 'right';
  className?: string;
}> = ({ children, align = 'left', className = '' }) => (
  <td
    className={`py-2.5 px-3 text-xs text-gray-700 border-t border-gray-100 ${
      align === 'right' ? 'text-right tabular-nums' : 'text-left'
    } ${className}`}
  >
    {children}
  </td>
);

/** Shown wherever a report is filtered, so a partial total never reads as complete. */
export const ExclusionNotice: React.FC<{ count: number; value: string }> = ({ count, value }) => {
  if (count <= 0) return null;
  return (
    <p className="text-[11px] text-gray-500 flex items-center gap-1.5 mt-3">
      <Info size={12} className="shrink-0" aria-hidden="true" />
      <span>
        {count} invoice{count === 1 ? '' : 's'} worth <strong className="text-gray-700">{value}</strong> not
        included — still awaiting verification.
      </span>
    </p>
  );
};
