/**
 * The issued bill, as a Rule 46A invoice-cum-bill-of-supply.
 *
 * Rule 46A is the right document for a pharmacy counter specifically because a
 * basket routinely mixes taxable medicine with exempt items, and supplying
 * both to an unregistered person on one document is exactly what 46A permits.
 * It is why the exempt value is a first-class figure throughout this feature
 * rather than a special case of zero-rated tax.
 *
 * The particulars below are the ones Rule 46 requires and 46A carries over:
 * supplier identity and GSTIN, a consecutive serial, the date, HSN per line,
 * quantity, taxable value, the rate and amount of tax, and the place of
 * supply. A field the shop has not filled in prints as a blank rather than
 * being omitted, so a missing statutory particular is visible on the bill
 * instead of silently absent.
 */

import React from 'react';
import { MessageCircle, Plus, Printer } from 'lucide-react';

import { formatPaise } from '../money';
import type { ShopProfile } from '../api';
import type { IssuedBill } from '../types';

type RollWidth = '58' | '80';

/** `2026-11-30` to `11/26`. Month precision is what a pack carries, and the
 *  full ISO date does not fit a 48mm roll without wrapping. */
function shortExpiry(expiry: string | null): string {
  if (!expiry) return '—';
  const [year, month] = expiry.split('-');
  if (!year || !month) return expiry;
  return `${month}/${year.slice(-2)}`;
}

/** Bill as plain text, for the WhatsApp share. */
function asText(bill: IssuedBill, shop: ShopProfile | null): string {
  const lines: string[] = [];
  lines.push(shop?.trade_name || shop?.legal_name || 'Pharmacy');
  lines.push(`Bill ${bill.serial} · ${bill.issued_at.slice(0, 10)}`);
  lines.push('');
  bill.lines.forEach((line, index) => {
    const computed = bill.computed[index];
    lines.push(`${line.product_name} x${line.quantity} — ${formatPaise(computed?.line_total_paise ?? null)}`);
  });
  lines.push('');
  lines.push(`Taxable ${formatPaise(bill.totals.taxable_paise)}`);
  lines.push(`CGST ${formatPaise(bill.totals.cgst_paise)}  SGST ${formatPaise(bill.totals.sgst_paise)}`);
  if ((bill.totals.exempt_paise ?? 0) > 0) lines.push(`Exempt ${formatPaise(bill.totals.exempt_paise)}`);
  lines.push(`TOTAL ${formatPaise(bill.totals.grand_total_paise)}`);
  return lines.join('\n');
}

