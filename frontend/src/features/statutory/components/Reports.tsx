import React from 'react';
import { Lock } from 'lucide-react';

import { Amount, Card, Empty, Flag, Note, Table, Td, Th } from './Primitives';
import type { Drill, Figure, Pack, ReportRow } from '../types';

type OnDrill = (drill: Drill, label: string) => void;

const asFigure = (value: unknown): Figure | null =>
  value && typeof value === 'object' && 'paise' in (value as object) ? (value as Figure) : null;

const text = (value: unknown): string =>
  value === null || value === undefined || value === '' ? '—' : String(value);

const flagTone = (flag: string): 'bad' | 'warn' | 'info' => {
  if (['GAP', 'DUPLICATE', 'ITC_BLOCKED', 'NO_PLACE_OF_SUPPLY', 'HSN_MISSING',
       'HSN_NOT_IN_MASTER', 'UQC_MISSING', 'UQC_UNMAPPED'].includes(flag)) return 'bad';
  if (['DRAFT', 'CANCELLED', 'MIXED_SUPPLY_TYPE'].includes(flag)) return 'warn';
  return 'info';
};

const Flags: React.FC<{ flags: string[] }> = ({ flags }) => (
  <>
    {flags.map((flag) => (
      <Flag key={flag} tone={flagTone(flag)}>
        {flag.replace(/_/g, ' ').toLowerCase()}
      </Flag>
    ))}
  </>
);

// ------------------------------------------------------------------ GSTR-1

