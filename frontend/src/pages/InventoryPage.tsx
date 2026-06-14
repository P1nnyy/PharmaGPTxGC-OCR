import React, { useState, useEffect } from 'react';
import { Search, Package, AlertTriangle, Calendar, BarChart2 } from 'lucide-react';

interface InventoryItem {
  id: string;
  product: string;
  batch: string;
  expiry: string;
  quantity: number;
  mrp: number;
  gst: number;
  source_invoice: string;
}



export const InventoryPage: React.FC = () => {
  const [inventory, setInventory] = useState<InventoryItem[]>([]);
  const [searchTerm, setSearchTerm] = useState('');

  // Load inventory on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem('pharmaflow_inventory');
      let items: InventoryItem[] = [];
      if (stored) {
        items = JSON.parse(stored);
      }
      // Clean up any old dummy seed items if they exist
      const cleaned = items.filter((item) => !item.id.startsWith('inv-seed-'));
      localStorage.setItem('pharmaflow_inventory', JSON.stringify(cleaned));
      setInventory(cleaned);
    } catch (e) {
      console.error(e);
      setInventory([]);
    }
  }, []);

  // Filter list
  const filteredInventory = inventory.filter(
    (item) =>
      item.product.toLowerCase().includes(searchTerm.toLowerCase()) ||
      item.batch.toLowerCase().includes(searchTerm.toLowerCase()) ||
      item.source_invoice.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Compute stat counters
  const totalSKUs = inventory.length;
  
  const lowStockCount = inventory.filter((item) => item.quantity <= 10).length;

  // Filter items expiring soon (e.g., in 2025 or before)
  const expiringSoonCount = inventory.filter((item) => {
    if (!item.expiry) return false;
    const parts = item.expiry.split('/');
    if (parts.length === 2) {
      const year = parseInt(parts[1]);
      return year <= 2026;
    }
    return false;
  }).length;

  const totalQuantity = inventory.reduce((sum, item) => sum + item.quantity, 0);

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
                    No matching stock items in inventory.
                  </td>
                </tr>
              ) : (
                filteredInventory.map((item) => {
                  const isLow = item.quantity <= 10;
                  
                  // Check if expiring soon (2025/2026 or before)
                  let isExpiring = false;
                  if (item.expiry) {
                    const parts = item.expiry.split('/');
                    if (parts.length === 2) {
                      isExpiring = parseInt(parts[1]) <= 2026;
                    }
                  }

                  return (
                    <tr key={item.id} className="hover:bg-[#f8fafc] transition-colors">
                      <td className="p-4 pl-6 font-semibold text-[#0f172a]">{item.product}</td>
                      <td className="p-4 font-mono font-medium">{item.batch}</td>
                      <td className="p-4">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          isExpiring ? 'bg-amber-50 text-amber-700 border border-amber-200' : 'text-gray-500'
                        }`}>
                          {item.expiry}
                        </span>
                      </td>
                      <td className="p-4 text-right">
                        <span className={`font-bold ${isLow ? 'text-red-600' : 'text-gray-900'}`}>
                          {item.quantity} units
                        </span>
                        {isLow && (
                          <span className="block text-[9px] text-red-500 font-semibold">Low Stock</span>
                        )}
                      </td>
                      <td className="p-4 text-right font-medium">₹{item.mrp.toFixed(2)}</td>
                      <td className="p-4 text-right text-gray-500 font-medium">{item.gst}%</td>
                      <td className="p-4 pr-6 text-gray-500 font-mono text-[10px]">{item.source_invoice}</td>
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
