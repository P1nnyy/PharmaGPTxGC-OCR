import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { getDetailsData } from '../api/client';
import {
  Search,
  Download,
  Trash2,
  Eye,
  ChevronLeft,
  ChevronRight,
  DollarSign,
  AlertCircle,
  Package,
  MoreVertical
} from 'lucide-react';

export const InvoiceHistoryPage: React.FC = () => {
  const { runs } = useRun();
  const navigate = useNavigate();

  // Search & Filter State
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sellerFilter, setSellerFilter] = useState('all');
  const [selectedInvoices, setSelectedInvoices] = useState<string[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 8;

  // Extract unique sellers for filter list
  const getSellers = () => {
    const sellers = new Set<string>();
    runs.forEach((r) => {
      const detail = getDetailsData(r.run_id);
      if (detail?.seller_name) {
        sellers.add(detail.seller_name);
      } else {
        const isGenome = r.filename.toLowerCase().includes('genome');
        sellers.add(isGenome ? 'Genome Pharmaceuticals' : 'Shivam Drugs House');
      }
    });
    return Array.from(sellers);
  };

  const sellers = getSellers();

  // Handle Select All checkbox
  const handleSelectAll = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.checked) {
      setSelectedInvoices(filteredRuns.map((r) => r.run_id));
    } else {
      setSelectedInvoices([]);
    }
  };

  // Handle single invoice selection
  const handleSelectInvoice = (runId: string, checked: boolean) => {
    if (checked) {
      setSelectedInvoices((prev) => [...prev, runId]);
    } else {
      setSelectedInvoices((prev) => prev.filter((id) => id !== runId));
    }
  };

  // Filtered invoices
  const filteredRuns = runs.filter((run) => {
    const detail = getDetailsData(run.run_id);
    const isGenome = run.filename.toLowerCase().includes('genome');
    const seller = detail?.seller_name || (isGenome ? 'Genome Pharmaceuticals' : 'Shivam Drugs House');
    const invoiceNum = detail?.invoice_number || run.filename;
    const matchesSearch =
      invoiceNum.toLowerCase().includes(searchTerm.toLowerCase()) ||
      seller.toLowerCase().includes(searchTerm.toLowerCase()) ||
      run.run_id.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesStatus =
      statusFilter === 'all' || 
      (statusFilter === 'verified' && run.status === 'verified') ||
      (statusFilter === 'safe_for_erp' && run.status === 'safe_for_erp') ||
      (statusFilter === 'needs_review' && (run.status === 'needs_review' || run.status === 'failed'));

    const matchesSeller =
      sellerFilter === 'all' || seller === sellerFilter;

    return matchesSearch && matchesStatus && matchesSeller;
  });

  // Pagination calculations
  const totalEntries = filteredRuns.length;
  const totalPages = Math.max(1, Math.ceil(totalEntries / itemsPerPage));
  const startIndex = (currentPage - 1) * itemsPerPage;
  const paginatedRuns = filteredRuns.slice(startIndex, startIndex + itemsPerPage);

  // Compute metrics totals
  const totalSpend = runs
    .filter((r) => r.status === 'verified')
    .reduce((sum, r) => {
      const detail = getDetailsData(r.run_id);
      return sum + (detail?.grand_total || 0);
    }, 0);

  const totalSKUsCount = (() => {
    try {
      const stored = localStorage.getItem('pharmaflow_inventory');
      if (stored) return JSON.parse(stored).length;
    } catch {}
    return 0;
  })();

  const pendingReviewCount = runs.filter((r) => r.status === 'needs_review' || r.status === 'failed').length;

  // Export history CSV mockup
  const handleExportCSV = () => {
    let csvContent = 'data:text/csv;charset=utf-8,';
    csvContent += 'Date,Invoice #,Seller,Amount,Status\n';
    filteredRuns.forEach((r) => {
      const detail = getDetailsData(r.run_id);
      const date = new Date(r.timestamp).toLocaleDateString();
      const isGenome = r.filename.toLowerCase().includes('genome');
      const seller = detail?.seller_name || (isGenome ? 'Genome Pharmaceuticals' : 'Shivam Drugs House');
      const amount = detail?.grand_total || (r.confidence ? r.confidence * 1500 : 0);
      const invoiceNum = detail?.invoice_number || r.filename;
      const row = [date, `"${invoiceNum.replace(/"/g, '""')}"`, `"${seller.replace(/"/g, '""')}"`, amount.toFixed(2), r.status].join(',');
      csvContent += row + '\n';
    });
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', 'PharmaFlow_Invoice_History.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Bulk Delete
  const handleBulkDelete = () => {
    if (selectedInvoices.length === 0) return;
    if (!window.confirm(`Are you sure you want to delete ${selectedInvoices.length} selected runs?`)) return;

    try {
      const storedRuns = localStorage.getItem('ocr_workbench_runs');
      if (storedRuns) {
        const parsed = JSON.parse(storedRuns);
        const remaining = parsed.filter((r: any) => !selectedInvoices.includes(r.run_id));
        localStorage.setItem('ocr_workbench_runs', JSON.stringify(remaining));

        // Clean up individual detail blocks too
        selectedInvoices.forEach((id) => {
          localStorage.removeItem(`ocr_workbench_run_detail_${id}`);
        });

        // Trigger reload by going back/refreshing context
        window.location.reload();
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-[#0f172a] tracking-tight">Invoice History</h2>
          <p className="text-gray-500 text-sm">View, search, and manage all pharmaceutical invoice extractions.</p>
        </div>
      </div>

      {/* Search and Filters Toolbar Card */}
      <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
          {/* Search Term */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Search Invoice</label>
            <div className="relative">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="ID, Seller or #"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl pl-9 pr-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors"
              />
            </div>
          </div>

          {/* Seller Filter */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Seller</label>
            <select
              value={sellerFilter}
              onChange={(e) => setSellerFilter(e.target.value)}
              className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors"
            >
              <option value="all">All Sellers</option>
              {sellers.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          {/* Status Filter */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Status</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors"
            >
              <option value="all">All Statuses</option>
              <option value="verified">Verified Only</option>
              <option value="needs_review">Needs Review</option>
            </select>
          </div>

          {/* Date range selection mock */}
          <div className="space-y-1">
            <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Date Range</label>
            <input
              type="text"
              disabled
              placeholder="Oct 01 - Oct 31, 2023"
              className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-3 py-2 text-xs text-gray-400 cursor-not-allowed"
            />
          </div>
        </div>
      </div>

      {/* Invoice Records Table Card */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden flex flex-col justify-between">
        
        {/* Table actions toolbar */}
        <div className="p-4 border-b border-[#e2e8f0] flex flex-col sm:flex-row items-center justify-between gap-4 bg-[#f8fafc]/50">
          <div className="flex items-center space-x-2">
            <h3 className="text-sm font-bold text-[#0f172a]">Invoice Records</h3>
            {selectedInvoices.length > 0 && (
              <span className="bg-blue-50 text-[#1b5dfc] text-[10px] font-bold px-2 py-0.5 rounded-full">
                {selectedInvoices.length} selected
              </span>
            )}
          </div>
          <div className="flex items-center space-x-2 w-full sm:w-auto">
            {selectedInvoices.length > 0 && (
              <button
                onClick={handleBulkDelete}
                className="bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 px-3 py-2 rounded-xl text-xs font-semibold flex items-center space-x-1.5 transition-colors cursor-pointer"
              >
                <Trash2 size={13} />
                <span>Bulk Action (Delete)</span>
              </button>
            )}
            <button
              onClick={handleExportCSV}
              className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-3 py-2 rounded-xl text-xs border border-gray-200 flex items-center space-x-1.5 shadow-sm transition-colors cursor-pointer"
            >
              <Download size={13} className="text-gray-500" />
              <span>Export CSV</span>
            </button>
          </div>
        </div>

        {/* Table View */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#f8fafc] border-b border-[#e2e8f0] text-gray-400 font-semibold text-[10px] uppercase tracking-wider">
                <th className="p-4 pl-6 w-[40px]">
                  <input
                    type="checkbox"
                    checked={paginatedRuns.length > 0 && selectedInvoices.length === paginatedRuns.length}
                    onChange={handleSelectAll}
                    className="w-4 h-4 rounded border-gray-300 text-blue-600 accent-blue-600 cursor-pointer"
                  />
                </th>
                <th className="p-4">Date</th>
                <th className="p-4">Invoice #</th>
                <th className="p-4">Seller</th>
                <th className="p-4 text-right">Amount</th>
                <th className="p-4 text-center">Status</th>
                <th className="p-4 text-center pr-6 w-[80px]">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0] text-xs text-gray-700 bg-white">
              {paginatedRuns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-16 text-gray-400 font-semibold">
                    No invoice records found matching the query criteria.
                  </td>
                </tr>
              ) : (
                paginatedRuns.map((r) => {
              const detail = getDetailsData(r.run_id);
              const isGenome = r.filename.toLowerCase().includes('genome');
              const seller = detail?.seller_name || (isGenome ? 'Genome Pharmaceuticals' : 'Shivam Drugs House');
              const isSelected = selectedInvoices.includes(r.run_id);
              const amount = detail?.grand_total 
                ? `₹${detail.grand_total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` 
                : (r.confidence ? `₹${(r.confidence * 1500).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—');
              const dispInvoiceNumber = detail?.invoice_number ? `#${detail.invoice_number}` : `#${r.filename.substring(0, 15) || r.run_id.substring(4, 12)}`;

              return (
                <tr key={r.run_id} className={`hover:bg-[#f8fafc] transition-colors ${isSelected ? 'bg-blue-50/20' : ''}`}>
                  <td className="p-4 pl-6">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => handleSelectInvoice(r.run_id, e.target.checked)}
                      className="w-4 h-4 rounded border-gray-300 text-blue-600 accent-blue-600 cursor-pointer"
                    />
                  </td>
                  <td className="p-4 text-gray-500">
                    {new Date(r.timestamp).toLocaleDateString(undefined, {
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                    })}
                  </td>
                  <td className="p-4 font-semibold text-[#0f172a] hover:underline cursor-pointer" onClick={() => navigate(`/review/${r.run_id}`)}>
                    {dispInvoiceNumber}
                  </td>
                  <td className="p-4 font-medium">{seller}</td>
                  <td className="p-4 text-right font-bold text-[#0f172a]">{amount}</td>
                  <td className="p-4 text-center">
                        <span
                          className={`inline-block px-2.5 py-1 rounded-full text-[10px] font-bold ${
                            r.status === 'verified'
                              ? 'bg-green-50 text-green-700 border border-green-200'
                              : r.status === 'safe_for_erp'
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                : 'bg-amber-50 text-amber-700 border border-amber-200'
                          }`}
                        >
                          {r.status === 'verified' ? 'Verified' : r.status === 'safe_for_erp' ? 'Auto Verified' : 'Needs Review'}
                        </span>
                      </td>
                      <td className="p-4 text-center pr-6 flex items-center justify-center space-x-1.5">
                        <button
                          onClick={() => navigate(`/review/${r.run_id}`)}
                          className="p-1.5 hover:bg-[#f4f5fa] text-[#1b5dfc] rounded-lg transition-colors cursor-pointer"
                          title="View Details"
                        >
                          <Eye size={14} />
                        </button>
                        <button
                          className="p-1.5 hover:bg-[#f4f5fa] text-gray-400 hover:text-gray-700 rounded-lg transition-colors cursor-pointer"
                          title="Actions menu"
                        >
                          <MoreVertical size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination bar */}
        <div className="p-4 border-t border-[#e2e8f0] flex items-center justify-between text-xs text-gray-500 bg-[#f8fafc]/30">
          <span>
            Showing <strong className="text-gray-700">{Math.min(totalEntries, startIndex + 1)}</strong> to{' '}
            <strong className="text-gray-700">{Math.min(totalEntries, startIndex + itemsPerPage)}</strong> of{' '}
            <strong className="text-gray-700">{totalEntries}</strong> entries
          </span>
          <div className="flex items-center space-x-1">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="p-1.5 rounded-lg border border-gray-200 hover:bg-[#f4f5fa] text-gray-500 disabled:opacity-40 disabled:hover:bg-transparent transition-colors cursor-pointer"
            >
              <ChevronLeft size={14} />
            </button>
            {Array.from({ length: totalPages }, (_, idx) => (
              <button
                key={idx}
                onClick={() => setCurrentPage(idx + 1)}
                className={`w-7 h-7 rounded-lg text-xs font-semibold border transition-colors cursor-pointer ${
                  currentPage === idx + 1
                    ? 'bg-[#1b5dfc] border-[#1b5dfc] text-white'
                    : 'bg-white border-gray-200 text-gray-600 hover:bg-[#f4f5fa]'
                }`}
              >
                {idx + 1}
              </button>
            ))}
            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className="p-1.5 rounded-lg border border-gray-200 hover:bg-[#f4f5fa] text-gray-500 disabled:opacity-40 disabled:hover:bg-transparent transition-colors cursor-pointer"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* Bottom Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Total Monthly Spend card */}
        <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center space-x-4">
          <div className="p-3 bg-blue-50 text-[#1b5dfc] rounded-xl shrink-0">
            <DollarSign size={22} />
          </div>
          <div>
            <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Total Spend</span>
            <strong className="text-lg font-bold text-[#0f172a]">
              ₹{totalSpend.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </strong>
            <span className="text-[9px] text-green-600 block mt-0.5 font-medium">+12% vs last month</span>
          </div>
        </div>

        {/* Pending Reviews card */}
        <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center space-x-4">
          <div className="p-3 bg-amber-50 text-amber-600 rounded-xl shrink-0">
            <AlertCircle size={22} />
          </div>
          <div>
            <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Pending Reviews</span>
            <strong className="text-lg font-bold text-[#0f172a]">{pendingReviewCount} Invoices</strong>
            <span className="text-[9px] text-amber-600 block mt-0.5 font-semibold">Priority: High</span>
          </div>
        </div>

        {/* Inventory Updates card */}
        <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center space-x-4">
          <div className="p-3 bg-indigo-50 text-indigo-600 rounded-xl shrink-0">
            <Package size={22} />
          </div>
          <div>
            <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Inventory updates</span>
            <strong className="text-lg font-bold text-[#0f172a]">{totalSKUsCount} SKUs</strong>
            <span className="text-[9px] text-indigo-600 block mt-0.5 font-medium">Automated matching active</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default InvoiceHistoryPage;
