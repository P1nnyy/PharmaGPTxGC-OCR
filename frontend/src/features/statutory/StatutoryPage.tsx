import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, FileSpreadsheet, Loader2, Printer, RefreshCw } from 'lucide-react';

import './statutory-print.css';
import { statutoryApi, type PackQuery } from './api';
import { CrossCheckBanner } from './components/CrossCheckBanner';
import { Note } from './components/Primitives';
import { DrillDrawer } from './components/Primitives';
import {
  DocumentSeriesReport,
  Gstr1Report,
  Gstr3bReport,
  HsnReport,
  ItcReversalsReport,
  PurchaseRegisterReport,
  SalesRegisterReport
} from './components/Reports';
import type { Drill, Pack, ReportId } from './types';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];

const TABS: Array<{ id: ReportId; label: string; exportAs?: Array<ReportId | 'hsn_inward'> }> = [
  { id: 'gstr1', label: 'GSTR-1 preview' },
  { id: 'gstr3b', label: 'GSTR-3B worksheet' },
  { id: 'purchase_register', label: 'Purchase register' },
  { id: 'sales_register', label: 'Sales register' },
  { id: 'hsn_summary', label: 'HSN summary', exportAs: ['hsn_summary', 'hsn_inward'] },
  { id: 'document_series', label: 'Document series' },
  { id: 'itc_reversals', label: 'ITC reversals' }
];

const toPeriod = (month: number, year: number) =>
  `${String(month + 1).padStart(2, '0')}${year}`;

