import React from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';

import type { Drill, Figure } from '../types';

const rupees = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

export const money = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : rupees.format(value);

/**
 * A money figure, clickable when it can explain itself.
 *
 * This is the component the whole pack turns on. Every amount the API returns
 * carries a `drill`, and rendering all of them through here is what makes the
 * traceability requirement structural rather than something each report has to
 * remember. A figure with no drill renders as plain text - which is a visible
 * signal in itself that the number is a subtotal of others rather than
 * something with documents behind it.
 *
 * A caveat (provisional ITC, a figure rounded from stored decimals) shows as a
 * marker beside the number rather than in a footnote, because the doubt is
 * most needed exactly where the number is read.
 */
export const Amount: React.FC<{
  figure: Figure | null | undefined;
  onDrill?: (drill: Drill, label: string) => void;
  label?: string;
  muted?: boolean;
  bold?: boolean;
}> = ({ figure, onDrill, label = 'this figure', muted, bold }) => {
  if (!figure) return <span className="text-gray-300">—</span>;

  const text = money(figure.value);
  const dim = muted && figure.value === 0;
  const className = [
    'tabular-nums',
    dim ? 'text-gray-300' : 'text-[#0f172a]',
    bold ? 'font-semibold' : ''
  ].join(' ');

  const body = (
    <>
      <span style={figure.value < 0 ? { color: '#8f1d1d', fontWeight: 600 } : undefined}>
        {text}
      </span>
      {figure.caveat && (
        <span
          title={figure.caveat}
          aria-label={figure.caveat}
          className="ml-1 text-[10px] font-bold text-[#7a5205] align-super print:hidden"
        >
          ?
        </span>
      )}
    </>
  );

  if (!figure.drill || !onDrill) {
    return <span className={className}>{body}</span>;
  }

  return (
    <button
      type="button"
      onClick={() => onDrill(figure.drill as Drill, label)}
      title={
        figure.drill.count
          ? `${figure.drill.count} ${figure.drill.count === 1 ? 'document' : 'documents'} — click to see them`
          : 'Click to see the documents behind this'
      }
      className={`${className} underline decoration-dotted decoration-gray-300 underline-offset-4 hover:decoration-[#1b5dfc] hover:text-[#1b5dfc] cursor-pointer print:no-underline print:text-[#0f172a]`}
    >
      {body}
    </button>
  );
};

export const Card: React.FC<{
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}> = ({ title, subtitle, action, children, className = '' }) => (
  <section className={`statutory-card bg-white rounded-2xl border border-[#e2e8f0] shadow-sm ${className}`}>
    {(title || action) && (
      <header className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-gray-100">
        <div>
          {title && <h3 className="text-sm font-bold text-[#0f172a]">{title}</h3>}
          {subtitle && <p className="text-xs text-gray-500 mt-0.5 max-w-3xl">{subtitle}</p>}
        </div>
        <div className="print:hidden">{action}</div>
      </header>
    )}
    <div className="p-6">{children}</div>
  </section>
);

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

export const Td: React.FC<{
  children?: React.ReactNode;
  right?: boolean;
  className?: string;
}> = ({ children, right, className = '' }) => (
  <td className={`py-2 pr-4 border-t border-gray-100 align-top ${right ? 'text-right' : ''} ${className}`}>
    {children}
  </td>
);

export const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="text-sm text-gray-500">{children}</p>
);

export const Flag: React.FC<{ children: React.ReactNode; tone?: 'bad' | 'warn' | 'info' }> = ({
  children,
  tone = 'info'
}) => {
  const tones = {
    bad: { background: '#fdecec', color: '#8f1d1d' },
    warn: { background: '#fdf3e0', color: '#7a5205' },
    info: { background: '#eaf0ff', color: '#123c9e' }
  } as const;
  return (
    <span
      className="inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold mr-1 whitespace-nowrap"
      style={tones[tone]}
    >
      {children}
    </span>
  );
};

export const Note: React.FC<{ tone?: 'info' | 'warn' | 'bad'; children: React.ReactNode }> = ({
  tone = 'info',
  children
}) => {
  const styles = {
    info: { border: '#cfe0ff', background: '#eaf0ff', color: '#123c9e', Icon: Info },
    warn: { border: '#f5dfae', background: '#fdf3e0', color: '#7a5205', Icon: AlertTriangle },
    bad: { border: '#f3c9c9', background: '#fdecec', color: '#8f1d1d', Icon: AlertCircle }
  } as const;
  const { border, background, color, Icon } = styles[tone];
  return (
    <div
      className="rounded-xl border p-4 text-sm flex gap-2.5 items-start"
      style={{ borderColor: border, background, color }}
    >
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div className="leading-relaxed">{children}</div>
    </div>
  );
};

export const AllClear: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="flex items-center gap-2 text-sm text-gray-600">
    <CheckCircle2 size={16} className="text-emerald-600" aria-hidden />
    {children}
  </p>
);

/** The drawer that opens when a figure is clicked. */
export const DrillDrawer: React.FC<{
  open: boolean;
  title: string;
  loading: boolean;
  error: string | null;
  rows: Array<Record<string, unknown>>;
  onClose: () => void;
}> = ({ open, title, loading, error, rows, onClose }) => {
  if (!open) return null;

  const columns = rows.length
    ? Object.keys(rows[0]).filter((k) => !k.endsWith('_json'))
    : [];

  // A `_paise` column is rendered in rupees, so the heading drops the suffix
  // with the conversion. "TAXABLE PAISE" above a value reading ₹1,000.00 is
  // the same confusion the naming rule exists to prevent.
  const heading = (key: string) =>
    (key.endsWith('_paise') ? key.slice(0, -6) : key).replace(/_/g, ' ');

  const render = (key: string, value: unknown) => {
    if (value === null || value === undefined) return '—';
    if (key.endsWith('_paise') && typeof value === 'number') return money(value / 100);
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end print:hidden" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} aria-hidden />
      <aside className="relative bg-white w-full max-w-4xl h-full shadow-2xl flex flex-col">
        <header className="flex items-start justify-between gap-4 px-6 py-4 border-b border-gray-100">
          <div>
            <h3 className="text-sm font-bold text-[#0f172a]">Behind {title}</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {loading ? 'Fetching…' : `${rows.length} ${rows.length === 1 ? 'record' : 'records'}`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 hover:bg-gray-100"
            aria-label="Close"
          >
            <X size={16} aria-hidden />
          </button>
        </header>

        <div className="flex-1 overflow-auto p-6">
          {error && <Note tone="bad">{error}</Note>}
          {!error && !loading && rows.length === 0 && (
            <Empty>Nothing sits behind this figure.</Empty>
          )}
          {!error && rows.length > 0 && (
            <Table head={columns.map((c) => <Th key={c} right={c.endsWith('_paise')}>{heading(c)}</Th>)}>
              {rows.map((row, index) => (
                <tr key={String(row.id ?? index)}>
                  {columns.map((column) => (
                    <Td
                      key={column}
                      right={column.endsWith('_paise')}
                      className="whitespace-nowrap"
                    >
                      {render(column, row[column])}
                    </Td>
                  ))}
                </tr>
              ))}
            </Table>
          )}
        </div>
      </aside>
    </div>
  );
};