export const BillPreview: React.FC<{
  bill: IssuedBill;
  shop: ShopProfile | null;
  onNewBill: () => void;
}> = ({ bill, shop, onNewBill }) => {
  const [width, setWidth] = React.useState<RollWidth>('80');

  const shareHref = `https://wa.me/${bill.customer_phone ? bill.customer_phone.replace(/\D/g, '') : ''}?text=${encodeURIComponent(asText(bill, shop))}`;

  return (
    <>
      {/* `@page` cannot be driven by a class, so the selected roll size is
          injected as its own rule and replaced when the width changes. */}
      <style>{`@page { size: ${width}mm auto; margin: 0; }`}</style>

      <div className="bill-no-print flex flex-wrap items-center gap-2 mb-3">
        <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-xl p-1">
          {(['58', '80'] as RollWidth[]).map((option) => (
            <button
              key={option}
              onClick={() => setWidth(option)}
              aria-pressed={width === option}
              className={`px-3 py-1.5 rounded-lg text-[11px] font-bold transition-colors cursor-pointer ${
                width === option ? 'bg-[#1b5dfc] text-white' : 'text-gray-500 hover:bg-slate-50'
              }`}
            >
              {option}mm
            </button>
          ))}
        </div>

        <button
          onClick={() => window.print()}
          className="flex items-center gap-1.5 bg-[#0f172a] hover:bg-slate-800 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md cursor-pointer"
        >
          <Printer size={14} /> Print
        </button>

        <a
          href={shareHref}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 bg-[#25D366] hover:bg-[#1eb355] text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md cursor-pointer"
        >
          <MessageCircle size={14} /> WhatsApp
        </a>

        <button
          onClick={onNewBill}
          className="flex items-center gap-1.5 bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm cursor-pointer ml-auto"
        >
          <Plus size={14} /> New bill
        </button>
      </div>

      <div className="bill-print-root bg-white border border-gray-200 rounded-2xl p-4 overflow-x-auto">
        <div className={`bill-roll roll-${width}`}>
          <div className="bill-centre bill-bold">
            {shop?.trade_name || shop?.legal_name || 'PHARMACY'}
          </div>
          {shop?.legal_name && shop?.trade_name && shop.legal_name !== shop.trade_name && (
            <div className="bill-centre">{shop.legal_name}</div>
          )}
          <div className="bill-centre">
            {[shop?.address_line1, shop?.address_line2].filter(Boolean).join(', ')}
          </div>
          <div className="bill-centre">
            {[shop?.city, shop?.pincode].filter(Boolean).join(' - ')}
          </div>
          {shop?.phone && <div className="bill-centre">Ph: {shop.phone}</div>}
          <div className="bill-centre">GSTIN: {shop?.gstin || '________'}</div>
          {shop?.drug_licence_number && (
            <div className="bill-centre">D.L. No: {shop.drug_licence_number}</div>
          )}

          <hr className="bill-rule" />
          <div className="bill-centre bill-bold">INVOICE-CUM-BILL OF SUPPLY</div>
          <div className="bill-centre" style={{ fontSize: '0.85em' }}>
            (Rule 46A, CGST Rules 2017)
          </div>
          <hr className="bill-rule" />

          <div>No: {bill.serial}</div>
          <div>Date: {bill.issued_at.slice(0, 10)}</div>
          <div>Customer: {bill.customer_name || 'Cash'}</div>
          {bill.customer_phone && <div>Phone: {bill.customer_phone}</div>}
          {/* Place of supply is a required particular; for a counter sale it is
              the shop's own state, since the customer takes the goods here. */}
          <div>
            Place of supply: {shop?.state || '________'}
            {shop?.state_code ? ` (${shop.state_code})` : ''}
          </div>

          <hr className="bill-rule" />

          {/* Two columns, not four. A 72mm roll cannot hold item, quantity,
              rate and amount side by side without the numbers running into
              each other, and 48mm has no chance - so the quantity and rate sit
              on their own line and only the amount keeps a column. */}
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {bill.lines.map((line, index) => {
                const computed = bill.computed[index];
                return (
                  <React.Fragment key={line.line_id}>
                    <tr>
                      <td className="bill-name" colSpan={2}>
                        {line.product_name}
                      </td>
                    </tr>
                    <tr>
                      <td className="bill-meta" colSpan={2}>
                        HSN {line.hsn || '—'} · B/{line.batch_number || '—'} · Exp{' '}
                        {shortExpiry(line.expiry)}
                      </td>
                    </tr>
                    <tr>
                      <td>
                        {line.quantity} &times; {formatPaise(line.unit_price_paise)}
                      </td>
                      <td className="num">{formatPaise(computed?.line_total_paise ?? null)}</td>
                    </tr>
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>

          <hr className="bill-rule" />

          {/* One row per rate block, which is what makes the tax on the bill
              tie back to the return it will be summarised into. */}
          <table>
            <tbody>
              {bill.totals.blocks.map((block) => (
                <tr key={`${block.supply_kind}-${block.rate_bp}`}>
                  <td>
                    {block.supply_kind === 'exempt' ? 'Exempt' : `Taxable @ ${block.rate_bp / 100}%`}
                  </td>
                  <td className="num">
                    {formatPaise(
                      block.supply_kind === 'exempt' ? block.exempt_paise : block.taxable_paise
                    )}
                  </td>
                  <td className="num">
                    {block.supply_kind === 'exempt'
                      ? '—'
                      : formatPaise(block.cgst_paise + block.sgst_paise)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <hr className="bill-rule" />

          <table>
            <tbody>
              <tr>
                <td>Taxable value</td>
                <td className="num">{formatPaise(bill.totals.taxable_paise)}</td>
              </tr>
              <tr>
                <td>CGST</td>
                <td className="num">{formatPaise(bill.totals.cgst_paise)}</td>
              </tr>
              <tr>
                <td>SGST</td>
                <td className="num">{formatPaise(bill.totals.sgst_paise)}</td>
              </tr>
              {(bill.totals.exempt_paise ?? 0) > 0 && (
                <tr>
                  <td>Exempt value</td>
                  <td className="num">{formatPaise(bill.totals.exempt_paise)}</td>
                </tr>
              )}
              <tr>
                <td>Round off</td>
                <td className="num">{formatPaise(bill.totals.round_off_paise)}</td>
              </tr>
              <tr className="bill-bold">
                <td>GRAND TOTAL</td>
                <td className="num">{formatPaise(bill.totals.grand_total_paise)}</td>
              </tr>
            </tbody>
          </table>

          <hr className="bill-rule" />

          <table>
            <tbody>
              {bill.payments.map((payment) => (
                <tr key={payment.method}>
                  <td style={{ textTransform: 'uppercase' }}>
                    {payment.method}
                    {payment.reference ? ` (${payment.reference})` : ''}
                  </td>
                  <td className="num">{formatPaise(payment.amount_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {bill.prescription_image_ref && (
            <>
              <hr className="bill-rule" />
              <div style={{ fontSize: '0.85em' }}>Prescription on file: {bill.prescription_image_ref}</div>
            </>
          )}

          <hr className="bill-rule" />
          <div className="bill-centre" style={{ fontSize: '0.85em' }}>
            E. &amp; O.E. · Goods once sold are returnable only per policy
          </div>
          <div style={{ marginTop: '6mm' }} className="bill-right">
            For {shop?.trade_name || shop?.legal_name || 'Pharmacy'}
          </div>
          <div style={{ marginTop: '8mm' }} className="bill-right" >
            Authorised Signatory
          </div>
        </div>
      </div>
    </>
  );
};
