import React, { useMemo, useState } from 'react';
import { ScanLine } from 'lucide-react';

import { getScanActivity } from '../api';
import { useReport } from '../useReport';
import type { ScanActivity, ScanGranularity } from '../types';
import { Card, EmptyState, ErrorState, LoadingState, SERIES, StatTile } from './Primitives';

/**
 * Scanning activity — how much work has gone through the system.
 *
 * This panel deliberately ignores the page's period selector. The other
 * reports answer "what did this financial year cost"; this one answers "how
 * much have I run through here", which is a lifetime figure and must not move
 * because someone changed a dropdown meant for the GST register.
 *
 * The headline number comes from an append-only ledger rather than a count of
 * invoices, so deleting a misfire does not reduce it. A count of work done
 * that falls when you tidy up is measuring the wrong thing.
 */

const GRANULARITIES: { id: ScanGranularity; label: string }[] = [
  { id: 'day', label: 'Daily' },
  { id: 'month', label: 'Monthly' },
  { id: 'year', label: 'Yearly' },
  { id: 'all', label: 'All time' }
];

const BUCKET_LIMIT: Record<ScanGranularity, number> = {
  day: 30,
  month: 12,
  year: 10,
  all: 1
};

function formatBucket(bucket: string, granularity: ScanGranularity): string {
  const date = new Date(`${bucket}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return bucket;
  if (granularity === 'year') return String(date.getUTCFullYear());
  if (granularity === 'month') {
    return date.toLocaleDateString(undefined, { month: 'short', year: '2-digit', timeZone: 'UTC' });
  }
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', timeZone: 'UTC' });
}

function formatWhen(iso: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export const ScansPanel: React.FC = () => {
  const [granularity, setGranularity] = useState<ScanGranularity>('month');

  const query = useMemo(
    () => ({ granularity, limit: BUCKET_LIMIT[granularity] }),
    [granularity]
  );
  const { data, loading, error, reload } = useReport<ScanActivity>(
    () => getScanActivity(query.granularity, query.limit),
    [query.granularity, query.limit]
  );

  const peak = useMemo(
    () => Math.max(1, ...(data?.series ?? []).map((row) => row.scans)),
    [data]
  );

  const toggle = (
    <div className="bg-[#f4f5fa] p-1 rounded-xl flex items-center border border-gray-200/60">
      {GRANULARITIES.map((option) => {
        const active = granularity === option.id;
        return (
          <button
            key={option.id}
            onClick={() => setGranularity(option.id)}
            aria-pressed={active}
            className={`px-3 py-1.5 text-[11px] font-semibold rounded-lg transition-colors cursor-pointer ${
              active ? 'bg-white text-[#1b5dfc] shadow-sm' : 'text-gray-500 hover:text-[#0f172a]'
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );

  if (loading && !data) return <LoadingState label="Loading scan activity…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatTile
          label="Total scans"
          value={data.total_scans.toLocaleString()}
          hint="Every scan ever run, including those whose invoice was later deleted."
        />
        <StatTile
          label="Pages processed"
          value={data.total_pages.toLocaleString()}
          hint="A two-page invoice counts as one scan and two pages."
        />
        <StatTile
          label="Still in the system"
          value={data.scans_with_invoice.toLocaleString()}
          hint={
            data.scans_without_invoice > 0
              ? `${data.scans_without_invoice.toLocaleString()} scan(s) no longer have an invoice.`
              : 'Every scan still has its invoice.'
          }
        />
        <StatTile
          label="First scan"
          value={formatWhen(data.first_scan)}
          hint={data.last_scan ? `Most recent: ${formatWhen(data.last_scan)}` : undefined}
        />
      </div>

      <Card
        title="Scanning activity"
        subtitle="Counted from an append-only ledger, so deleting an invoice does not reduce it."
        action={toggle}
      >
        {granularity === 'all' ? (
          <p className="text-xs text-gray-500 leading-relaxed">
            <strong className="text-[#0f172a]">{data.total_scans.toLocaleString()}</strong> scans
            covering <strong className="text-[#0f172a]">{data.total_pages.toLocaleString()}</strong>{' '}
            pages, from {formatWhen(data.first_scan)} to {formatWhen(data.last_scan)}. Pick a
            smaller bucket above to see how that is spread over time.
          </p>
        ) : data.series.length === 0 ? (
          <EmptyState
            title="No scans in this window"
            detail="Upload an invoice and it will appear here."
            icon={<ScanLine size={18} />}
          />
        ) : (
          <div className="space-y-3">
            {/* justify-start + a bar cap: with one or two buckets, flex-1
                alone stretches a single scan into a block filling the panel,
                which reads as a huge number rather than the one it is. */}
            <div
              className="flex items-end justify-start gap-1.5 h-40"
              role="img"
              aria-label={`Scans per ${granularity}: ${data.series
                .map((row) => `${formatBucket(row.bucket, granularity)} ${row.scans}`)
                .join(', ')}`}
            >
              {data.series.map((row) => (
                <div
                  key={row.bucket}
                  className="flex-1 min-w-0 max-w-[72px] flex flex-col items-center gap-1.5"
                >
                  <span className="text-[10px] font-semibold text-gray-400 tabular-nums">
                    {row.scans}
                  </span>
                  <div
                    className="w-full rounded-t transition-all"
                    style={{
                      // A floor of 4px so a bucket with one scan is still a
                      // visible mark rather than an apparently empty column.
                      height: `${Math.max(4, (row.scans / peak) * 116)}px`,
                      backgroundColor: SERIES
                    }}
                    title={`${row.scans} scan(s), ${row.pages} page(s)`}
                  />
                </div>
              ))}
            </div>
            <div className="flex items-start justify-start gap-1.5">
              {data.series.map((row) => (
                <span
                  key={row.bucket}
                  className="flex-1 min-w-0 max-w-[72px] text-center text-[9px] text-gray-400 truncate"
                >
                  {formatBucket(row.bucket, granularity)}
                </span>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
};
