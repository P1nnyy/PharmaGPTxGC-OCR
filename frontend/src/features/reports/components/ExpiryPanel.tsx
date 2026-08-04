import React, { useState } from 'react';
import { Download, PackageCheck } from 'lucide-react';

import { reportsApi } from '../api';
import { downloadCsv, toCsv } from '../csv';
import { currency, dateLabel, daysLabel, number } from '../format';
import type { ExpiryBucketKey, ExpiryExposure, Severity } from '../types';
import { periodKey, useReport } from '../useReport';
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  SERIES,
  SeverityChip,
  StatTile,
  TableScroll,
  Td,
  Th
} from './Primitives';

// Urgency drives the chip, not the bar: the bars plot one series (value at
// risk) and take one hue, while the chip carries severity with a text label
// beside it so colour never has to say it alone.
const BUCKET_SEVERITY: Record<ExpiryBucketKey, Severity | null> = {
  expired: 'blocking',
  '0_30': 'blocking',
  '31_60': 'warning',
  '61_90': 'warning',
  '91_180': 'info',
  beyond_180: null
};

const HORIZONS = [60, 90, 180, 365];

export const ExpiryPanel: React.FC<{ statuses?: string }> = ({ statuses }) => {
  const [horizon, setHorizon] = useState(180);
  const report = useReport<ExpiryExposure>(
    () => reportsApi.expiry(horizon, statuses),
    [horizon, periodKey({ statuses })]
  );

  if (report.loading) return <LoadingState />;
  if (report.error) return <ErrorState message={report.error} onRetry={report.reload} />;
  if (!report.data) return null;

  const data = report.data;
  const peak = Math.max(...data.buckets.map((bucket) => bucket.value_at_risk), 0);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatTile
          label={`At risk within ${horizon} days`}
          value={currency(data.total_value_at_risk)}
          hint="Valued at purchase cost, not MRP"
          tone={data.total_value_at_risk > 0 ? 'warning' : 'default'}
        />
        <StatTile
          label="Needs action now"
          value={currency(data.actionable_value)}
          hint="Expired, or inside 90 days"
          tone={data.actionable_value > 0 ? 'blocking' : 'default'}
        />
        <StatTile
          label="Batches listed"
          value={number(data.rows.length)}
          hint={`As at ${dateLabel(data.as_of)}`}
        />
      </div>

      <Card
        title="Expiry exposure by bucket"
        subtitle={data.basis_note}
        action={
          <select
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
            aria-label="Expiry horizon"
            className="text-xs font-medium text-[#0f172a] bg-white border border-[#e2e8f0] rounded-lg
                       px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-[#1b5dfc]/30 cursor-pointer shrink-0"
          >
            {HORIZONS.map((days) => (
              <option key={days} value={days}>
                Next {days} days
              </option>
            ))}
          </select>
        }
      >
        {peak <= 0 ? (
          <EmptyState
            title="Nothing expiring in view"
            detail="Batch and expiry data is read from verified invoices. Verify some invoices with batch details to populate this."
            icon={<PackageCheck size={28} className="text-gray-300" aria-hidden="true" />}
          />
        ) : (
          <ul className="space-y-3">
            {data.buckets.map((bucket) => {
              const severity = BUCKET_SEVERITY[bucket.bucket];
              return (
                <li key={bucket.bucket} className="flex items-center gap-3">
                  <div className="w-32 shrink-0">
                    <span className="text-xs font-medium text-[#0f172a] block">{bucket.label}</span>
                    <span className="text-[10px] text-gray-400">
                      {number(bucket.batch_count)} batch{bucket.batch_count === 1 ? '' : 'es'}
                    </span>
                  </div>
                  <div className="flex-1 h-6 bg-[#f1f5f9] rounded-md overflow-hidden">
                    <div
                      className="h-full rounded-md transition-[width] duration-300"
                      style={{
                        width: `${peak > 0 ? (bucket.value_at_risk / peak) * 100 : 0}%`,
                        background: SERIES
                      }}
                      title={currency(bucket.value_at_risk)}
                    />
                  </div>
                  <span className="w-24 text-right text-xs font-semibold text-[#0f172a] tabular-nums shrink-0">
                    {currency(bucket.value_at_risk)}
                  </span>
                  <span className="w-24 shrink-0">
                    {severity && <SeverityChip severity={severity} label={severity === 'blocking' ? 'Act now' : severity === 'warning' ? 'Plan return' : 'Monitor'} />}
                  </span>
                </li>
              );
            })}
          </ul>
        )}

        {data.batches_with_unreadable_expiry > 0 && (
          <p className="text-[11px] text-gray-500 mt-4">
            {data.batches_with_unreadable_expiry} batch
            {data.batches_with_unreadable_expiry === 1 ? '' : 'es'} carry an expiry that could not be
            read and are excluded from these totals.
          </p>
        )}
      </Card>

      {data.rows.length > 0 && (
        <Card
          title="Batches to act on"
          subtitle="Most urgent first. Return windows with distributors usually close well before expiry."
          action={
            <button
              onClick={() =>
                downloadCsv(
                  `PharmaGPT_Expiry_${horizon}d_${data.as_of}.csv`,
                  toCsv(data.rows, [
                    { header: 'Expiry', value: (r) => r.expiry_date },
                    { header: 'Days Remaining', value: (r) => r.days_remaining },
                    { header: 'Product', value: (r) => r.product_name },
                    { header: 'Pack', value: (r) => r.pack },
                    { header: 'Batch', value: (r) => r.batch_number },
                    { header: 'Units', value: (r) => r.units },
                    { header: 'Rate', value: (r) => r.rate },
                    { header: 'MRP', value: (r) => r.mrp },
                    { header: 'Value At Cost', value: (r) => r.value_at_risk },
                    { header: 'Supplier', value: (r) => r.vendor_name },
                    { header: 'Invoice', value: (r) => r.invoice_number }
                  ])
                )
              }
              className="text-xs font-semibold text-[#1b5dfc] hover:text-[#154ecb] flex items-center gap-1 cursor-pointer shrink-0"
            >
              <Download size={13} aria-hidden="true" />
              Export list
            </button>
          }
        >
          <TableScroll>
            <table className="w-full min-w-[720px]">
              <thead>
                <tr>
                  <Th>Expiry</Th>
                  <Th align="right">Left</Th>
                  <Th>Product</Th>
                  <Th>Batch</Th>
                  <Th align="right">Units</Th>
                  <Th align="right">Value at cost</Th>
                  <Th>Supplier</Th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={`${row.invoice_id}-${row.batch_number}-${row.expiry_date}`} className="hover:bg-[#f8fafc]">
                    <Td>{dateLabel(row.expiry_date)}</Td>
                    <Td align="right">
                      <span
                        className="font-semibold"
                        style={{ color: row.days_remaining < 0 ? '#8f1d1d' : undefined }}
                      >
                        {daysLabel(row.days_remaining)}
                      </span>
                    </Td>
                    <Td className="font-medium text-[#0f172a]">
                      <span className="block max-w-[200px] truncate" title={row.product_name ?? ''}>
                        {row.product_name ?? '—'}
                      </span>
                      {row.pack && <span className="text-[10px] text-gray-400">{row.pack}</span>}
                    </Td>
                    <Td className="font-mono text-[11px]">{row.batch_number ?? '—'}</Td>
                    <Td align="right">{number(row.units)}</Td>
                    <Td align="right" className="font-semibold text-[#0f172a]">
                      {currency(row.value_at_risk)}
                    </Td>
                    <Td>
                      <span className="block max-w-[150px] truncate" title={row.vendor_name ?? ''}>
                        {row.vendor_name ?? '—'}
                      </span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      )}
    </div>
  );
};
