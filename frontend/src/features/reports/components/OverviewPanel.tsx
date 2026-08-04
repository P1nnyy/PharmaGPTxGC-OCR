import React from 'react';

import { reportsApi } from '../api';
import { currency, currencyCompact, monthLabel, number, percent } from '../format';
import type { PeriodQuery, SpendTrend, Summary } from '../types';
import { periodKey, useReport } from '../useReport';
import {
  Card,
  ErrorState,
  ExclusionNotice,
  LoadingState,
  SERIES,
  StatTile
} from './Primitives';

/**
 * Monthly spend as a bar chart.
 *
 * One series, so no legend and no categorical palette — the axis carries the
 * identity. Months with no purchases render as an empty slot rather than being
 * dropped: the gap is the information.
 */
const SpendChart: React.FC<{ trend: SpendTrend }> = ({ trend }) => {
  const peak = Math.max(...trend.series.map((point) => point.gross_total), 0);

  if (peak <= 0) {
    return (
      <p className="text-xs text-gray-500 py-8 text-center">
        No purchases recorded in this period.
      </p>
    );
  }

  return (
    <figure className="m-0">
      <div
        className="flex items-end gap-1.5 h-40 border-b border-[#e2e8f0]"
        role="img"
        aria-label={`Monthly purchase spend from ${trend.series[0]?.month} to ${
          trend.series[trend.series.length - 1]?.month
        }`}
      >
        {trend.series.map((point) => {
          const height = (point.gross_total / peak) * 100;
          return (
            <div key={point.month} className="flex-1 flex flex-col justify-end h-full group relative">
              {/* Hover target spans the full column height, not just the bar,
                  so a short month is still easy to hit. */}
              <div
                className="absolute inset-0 rounded-t-md group-hover:bg-[#f1f5ff] transition-colors"
                aria-hidden="true"
              />
              {/* A month with no purchases renders nothing at all. Giving it a
                  minimum height — even a 2px sliver — draws a bar where there
                  was no spend, which is the one thing the chart must not do. */}
              {point.gross_total > 0 && (
                <div
                  className="relative rounded-t-[4px] transition-[height] duration-300"
                  style={{ height: `${Math.max(height, 2)}%`, background: SERIES }}
                />
              )}
              <div
                role="tooltip"
                className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 z-10
                           opacity-0 group-hover:opacity-100 transition-opacity
                           bg-[#0f172a] text-white text-[10px] rounded-md px-2 py-1 whitespace-nowrap shadow-lg"
              >
                <strong className="font-semibold">{currency(point.gross_total)}</strong>
                <span className="text-gray-300">
                  {' · '}
                  {point.invoice_count} invoice{point.invoice_count === 1 ? '' : 's'}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex gap-1.5 mt-1.5">
        {trend.series.map((point) => (
          <span
            key={point.month}
            className="flex-1 text-[9px] text-gray-400 text-center tabular-nums truncate"
          >
            {monthLabel(point.month)}
          </span>
        ))}
      </div>
    </figure>
  );
};

export const OverviewPanel: React.FC<{ query: PeriodQuery }> = ({ query }) => {
  const key = periodKey(query);
  const summary = useReport<Summary>(() => reportsApi.summary(query), [key]);
  const trend = useReport<SpendTrend>(() => reportsApi.spendTrend(query), [key]);

  if (summary.loading || trend.loading) return <LoadingState />;
  if (summary.error) return <ErrorState message={summary.error} onRetry={summary.reload} />;
  if (trend.error) return <ErrorState message={trend.error} onRetry={trend.reload} />;
  if (!summary.data || !trend.data) return null;

  const data = summary.data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatTile
          label="Gross purchases"
          value={currency(data.gross_total)}
          hint={`${number(data.invoice_count)} invoices from ${number(data.vendor_count)} suppliers`}
        />
        <StatTile
          label="Taxable value"
          value={currency(data.taxable_total)}
          hint="Net of discounts, before tax"
        />
        <StatTile
          label="Tax paid"
          value={currency(data.tax_total)}
          hint={`CGST ${currencyCompact(data.cgst_total)} · SGST ${currencyCompact(
            data.sgst_total
          )} · IGST ${currencyCompact(data.igst_total)}`}
        />
        <StatTile
          label="Effective discount"
          value={percent(data.effective_discount_rate)}
          hint="Against list value, including free goods"
        />
      </div>

      <Card
        title="Monthly purchase trend"
        subtitle={`${data.period.label} · average ${currency(trend.data.average_active_month)} per active month`}
      >
        <SpendChart trend={trend.data} />
        <ExclusionNotice
          count={data.excluded.invoice_count}
          value={currency(data.excluded.gross_total)}
        />
        {data.estimated_line_count > 0 && (
          <p className="text-[11px] text-gray-500 mt-2">
            {data.estimated_line_count} line amount
            {data.estimated_line_count === 1 ? ' was' : 's were'} inferred rather than read from the
            invoice.
          </p>
        )}
      </Card>
    </div>
  );
};
