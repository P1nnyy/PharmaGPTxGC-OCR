import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';

import { managementApi } from './api';
import { Note } from './components/Reports';
import {
  DailySalesReportView,
  ExpiryRiskReport,
  MarginReportView,
  MoversReportView,
  StockLedgerReport,
  TrendReportView,
  VendorScorecardView
} from './components/Reports';
import type {
  DailySalesReport, ExpiryReport, LedgerReport, MarginReport,
  MoversReport, TrendReport, VendorScorecard
} from './types';

type TabId =
  | 'expiry-risk' | 'margin' | 'vendor-scorecard'
  | 'stock-ledger' | 'movers' | 'daily-sales' | 'trend';

// Expiry risk first, deliberately. It is the report with something to do in it,
// and the one that makes the difference between opening this daily and monthly.
const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'expiry-risk', label: 'Expiry risk' },
  { id: 'margin', label: 'Gross margin' },
  { id: 'vendor-scorecard', label: 'Distributors' },
  { id: 'stock-ledger', label: 'Stock ledger' },
  { id: 'movers', label: 'Fast & slow' },
  { id: 'daily-sales', label: 'Daily sales' },
  { id: 'trend', label: 'Purchases vs sales' }
];

const isoDaysAgo = (days: number) =>
  new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);

export const ManagementPage: React.FC<{ initialTab?: TabId }> = ({ initialTab }) => {
  const [tab, setTab] = useState<TabId>(initialTab ?? 'expiry-risk');
  const [start, setStart] = useState(isoDaysAgo(29));
  const [end, setEnd] = useState(isoDaysAgo(0));

  const [data, setData] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const window = { start, end };
      switch (tab) {
        case 'expiry-risk': setData(await managementApi.expiryRisk()); break;
        case 'margin': setData(await managementApi.margin(window)); break;
        case 'vendor-scorecard': setData(await managementApi.vendorScorecard(window)); break;
        case 'stock-ledger': setData(await managementApi.stockLedger(window)); break;
        case 'movers': setData(await managementApi.movers(window)); break;
        case 'daily-sales': setData(await managementApi.dailySales(end)); break;
        case 'trend': setData(await managementApi.trend(window)); break;
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load this report.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [tab, start, end]);

  useEffect(() => { void load(); }, [load]);

  const setReturnWindow = async (vendorId: string, days: number | null) => {
    try {
      await managementApi.setReturnWindow(vendorId, days);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save that return window.');
    }
  };

  const body = () => {
    if (!data) return null;
    switch (tab) {
      case 'expiry-risk': return <ExpiryRiskReport report={data as ExpiryReport} />;
      case 'margin': return <MarginReportView report={data as MarginReport} />;
      case 'stock-ledger': return <StockLedgerReport report={data as LedgerReport} />;
      case 'movers': return <MoversReportView report={data as MoversReport} />;
      case 'daily-sales': return <DailySalesReportView report={data as DailySalesReport} />;
      case 'trend': return <TrendReportView report={data as TrendReport} />;
      case 'vendor-scorecard':
        return (
          <VendorScorecardView
            report={data as VendorScorecard}
            onSetWindow={(vendorId, days) => void setReturnWindow(vendorId, days)}
          />
        );
      default: return null;
    }
  };

  // Expiry risk is a position, not a period: what is on the shelf today does
  // not depend on which window somebody picked.
  const windowApplies = tab !== 'expiry-risk';

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1500px] mx-auto">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#0f172a]">Business reports</h1>
          <p className="text-sm text-gray-500 mt-1">
            What the shop is actually doing — margin, expiry exposure, and where the money is.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {windowApplies && (
            <>
              <input
                type="date" value={start} max={end}
                onChange={(e) => setStart(e.target.value)}
                className="rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white"
                aria-label="From"
              />
              <span className="text-gray-400 text-sm">to</span>
              <input
                type="date" value={end} min={start}
                onChange={(e) => setEnd(e.target.value)}
                className="rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white"
                aria-label="To"
              />
            </>
          )}
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white hover:bg-gray-50"
          >
            <RefreshCw size={14} aria-hidden /> Refresh
          </button>
        </div>
      </header>

      <nav className="flex flex-wrap gap-1 border-b border-gray-200">
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

      {loading && (
        <p className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" aria-hidden /> Working it out…
        </p>
      )}
      {error && <Note tone="bad">{error}</Note>}
      {!loading && body()}
    </div>
  );
};
