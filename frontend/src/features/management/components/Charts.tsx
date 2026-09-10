import React, { useId } from 'react';

/**
 * Small inline-SVG charts.
 *
 * There is no charting library in this frontend, and the brief said not to add
 * a second charting dependency. The existing reports feature already draws its
 * magnitude bars with plain CSS widths, so these follow the same approach one
 * step further into SVG for the shapes CSS cannot do — a two-series line, a
 * histogram with a baseline.
 *
 * They are deliberately small and dumb. Every one takes values that are already
 * final: nothing here scales, aggregates or rounds a figure, because a chart
 * that recomputes its own numbers can disagree with the table beside it.
 *
 * One hue carries magnitude, a second is reserved for the comparison series,
 * and status colours are never reused for data. Each chart is also given a
 * text alternative, because a bar somebody cannot read is not information.
 */

export const SERIES = '#1b5dfc';
export const SERIES_SOFT = '#a8c2ff';
export const COMPARISON = '#94a3b8';
export const BAD = '#d03b3b';
export const GOOD = '#1c9c66';

const rupees = new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', maximumFractionDigits: 0
});

export const compactMoney = (value: number): string => rupees.format(value);

/** A row of labelled magnitude bars. The workhorse. */
export const BarRows: React.FC<{
  rows: Array<{ label: string; value: number; secondary?: string; tone?: 'series' | 'bad' | 'good' }>;
  format?: (value: number) => string;
  emptyLabel?: string;
}> = ({ rows, format = compactMoney, emptyLabel = 'Nothing to show.' }) => {
  if (rows.length === 0) return <p className="text-sm text-gray-500">{emptyLabel}</p>;
  const peak = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  const colour = { series: SERIES, bad: BAD, good: GOOD };

  return (
    <ul className="flex flex-col gap-2">
      {rows.map((row) => (
        <li key={row.label} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 items-baseline">
          <span className="text-sm text-[#0f172a] truncate" title={row.label}>{row.label}</span>
          <span className="text-sm tabular-nums font-medium">{format(row.value)}</span>
          <span className="col-span-2 h-1.5 rounded-full bg-gray-100 overflow-hidden">
            <span
              className="block h-full rounded-full"
              style={{
                width: `${(Math.abs(row.value) / peak) * 100}%`,
                background: colour[row.tone ?? 'series']
              }}
            />
          </span>
          {row.secondary && (
            <span className="col-span-2 text-[11px] text-gray-500 -mt-0.5">{row.secondary}</span>
          )}
        </li>
      ))}
    </ul>
  );
};

/** Bills or value by hour of day. Every hour, including the quiet ones. */
export const HourHistogram: React.FC<{
  hours: Array<{ hour: number; label: string; value: number; bill_count: number }>;
}> = ({ hours }) => {
  const peak = Math.max(...hours.map((h) => h.value), 1);
  const busiest = hours.reduce((a, b) => (b.value > a.value ? b : a), hours[0]);

  return (
    <figure className="m-0">
      <div
        className="flex items-end gap-[3px] h-32"
        role="img"
        aria-label={`Sales by hour. Busiest hour ${busiest?.label} at ${compactMoney(busiest?.value ?? 0)}.`}
      >
        {hours.map((hour) => (
          <div key={hour.hour} className="flex-1 flex flex-col justify-end h-full group relative">
            <div
              className="rounded-t-sm transition-opacity group-hover:opacity-80"
              style={{
                height: `${Math.max((hour.value / peak) * 100, hour.value > 0 ? 2 : 0)}%`,
                background: hour.value > 0 ? SERIES : 'transparent',
                minHeight: hour.value > 0 ? '2px' : 0
              }}
            />
            {/* The quiet hours still occupy the axis - a chart drawn only from
                hours that had a sale hides the shape somebody is looking for. */}
            <div className="h-px bg-gray-200" />
            <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 text-[9px] text-gray-400 tabular-nums">
              {hour.hour % 6 === 0 ? hour.hour : ''}
            </span>
            <span className="pointer-events-none absolute bottom-full mb-1 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-[#0f172a] px-1.5 py-0.5 text-[10px] text-white opacity-0 group-hover:opacity-100">
              {hour.label} · {compactMoney(hour.value)} · {hour.bill_count} bills
            </span>
          </div>
        ))}
      </div>
      <figcaption className="mt-6 text-[11px] text-gray-500">
        {busiest && busiest.value > 0
          ? `Busiest around ${busiest.label} — ${compactMoney(busiest.value)} across ${busiest.bill_count} bills.`
          : 'No bills with a recorded time in this period.'}
      </figcaption>
    </figure>
  );
};