export const StatutoryPage: React.FC = () => {
  const now = new Date();
  // Last month by default: the current one is still being sold in.
  const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const [month, setMonth] = useState(previous.getMonth());
  const [year, setYear] = useState(previous.getFullYear());
  const [tab, setTab] = useState<ReportId>('gstr1');

  const [filters, setFilters] = useState<PackQuery>({});
  const [pack, setPack] = useState<Pack | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const [drill, setDrill] = useState<{ open: boolean; title: string; loading: boolean; error: string | null; rows: any[] }>(
    { open: false, title: '', loading: false, error: null, rows: [] }
  );

  const period = useMemo(() => toPeriod(month, year), [month, year]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPack(await statutoryApi.pack(period, filters));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load this period.');
      setPack(null);
    } finally {
      setLoading(false);
    }
  }, [period, filters]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDrill = useCallback(async (target: Drill, label: string) => {
    setDrill({ open: true, title: label, loading: true, error: null, rows: [] });
    try {
      const result = await statutoryApi.drill(target);
      setDrill({ open: true, title: label, loading: false, error: null, rows: result.rows });
    } catch (caught) {
      setDrill({
        open: true, title: label, loading: false, rows: [],
        error: caught instanceof Error ? caught.message : 'Could not open the documents behind this.'
      });
    }
  }, []);

  const download = async (reportId: ReportId | 'hsn_inward', fmt: 'csv' | 'xlsx') => {
    setExporting(true);
    try {
      await statutoryApi.download(period, reportId, fmt, filters);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Export failed.');
    } finally {
      setExporting(false);
    }
  };

  const currentTab = TABS.find((t) => t.id === tab)!;
  const exportTargets = currentTab.exportAs ?? [currentTab.id];

  const body = () => {
    if (!pack) return null;
    const props = { pack, onDrill: openDrill };
    switch (tab) {
      case 'gstr1': return <Gstr1Report {...props} />;
      case 'gstr3b': return <Gstr3bReport {...props} />;
      case 'purchase_register': return <PurchaseRegisterReport {...props} />;
      case 'sales_register': return <SalesRegisterReport {...props} />;
      case 'hsn_summary': return <HsnReport {...props} />;
      case 'document_series': return <DocumentSeriesReport {...props} />;
      case 'itc_reversals': return <ItcReversalsReport {...props} />;
      default: return null;
    }
  };

  return (
    <div className="statutory-page flex flex-col gap-6 p-6 max-w-[1600px] mx-auto">
      {/* Only ever visible on paper: a printed sheet has to say whose it is. */}
      <div className="statutory-print-header hidden">
        <strong style={{ fontSize: '13pt' }}>{currentTab.label}</strong>
        <div style={{ fontSize: '9pt', marginTop: '2mm' }}>
          {pack?.shop.trade_name || pack?.shop.legal_name} · GSTIN {pack?.shop.gstin || '—'} ·{' '}
          {pack?.period.label} ({pack?.period.start_date} to {pack?.period.end_date})
        </div>
      </div>

      <header className="statutory-toolbar flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#0f172a]">Statutory reports</h1>
          <p className="text-sm text-gray-500 mt-1">
            {pack
              ? `${pack.period.label} · ${pack.period.frequency === 'QUARTERLY' ? 'quarterly filer' : 'monthly filer'} · every figure drills to its documents`
              : 'One filing period, seven reports.'}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={month}
            onChange={(e) => setMonth(Number(e.target.value))}
            className="rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white"
            aria-label="Month"
          >
            {MONTHS.map((name, index) => <option key={name} value={index}>{name}</option>)}
          </select>
          <input
            type="number"
            value={year}
            min={2017}
            max={now.getFullYear() + 1}
            onChange={(e) => setYear(Number(e.target.value))}
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
          <button
            type="button"
            onClick={() => window.print()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white hover:bg-gray-50"
          >
            <Printer size={14} aria-hidden /> Print
          </button>
          {exportTargets.map((target) => (
            <React.Fragment key={target}>
              <button
                type="button"
                disabled={exporting || !pack}
                onClick={() => void download(target, 'csv')}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white hover:bg-gray-50 disabled:opacity-50"
              >
                {exporting ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Download size={14} aria-hidden />}
                CSV{exportTargets.length > 1 ? ` (${target === 'hsn_inward' ? 'inward' : 'outward'})` : ''}
              </button>
              <button
                type="button"
                disabled={exporting || !pack}
                onClick={() => void download(target, 'xlsx')}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white hover:bg-gray-50 disabled:opacity-50"
              >
                <FileSpreadsheet size={14} aria-hidden />
                Excel{exportTargets.length > 1 ? ` (${target === 'hsn_inward' ? 'inward' : 'outward'})` : ''}
              </button>
            </React.Fragment>
          ))}
        </div>
      </header>

      {loading && (
        <p className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" aria-hidden /> Building the pack…
        </p>
      )}

      {error && <Note tone="bad">{error}</Note>}

      {pack && !loading && (
        <>
          <CrossCheckBanner checks={pack.cross_checks} onDrill={openDrill} />

          <nav className="statutory-tabs flex flex-wrap gap-1 border-b border-gray-200">
            {TABS.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => setTab(entry.id)}
                className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
                  tab === entry.id
                    ? 'border-[#1b5dfc] text-[#1b5dfc]'
                    : 'border-transparent text-gray-500 hover:text-[#0f172a]'
                }`}
              >
                {entry.label}
              </button>
            ))}
          </nav>

          {tab === 'sales_register' && (
            <div className="statutory-toolbar flex flex-wrap items-center gap-2 text-sm">
              <select
                value={filters.rate ?? ''}
                onChange={(e) => setFilters((f) => ({ ...f, rate: e.target.value ? Number(e.target.value) : undefined }))}
                className="rounded-lg border border-[#e2e8f0] px-2 py-1.5 bg-white"
                aria-label="Rate"
              >
                <option value="">All rates</option>
                {pack.reports.sales_register.available_filters.rates.map((rate) => (
                  <option key={rate} value={rate}>{rate}%</option>
                ))}
              </select>
              <select
                value={filters.capture_mode ?? ''}
                onChange={(e) => setFilters((f) => ({ ...f, capture_mode: e.target.value || undefined }))}
                className="rounded-lg border border-[#e2e8f0] px-2 py-1.5 bg-white"
                aria-label="Capture mode"
              >
                <option value="">All capture modes</option>
                {pack.reports.sales_register.available_filters.capture_modes.map((mode) => (
                  <option key={mode} value={mode}>{mode}</option>
                ))}
              </select>
              <select
                value={filters.payment_method ?? ''}
                onChange={(e) => setFilters((f) => ({ ...f, payment_method: e.target.value || undefined }))}
                className="rounded-lg border border-[#e2e8f0] px-2 py-1.5 bg-white"
                aria-label="Payment method"
              >
                <option value="">All payment methods</option>
                {pack.reports.sales_register.available_filters.payment_methods.map((method) => (
                  <option key={method} value={method}>{method}</option>
                ))}
              </select>
            </div>
          )}

          {tab === 'purchase_register' && (
            <div className="statutory-toolbar flex flex-wrap items-center gap-2 text-sm">
              <input
                type="search"
                placeholder="Filter by supplier name or GSTIN"
                defaultValue={filters.vendor ?? ''}
                onBlur={(e) => setFilters((f) => ({ ...f, vendor: e.target.value || undefined }))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') setFilters((f) => ({ ...f, vendor: (e.target as HTMLInputElement).value || undefined }));
                }}
                className="rounded-lg border border-[#e2e8f0] px-3 py-1.5 bg-white w-72"
                aria-label="Supplier"
              />
            </div>
          )}

          <div className="statutory-card-wrap">{body()}</div>
        </>
      )}

      <DrillDrawer
        open={drill.open}
        title={drill.title}
        loading={drill.loading}
        error={drill.error}
        rows={drill.rows}
        onClose={() => setDrill((d) => ({ ...d, open: false }))}
      />
    </div>
  );
};
