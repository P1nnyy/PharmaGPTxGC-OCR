import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, Loader2, Lock, RefreshCw } from 'lucide-react';

import { gstr1Api } from './api';
import { Card, Money, StatTile } from './components/Primitives';
import { ReturnTables } from './components/ReturnTables';
import { ValidationPanel } from './components/ValidationPanel';
import type { Gstr1Return } from './types';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];

/** `092026`. The period a return is filed for, which is not a date range. */
const toPeriod = (month: number, year: number) => `${String(month + 1).padStart(2, '0')}${year}`;

const rupees = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0
});

export const Gstr1Page: React.FC = () => {
  const now = new Date();
  // Defaults to last month, because that is the one being filed. The current
  // month is still open and nobody files a period they are still selling in.
  const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const [month, setMonth] = useState(previous.getMonth());
  const [year, setYear] = useState(previous.getFullYear());

  const [data, setData] = useState<Gstr1Return | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set());
  const [closing, setClosing] = useState(false);

  const period = useMemo(() => toPeriod(month, year), [month, year]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await gstr1Api.preview(period);
      setData(result);
      // Acknowledgements are per period and are not carried across a change of
      // month: accepting a problem in September says nothing about August.
      setAcknowledged(new Set());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load this period.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (id: string) =>
    setAcknowledged((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const close = async () => {
    if (!data) return;
    const label = data.period.label;
    const months = data.period.months.length;
    const confirmed = window.confirm(
      months > 1
        ? `Close ${label}? This locks all ${months} months of the quarter. Sales in them can no longer be edited — a correction becomes a credit note or an amendment.`
        : `Close ${label}? Sales in it can no longer be edited — a correction becomes a credit note or an amendment.`
    );
    if (!confirmed) return;

    setClosing(true);
    setError(null);
    try {
      const result = await gstr1Api.close(period, [...acknowledged]);
      setData(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not close this period.');
      // The server recomputes on close, so what it refused on may differ from
      // what the screen was showing. Re-read rather than leaving a stale list.
      void load();
    } finally {
      setClosing(false);
    }
  };

  const downloadPayload = async () => {
    const payload = await gstr1Api.payload(period);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `gstr1-${period}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const isClosed = data?.period.status === 'CLOSED';
  const outstanding = data?.validation.blocking.filter((i) => !acknowledged.has(i.id)) ?? [];

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1400px] mx-auto">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#0f172a]">GSTR-1 — outward supplies</h1>
          <p className="text-sm text-gray-500 mt-1">
            {data
              ? `${data.period.label} · ${
                  data.period.frequency === 'QUARTERLY' ? 'quarterly filer' : 'monthly filer'
                }`
              : 'Review a period before closing it.'}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={month}
            onChange={(event) => setMonth(Number(event.target.value))}
            className="rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white"
            aria-label="Month"
          >
            {MONTHS.map((name, index) => (
              <option key={name} value={index}>{name}</option>
            ))}
          </select>
          <input
            type="number"
            value={year}
            min={2017}
            max={now.getFullYear() + 1}
            onChange={(event) => setYear(Number(event.target.value))}
            className="rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm w-24 bg-white"
            aria-label="Year"
          />
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white hover:bg-gray-50"
          >
            <RefreshCw size={14} aria-hidden /> Refresh
          </button>
        </div>
      </header>

      {loading && (
        <p className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" aria-hidden /> Working out the return…
        </p>
      )}

      {error && (
        <div className="rounded-xl border border-[#f3c9c9] bg-[#fdecec] p-4 text-sm text-[#8f1d1d]">
          {error}
        </div>
      )}

      {data && !loading && (
        <>
          {data.period.frequency === 'QUARTERLY' && (
            <div className="rounded-xl border border-[#cfe0ff] bg-[#eaf0ff] p-4 text-sm text-[#123c9e]">
              This shop is on QRMP, so one return covers {data.period.months.length} months —{' '}
              {data.period.start_date} to {data.period.end_date}. Closing it locks all of them.
            </div>
          )}

          {data.is_nil_return && (
            <div className="rounded-xl border border-[#cfe0ff] bg-[#eaf0ff] p-4 text-sm text-[#123c9e]">
              Nothing was supplied in {data.period.label}. A nil GSTR-1 still has to be
              filed — a late fee accrues for every day a period goes unfiled, whether or
              not there was anything to report.
            </div>
          )}

          {isClosed && (
            <div className="rounded-xl border border-[#e2e8f0] bg-gray-50 p-4 text-sm text-gray-700 flex items-center gap-2">
              <Lock size={15} aria-hidden />
              <span>
                Closed{data.period.closed_at ? ` on ${data.period.closed_at.slice(0, 10)}` : ''}.
                Sales in this period are locked; a correction is a credit note or an
                amendment. The payload below is the one that was filed, not a fresh
                computation.
              </span>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-4">
            <StatTile label="Taxable value" value={rupees.format(data.totals.taxable)} />
            <StatTile label="CGST" value={rupees.format(data.totals.cgst)} />
            <StatTile label="SGST" value={rupees.format(data.totals.sgst)} />
            <StatTile label="IGST" value={rupees.format(data.totals.igst)} />
            <StatTile
              label="Nil / exempt"
              value={rupees.format(data.totals.untaxed)}
              hint="Reported in Table 8"
            />
            <StatTile
              label="Documents"
              value={String(data.totals.document_count)}
              hint="Counted in this return"
            />
          </div>

          <ValidationPanel
            blocking={data.validation.blocking}
            warnings={data.validation.warnings}
            acknowledged={acknowledged}
            onToggle={toggle}
            readOnly={isClosed}
          />

          <Card
            title="Close the period"
            subtitle={
              isClosed
                ? 'Already closed.'
                : outstanding.length > 0
                  ? `${outstanding.length} blocking ${
                      outstanding.length === 1 ? 'item' : 'items'
                    } still outstanding.`
                  : 'Everything checks out.'
            }
            action={
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void downloadPayload()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white hover:bg-gray-50"
                >
                  <Download size={14} aria-hidden /> Download JSON
                </button>
                {!isClosed && (
                  <button
                    type="button"
                    onClick={() => void close()}
                    disabled={outstanding.length > 0 || closing}
                    className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-white bg-[#1b5dfc] hover:bg-[#1749c8] disabled:bg-gray-300 disabled:cursor-not-allowed"
                  >
                    {closing ? (
                      <Loader2 size={14} className="animate-spin" aria-hidden />
                    ) : (
                      <Lock size={14} aria-hidden />
                    )}
                    Close {data.period.label}
                  </button>
                )}
              </div>
            }
          >
            <p className="text-sm text-gray-600">
              Closing produces the GSTR-1 JSON in the offline utility's schema and locks
              the period. Total supplies for the period:{' '}
              <Money value={data.totals.supplies} />.
            </p>
          </Card>

          <ReturnTables data={data} />
        </>
      )}
    </div>
  );
};
