import React from 'react';
import { Download, FileSpreadsheet } from 'lucide-react';

import { reportsApi } from '../api';
import { downloadCsv, reportFilename, toCsv } from '../csv';
import { currency, dateLabel, number, percent } from '../format';
import type { GstRegister, HsnSummary, PeriodQuery, RegisterRow } from '../types';
import { periodKey, useReport } from '../useReport';
import {
  Card,
  ErrorState,
  EmptyState,
  LoadingState,
  SeverityChip,
  ShareBar,
  StatTile,
  TableScroll,
  Td,
  Th
} from './Primitives';

const SUPPLY_LABEL: Record<string, string> = {
  intra_state: 'Intra-state',
  inter_state: 'Inter-state',
  mixed: 'Mixed'
};

// Column order is fixed and matches what reconciliation tools expect from a
// purchase register. Changing it breaks month-on-month comparison of exports.
const REGISTER_COLUMNS = [
  { header: 'Invoice Date', value: (row: RegisterRow) => row.invoice_date },
  { header: 'Invoice Number', value: (row: RegisterRow) => row.invoice_number },
  { header: 'Supplier', value: (row: RegisterRow) => row.seller_name },
  { header: 'Supplier GSTIN', value: (row: RegisterRow) => row.seller_gstin },
  { header: 'Taxable Value', value: (row: RegisterRow) => row.taxable_value },
  { header: 'Discount', value: (row: RegisterRow) => row.discount },
  { header: 'CGST', value: (row: RegisterRow) => row.cgst },
  { header: 'SGST', value: (row: RegisterRow) => row.sgst },
  { header: 'IGST', value: (row: RegisterRow) => row.igst },
  { header: 'Round Off', value: (row: RegisterRow) => row.roundoff },
  { header: 'Invoice Total', value: (row: RegisterRow) => row.grand_total },
  { header: 'Supply Type', value: (row: RegisterRow) => row.supply_type },
  { header: 'ITC Eligible', value: (row: RegisterRow) => (row.itc_eligible ? 'Yes' : 'No') },
  { header: 'ITC Blocked Reason', value: (row: RegisterRow) => row.itc_blocked_reason }
];

