import React from 'react';
import { Download, TrendingUp } from 'lucide-react';

import { reportsApi } from '../api';
import { downloadCsv, reportFilename, toCsv } from '../csv';
import { currency, dateLabel, number, percent, signedPercent } from '../format';
import type { PeriodQuery, PriceVariance, VendorScorecard } from '../types';
import { periodKey, useReport } from '../useReport';
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  SeverityChip,
  ShareBar,
  StatTile,
  TableScroll,
  Td,
  Th
} from './Primitives';

export const SuppliersPanel: React.FC<{ query: PeriodQuery }> = ({ query }) => {
  const key = periodKey(query);
  const scorecard = useReport<VendorScorecard>(() => reportsApi.vendors(query), [key]);
  const variance = useReport<PriceVariance>(() => reportsApi.priceVariance(query), [key]);

  if (scorecard.loading || variance.loading) return <LoadingState />;
  if (scorecard.error) return <ErrorState message={scorecard.error} onRetry={scorecard.reload} />;
  if (variance.error) return <ErrorState message={variance.error} onRetry={variance.reload} />;
  if (!scorecard.data || !variance.data) return null;

  const data = scorecard.data;
  const movers = variance.data.products.filter(
    (product) => product.rate_increased || product.cross_vendor_spread !== null
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatTile
          label="Total spend"
          value={currency(data.total_spend)}
          hint={`Across ${number(data.vendor_count)} suppliers`}
        />
        <StatTile
          label="Top three share"
          value={percent(data.top_three_share)}
          hint="Concentration is a supply risk as well as a negotiating position"
        />
        <StatTile
          label="Products bought dearer"
          value={number(variance.data.increased_count)}
          hint="Effective unit cost rose within the period"
          tone={variance.data.increased_count > 0 ? 'warning' : 'default'}
        />
      </div>

      <Card
        title="Supplier scorecard"
        subtitle="Effective discount folds rupee discounts and free goods into one comparable rate."
        action={
          data.vendors.length > 0 ? (
            <button
              onClick={() =>
                downloadCsv(
                  reportFilename('Suppliers', data.period.label),
                  toCsv(data.vendors, [
                    { header: 'Supplier', value: (v) => v.vendor_name },
                    { header: 'GSTIN', value: (v) => v.gstin },
                    { header: 'Invoices', value: (v) => v.invoice_count },
                    { header: 'Gross Spend', value: (v) => v.gross_total },
                    { header: 'Share', value: (v) => v.share },
                    { header: 'Billed Units', value: (v) => v.billed_units },
                    { header: 'Free Units', value: (v) => v.free_units },
                    { header: 'Effective Discount', value: (v) => v.effective_discount_rate },
                    { header: 'Last Purchase', value: (v) => v.last_purchase_date }
                  ])
                )
              }
              className="text-xs font-semibold text-[#1b5dfc] hover:text-[#154ecb] flex items-center gap-1 cursor-pointer shrink-0"
            >
              <Download size={13} aria-hidden="true" />
              Export
            </button>
          ) : undefined
        }
      >
        {data.vendors.length === 0 ? (
          <EmptyState title="No supplier purchases in this period" />
        ) : (
          <TableScroll>
            <table className="w-full min-w-[720px]">
              <thead>
                <tr>
                  <Th>Supplier</Th>
                  <Th align="right">Invoices</Th>
                  <Th align="right">Spend</Th>
                  <Th>Share</Th>
                  <Th align="right">Free units</Th>
                  <Th align="right">Effective discount</Th>
                  <Th>Last purchase</Th>
                </tr>
              </thead>
              <tbody>
                {data.vendors.map((vendor) => (
                  <tr key={`${vendor.gstin ?? vendor.vendor_name}`} className="hover:bg-[#f8fafc]">
                    <Td className="font-medium text-[#0f172a]">
                      <span className="block max-w-[200px] truncate" title={vendor.vendor_name}>
                        {vendor.vendor_name}
                      </span>
                      {!vendor.identified && (
                        <span className="inline-block mt-0.5">
                          <SeverityChip severity="blocking" label="No GSTIN" />
                        </span>
                      )}
                    </Td>
                    <Td align="right">{number(vendor.invoice_count)}</Td>
                    <Td align="right" className="font-semibold text-[#0f172a]">
                      {currency(vendor.gross_total)}
                    </Td>
                    <Td>
                      <div className="flex items-center gap-2 min-w-[110px]">
                        <ShareBar share={vendor.share} />
                        <span className="text-[10px] text-gray-500 tabular-nums w-9 shrink-0">
                          {percent(vendor.share, 0)}
                        </span>
                      </div>
                    </Td>
                    <Td align="right">
                      {number(vendor.free_units)}
                      {vendor.free_unit_share !== null && vendor.free_unit_share > 0 && (
                        <span className="text-[10px] text-gray-400 block">
                          {percent(vendor.free_unit_share, 1)} of units
                        </span>
                      )}
                    </Td>
                    <Td align="right" className="font-semibold text-[#0f172a]">
                      {percent(vendor.effective_discount_rate)}
                    </Td>
                    <Td>{dateLabel(vendor.last_purchase_date)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Card>

      <Card
        title="Price movement and sourcing spread"
        subtitle="Effective unit cost includes free goods, so a scheme change shows up as a price change."
      >
        {movers.length === 0 ? (
          <EmptyState
            title="No price movement detected"
            detail="A product needs at least two purchases in the period before a rate change means anything."
            icon={<TrendingUp size={28} className="text-gray-300" aria-hidden="true" />}
          />
        ) : (
          <TableScroll>
            <table className="w-full min-w-[700px]">
              <thead>
                <tr>
                  <Th>Product</Th>
                  <Th align="right">Purchases</Th>
                  <Th align="right">First cost</Th>
                  <Th align="right">Latest cost</Th>
                  <Th align="right">Change</Th>
                  <Th align="right">Margin at MRP</Th>
                  <Th>Cheapest supplier</Th>
                </tr>
              </thead>
              <tbody>
                {movers.map((product) => (
                  <tr key={product.product_id} className="hover:bg-[#f8fafc]">
                    <Td className="font-medium text-[#0f172a]">
                      <span className="block max-w-[200px] truncate" title={product.product_name ?? ''}>
                        {product.product_name ?? '—'}
                      </span>
                      {product.pack && <span className="text-[10px] text-gray-400">{product.pack}</span>}
                    </Td>
                    <Td align="right">
                      {number(product.purchase_count)}
                      {product.vendor_count > 1 && (
                        <span className="text-[10px] text-gray-400 block">
                          {product.vendor_count} suppliers
                        </span>
                      )}
                    </Td>
                    <Td align="right">{currency(product.first_unit_cost)}</Td>
                    <Td align="right" className="font-semibold text-[#0f172a]">
                      {currency(product.latest_unit_cost)}
                    </Td>
                    <Td align="right">
                      <span className="inline-flex items-center gap-1.5 justify-end">
                        <span className="tabular-nums">{signedPercent(product.rate_change)}</span>
                        {product.rate_increased && <SeverityChip severity="warning" label="Up" />}
                      </span>
                    </Td>
                    <Td align="right">{percent(product.latest_margin)}</Td>
                    <Td>
                      {product.cheapest_vendor ? (
                        <>
                          <span className="block max-w-[140px] truncate" title={product.cheapest_vendor}>
                            {product.cheapest_vendor}
                          </span>
                          <span className="text-[10px] text-gray-400">
                            saves {currency(product.cross_vendor_spread)}/unit
                          </span>
                        </>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
        <p className="text-[11px] text-gray-500 mt-3">
          Margin is measured against MRP net of GST, since the tax on a purchase comes back as input
          credit. It is blank where the GST rate on a line was not captured.
        </p>
      </Card>
    </div>
  );
};
