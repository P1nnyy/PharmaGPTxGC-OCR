import React from 'react';

import { Card, Empty, Money, Table, Td, Th } from './Primitives';
import type { Gstr1Return } from '../types';

const percent = (rate: number) => `${rate % 1 === 0 ? rate.toFixed(0) : rate}%`;

/** Table 7. The one that matters most for a counter pharmacy - almost every
 *  supply it makes lands here. */
const B2cs: React.FC<{ data: Gstr1Return['tables'] }> = ({ data }) => (
  <Card
    title="Table 7 — B2CS"
    subtitle="Supplies to unregistered customers, aggregated by place of supply and rate. Customer returns are netted in."
  >
    {data.b2cs.length === 0 && data.b2cs_negative.length === 0 ? (
      <Empty>No supplies to unregistered customers in this period.</Empty>
    ) : (
      <>
        <Table
          head={
            <>
              <Th>Place of supply</Th>
              <Th>Type</Th>
              <Th right>Rate</Th>
              <Th right>Taxable</Th>
              <Th right>CGST</Th>
              <Th right>SGST</Th>
              <Th right>IGST</Th>
              <Th right>Bills</Th>
            </>
          }
        >
          {data.b2cs.map((row) => (
            <tr key={`${row.place_of_supply}-${row.supply_type}-${row.rate}`}>
              <Td>{row.place_of_supply}</Td>
              <Td>{row.supply_type === 'INTRA' ? 'Intra-state' : 'Inter-state'}</Td>
              <Td right>{percent(row.rate)}</Td>
              <Td right><Money value={row.taxable} /></Td>
              <Td right><Money value={row.cgst} muted /></Td>
              <Td right><Money value={row.sgst} muted /></Td>
              <Td right><Money value={row.igst} muted /></Td>
              <Td right>{row.document_ids.length}</Td>
            </tr>
          ))}
        </Table>

        {data.b2cs_negative.length > 0 && (
          <div className="mt-6 rounded-xl border border-[#f3c9c9] bg-[#fdecec] p-4">
            <p className="text-xs font-semibold text-[#8f1d1d] mb-2">
              Withheld: returns exceeded sales
            </p>
            <p className="text-[11px] text-[#8f1d1d] mb-3 leading-relaxed">
              These buckets are not in the return. The portal will not accept a negative
              aggregate — the credit note belongs against the period the original sale was
              in, as an amendment.
            </p>
            <Table
              head={
                <>
                  <Th>Place of supply</Th>
                  <Th>Type</Th>
                  <Th right>Rate</Th>
                  <Th right>Taxable</Th>
                </>
              }
            >
              {data.b2cs_negative.map((row) => (
                <tr key={`neg-${row.place_of_supply}-${row.supply_type}-${row.rate}`}>
                  <Td>{row.place_of_supply}</Td>
                  <Td>{row.supply_type === 'INTRA' ? 'Intra-state' : 'Inter-state'}</Td>
                  <Td right>{percent(row.rate)}</Td>
                  <Td right><Money value={row.taxable} /></Td>
                </tr>
              ))}
            </Table>
          </div>
        )}
      </>
    )}
  </Card>
);

const InvoiceTable: React.FC<{
  title: string;
  subtitle: string;
  rows: Gstr1Return['tables']['b2b'];
  empty: string;
  showCustomer?: boolean;
}> = ({ title, subtitle, rows, empty, showCustomer }) => (
  <Card title={title} subtitle={subtitle}>
    {rows.length === 0 ? (
      <Empty>{empty}</Empty>
    ) : (
      <Table
        head={
          <>
            <Th>Bill</Th>
            <Th>Date</Th>
            {showCustomer && <Th>Customer</Th>}
            <Th>Place of supply</Th>
            <Th right>Invoice value</Th>
          </>
        }
      >
        {rows.map((row) => (
          <tr key={row.document_id}>
            <Td>{row.bill_number ?? '—'}</Td>
            <Td>{row.sale_date}</Td>
            {showCustomer && (
              <Td>
                <span className="font-mono text-xs">{row.customer_gstin}</span>
                {row.customer_name && (
                  <span className="block text-[11px] text-gray-500">{row.customer_name}</span>
                )}
              </Td>
            )}
            <Td>{row.place_of_supply}</Td>
            <Td right><Money value={row.invoice_value} /></Td>
          </tr>
        ))}
      </Table>
    )}
  </Card>
);

const NilExempt: React.FC<{ rows: Gstr1Return['tables']['nil_exempt'] }> = ({ rows }) => (
  <Card
    title="Table 8 — nil rated, exempted and non-GST"
    subtitle="Material for a pharmacy: the notified life-saving drugs are nil rated, which is not the same as exempt."
  >
    <Table
      head={
        <>
          <Th />
          <Th>Supplies</Th>
          <Th right>Nil rated</Th>
          <Th right>Exempted</Th>
          <Th right>Non-GST</Th>
          <Th right>Total</Th>
        </>
      }
    >
      {rows.map((row) => (
        <tr key={row.code}>
          <Td className="font-semibold text-gray-500">{row.code}</Td>
          <Td>{row.description}</Td>
          <Td right><Money value={row.nil_rated} muted /></Td>
          <Td right><Money value={row.exempted} muted /></Td>
          <Td right><Money value={row.non_gst} muted /></Td>
          <Td right><Money value={row.total} /></Td>
        </tr>
      ))}
    </Table>
  </Card>
);