/** Two series over time, plus an optional cumulative line. */
export const DualLineChart: React.FC<{
  rows: Array<{ day: string; a: number; b: number; cumulative?: number }>;
  labelA: string;
  labelB: string;
  height?: number;
}> = ({ rows, labelA, labelB, height = 180 }) => {
  const gradientId = useId();
  if (rows.length === 0) return <p className="text-sm text-gray-500">Nothing to chart yet.</p>;

  const width = 720;
  const pad = { top: 8, right: 8, bottom: 18, left: 8 };
  const inner = { w: width - pad.left - pad.right, h: height - pad.top - pad.bottom };
  const peak = Math.max(...rows.flatMap((r) => [r.a, r.b]), 1);
  const step = rows.length > 1 ? inner.w / (rows.length - 1) : 0;

  const path = (pick: (r: typeof rows[number]) => number) =>
    rows
      .map((row, index) => {
        const x = pad.left + index * step;
        const y = pad.top + inner.h - (pick(row) / peak) * inner.h;
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');

  const hasCumulative = rows.some((r) => r.cumulative !== undefined);
  const cumulativePeak = Math.max(...rows.map((r) => Math.abs(r.cumulative ?? 0)), 1);

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        role="img"
        aria-label={`${labelA} against ${labelB} over ${rows.length} days.`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES} stopOpacity="0.18" />
            <stop offset="100%" stopColor={SERIES} stopOpacity="0" />
          </linearGradient>
        </defs>

        <line
          x1={pad.left} y1={pad.top + inner.h} x2={width - pad.right} y2={pad.top + inner.h}
          stroke="#e2e8f0" strokeWidth="1"
        />

        <path
          d={`${path((r) => r.a)} L${pad.left + (rows.length - 1) * step},${pad.top + inner.h} L${pad.left},${pad.top + inner.h} Z`}
          fill={`url(#${gradientId})`}
        />
        <path d={path((r) => r.a)} fill="none" stroke={SERIES} strokeWidth="2"
              strokeLinejoin="round" strokeLinecap="round" />
        <path d={path((r) => r.b)} fill="none" stroke={COMPARISON} strokeWidth="2"
              strokeDasharray="4 3" strokeLinejoin="round" strokeLinecap="round" />

        {hasCumulative && (
          <path
            d={rows
              .map((row, index) => {
                const x = pad.left + index * step;
                const mid = pad.top + inner.h / 2;
                const y = mid - ((row.cumulative ?? 0) / cumulativePeak) * (inner.h / 2);
                return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
              })
              .join(' ')}
            fill="none" stroke={GOOD} strokeWidth="1.5" strokeOpacity="0.7"
          />
        )}
      </svg>

      <figcaption className="flex flex-wrap gap-4 text-[11px] text-gray-600 mt-1">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded" style={{ background: SERIES }} /> {labelA}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded" style={{ background: COMPARISON }} /> {labelB}
        </span>
        {hasCumulative && (
          <span className="inline-flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded" style={{ background: GOOD }} /> running difference
          </span>
        )}
        <span className="text-gray-400">
          {rows[0].day} to {rows[rows.length - 1].day}
        </span>
      </figcaption>
    </figure>
  );
};

/** The payment split, as a single proportional bar. */
export const SplitBar: React.FC<{
  parts: Array<{ label: string; value: number; share: number | null }>;
}> = ({ parts }) => {
  const palette = [SERIES, SERIES_SOFT, '#7c9cff', '#c7d7ff', '#e2e8f0'];
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  if (total <= 0) return <p className="text-sm text-gray-500">Nothing was recorded as taken.</p>;

  return (
    <div>
      <div className="flex h-3 rounded-full overflow-hidden bg-gray-100" role="img"
           aria-label={parts.map((p) => `${p.label} ${p.share ?? 0}%`).join(', ')}>
        {parts.map((part, index) => (
          <span
            key={part.label}
            title={`${part.label}: ${compactMoney(part.value)}`}
            style={{
              width: `${(part.value / total) * 100}%`,
              background: palette[index % palette.length]
            }}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1 mt-3">
        {parts.map((part, index) => (
          <li key={part.label} className="inline-flex items-center gap-1.5 text-xs">
            <span className="w-2.5 h-2.5 rounded-sm"
                  style={{ background: palette[index % palette.length] }} />
            <span className="text-gray-600">{part.label}</span>
            <span className="tabular-nums font-medium">{compactMoney(part.value)}</span>
            {part.share !== null && <span className="text-gray-400">{part.share}%</span>}
          </li>
        ))}
      </ul>
    </div>
  );
};