export const GstPanel: React.FC<{ query: PeriodQuery }> = ({ query }) => {
  const key = periodKey(query);
  const register = useReport<GstRegister>(() => reportsApi.gstRegister(query), [key]);
  const hsn = useReport<HsnSummary>(() => reportsApi.hsnSummary(query), [key]);

  if (register.loading || hsn.loading) return <LoadingState />;
  if (register.error) return <ErrorState message={register.error} onRetry={register.reload} />;
  if (hsn.error) return <ErrorState message={hsn.error} onRetry={hsn.reload} />;
  if (!register.data || !hsn.data) return null;

  const data = register.data;

  const exportRegister = () =>
    downloadCsv(
      reportFilename('GST_Register', data.period.label),
      toCsv(data.rows, REGISTER_COLUMNS)
    );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatTile
          label="Claimable input credit"
          value={currency(data.claimable_tax)}
          hint={`Across ${number(data.row_count)} invoices in ${data.period.label}`}
        />
        <StatTile
          label="Blocked credit"
          value={currency(data.blocked_tax)}
          hint="Tax on invoices with no supplier GSTIN"
          tone={data.blocked_tax > 0 ? 'blocking' : 'default'}
        />
        <StatTile
          label="Invoices needing a GSTIN"
          value={number(data.blocked_invoice_count)}
          hint="Cannot support a credit claim as they stand"
          tone={data.blocked_invoice_count > 0 ? 'blocking' : 'default'}
        />
      </div>

      <Card
        title="GST purchase register"
        subtitle="Invoice-level rows for the ITC claim and GSTR-2B reconciliation."
        action={
          <button
            onClick={exportRegister}
            disabled={data.rows.length === 0}
            className="bg-[#1b5dfc] hover:bg-[#154ecb] disabled:bg-gray-200 disabled:text-gray-400
                       disabled:cursor-not-allowed text-white font-semibold px-3 py-2 rounded-xl text-xs
                       flex items-center gap-1.5 transition-colors cursor-pointer shrink-0"
          >
            <FileSpreadsheet size={13} aria-hidden="true" />
            Export register
          </button>
        }
      >
        {data.rows.length === 0 ? (
          <EmptyState
            title="No invoices in this period"
            detail="Upload and verify invoices dated inside the selected period to build the register."
          />
        ) : (
          <TableScroll>
            <table className="w-full min-w-[820px]">
              <thead>
                <tr>
                  <Th>Date</Th>
                  <Th>Invoice</Th>
                  <Th>Supplier</Th>
                  <Th>GSTIN</Th>
                  <Th align="right">Taxable</Th>
                  <Th align="right">CGST</Th>
                  <Th align="right">SGST</Th>
                  <Th align="right">IGST</Th>
                  <Th align="right">Total</Th>
                  <Th>ITC</Th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.invoice_id} className="hover:bg-[#f8fafc]">
                    <Td>{dateLabel(row.invoice_date)}</Td>
                    <Td className="font-medium text-[#0f172a]">{row.invoice_number ?? '—'}</Td>
                    <Td>
                      <span className="block max-w-[180px] truncate" title={row.seller_name ?? ''}>
                        {row.seller_name ?? '—'}
                      </span>
                      {row.supply_type && (
                        <span className="text-[10px] text-gray-400">
                          {SUPPLY_LABEL[row.supply_type]}
                        </span>
                      )}
                    </Td>
                    <Td className="font-mono text-[10px]">{row.seller_gstin ?? '—'}</Td>
                    <Td align="right">{currency(row.taxable_value)}</Td>
                    <Td align="right">{currency(row.cgst)}</Td>
                    <Td align="right">{currency(row.sgst)}</Td>
                    <Td align="right">{currency(row.igst)}</Td>
                    <Td align="right" className="font-semibold text-[#0f172a]">
                      {currency(row.grand_total)}
                    </Td>
                    <Td>
                      {row.itc_eligible ? (
                        <span className="text-[10px] text-gray-500">Eligible</span>
                      ) : (
                        <SeverityChip severity="blocking" label={row.itc_blocked_reason ?? 'Blocked'} />
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Card>

      <Card
        title="HSN and rate-slab summary"
        subtitle="Taxable value by classification. Pharma sits mostly at 5% and 12%."
        action={
          hsn.data.rows.length > 0 ? (
            <button
              onClick={() =>
                downloadCsv(
                  reportFilename('HSN_Summary', hsn.data!.period.label),
                  toCsv(hsn.data!.rows, [
                    { header: 'HSN', value: (r) => r.hsn },
                    { header: 'GST %', value: (r) => r.gst_percent },
                    { header: 'Lines', value: (r) => r.line_count },
                    { header: 'Quantity', value: (r) => r.quantity },
                    { header: 'Taxable Value', value: (r) => r.taxable_value }
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
        {hsn.data.rows.length === 0 ? (
          <EmptyState title="No classified line items in this period" />
        ) : (
          <>
            <div className="flex flex-wrap gap-2 mb-5">
              {hsn.data.slabs.map((slab) => (
                <div
                  key={String(slab.gst_percent)}
                  className="flex-1 min-w-[130px] bg-[#f8fafc] border border-gray-100 rounded-xl p-3"
                >
                  <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">
                    {slab.gst_percent === null ? 'Rate not read' : `${slab.gst_percent}% slab`}
                  </span>
                  <strong className="text-sm font-bold text-[#0f172a] block mt-1 tabular-nums">
                    {currency(slab.taxable_value)}
                  </strong>
                  <span className="text-[10px] text-gray-500">
                    {percent(slab.share)} · {number(slab.line_count)} lines
                  </span>
                </div>
              ))}
            </div>

            {hsn.data.slab_conflicts.length > 0 && (
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <SeverityChip severity="warning" label="Slab conflict" />
                <p className="text-[11px] text-gray-600">
                  {hsn.data.slab_conflicts.map((c) => c.hsn).join(', ')} appear under more than one GST
                  rate. An HSN code determines its slab, so this usually means a misread rate.
                </p>
              </div>
            )}

            <TableScroll>
              <table className="w-full min-w-[560px]">
                <thead>
                  <tr>
                    <Th>HSN</Th>
                    <Th align="right">GST %</Th>
                    <Th align="right">Lines</Th>
                    <Th align="right">Quantity</Th>
                    <Th align="right">Taxable value</Th>
                    <Th>Share</Th>
                  </tr>
                </thead>
                <tbody>
                  {hsn.data.rows.map((row) => (
                    <tr key={`${row.hsn}-${row.gst_percent}`} className="hover:bg-[#f8fafc]">
                      <Td className="font-mono text-[11px] text-[#0f172a]">{row.hsn}</Td>
                      <Td align="right">
                        {row.gst_percent === null ? '—' : `${row.gst_percent}%`}
                        {row.slab_is_expected === false && (
                          <span className="ml-1.5 inline-block align-middle">
                            <SeverityChip severity="warning" label="Unusual" />
                          </span>
                        )}
                      </Td>
                      <Td align="right">{number(row.line_count)}</Td>
                      <Td align="right">{number(row.quantity)}</Td>
                      <Td align="right" className="font-semibold text-[#0f172a]">
                        {currency(row.taxable_value)}
                      </Td>
                      <Td>
                        <div className="flex items-center gap-2 min-w-[110px]">
                          <ShareBar share={row.share} />
                          <span className="text-[10px] text-gray-500 tabular-nums w-10 shrink-0">
                            {percent(row.share, 0)}
                          </span>
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>

            {hsn.data.unclassified_line_count > 0 && (
              <p className="text-[11px] text-gray-500 mt-3">
                {hsn.data.unclassified_line_count} line
                {hsn.data.unclassified_line_count === 1 ? '' : 's'} carry no HSN code and are grouped as
                unclassified.
              </p>
            )}
          </>
        )}
      </Card>
    </div>
  );
};