const HsnSection: React.FC<{ label: string; rows: Gstr1Return['tables']['hsn']['b2c'] }> = ({
  label,
  rows
}) => (
  <div>
    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{label}</p>
    {rows.length === 0 ? (
      <Empty>Nothing to summarise.</Empty>
    ) : (
      <Table
        head={
          <>
            <Th>HSN</Th>
            <Th>UQC</Th>
            <Th right>Rate</Th>
            <Th right>Quantity</Th>
            <Th right>Taxable</Th>
            <Th right>CGST</Th>
            <Th right>SGST</Th>
            <Th right>IGST</Th>
            <Th right>Total value</Th>
          </>
        }
      >
        {rows.map((row) => (
          <tr key={`${row.hsn}-${row.uqc}-${row.rate}`}>
            <Td className="font-mono text-xs">{row.hsn}</Td>
            <Td>
              {row.uqc ?? <span className="text-[#8f1d1d] font-semibold">missing</span>}
            </Td>
            <Td right>{percent(row.rate)}</Td>
            <Td right className="tabular-nums">{row.quantity}</Td>
            <Td right><Money value={row.taxable} /></Td>
            <Td right><Money value={row.cgst} muted /></Td>
            <Td right><Money value={row.sgst} muted /></Td>
            <Td right><Money value={row.igst} muted /></Td>
            <Td right><Money value={row.total_value} /></Td>
          </tr>
        ))}
      </Table>
    )}
  </div>
);

const Hsn: React.FC<{ hsn: Gstr1Return['tables']['hsn']; digits: number }> = ({ hsn, digits }) => (
  <Card
    title="Table 12 — HSN summary"
    subtitle={`Recomputed from line items, never from a stored total. This shop reports HSN at ${digits} digits.`}
  >
    <div className="flex flex-col gap-6">
      <HsnSection label="B2B" rows={hsn.b2b} />
      <HsnSection label="B2C" rows={hsn.b2c} />
    </div>
  </Card>
);

const DocumentsIssued: React.FC<{ rows: Gstr1Return['tables']['documents_issued'] }> = ({ rows }) => (
  <Card
    title="Table 13 — documents issued"
    subtitle="The portal cross-checks these counts against the tables above, so a cancelled bill is reported rather than removed."
  >
    {rows.length === 0 ? (
      <Empty>No numbered documents in this period.</Empty>
    ) : (
      <Table
        head={
          <>
            <Th>Series</Th>
            <Th>From</Th>
            <Th>To</Th>
            <Th right>Issued</Th>
            <Th right>Cancelled</Th>
            <Th right>Net</Th>
            <Th>Gaps</Th>
            <Th>Duplicates</Th>
          </>
        }
      >
        {rows.map((row) => (
          <tr key={row.series_prefix}>
            <Td className="font-mono text-xs">{row.series_prefix}</Td>
            <Td>{row.opening_number ?? '—'}</Td>
            <Td>{row.closing_number ?? '—'}</Td>
            <Td right>{row.total_issued}</Td>
            <Td right>{row.cancelled}</Td>
            <Td right>{row.net_issued}</Td>
            <Td>
              {row.gaps.length === 0 ? (
                <span className="text-gray-300">none</span>
              ) : (
                <span className="font-semibold" style={{ color: '#8f1d1d' }}>
                  {row.gaps.slice(0, 8).join(', ')}
                  {row.gaps.length > 8 ? ` +${row.gaps.length - 8} more` : ''}
                </span>
              )}
            </Td>
            <Td>
              {row.duplicates.length === 0 ? (
                <span className="text-gray-300">none</span>
              ) : (
                <span className="font-semibold" style={{ color: '#8f1d1d' }}>
                  {row.duplicates.slice(0, 8).join(', ')}
                  {row.duplicates.length > 8 ? ` +${row.duplicates.length - 8} more` : ''}
                </span>
              )}
            </Td>
          </tr>
        ))}
      </Table>
    )}
  </Card>
);

export const ReturnTables: React.FC<{ data: Gstr1Return }> = ({ data }) => (
  <div className="flex flex-col gap-6">
    <B2cs data={data.tables} />
    <InvoiceTable
      title="Table 4A — B2B"
      subtitle="Supplies to registered persons. For a pharmacy this is usually expired stock returned to a distributor on its own outward invoice."
      rows={data.tables.b2b}
      empty="No supplies to registered persons in this period."
      showCustomer
    />
    <InvoiceTable
      title="Table 5 — B2CL"
      subtitle="Inter-state supplies to consumers above ₹2,50,000. An over-the-counter sale is supplied where the counter is, so anything here is worth a second look."
      rows={data.tables.b2cl}
      empty="Nothing qualifies — which is what you would expect for a counter pharmacy."
    />
    <NilExempt rows={data.tables.nil_exempt} />
    <Hsn hsn={data.tables.hsn} digits={data.shop.hsn_digits} />
    <DocumentsIssued rows={data.tables.documents_issued} />
  </div>
);
