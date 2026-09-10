import React from 'react';
import { AlertCircle, AlertTriangle, ArrowDownRight, ArrowUpRight, CheckCircle2, Info } from 'lucide-react';

import { BarRows, DualLineChart, HourHistogram, SplitBar } from './Charts';
import type {
  DailySalesReport, ExpiryReport, LedgerReport, MarginReport,
  MoversReport, TrendReport, VendorScorecard
} from '../types';

const rupees = new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2
});
export const money = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : rupees.format(v);

export const Card: React.FC<{
  title?: string; subtitle?: string; action?: React.ReactNode;
  children: React.ReactNode; className?: string;
}> = ({ title, subtitle, action, children, className = '' }) => (
  <section className={`bg-white rounded-2xl border border-[#e2e8f0] shadow-sm ${className}`}>
    {(title || action) && (
      <header className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-gray-100">
        <div>
          {title && <h3 className="text-sm font-bold text-[#0f172a]">{title}</h3>}
          {subtitle && <p className="text-xs text-gray-500 mt-0.5 max-w-3xl">{subtitle}</p>}
        </div>
        {action}
      </header>
    )}
    <div className="p-6">{children}</div>
  </section>
);

export const Note: React.FC<{ tone?: 'info' | 'warn' | 'bad' | 'good'; children: React.ReactNode }> = ({
  tone = 'info', children
}) => {
  const styles = {
    info: { border: '#cfe0ff', background: '#eaf0ff', color: '#123c9e', Icon: Info },
    warn: { border: '#f5dfae', background: '#fdf3e0', color: '#7a5205', Icon: AlertTriangle },
    bad: { border: '#f3c9c9', background: '#fdecec', color: '#8f1d1d', Icon: AlertCircle },
    good: { border: '#c6e9d4', background: '#eaf7f0', color: '#1c6b41', Icon: CheckCircle2 }
  } as const;
  const { border, background, color, Icon } = styles[tone];
  return (
    <div className="rounded-xl border p-4 text-sm flex gap-2.5 items-start"
         style={{ borderColor: border, background, color }}>
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div className="leading-relaxed">{children}</div>
    </div>
  );
};

const Table: React.FC<{ head: React.ReactNode; children: React.ReactNode }> = ({ head, children }) => (
  <div className="overflow-x-auto -mx-2 px-2">
    <table className="w-full text-sm border-collapse">
      <thead><tr className="text-[11px] uppercase tracking-wide text-gray-400 text-left">{head}</tr></thead>
      <tbody>{children}</tbody>
    </table>
  </div>
);
const Th: React.FC<{ children?: React.ReactNode; right?: boolean }> = ({ children, right }) => (
  <th className={`font-semibold py-2 pr-4 whitespace-nowrap ${right ? 'text-right' : ''}`}>{children}</th>
);
const Td: React.FC<{ children?: React.ReactNode; right?: boolean; className?: string }> = ({
  children, right, className = ''
}) => (
  <td className={`py-2 pr-4 border-t border-gray-100 align-top ${right ? 'text-right' : ''} ${className}`}>
    {children}
  </td>
);

const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="text-sm text-gray-500 leading-relaxed">{children}</p>
);

// ------------------------------------------------------------ expiry risk

