import React, { useState, useEffect } from 'react';
import { BarChart3, TrendingUp, PieChart, FileSpreadsheet, Download, FileText } from 'lucide-react';

interface ReportInvoice {
  run_id: string;
  invoice_number?: string;
  invoice_date?: string;
  seller_name?: string;
  subtotal: number;
  discount: number;
  cgst: number;
  sgst: number;
  igst: number;
  grand_total: number;
}

const getLast6Months = () => {
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const result = [];
  const date = new Date();
  for (let i = 5; i >= 0; i--) {
    const d = new Date(date.getFullYear(), date.getMonth() - i, 1);
    result.push({
      key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      label: months[d.getMonth()]
    });
  }
  return result;
};

const COLORS = ['bg-blue-500', 'bg-indigo-500', 'bg-purple-500', 'bg-emerald-500', 'bg-amber-500'];

export const ReportsPage: React.FC = () => {
  const [verifiedInvoices, setVerifiedInvoices] = useState<ReportInvoice[]>([]);
  const [last6Months] = useState(getLast6Months);

  useEffect(() => {
    try {
      const storedRuns = localStorage.getItem('ocr_workbench_runs');
      if (storedRuns) {
        const parsedRuns = JSON.parse(storedRuns);
        const verifiedRuns = parsedRuns.filter((r: any) => r.status === 'verified');
        
        const detailedInvoices: ReportInvoice[] = [];
        verifiedRuns.forEach((run: any) => {
          const detailStr = localStorage.getItem(`ocr_workbench_run_detail_${run.run_id}`);
          if (detailStr) {
            try {
              const detail = JSON.parse(detailStr);
              
              // Estimate CGST/SGST if missing or zero, but line items are present
              let cgst = parseFloat(detail.cgst ?? detail.metadata?.tax?.cgst ?? 0);
              let sgst = parseFloat(detail.sgst ?? detail.metadata?.tax?.sgst ?? 0);
              let igst = parseFloat(detail.igst ?? detail.metadata?.tax?.igst ?? 0);
              
              if (cgst === 0 && sgst === 0 && igst === 0 && detail.line_items) {
                const totalTax = detail.line_items.reduce(
                  (sum: number, item: any) => sum + (parseFloat(item.amount || 0) * parseFloat(item.gst_percent || 0)) / 100,
                  0
                );
                cgst = parseFloat((totalTax / 2).toFixed(2));
                sgst = parseFloat((totalTax / 2).toFixed(2));
              }

              detailedInvoices.push({
                run_id: run.run_id,
                invoice_number: detail.invoice_number,
                invoice_date: detail.invoice_date,
                seller_name: detail.seller_name,
                subtotal: parseFloat(detail.subtotal || 0),
                discount: parseFloat(detail.discount || 0),
                cgst,
                sgst,
                igst,
                grand_total: parseFloat(detail.grand_total || 0)
              });
            } catch (e) {
              console.error(`Failed to parse run detail for report calculations: ${run.run_id}`, e);
            }
          }
        });
        setVerifiedInvoices(detailedInvoices);
      }
    } catch (err) {
      console.error('Failed to load reports metrics data:', err);
    }
  }, []);

  // 1. Monthly Trends
  const spendMap: Record<string, number> = {};
  verifiedInvoices.forEach((inv) => {
    if (inv.invoice_date) {
      const key = inv.invoice_date.substring(0, 7); // 'YYYY-MM'
      spendMap[key] = (spendMap[key] || 0) + inv.grand_total;
    }
  });

  const monthlyData = last6Months.map((m) => ({
    label: m.label,
    spend: spendMap[m.key] || 0
  }));

  const totalSpend = monthlyData.reduce((sum, d) => sum + d.spend, 0);
  const activeMonthsCount = monthlyData.filter((d) => d.spend > 0).length || 1;
  const avgMonthlySpend = totalSpend / activeMonthsCount;
  const maxMonthSpend = Math.max(...monthlyData.map((d) => d.spend), 100);

  // 2. Vendor Wise Purchase
  const vendorMap: Record<string, number> = {};
  verifiedInvoices.forEach((inv) => {
    const name = inv.seller_name?.trim() || 'Unknown Supplier';
    vendorMap[name] = (vendorMap[name] || 0) + inv.grand_total;
  });

  const vendorData = Object.entries(vendorMap)
    .map(([name, amt]) => ({
      name,
      amt,
      share: totalSpend > 0 ? Math.round((amt / totalSpend) * 100) : 0
    }))
    .sort((a, b) => b.amt - a.amt);

  // 3. Tax and GST summaries
  let cgstTotal = 0;
  let sgstTotal = 0;
  let igstTotal = 0;
  let taxableSubtotal = 0;
  let totalDiscounts = 0;
  let grossPurchases = 0;

  verifiedInvoices.forEach((inv) => {
    cgstTotal += inv.cgst;
    sgstTotal += inv.sgst;
    igstTotal += inv.igst;
    taxableSubtotal += inv.subtotal;
    totalDiscounts += inv.discount;
    grossPurchases += inv.grand_total;
  });

  // Export actions
  const handleExportCSV = (filename: string) => {
    if (verifiedInvoices.length === 0) {
      alert('No verified invoices available to export.');
      return;
    }
    let csvContent = 'data:text/csv;charset=utf-8,';
    csvContent += 'Date,Invoice #,Seller,Subtotal,Discount,CGST,SGST,IGST,Grand Total\n';
    
    verifiedInvoices.forEach((inv) => {
      const row = [
        inv.invoice_date || 'N/A',
        `"${(inv.invoice_number || '').replace(/"/g, '""')}"`,
        `"${(inv.seller_name || '').replace(/"/g, '""')}"`,
        inv.subtotal,
        inv.discount,
        inv.cgst,
        inv.sgst,
        inv.igst,
        inv.grand_total
      ].join(',');
      csvContent += row + '\n';
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Title Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-[#0f172a] tracking-tight">Analytics &amp; Purchasing Reports</h2>
          <p className="text-gray-500 text-sm">Analyze pharmacy spend summaries, supplier tax distributions, and GST breakdowns.</p>
        </div>
        <button
          onClick={() => handleExportCSV('PharmaGPT_Full_Purchase_Audit.csv')}
          disabled={verifiedInvoices.length === 0}
          className="bg-[#1b5dfc] hover:bg-[#154ecb] disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed text-white font-semibold px-4 py-2.5 rounded-xl text-xs flex items-center space-x-1.5 shadow-md shadow-blue-500/10 transition-colors cursor-pointer"
        >
          <FileSpreadsheet size={14} />
          <span>Export Full Audit</span>
        </button>
      </div>

      {verifiedInvoices.length === 0 ? (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] p-12 text-center space-y-4">
          <FileText size={48} className="text-gray-300 mx-auto" />
          <h3 className="text-lg font-bold text-[#0f172a]">No Reports Data Available</h3>
          <p className="text-gray-500 text-sm max-w-md mx-auto">
            Real-time analytics and ledger reconciliations will generate dynamically once you upload invoices, complete OCR structure audits, and mark them as verified.
          </p>
        </div>
      ) : (
        <>
          {/* Analytics highlights grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Monthly spend card */}
            <div className="bg-white p-6 rounded-2xl border border-[#e2e8f0] shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-[#0f172a] flex items-center space-x-2">
                  <TrendingUp size={16} className="text-[#1b5dfc]" />
                  <span>Monthly Purchase Trends</span>
                </h3>
              </div>

              <div className="h-32 flex items-end justify-between gap-2 border-b border-gray-100 pb-2">
                {monthlyData.map((val, idx) => (
                  <div key={idx} className="flex-1 flex flex-col items-center">
                    <div 
                      className="w-full bg-blue-500 rounded-t-sm transition-all duration-300" 
                      style={{ height: `${(val.spend / maxMonthSpend) * 100}%` }} 
                      title={`₹${val.spend.toFixed(2)}`}
                    />
                    <span className="text-[9px] text-gray-400 mt-1 font-mono">
                      {val.label}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-gray-500">Average Monthly Spend:</span>
                <strong className="text-gray-900">₹{avgMonthlySpend.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
              </div>
            </div>

            {/* Vendor wise purchase card */}
            <div className="bg-white p-6 rounded-2xl border border-[#e2e8f0] shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-[#0f172a] flex items-center space-x-2">
                  <PieChart size={16} className="text-indigo-600" />
                  <span>Vendor-Wise Purchase</span>
                </h3>
                <span className="text-[10px] text-gray-400 font-medium">{vendorData.length} Active Vendors</span>
              </div>

              <div className="space-y-3 py-2 max-h-[140px] overflow-y-auto custom-scrollbar">
                {vendorData.slice(0, 3).map((vendor, idx) => {
                  const color = COLORS[idx % COLORS.length];
                  return (
                    <div key={idx} className="space-y-1.5">
                      <div className="flex justify-between text-xs font-medium">
                        <span className="text-gray-700 truncate max-w-[150px]">{vendor.name}</span>
                        <span className="text-gray-900 font-bold">₹{vendor.amt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                      </div>
                      <div className="w-full bg-[#f1f2f6] h-2 rounded-full overflow-hidden flex">
                        <div className={`${color} h-full transition-all duration-500`} style={{ width: `${vendor.share}%` }} />
                      </div>
                      <div className="text-[9px] text-gray-400 text-right">{vendor.share}% of total spend</div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* GST summary card */}
            <div className="bg-white p-6 rounded-2xl border border-[#e2e8f0] shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-[#0f172a] flex items-center space-x-2">
                  <BarChart3 size={16} className="text-emerald-600" />
                  <span>Tax &amp; GST Summary</span>
                </h3>
                <span className="text-[10px] text-green-600 bg-green-50 px-2 py-0.5 rounded-full font-semibold">Verified</span>
              </div>

              <div className="space-y-3 py-2">
                {[
                  { slab: 'CGST Total', value: `₹${cgstTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, desc: 'Central GST portion' },
                  { slab: 'SGST Total', value: `₹${sgstTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, desc: 'State GST portion' },
                  { slab: 'IGST Total', value: `₹${igstTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, desc: 'Interstate GST portion' },
                  { slab: 'Taxable Subtotal', value: `₹${taxableSubtotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, desc: 'Net Taxable Goods' }
                ].map((tax, idx) => (
                  <div key={idx} className="flex justify-between items-center p-2 bg-[#f8fafc] rounded-xl border border-gray-100">
                    <div>
                      <span className="text-xs font-semibold text-gray-700 block">{tax.slab}</span>
                      <span className="text-[9px] text-gray-400 block">{tax.desc}</span>
                    </div>
                    <strong className="text-xs text-gray-900 font-mono font-bold">{tax.value}</strong>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Ledger preview listing */}
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <h3 className="text-base font-bold text-[#0f172a]">Ledger Reconciliation</h3>
              <button
                onClick={() => handleExportCSV('PharmaGPT_Ledger_Reconciliation.csv')}
                className="text-xs font-semibold text-[#1b5dfc] hover:text-[#154ecb] flex items-center space-x-1 cursor-pointer"
              >
                <Download size={14} />
                <span>Save Ledger CSV</span>
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
              <div className="p-4 bg-slate-50 border border-slate-100 rounded-xl space-y-2">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Gross Purchases</span>
                <strong className="text-xl font-bold text-gray-900 block">₹{grossPurchases.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                <p className="text-[10px] text-gray-500 leading-normal">Sum total value of all invoices received.</p>
              </div>
              <div className="p-4 bg-slate-50 border border-slate-100 rounded-xl space-y-2">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Total Discounts</span>
                <strong className="text-xl font-bold text-green-600 block">₹{totalDiscounts.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                <p className="text-[10px] text-gray-500 leading-normal">Calculated trade and scheme savings.</p>
              </div>
              <div className="p-4 bg-slate-50 border border-slate-100 rounded-xl space-y-2">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Total Taxes Paid</span>
                <strong className="text-xl font-bold text-gray-900 block">₹{(cgstTotal + sgstTotal + igstTotal).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                <p className="text-[10px] text-gray-500 leading-normal">Accumulated CGST + SGST + IGST tax payouts.</p>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default ReportsPage;
