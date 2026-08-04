import React from 'react';
import { ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { reportsApi } from '../api';
import { currency, dateLabel, number } from '../format';
import type { DataQuality, PeriodQuery } from '../types';
import { periodKey, useReport } from '../useReport';
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  SeverityChip,
  StatTile
} from './Primitives';

export const QualityPanel: React.FC<{ query: PeriodQuery }> = ({ query }) => {
  const navigate = useNavigate();
  const report = useReport<DataQuality>(() => reportsApi.dataQuality(query), [periodKey(query)]);

  if (report.loading) return <LoadingState />;
  if (report.error) return <ErrorState message={report.error} onRetry={report.reload} />;
  if (!report.data) return null;

  const data = report.data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatTile
          label="Input credit at risk"
          value={currency(data.itc_at_risk)}
          hint="Tax on invoices with no supplier GSTIN"
          tone={data.itc_at_risk > 0 ? 'blocking' : 'default'}
        />
        <StatTile
          label="Blocking issues"
          value={number(data.blocking_count)}
          hint="Cost money or hide invoices from reports"
          tone={data.blocking_count > 0 ? 'blocking' : 'default'}
        />
        <StatTile
          label="Invoices checked"
          value={number(data.invoices_checked)}
          hint="Every status, not just verified"
        />
      </div>

      <Card
        title="Ledger issues"
        subtitle="Sorted by severity, then by what each one costs."
      >
        {data.issues.length === 0 ? (
          <EmptyState
            title="Nothing to fix"
            detail="Every invoice in this period has a supplier GSTIN, a readable date, and adds up."
            icon={<ShieldCheck size={28} className="text-gray-300" aria-hidden="true" />}
          />
        ) : (
          <ul className="divide-y divide-gray-100 -my-2">
            {data.issues.map((issue, index) => (
              <li
                key={`${issue.code}-${issue.invoice_id ?? issue.invoice_number ?? index}`}
                className="py-3 flex items-start gap-3"
              >
                <span className="mt-0.5 shrink-0">
                  <SeverityChip severity={issue.severity} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-[#0f172a]">{issue.title}</p>
                  <p className="text-[11px] text-gray-600 mt-0.5">{issue.detail}</p>
                  <p className="text-[10px] text-gray-400 mt-1">
                    {issue.invoice_number ? `Invoice ${issue.invoice_number}` : 'Invoice'}
                    {issue.seller_name ? ` · ${issue.seller_name}` : ''}
                    {issue.invoice_date ? ` · ${dateLabel(issue.invoice_date)}` : ''}
                  </p>
                </div>
                <div className="text-right shrink-0 flex flex-col items-end gap-1">
                  {issue.value_at_stake !== null && (
                    <span className="text-xs font-bold text-[#0f172a] tabular-nums">
                      {currency(issue.value_at_stake)}
                    </span>
                  )}
                  {issue.invoice_id && (
                    <button
                      onClick={() => navigate(`/review/${issue.invoice_id}`)}
                      className="text-[10px] font-semibold text-[#1b5dfc] hover:text-[#154ecb] cursor-pointer"
                    >
                      Open invoice
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
};