export const ExpiryRiskReport: React.FC<{ report: ExpiryReport }> = ({ report }) => {
  const { totals } = report;
  const rows = [...report.buckets.flatMap((b) => b.rows), ...report.expired.rows];

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-[#f3c9c9] bg-[#fdecec] p-5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[#8f1d1d]/70">
            Input credit at risk
          </span>
          <strong className="block text-3xl font-bold text-[#8f1d1d] mt-1 tabular-nums">
            {money(totals.input_tax_at_risk)}
          </strong>
          <p className="text-[11px] text-[#8f1d1d] mt-1.5 leading-snug">
            Reversed permanently under 17(5)(h) if this stock is written off.
          </p>
        </div>
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
            Stock value at cost
          </span>
          <strong className="block text-3xl font-bold text-[#0f172a] mt-1 tabular-nums">
            {money(totals.value_at_cost)}
          </strong>
          <p className="text-[11px] text-gray-500 mt-1.5">
            {money(totals.value_at_mrp)} at MRP · {totals.batch_count} batches
          </p>
        </div>
        <div className="rounded-2xl border border-[#c6e9d4] bg-[#eaf7f0] p-5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[#1c6b41]/70">
            Can still go back
          </span>
          <strong className="block text-3xl font-bold text-[#1c6b41] mt-1 tabular-nums">
            {money(totals.still_returnable_value_at_cost)}
          </strong>
          <p className="text-[11px] text-[#1c6b41] mt-1.5 leading-snug">
            {totals.still_returnable_batch_count} batch
            {totals.still_returnable_batch_count === 1 ? '' : 'es'} inside the distributor's
            return window.
          </p>
        </div>
      </div>

      <Note tone="warn">{report.statutory_note}</Note>
      {report.return_window_note && <Note tone="info">{report.return_window_note}</Note>}

      <Card title="By how soon it expires"
            subtitle="Buckets do not overlap, so these add up to the totals above.">
        <BarRows
          rows={report.buckets.map((b) => ({
            label: `Within ${b.label}`,
            value: b.input_tax_at_risk,
            tone: 'bad' as const,
            secondary: `${b.batch_count} batch${b.batch_count === 1 ? '' : 'es'} · ${money(b.value_at_cost)} at cost`
          }))}
          emptyLabel="Nothing expiring inside the horizon."
        />
      </Card>

      <Card title="Batch by batch"
            subtitle="Soonest first. The top row is the one to deal with today.">
        {rows.length === 0 ? (
          <Empty>
            Nothing on the shelf is expiring within {report.horizon_days} days. This report
            reads batch expiry from purchase invoices, so it fills in as stock is scanned.
          </Empty>
        ) : (
          <Table head={
            <><Th>Expires</Th><Th>Left</Th><Th>Product</Th><Th>Batch</Th><Th>Distributor</Th>
              <Th right>Qty</Th><Th right>At cost</Th><Th right>At MRP</Th>
              <Th right>Credit at risk</Th><Th>Return</Th></>
          }>
            {rows.map((row) => (
              <tr key={`${row.product_id}-${row.batch_number}`}>
                <Td className="whitespace-nowrap">{row.expiry}</Td>
                <Td right className={row.days_left < 0 ? 'text-[#8f1d1d] font-semibold' : ''}>
                  {row.days_left < 0 ? 'expired' : `${row.days_left}d`}
                </Td>
                <Td>{row.product_name ?? row.product_id}</Td>
                <Td className="font-mono text-xs">{row.batch_number || '—'}</Td>
                <Td>{row.vendor_name ?? '—'}</Td>
                <Td right>{row.quantity}</Td>
                <Td right>{money(row.value_at_cost)}</Td>
                <Td right className="text-gray-500">{money(row.value_at_mrp)}</Td>
                <Td right className="font-semibold text-[#8f1d1d]">{money(row.input_tax_at_risk)}</Td>
                <Td className="whitespace-nowrap">
                  {row.can_still_be_returned === null ? (
                    <span className="text-[11px] text-gray-400">window unknown</span>
                  ) : row.can_still_be_returned ? (
                    <span className="text-[11px] font-semibold text-[#1c6b41]">
                      {row.days_left_to_return}d to send back
                    </span>
                  ) : (
                    <span className="text-[11px] font-semibold text-[#8f1d1d]">window closed</span>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
};

// ---------------------------------------------------------------- margin

const confidenceLabel = {
  BATCH: null,
  PRODUCT: 'estimated',
  NONE: 'no cost basis'
} as const;

export const MarginReportView: React.FC<{ report: MarginReport }> = ({ report }) => {
  if (report.empty_reason) {
    return (
      <Card title="Gross margin">
        <Empty>{report.empty_reason}</Empty>
      </Card>
    );
  }

  const marginRow = (row: MarginReport['by_product'][number]) => (
    <tr key={row.key}>
      <Td>
        {row.label}
        {confidenceLabel[row.confidence] && (
          <span className="ml-2 text-[10px] text-[#7a5205] bg-[#fdf3e0] rounded px-1.5 py-0.5">
            {confidenceLabel[row.confidence]}
          </span>
        )}
      </Td>
      <Td right>{row.quantity}</Td>
      <Td right>{money(row.revenue)}</Td>
      <Td right className="text-gray-500">{money(row.cost)}</Td>
      <Td right className={row.is_below_cost ? 'font-semibold text-[#8f1d1d]' : 'font-medium'}>
        {money(row.margin)}
      </Td>
      <Td right className={row.is_below_cost ? 'text-[#8f1d1d]' : 'text-gray-500'}>
        {row.margin_percent === null ? '—' : `${row.margin_percent}%`}
      </Td>
    </tr>
  );

  const head = (
    <><Th>Product</Th><Th right>Units</Th><Th right>Revenue</Th>
      <Th right>Cost</Th><Th right>Margin</Th><Th right>%</Th></>
  );

  return (
    <div className="flex flex-col gap-6">
      {report.excluded.note && <Note tone="info">{report.excluded.note}</Note>}

      {report.below_cost.length > 0 && (
        <Card title="Selling below cost"
              subtitle="Revenue under the weighted average cost of the batch that was sold.">
          <Note tone="bad">
            {report.below_cost.length} product
            {report.below_cost.length === 1 ? ' is' : 's are'} losing money on every sale.
          </Note>
          <div className="mt-4">
            <Table head={head}>{report.below_cost.map(marginRow)}</Table>
          </div>
        </Card>
      )}

      <Card title="By product" subtitle="Best margin first."
            action={<span className="text-xs text-gray-500">
              {money(report.totals.margin)} total margin
            </span>}>
        <Table head={head}>{report.by_product.map(marginRow)}</Table>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="By distributor">
          <BarRows
            rows={report.by_vendor.map((r) => ({
              label: r.label,
              value: r.margin,
              tone: r.is_below_cost ? ('bad' as const) : ('series' as const),
              secondary: `${money(r.revenue)} revenue · ${r.margin_percent ?? '—'}%`
            }))}
          />
        </Card>
        <Card title="By month">
          <BarRows
            rows={report.by_month.map((r) => ({
              label: r.label,
              value: r.margin,
              secondary: `${money(r.revenue)} revenue`
            }))}
          />
        </Card>
      </div>

      {report.totals.uncosted_line_count > 0 && (
        <Note tone="warn">
          {report.totals.uncosted_line_count} sold line
          {report.totals.uncosted_line_count === 1 ? ' has' : 's have'} no cost basis — the
          batch was never received through a scanned purchase. Their revenue is excluded from
          margin rather than counted as pure profit.
        </Note>
      )}
    </div>
  );
};

// ---------------------------------------------------------- stock ledger

export const StockLedgerReport: React.FC<{ report: LedgerReport }> = ({ report }) => (
  <Card
    title="Stock ledger"
    subtitle="Every movement, with a running balance per batch. Purchases add, sales take away."
    action={<span className="text-xs text-gray-500">{report.row_count} movements</span>}
  >
    {report.negative_balance_count > 0 && (
      <div className="mb-4">
        <Note tone="warn">
          {report.negative_balance_count} movement
          {report.negative_balance_count === 1 ? '' : 's'} take a batch below zero — stock left
          the shelf that no scanned purchase put there. Usually an imported bill, or stock that
          predates this ledger.
        </Note>
      </div>
    )}
    {report.rows.length === 0 ? (
      <Empty>No movements in this window.</Empty>
    ) : (
      <Table head={
        <><Th>Date</Th><Th>Product</Th><Th>Batch</Th><Th>Movement</Th>
          <Th right>Change</Th><Th right>Balance</Th><Th right>Value</Th></>
      }>
        {report.rows.map((row) => (
          <tr key={row.id}>
            <Td className="whitespace-nowrap">{row.occurred_on}</Td>
            <Td>{row.product_name ?? row.product_id}</Td>
            <Td className="font-mono text-xs">{row.batch_number || '—'}</Td>
            <Td>
              <span className={`text-[10px] rounded px-1.5 py-0.5 font-semibold ${
                row.reason === 'PURCHASE' ? 'bg-[#eaf7f0] text-[#1c6b41]' : 'bg-[#eaf0ff] text-[#123c9e]'
              }`}>
                {row.reason.toLowerCase()}
              </span>
            </Td>
            <Td right className={row.quantity_delta < 0 ? 'text-gray-600' : 'text-[#1c6b41] font-medium'}>
              {row.quantity_delta > 0 ? '+' : ''}{row.quantity_delta}
            </Td>
            <Td right className={row.flags.includes('NEGATIVE_BALANCE') ? 'text-[#8f1d1d] font-semibold' : 'font-medium'}>
              {row.balance}
            </Td>
            <Td right className="text-gray-500">{row.value ? money(row.value) : '—'}</Td>
          </tr>
        ))}
      </Table>
    )}
  </Card>
);

// --------------------------------------------------------------- movers

export const MoversReportView: React.FC<{ report: MoversReport }> = ({ report }) => {
  const cover = (row: MoversReport['slow'][number]) =>
    row.never_sold ? 'never sold' :
    row.days_of_cover === null ? '—' :
    `${row.days_of_cover}d of cover`;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Fastest by units" subtitle={`Over ${report.days_observed} days.`}>
        <BarRows
          rows={report.fast_by_units.slice(0, 12).map((r) => ({
            label: r.product_name ?? r.product_id,
            value: r.units_sold,
            secondary: `${money(r.revenue)} · ${cover(r)}`
          }))}
          format={(v) => `${v}`}
        />
      </Card>

      <Card title="Fastest by value">
        <BarRows
          rows={report.fast_by_value.slice(0, 12).map((r) => ({
            label: r.product_name ?? r.product_id,
            value: r.revenue,
            secondary: `${r.units_sold} units · ${cover(r)}`
          }))}
        />
      </Card>

      <Card
        className="lg:col-span-2"
        title="Slow and dead stock"
        subtitle="Money sitting still. Never-sold first, then the longest cover — on a pharmacy shelf a year of cover means it will expire before it sells."
        action={
          <span className="text-xs text-gray-500">
            {report.totals.never_sold_count} never sold · {report.totals.dead_stock_count} over a year
          </span>
        }
      >
        {report.slow.length === 0 ? <Empty>Nothing is sitting still.</Empty> : (
          <Table head={
            <><Th>Product</Th><Th right>On hand</Th><Th right>Stock value</Th>
              <Th right>Sold</Th><Th right>Days of cover</Th></>
          }>
            {report.slow.map((row) => (
              <tr key={row.product_id}>
                <Td>{row.product_name ?? row.product_id}</Td>
                <Td right>{row.on_hand}</Td>
                <Td right>{money(row.stock_value)}</Td>
                <Td right className="text-gray-500">{row.units_sold}</Td>
                <Td right className={row.never_sold || row.dead_stock ? 'text-[#8f1d1d] font-semibold' : ''}>
                  {cover(row)}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
};

// --------------------------------------------------------- daily sales

const Delta: React.FC<{ percent: number | null }> = ({ percent }) => {
  if (percent === null) return <span className="text-xs text-gray-400">no comparison</span>;
  const up = percent >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-semibold ${
      up ? 'text-[#1c6b41]' : 'text-[#8f1d1d]'
    }`}>
      <Icon size={13} aria-hidden />{Math.abs(percent)}%
    </span>
  );
};

export const DailySalesReportView: React.FC<{ report: DailySalesReport }> = ({ report }) => (
  <div className="flex flex-col gap-6">
    <div className="grid gap-4 sm:grid-cols-3">
      {[
        { label: 'Sales', value: money(report.totals.value),
          delta: report.comparison.value_change_percent,
          was: money(report.comparison.previous_value) },
        { label: 'Bills', value: String(report.totals.bill_count),
          delta: report.comparison.bill_count_change_percent,
          was: String(report.comparison.previous_bill_count) },
        { label: 'Average bill', value: money(report.totals.average_bill_value),
          delta: report.comparison.average_bill_change_percent,
          was: money(report.comparison.previous_average_bill_value) }
      ].map((tile) => (
        <div key={tile.label} className="rounded-2xl border border-[#e2e8f0] bg-white p-5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
            {tile.label}
          </span>
          <strong className="block text-2xl font-bold text-[#0f172a] mt-1 tabular-nums">
            {tile.value}
          </strong>
          <div className="flex items-center gap-2 mt-1.5">
            <Delta percent={tile.delta} />
            <span className="text-[11px] text-gray-500">vs {tile.was} last month</span>
          </div>
        </div>
      ))}
    </div>

    <Card title="By hour" subtitle="When the shop is actually busy.">
      <HourHistogram
        hours={report.by_hour.map((h) => ({
          hour: h.hour, label: h.label, value: h.value, bill_count: h.bill_count
        }))}
      />
      {report.bills_without_a_time > 0 && (
        <p className="text-[11px] text-gray-500 mt-3">
          {report.bills_without_a_time} bill{report.bills_without_a_time === 1 ? '' : 's'} carry no
          issue time and are not in this chart — day totals and some imported rows.
        </p>
      )}
    </Card>

    <Card title="How it was paid">
      <SplitBar
        parts={report.payment_split.map((p) => ({
          label: p.method, value: p.amount, share: p.share_percent
        }))}
      />
      <div className="mt-5 flex flex-wrap gap-6 text-sm">
        <span>Cash <strong className="tabular-nums">{money(report.cash_vs_digital.cash)}</strong>
          <span className="text-gray-400 ml-1">({report.cash_vs_digital.cash_share_percent ?? 0}%)</span>
        </span>
        <span>Digital <strong className="tabular-nums">{money(report.cash_vs_digital.digital)}</strong></span>
      </div>
      {report.cash_vs_digital.unrecorded !== 0 && (
        <div className="mt-4">
          <Note tone="warn">
            Bills come to {money(report.cash_vs_digital.unrecorded)} more than was recorded as
            taken. Either payments went unentered or sales did — and a scrutiny officer runs
            this same comparison.
          </Note>
        </div>
      )}
    </Card>

    <Card title="Day by day">
      <DualLineChart
        rows={report.by_day.map((d) => ({ day: d.day, a: d.value, b: 0 }))}
        labelA="Sales" labelB=""
      />
    </Card>
  </div>
);

// ---------------------------------------------------------------- trend

export const TrendReportView: React.FC<{ report: TrendReport }> = ({ report }) => (
  <Card
    title="Purchases against sales"
    subtitle={report.note}
    action={
      <span className="text-xs text-gray-500">
        {money(report.totals.sales)} in · {money(report.totals.purchases)} out
      </span>
    }
  >
    <DualLineChart
      rows={report.rows.map((r) => ({
        day: r.day, a: r.sales, b: r.purchases, cumulative: r.cumulative_net
      }))}
      labelA="Sales" labelB="Purchases"
      height={220}
    />
    <div className="mt-6 grid gap-4 sm:grid-cols-3 text-sm">
      <div><span className="text-gray-500 block text-xs">Sales</span>
        <strong className="tabular-nums">{money(report.totals.sales)}</strong></div>
      <div><span className="text-gray-500 block text-xs">Purchases</span>
        <strong className="tabular-nums">{money(report.totals.purchases)}</strong></div>
      <div><span className="text-gray-500 block text-xs">Difference</span>
        <strong className={`tabular-nums ${report.totals.net < 0 ? 'text-[#8f1d1d]' : 'text-[#1c6b41]'}`}>
          {money(report.totals.net)}
        </strong></div>
    </div>
  </Card>
);

// ------------------------------------------------------ vendor scorecard

export const VendorScorecardView: React.FC<{
  report: VendorScorecard;
  onSetWindow: (vendorId: string, days: number | null) => void;
}> = ({ report, onSetWindow }) => (
  <div className="flex flex-col gap-6">
    {report.source.note && <Note tone="info">{report.source.note}</Note>}

    <Card
      title="Distributors"
      subtitle="Ranked by how much of your input credit rides on them — which is the order in which their filing behaviour matters."
      action={<span className="text-xs text-gray-500">
        {money(report.totals.credit_at_stake)} of credit across {report.totals.vendor_count}
      </span>}
    >
      {report.rows.length === 0 ? <Empty>No purchases in this window.</Empty> : (
        <div className="flex flex-col gap-4">
          {report.rows.map((row) => (
            <div key={row.vendor_id} className="rounded-xl border border-[#e2e8f0] p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <div>
                  <strong className="text-sm text-[#0f172a]">{row.name}</strong>
                  {row.gstin && (
                    <span className="ml-2 font-mono text-[11px] text-gray-400">{row.gstin}</span>
                  )}
                </div>
                <span className="text-sm tabular-nums font-medium">
                  {money(row.credit_from_this_supplier)}
                </span>
              </div>

              {row.summary && (
                <p className="text-sm text-gray-700 mt-2 leading-relaxed">{row.summary}</p>
              )}

              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mt-3 text-[11px] text-gray-500">
                <span>{row.invoice_count} invoices · {money(row.purchase_taxable)} bought</span>
                <label className="inline-flex items-center gap-1.5">
                  Returns accepted until
                  <input
                    type="number"
                    min={0}
                    max={730}
                    defaultValue={row.return_window_days ?? ''}
                    placeholder="?"
                    onBlur={(e) => {
                      const raw = e.target.value.trim();
                      const next = raw === '' ? null : Number(raw);
                      if (next !== row.return_window_days) onSetWindow(row.vendor_id, next);
                    }}
                    className="w-16 rounded border border-[#e2e8f0] px-1.5 py-0.5 text-center tabular-nums"
                    aria-label={`Return window in days for ${row.name}`}
                  />
                  days before expiry
                </label>
                {row.return_window_days === null && (
                  <span className="text-[#7a5205]">
                    unknown — the expiry report cannot say whether stock can still go back
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  </div>
);