export const Gstr1Report: React.FC<{ pack: Pack; onDrill: OnDrill }> = ({ pack, onDrill }) => {
  const report = pack.reports.gstr1;
  const tables = report.tables;

  return (
    <div className="flex flex-col gap-6">
      {(report.validation.blocking.length > 0 || report.validation.warnings.length > 0) && (
        <Card
          title="Validation"
          subtitle="Shown inline with the return rather than on another screen — the figures and the reasons they cannot be filed belong together."
        >
          <Table head={<><Th>Severity</Th><Th>What is wrong</Th><Th>Record</Th></>}>
            {[...report.validation.blocking, ...report.validation.warnings].map((item) => (
              <tr key={item.id}>
                <Td><Flag tone={item.severity === 'BLOCKING' ? 'bad' : 'warn'}>{item.severity.toLowerCase()}</Flag></Td>
                <Td className="max-w-xl">{item.message}</Td>
                <Td className="text-[11px] text-gray-400">{item.record_id ?? item.record_type}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      )}

      <Card title="Table 7 — B2CS" subtitle="Supplies to unregistered customers, aggregated. Returns netted in.">
        {tables.b2cs.length === 0 ? <Empty>Nothing in this table.</Empty> : (
          <Table head={<><Th>Place</Th><Th>Type</Th><Th right>Rate</Th><Th right>Taxable</Th><Th right>CGST</Th><Th right>SGST</Th><Th right>IGST</Th></>}>
            {tables.b2cs.map((row: any, i: number) => (
              <tr key={i}>
                <Td>{row.place_of_supply}</Td>
                <Td>{row.supply_type === 'INTRA' ? 'Intra-state' : 'Inter-state'}</Td>
                <Td right>{row.rate}%</Td>
                <Td right><Amount figure={row.taxable} onDrill={onDrill} label="this bucket" /></Td>
                <Td right><Amount figure={row.cgst} onDrill={onDrill} label="this bucket" muted /></Td>
                <Td right><Amount figure={row.sgst} onDrill={onDrill} label="this bucket" muted /></Td>
                <Td right><Amount figure={row.igst} onDrill={onDrill} label="this bucket" muted /></Td>
              </tr>
            ))}
          </Table>
        )}
        {tables.b2cs_negative?.length > 0 && (
          <div className="mt-4">
            <Note tone="bad">
              <strong>Withheld — returns exceeded sales.</strong> These buckets are not in the
              return: the portal will not accept a negative aggregate, and the credit note
              belongs against the period the original sale was in.
            </Note>
          </div>
        )}
      </Card>

      <Card title="Table 4A — B2B" subtitle="Supplies to registered persons, invoice-wise.">
        {tables.b2b.length === 0 ? <Empty>No supplies to registered persons.</Empty> : (
          <Table head={<><Th>Bill</Th><Th>Date</Th><Th>Customer GSTIN</Th><Th>Place</Th><Th right>Invoice value</Th></>}>
            {tables.b2b.map((row: any) => (
              <tr key={row.document_id}>
                <Td>{text(row.bill_number)}</Td>
                <Td>{row.sale_date}</Td>
                <Td className="font-mono text-xs">{text(row.customer_gstin)}</Td>
                <Td>{row.place_of_supply}</Td>
                <Td right><Amount figure={row.invoice_value} onDrill={onDrill} label="this bill" /></Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Table 5 — B2CL" subtitle="Inter-state consumer supplies above ₹2,50,000. An over-the-counter sale is supplied where the counter is, so anything here deserves a second look.">
        {tables.b2cl.length === 0 ? <Empty>Nothing qualifies — which is what you would expect.</Empty> : (
          <Table head={<><Th>Bill</Th><Th>Date</Th><Th>Place</Th><Th right>Invoice value</Th></>}>
            {tables.b2cl.map((row: any) => (
              <tr key={row.document_id}>
                <Td>{text(row.bill_number)}</Td>
                <Td>{row.sale_date}</Td>
                <Td>{row.place_of_supply}</Td>
                <Td right><Amount figure={row.invoice_value} onDrill={onDrill} label="this bill" /></Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Table 8 — nil rated, exempted and non-GST">
        <Table head={<><Th /><Th>Supplies</Th><Th right>Nil rated</Th><Th right>Exempted</Th><Th right>Non-GST</Th><Th right>Total</Th></>}>
          {tables.nil_exempt.map((row: any) => (
            <tr key={row.code}>
              <Td className="font-semibold text-gray-500">{row.code}</Td>
              <Td>{row.description}</Td>
              <Td right><Amount figure={row.nil_rated} onDrill={onDrill} label="nil-rated supplies" muted /></Td>
              <Td right><Amount figure={row.exempted} onDrill={onDrill} label="exempt supplies" muted /></Td>
              <Td right><Amount figure={row.non_gst} onDrill={onDrill} label="non-GST supplies" muted /></Td>
              <Td right><Amount figure={row.total} onDrill={onDrill} label="this row" bold /></Td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
};

// ------------------------------------------------------------------ GSTR-3B

export const Gstr3bReport: React.FC<{ pack: Pack; onDrill: OnDrill }> = ({ pack, onDrill }) => {
  const report = pack.reports.gstr3b;

  const rows = (list: typeof report.outward) => list.map((row) => (
    <tr key={row.code}>
      <Td className="font-semibold whitespace-nowrap">
        {row.code}
        {row.auto_populated && (
          <Lock size={11} className="inline ml-1.5 text-gray-400 align-baseline" aria-label="Not editable at the portal" />
        )}
      </Td>
      <Td className="max-w-md">
        {row.label}
        {row.note && <span className="block text-[11px] text-gray-500 mt-0.5">{row.note}</span>}
      </Td>
      <Td right><Amount figure={row.taxable} onDrill={onDrill} label={row.code} /></Td>
      <Td right><Amount figure={row.igst} onDrill={onDrill} label={row.code} muted /></Td>
      <Td right><Amount figure={row.cgst} onDrill={onDrill} label={row.code} muted /></Td>
      <Td right><Amount figure={row.sgst} onDrill={onDrill} label={row.code} muted /></Td>
    </tr>
  ));

  const head = <><Th>Row</Th><Th>Description</Th><Th right>Taxable</Th><Th right>IGST</Th><Th right>CGST</Th><Th right>SGST</Th></>;

  return (
    <div className="flex flex-col gap-6">
      <Note tone="warn">
        <strong>Table 3 is auto-populated and locked at the portal.</strong>{' '}
        {report.auto_populated_warning}
      </Note>

      <Card title="3.1 — Outward supplies" subtitle="From this period's GSTR-1. Rows marked with a lock cannot be edited in 3B.">
        <Table head={head}>{rows(report.outward)}</Table>
      </Card>

      <Card
        title="4 — Input tax credit"
        subtitle={`Sourced from ${report.itc_source.name === 'GSTR_2B' ? 'GSTR-2B' : 'the purchase register'}. Table 4 is editable at the portal.`}
      >
        {!report.itc_source.is_authoritative && (
          <div className="mb-4">
            <Note tone="warn">
              <strong>Provisional figure.</strong>
              <ul className="list-disc pl-4 mt-1 space-y-1">
                {report.itc_source.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
              </ul>
              {report.itc_source.excluded.length > 0 && (
                <p className="mt-2">
                  {report.itc_source.excluded.length}{' '}
                  {report.itc_source.excluded.length === 1 ? 'invoice was' : 'invoices were'} left
                  out: {report.itc_source.excluded.map((e) => `${e.invoice_number} (${e.reason})`).join(', ')}.
                </p>
              )}
            </Note>
          </div>
        )}
        <Table head={head}>
          {rows(report.itc)}
          {report.net_itc && (
            <tr className="bg-gray-50">
              <Td className="font-bold">{report.net_itc.code}</Td>
              <Td className="font-semibold">
                {report.net_itc.label}
                <span className="block text-[11px] text-gray-500 mt-0.5 font-normal">{report.net_itc.note}</span>
              </Td>
              <Td right />
              <Td right><Amount figure={report.net_itc.igst} bold /></Td>
              <Td right><Amount figure={report.net_itc.cgst} bold /></Td>
              <Td right><Amount figure={report.net_itc.sgst} bold /></Td>
            </tr>
          )}
        </Table>
      </Card>
    </div>
  );
};

// --------------------------------------------------------------- registers

const RowTable: React.FC<{
  rows: ReportRow[];
  columns: Array<{ key: string; header: string; right?: boolean; mono?: boolean }>;
  onDrill: OnDrill;
  label: string;
  empty: string;
}> = ({ rows, columns, onDrill, label, empty }) => {
  if (rows.length === 0) return <Empty>{empty}</Empty>;
  return (
    <Table head={<><Th />{columns.map((c) => <Th key={c.key} right={c.right}>{c.header}</Th>)}</>}>
      {rows.map((row, index) => (
        <tr key={String(row.cells.invoice_id ?? row.cells.document_id ?? row.cells.id ?? index)}>
          <Td><Flags flags={row.flags} /></Td>
          {columns.map((column) => {
            const value = row.cells[column.key];
            const figure = asFigure(value);
            return (
              <Td key={column.key} right={column.right} className={column.mono ? 'font-mono text-xs' : ''}>
                {figure
                  ? <Amount figure={figure} onDrill={onDrill} label={label} muted={column.key !== 'taxable'} />
                  : Array.isArray(value) ? (value.length ? value.join(', ') : '—')
                  : typeof value === 'boolean' ? (value ? 'Yes' : 'No')
                  : text(value)}
              </Td>
            );
          })}
        </tr>
      ))}
    </Table>
  );
};

export const PurchaseRegisterReport: React.FC<{ pack: Pack; onDrill: OnDrill }> = ({ pack, onDrill }) => {
  const report = pack.reports.purchase_register;
  return (
    <Card
      title="Purchase register"
      subtitle="Invoice-wise inward supplies. ITC eligibility here is a necessary condition, not a sufficient one — what is claimable is capped by GSTR-2B."
      action={
        <span className="text-xs text-gray-500">
          {report.row_count} invoices · {report.blocked_invoice_count} with ITC blocked
        </span>
      }
    >
      <RowTable
        rows={report.rows}
        onDrill={onDrill}
        label="this invoice"
        empty="No inward supplies in this period."
        columns={[
          { key: 'invoice_date', header: 'Date' },
          { key: 'invoice_number', header: 'Invoice no.' },
          { key: 'seller_name', header: 'Supplier' },
          { key: 'seller_gstin', header: 'GSTIN', mono: true },
          { key: 'taxable', header: 'Taxable', right: true },
          { key: 'cgst', header: 'CGST', right: true },
          { key: 'sgst', header: 'SGST', right: true },
          { key: 'igst', header: 'IGST', right: true },
          { key: 'grand_total', header: 'Invoice value', right: true },
          { key: 'itc_eligible', header: 'ITC' },
          { key: 'itc_blocked_reason', header: 'Blocked because' }
        ]}
      />
      <div className="mt-4 flex flex-wrap gap-6 text-xs text-gray-600">
        <span>Claimable tax: <Amount figure={report.totals.itc_eligible_tax} bold /></span>
        <span>Blocked tax: <Amount figure={report.totals.itc_blocked_tax} bold /></span>
      </div>
    </Card>
  );
};

export const SalesRegisterReport: React.FC<{ pack: Pack; onDrill: OnDrill }> = ({ pack, onDrill }) => {
  const report = pack.reports.sales_register;
  return (
    <Card
      title="Sales register"
      subtitle="Bill-wise outward supplies. Drafts and cancellations are kept and flagged — a register that omits them disagrees with the bill book it is checked against."
      action={<span className="text-xs text-gray-500">{report.row_count} bills</span>}
    >
      <RowTable
        rows={report.rows}
        onDrill={onDrill}
        label="this bill"
        empty="No outward supplies match these filters."
        columns={[
          { key: 'sale_date', header: 'Date' },
          { key: 'bill_number', header: 'Bill no.' },
          { key: 'capture_mode', header: 'Captured as' },
          { key: 'rates', header: 'Rates %' },
          { key: 'payment_methods', header: 'Paid by' },
          { key: 'place_of_supply', header: 'Place' },
          { key: 'taxable', header: 'Taxable', right: true },
          { key: 'cgst', header: 'CGST', right: true },
          { key: 'sgst', header: 'SGST', right: true },
          { key: 'igst', header: 'IGST', right: true },
          { key: 'grand_total', header: 'Bill value', right: true }
        ]}
      />
    </Card>
  );
};

// --------------------------------------------------------------------- HSN

export const HsnReport: React.FC<{ pack: Pack; onDrill: OnDrill }> = ({ pack, onDrill }) => {
  const { outward, inward } = pack.reports.hsn_summary;

  const outwardColumns = [
    { key: 'hsn', header: 'HSN', mono: true },
    { key: 'description', header: 'Description' },
    { key: 'uqc', header: 'UQC' },
    { key: 'uqc_status', header: 'UQC status' },
    { key: 'rate', header: 'Rate %', right: true },
    { key: 'quantity', header: 'Qty', right: true },
    { key: 'taxable', header: 'Taxable', right: true },
    { key: 'total_value', header: 'Total value', right: true }
  ];

  return (
    <div className="flex flex-col gap-6">
      <Card
        title="HSN summary — outward"
        subtitle="Recomputed from line items. Every row is checked against the stored GSTN master and the portal's unit codes."
        action={
          outward.unfilable_row_count > 0
            ? <span className="text-xs font-semibold text-[#8f1d1d]">{outward.unfilable_row_count} row(s) would be rejected</span>
            : <span className="text-xs text-emerald-700">every row filable</span>
        }
      >
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">B2B</p>
        <RowTable rows={outward.b2b} onDrill={onDrill} label="this HSN row" empty="Nothing to summarise." columns={outwardColumns} />
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mt-6 mb-2">B2C</p>
        <RowTable rows={outward.b2c} onDrill={onDrill} label="this HSN row" empty="Nothing to summarise." columns={outwardColumns} />
      </Card>

      <Card title="HSN summary — inward" subtitle={inward.note}>
        {inward.rows_without_uqc > 0 && (
          <div className="mb-4">
            <Note tone="warn">
              {inward.rows_without_uqc} row(s) have no unit quantity code, and{' '}
              {inward.rows_without_known_hsn} have no HSN the portal recognises. Inward lines
              carry the supplier's pack column, not a UQC.
            </Note>
          </div>
        )}
        <RowTable
          rows={inward.rows}
          onDrill={onDrill}
          label="this HSN row"
          empty="No inward lines in this period."
          columns={[
            { key: 'hsn', header: 'HSN', mono: true },
            { key: 'description', header: 'Description' },
            { key: 'uqc', header: 'UQC' },
            { key: 'pack_as_printed', header: 'Pack as printed' },
            { key: 'rate', header: 'Rate %', right: true },
            { key: 'quantity', header: 'Qty', right: true },
            { key: 'line_count', header: 'Lines', right: true },
            { key: 'taxable', header: 'Taxable', right: true }
          ]}
        />
      </Card>
    </div>
  );
};

// ---------------------------------------------------------- document series

export const DocumentSeriesReport: React.FC<{ pack: Pack; onDrill: OnDrill }> = ({ pack, onDrill }) => {
  const report = pack.reports.document_series;
  return (
    <Card
      title="Table 13 — documents issued"
      subtitle="The portal cross-checks these counts against the document tables, so a cancelled bill is reported rather than removed."
    >
      {(report.has_gaps || report.has_duplicates) && (
        <div className="mb-4">
          <Note tone="bad">
            {report.has_gaps && <p><strong>A series has a gap.</strong> Either a bill was issued on a device and never synced — in which case this return is missing its supplies — or a number was skipped.</p>}
            {report.has_duplicates && <p className="mt-1"><strong>A number is used twice.</strong> Rule 46(b) makes a serial unique within the financial year, and two bills sharing one are indistinguishable in a return.</p>}
          </Note>
        </div>
      )}
      <RowTable
        rows={report.rows}
        onDrill={onDrill}
        label="this series"
        empty="No numbered documents in this period."
        columns={[
          { key: 'series_prefix', header: 'Series', mono: true },
          { key: 'opening_number', header: 'From' },
          { key: 'closing_number', header: 'To' },
          { key: 'total_issued', header: 'Issued', right: true },
          { key: 'cancelled', header: 'Cancelled', right: true },
          { key: 'net_issued', header: 'Net', right: true },
          { key: 'gaps', header: 'Gaps' },
          { key: 'duplicates', header: 'Duplicates' }
        ]}
      />
    </Card>
  );
};

// -------------------------------------------------------------- reversals

export const ItcReversalsReport: React.FC<{ pack: Pack; onDrill: OnDrill }> = ({ pack, onDrill }) => {
  const report = pack.reports.itc_reversals;
  return (
    <Card title="ITC reversal register" subtitle={report.note}>
      <RowTable
        rows={report.rows}
        onDrill={onDrill}
        label="this reversal"
        empty="No credit has been reversed in this period."
        columns={[
          { key: 'tax_period', header: 'Period' },
          { key: 'trigger', header: 'Trigger' },
          { key: 'statutory_reference', header: 'Provision' },
          { key: 'gstr3b_table', header: '3B table' },
          { key: 'source_invoice_number', header: 'Source invoice' },
          { key: 'reason', header: 'Reason' },
          { key: 'cgst', header: 'CGST', right: true },
          { key: 'sgst', header: 'SGST', right: true },
          { key: 'igst', header: 'IGST', right: true },
          { key: 'total', header: 'Total', right: true }
        ]}
      />
      <div className="mt-4 flex flex-wrap gap-6 text-xs text-gray-600">
        <span>Permanent — 4(B)(1): <Amount figure={report.totals.permanent} bold /></span>
        <span>Temporary — 4(B)(2): <Amount figure={report.totals.temporary} bold /></span>
        <span>Reclaimed — 4(D)(1): <Amount figure={report.totals.reclaimed} bold /></span>
      </div>
    </Card>
  );
};
