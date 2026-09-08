import React, { useState, useEffect } from 'react';
import { Search, Package, AlertTriangle, Calendar, BarChart2 } from 'lucide-react';
import { apiClient } from '../api/client';
import type { InventoryItem, InventoryStats } from '../api/types';

// Stock is read from the server, not from this browser. It used to live in
// localStorage, written by whichever machine happened to press "Mark as
// Verified" - which is why the page was empty for everyone else, including on
// the deployed site. The invoices were always the real record; now the page
// reads them.

const EMPTY_STATS: InventoryStats = {
  total_skus: 0,
  total_quantity: 0,
  low_stock: 0,
  expiring_soon: 0,
  expired: 0
};

// Stored as ISO for sorting and comparison; pharmacists read expiry as MM/YY.
const formatExpiry = (value: string | null): string => {
  if (!value) return '—';
  const match = /^(\d{4})-(\d{2})/.exec(value);
  return match ? `${match[2]}/${match[1].slice(2)}` : value;
};

const formatMoney = (value: number | null): string =>
  value === null || value === undefined ? '—' : `₹${value.toFixed(2)}`;

export const InventoryPage: React.FC = () => {
  const [inventory, setInventory] = useState<InventoryItem[]>([]);
  const [stats, setStats] = useState<InventoryStats>(EMPTY_STATS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiClient.getInventory();
        if (cancelled) return;
        setInventory(data.items);
        setStats(data.stats);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        // Say the load failed rather than rendering zeroes, which would read
        // as "you have no stock" - a different and much worse claim.
        setError(e instanceof Error ? e.message : 'Failed to load inventory.');
        setInventory([]);
        setStats(EMPTY_STATS);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Filter list
  const filteredInventory = inventory.filter((item) => {
    const term = searchTerm.toLowerCase();
    return (
      (item.product || '').toLowerCase().includes(term) ||
      (item.batch || '').toLowerCase().includes(term) ||
      (item.source_invoice || '').toLowerCase().includes(term)
    );
  });

  const totalSKUs = stats.total_skus;
  const lowStockCount = stats.low_stock;
  const expiringSoonCount = stats.expiring_soon;
  const totalQuantity = stats.total_quantity;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Title Header */}
      <div>
        <h2 className="text-2xl font-bold text-[#0f172a] tracking-tight">Inventory Stock Manager</h2>
        <p className="text-gray-500 text-sm">Monitor medicine quantities, batch numbers, and expiry states auto-syncing from verified invoices.</p>
      </div>

      {/* Summary widgets grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Total SKUs */}
        <div className="bg-white p-6 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center space-x-4">
          <div className="p-3 bg-blue-50 text-[#1b5dfc] rounded-xl">
            <Package size={24} />
          </div>
          <div>
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block">Total SKUs</span>
            <strong className="text-2xl font-bold text-[#0f172a]">{totalSKUs}</strong>
          </div>
        </div>

        {/* Expiring Soon */}
        <div className="bg-white p-6 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center space-x-4">
          <div className="p-3 bg-amber-50 text-amber-600 rounded-xl">
            <Calendar size={24} />
          </div>
          <div>
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block">Expiring Soon</span>
            <strong className="text-2xl font-bold text-[#0f172a]">{expiringSoonCount}</strong>
          </div>
        </div>

        {/* Low Stock */}
        <div className="bg-white p-6 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center space-x-4">
          <div className="p-3 bg-red-50 text-red-600 rounded-xl">
            <AlertTriangle size={24} />
          </div>
          <div>
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block">Low Stock</span>
            <strong className="text-2xl font-bold text-[#0f172a]">{lowStockCount}</strong>
          </div>
        </div>

        {/* Total Units */}
        <div className="bg-white p-6 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center space-x-4">
          <div className="p-3 bg-green-50 text-green-600 rounded-xl">
            <BarChart2 size={24} />
          </div>
          <div>
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block">Total Stock Units</span>
            <strong className="text-2xl font-bold text-[#0f172a]">{totalQuantity.toLocaleString()}</strong>
          </div>
        </div>
      </div>

      {/* Search Filter Toolbar */}
      <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center">
        <div className="relative w-full max-w-md">
          <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search by Product Name, Batch, or Source Invoice..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-[#f4f5fa] border border-transparent rounded-xl pl-9 pr-4 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-all duration-200"
          />
        </div>
      </div>

      {/* Stock Items Table */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#f8fafc] border-b border-[#e2e8f0] text-gray-400 font-semibold text-[10px] uppercase tracking-wider">
                <th className="p-4 pl-6">Product</th>
                <th className="p-4">Batch</th>
                <th className="p-4">Expiry</th>
                <th className="p-4 text-right">Quantity</th>
                <th className="p-4 text-right">MRP (Rs)</th>
                <th className="p-4 text-right">GST %</th>
                <th className="p-4 pr-6">Source Invoice</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0] text-xs text-gray-700">
              {filteredInventory.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-gray-400 font-medium">
                    {loading
                      ? 'Loading stock from verified invoices...'
                      : error
                        ? error
                        : inventory.length === 0
                          ? 'No stock yet. Verify an invoice and its items appear here.'
                          : 'No matching stock items in inventory.'}
                  </td>
                </tr>
              ) : (
                filteredInventory.map((item) => {
                  // Both flags come from the server, which knows today's
                  // date. The old client-side test hardcoded "year <= 2026"
                  // and would have quietly called everything expiring.
                  const isLow = item.is_low_stock;
                  const isExpiring = item.is_expiring_soon || item.is_expired;

                  return (
                    <tr key={item.id} className="hover:bg-[#f8fafc] transition-colors">
                      <td className="p-4 pl-6 font-semibold text-[#0f172a]">{item.product}</td>
                      <td className="p-4 font-mono font-medium">{item.batch || '—'}</td>
                      <td className="p-4">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          isExpiring ? 'bg-amber-50 text-amber-700 border border-amber-200' : 'text-gray-500'
                        }`}>
                          {formatExpiry(item.expiry)}
                        </span>
                      </td>
                      <td className="p-4 text-right">
                        <span className={`font-bold ${isLow ? 'text-red-600' : 'text-gray-900'}`}>
                          {item.quantity.toLocaleString()} units
                        </span>
                        {isLow && (
                          <span className="block text-[9px] text-red-500 font-semibold">Low Stock</span>
                        )}
                      </td>
                      <td className="p-4 text-right font-medium">{formatMoney(item.mrp)}</td>
                      <td className="p-4 text-right text-gray-500 font-medium">{item.gst === null || item.gst === undefined ? '—' : `${item.gst}%`}</td>
                      <td className="p-4 pr-6 text-gray-500 font-mono text-[10px]">{item.source_invoice || '—'}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default InventoryPage;
