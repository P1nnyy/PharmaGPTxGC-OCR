import React, { useMemo, useState } from 'react';
import { AlertTriangle, BarChart3, CalendarClock, Receipt, ScanLine, Truck } from 'lucide-react';

import { ExpiryPanel } from './components/ExpiryPanel';
import { GstPanel } from './components/GstPanel';
import { OverviewPanel } from './components/OverviewPanel';
import { PeriodSelector } from './components/PeriodSelector';
import { QualityPanel } from './components/QualityPanel';
import { ScansPanel } from './components/ScansPanel';
import { SuppliersPanel } from './components/SuppliersPanel';
import type { PeriodQuery } from './types';

type TabId = 'overview' | 'activity' | 'gst' | 'expiry' | 'suppliers' | 'quality';

const TABS: { id: TabId; label: string; icon: React.ElementType; hint: string }[] = [
  { id: 'overview', label: 'Overview', icon: BarChart3, hint: 'Spend and tax totals' },
  { id: 'activity', label: 'Activity', icon: ScanLine, hint: 'Scans run, by day, month or year' },
  { id: 'gst', label: 'GST & ITC', icon: Receipt, hint: 'Purchase register and HSN summary' },
  { id: 'expiry', label: 'Expiry risk', icon: CalendarClock, hint: 'Value at risk by batch' },
  { id: 'suppliers', label: 'Suppliers', icon: Truck, hint: 'Landed cost and price movement' },
  { id: 'quality', label: 'Data quality', icon: AlertTriangle, hint: 'What is wrong and what it costs' }
];

/**
 * Analytics home.
 *
 * Every figure on this page is aggregated server-side from the graph. The page
 * holds one piece of state — the reporting period — and each panel fetches its
 * own report against it, so a slow report never blocks a fast one.
 *
 * The expiry panel deliberately ignores the period: stock bought in March can
 * expire in September, and filtering it to a period would hide exactly the
 * batches worth acting on.
 */
export const ReportsPage: React.FC = () => {
  const [tab, setTab] = useState<TabId>('overview');
  const [period, setPeriod] = useState<PeriodQuery>({ kind: 'fy', statuses: 'verified' });

  // Panels take this by identity, so a new object each render would refetch
  // every report on every keystroke elsewhere on the page.
  const query = useMemo(() => period, [period]);

  return (
    <div className="space-y-6 animate-fade-in">
      <header className="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-[#0f172a] tracking-tight">Analytics &amp; Reports</h2>
          <p className="text-gray-500 text-sm">
            Purchase spend, input tax credit, expiry exposure and supplier pricing.
          </p>
        </div>
        {tab !== 'expiry' && (
          <PeriodSelector value={period} onChange={setPeriod} />
        )}
      </header>

      <nav className="border-b border-[#e2e8f0] flex gap-1 overflow-x-auto" aria-label="Report sections">
        {TABS.map((entry) => {
          const Icon = entry.icon;
          const active = tab === entry.id;
          return (
            <button
              key={entry.id}
              onClick={() => setTab(entry.id)}
              title={entry.hint}
              aria-current={active ? 'page' : undefined}
              className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold whitespace-nowrap
                          border-b-2 -mb-px transition-colors cursor-pointer
                          focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1b5dfc]/40 rounded-t
                          ${
                            active
                              ? 'border-[#1b5dfc] text-[#1b5dfc]'
                              : 'border-transparent text-gray-500 hover:text-[#0f172a]'
                          }`}
            >
              <Icon size={14} aria-hidden="true" />
              {entry.label}
            </button>
          );
        })}
      </nav>

      {tab === 'overview' && <OverviewPanel query={query} />}
      {tab === 'activity' && <ScansPanel />}
      {tab === 'gst' && <GstPanel query={query} />}
      {tab === 'expiry' && <ExpiryPanel statuses={period.statuses} />}
      {tab === 'suppliers' && <SuppliersPanel query={query} />}
      {tab === 'quality' && <QualityPanel query={query} />}
    </div>
  );
};

export default ReportsPage;
