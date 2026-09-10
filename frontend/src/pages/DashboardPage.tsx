import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertCircle, ArrowDownRight, ArrowRight, ArrowUpRight,
  CheckCircle2, Loader2, RefreshCw
} from 'lucide-react';

import { managementApi } from '../features/management/api';
import type { DashboardCard, DashboardReport } from '../features/management/types';

/**
 * Four cards, each one a number somebody can act on.
 *
 * This page used to show lifetime scans, invoices processed and products in
 * catalogue. Every one of those describes the software's activity rather than
 * the shop's, and none of them changes what anybody does today - which is why
 * a dashboard made of them gets opened once and then ignored.
 *
 * The test each card here had to pass: **if this number moves, does the
 * shopkeeper do something differently?** Input credit at risk from expiry
 * passes it hardest, which is why it is not buried at the bottom.
 *
 * Every figure comes from `/management/dashboard`. Nothing is computed here.
 */

const rupees = new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', maximumFractionDigits: 0
});

const TONES = {
  neutral: { border: '#e2e8f0', background: '#ffffff', ink: '#0f172a', accent: '#64748b' },
  good: { border: '#c6e9d4', background: '#f4fbf7', ink: '#1c6b41', accent: '#1c9c66' },
  warn: { border: '#f5dfae', background: '#fffbf3', ink: '#7a5205', accent: '#b8860b' },
  bad: { border: '#f3c9c9', background: '#fff7f7', ink: '#8f1d1d', accent: '#d03b3b' }
} as const;

const Delta: React.FC<{ percent?: number | null; label?: string; was?: number }> = ({
  percent, label, was
}) => {
  if (percent === null || percent === undefined) {
    return <span className="text-[11px] text-gray-400">{label ? `${label} — no comparison` : ''}</span>;
  }
  const up = percent >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="inline-flex items-center gap-1 text-[11px]">
      <span className={`inline-flex items-center gap-0.5 font-semibold ${
        up ? 'text-[#1c6b41]' : 'text-[#8f1d1d]'
      }`}>
        <Icon size={12} aria-hidden />{Math.abs(percent)}%
      </span>
      <span className="text-gray-500">
        {label}{was !== undefined ? ` (${rupees.format(was)})` : ''}
      </span>
    </span>
  );
};

const Card: React.FC<{ card: DashboardCard }> = ({ card }) => {
  const tone = TONES[card.tone];
  const value = card.unit === 'currency' ? rupees.format(card.value) : String(card.value);

  return (
    <Link
      to={card.link}
      className="group rounded-2xl border p-5 flex flex-col gap-1.5 transition-shadow hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1b5dfc]"
      style={{ borderColor: tone.border, background: tone.background }}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: tone.accent }}>
          {card.title}
        </span>
        <ArrowRight
          size={14}
          className="text-gray-300 group-hover:text-[#1b5dfc] transition-colors"
          aria-hidden
        />
      </span>

      <strong className="text-3xl font-bold leading-tight tabular-nums" style={{ color: tone.ink }}>
        {value}
      </strong>

      <span className="text-xs text-gray-600">{card.detail}</span>

      {card.comparison_label && (
        <Delta
          percent={card.comparison_percent}
          label={card.comparison_label}
          was={card.comparison_value}
        />
      )}

      {card.secondary && (
        <span className="text-[11px] text-gray-500">
          {card.secondary.label}: <strong className="tabular-nums">
            {typeof card.secondary.value === 'number'
              ? rupees.format(card.secondary.value)
              : card.secondary.value}
          </strong>
        </span>
      )}

      {card.note && (
        <span className="text-[11px] leading-snug mt-0.5" style={{ color: tone.ink }}>
          {card.note}
        </span>
      )}
    </Link>
  );
};

export const DashboardPage: React.FC = () => {
  const [report, setReport] = useState<DashboardReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await managementApi.dashboard());
    } catch (caught) {
      // Say the load failed rather than rendering zeroes, which would read as
      // "no sales, no stock, nothing expiring" - a very different claim.
      setError(caught instanceof Error ? caught.message : 'Could not load the dashboard.');
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const blocking = report?.cards.find((c) => c.id === 'compliance_actions');
  const atRisk = report?.cards.find((c) => c.id === 'itc_at_risk');

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1400px] mx-auto">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#0f172a]">Today</h1>
          <p className="text-sm text-gray-500 mt-1">
            {report ? `As of ${report.as_of}` : 'Where the shop stands right now.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white hover:bg-gray-50"
        >
          <RefreshCw size={14} aria-hidden /> Refresh
        </button>
      </header>

      {loading && (
        <p className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" aria-hidden /> Working out where things stand…
        </p>
      )}

      {error && (
        <div className="rounded-xl border border-[#f3c9c9] bg-[#fdecec] p-4 text-sm text-[#8f1d1d] flex gap-2.5">
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
          {error}
        </div>
      )}

      {report && !loading && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {report.cards.map((card) => <Card key={card.id} card={card} />)}
          </div>

          {/* One line under the cards, and only when there is something to say. */}
          {atRisk && atRisk.value > 0 ? (
            <p className="text-sm text-gray-600">
              The quickest win today is usually the expiry list —{' '}
              <Link to="/reports/expiry-risk" className="text-[#1b5dfc] hover:underline">
                see what can still go back to the distributor
              </Link>.
            </p>
          ) : blocking && blocking.value === 0 ? (
            <p className="flex items-center gap-2 text-sm text-gray-600">
              <CheckCircle2 size={15} className="text-emerald-600" aria-hidden />
              Nothing expiring soon and nothing blocking this period's return.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
};
