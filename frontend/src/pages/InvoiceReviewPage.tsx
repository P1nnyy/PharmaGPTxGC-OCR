import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { selectMainTable, getInvoiceImageUrl } from '../api/client';
import {
  ZoomIn,
  ZoomOut,
  RotateCw,
  Plus,
  Trash2,
  CheckCircle,
  FileSpreadsheet,
  AlertTriangle,
  Info,
  RefreshCw,
  Calculator,
  X // Used for closing the details side drawer
} from 'lucide-react';

// Type definition for parsed invoice header attributes
interface InvoiceHeader {
  invoice_number: string;
  invoice_date: string;
  seller_name: string;
  buyer_name: string;
  subtotal: number | null;
  discount: number | null;
  cgst: number | null;
  sgst: number | null;
  igst: number | null;
  grand_total: number | null;
}

// Type definition for spreadsheet row attributes (allowing nulls for clean validation)
interface TableLineItem {
  id: string;
  product_name: string;
  batch: string;
  expiry: string;
  hsn: string;
  pack: string;
  quantity: number | null;
  free_quantity: number | null;
  mrp: number | null;
  rate: number | null;
  discount: number | null;
  gst_percent: number | null;
  amount: number | null;
}

// Helper: Safely parses numeric fields, returning null on missing/empty values
const parseOptionalFloat = (val: any): number | null => {
  if (val === null || val === undefined || val === '') return null;
  const num = parseFloat(val);
  return isNaN(num) ? null : num;
};

// Helper: Safely normalizes string values, returning empty string on missing/null
const parseOptionalString = (val: any): string => {
  if (val === null || val === undefined) return '';
  return String(val).trim();
};

// Helper: Formats currency displays, returning "—" for missing totals
const formatCurrency = (value: any): string => {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  const num = parseFloat(value);
  if (isNaN(num)) {
    return '—';
  }
  return `₹${num.toFixed(2)}`;
};



// Helper: Extracts quantity dynamically, supporting qty / quantity mappings
const getLineItemQty = (item: any): any => {
  if (item.quantity !== undefined && item.quantity !== null && item.quantity !== '') {
    return item.quantity;
  }
  if (item.qty !== undefined && item.qty !== null && item.qty !== '') {
    return item.qty;
  }
  return '';
};

// Helper: Safely returns line item amount
const getLineItemAmount = (item: any): any => {
  if (item.amount !== undefined && item.amount !== null && item.amount !== '') {
    return item.amount;
  }
  return '';
};

// Helper: Safely returns line item MRP
const getLineItemMRP = (item: any): any => {
  if (item.mrp !== undefined && item.mrp !== null && item.mrp !== '') {
    return item.mrp;
  }
  return '';
};

export const InvoiceReviewPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { runs } = useRun();

  // Selected Run Summary metadata
  const runSummary = runs.find((r) => r.run_id === runId) || null;

  // Zoom & Rotation Preview State for the original scan
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);

  // Editor states
  const [header, setHeader] = useState<InvoiceHeader>({
    invoice_number: '',
    invoice_date: '',
    seller_name: '',
    buyer_name: '',
    subtotal: null,
    discount: null,
    cgst: null,
    sgst: null,
    igst: null,
    grand_total: null
  });

  const [lineItems, setLineItems] = useState<TableLineItem[]>([]);
  const [confidence, setConfidence] = useState(85);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ID of the line item currently active in the details side drawer
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);

  // Check if critical header fields are missing
  const isCriticalHeaderMissing = (field: keyof InvoiceHeader) => {
    const val = header[field];
    return val === null || val === undefined || val === '';
  };

  // Check if critical line item fields are missing
  const isCriticalItemMissing = (item: TableLineItem, field: keyof TableLineItem) => {
    let val: any = item[field];
    if (field === 'quantity') {
      val = getLineItemQty(item);
    } else if (field === 'amount') {
      val = getLineItemAmount(item);
    }
    return val === null || val === undefined || val === '';
  };

  // Calculate the total number of missing critical fields
  const getMissingFieldsCount = () => {
    let count = 0;
    if (isCriticalHeaderMissing('invoice_number')) count++;
    if (isCriticalHeaderMissing('invoice_date')) count++;
    if (isCriticalHeaderMissing('seller_name')) count++;
    if (isCriticalHeaderMissing('grand_total')) count++;
    
    lineItems.forEach((item) => {
      if (isCriticalItemMissing(item, 'product_name')) count++;
      if (isCriticalItemMissing(item, 'hsn')) count++;
      if (isCriticalItemMissing(item, 'quantity')) count++;
      if (isCriticalItemMissing(item, 'amount')) count++;
    });
    
    return count;
  };

  // Load and Map details on mount
  useEffect(() => {
    if (!runId) return;
    setIsLoading(true);
    setError(null);

    try {
      const storedRuns = localStorage.getItem('ocr_workbench_runs');
      const parsedRuns = storedRuns ? JSON.parse(storedRuns) : [];
      const matchingSummary = parsedRuns.find((r: any) => r.run_id === runId);

      const rawDetailStr = localStorage.getItem(`ocr_workbench_run_detail_${runId}`);
      
      // Handle fallback mockup calculations for demo run if cache is missing
      if (!rawDetailStr) {
        if (matchingSummary?.is_demo) {
          const isGenome = matchingSummary.filename.toLowerCase().includes('genome');
          setHeader({
            invoice_number: isGenome ? 'INV-GEN-9921' : 'TBL_UUID_99120-X',
            invoice_date: '2026-06-03',
            seller_name: isGenome ? 'Genome Pharmaceuticals' : 'Shivam Drugs House',
            buyer_name: 'My Pharmacy Central',
            subtotal: 1524.50,
            discount: 121.96,
            cgst: 121.96,
            sgst: 121.96,
            igst: 0,
            grand_total: 1646.46
          });

          setLineItems([
            {
              id: 'item-1',
              product_name: 'Amoxicillin 500mg Cap (100)',
              batch: 'BN-99212',
              expiry: '12/2028',
              hsn: '3004',
              pack: '10x10',
              quantity: 12,
              free_quantity: 0,
              mrp: 54.00,
              rate: 42.00,
              discount: 0,
              gst_percent: 18,
              amount: 504.00
            },
            {
              id: 'item-2',
              product_name: 'Ciprofloxacin 250mg Tab (20)',
              batch: '',
              expiry: '05/2027',
              hsn: '3004',
              pack: '15x10',
              quantity: 5,
              free_quantity: 0,
              mrp: 140.00,
              rate: 125.50,
              discount: 0,
              gst_percent: 18,
              amount: 627.50
            },
            {
              id: 'item-3',
              product_name: 'Ibuprofen 400mg (50)',
              batch: 'BN-8812',
              expiry: '08/2028',
              hsn: '3004',
              pack: '3x10',
              quantity: 20,
              free_quantity: 0,
              mrp: 18.00,
              rate: 15.20,
              discount: 0,
              gst_percent: 12,
              amount: 304.00
            },
            {
              id: 'item-4',
              product_name: 'Omeprazole 20mg (30)',
              batch: 'BN-4451',
              expiry: '11/2026',
              hsn: '3004',
              pack: '100ml',
              quantity: 10,
              free_quantity: 0,
              mrp: 12.00,
              rate: 8.90,
              discount: 0,
              gst_percent: 12,
              amount: 89.00
            }
          ]);
          setConfidence(Math.round((matchingSummary.confidence || 0.88) * 100));
          setIsLoading(false);
          return;
        } else {
          throw new Error('Invoice extraction details not found in local cache.');
        }
      }

      const detail = JSON.parse(rawDetailStr);
      setConfidence(Math.round((detail.confidence || 0.85) * 100));

      // Parse structured header fields without zero-defaulting
      setHeader({
        invoice_number: parseOptionalString(detail.invoice_number || detail.metadata?.invoice_number),
        invoice_date: parseOptionalString(detail.invoice_date || detail.metadata?.invoice_date),
        seller_name: parseOptionalString(detail.seller_name || detail.metadata?.seller_name || detail.metadata?.supplier_name),
        buyer_name: parseOptionalString(detail.buyer_name || detail.metadata?.buyer_name),
        subtotal: parseOptionalFloat(detail.subtotal ?? detail.metadata?.subtotal),
        discount: parseOptionalFloat(detail.discount ?? detail.metadata?.discount),
        cgst: parseOptionalFloat(detail.cgst ?? detail.metadata?.tax?.cgst),
        sgst: parseOptionalFloat(detail.sgst ?? detail.metadata?.tax?.sgst),
        igst: parseOptionalFloat(detail.igst ?? detail.metadata?.tax?.igst),
        grand_total: parseOptionalFloat(detail.grand_total ?? detail.metadata?.grand_total)
      });

      // Parse structured line items (handling Azure DI & Legacy schemas)
      let parsedItems: TableLineItem[] = [];

      if (Array.isArray(detail.line_items) && detail.line_items.length > 0) {
        parsedItems = detail.line_items.map((item: any, idx: number) => {
          const qty = item.quantity !== undefined ? item.quantity : item.qty;
          return {
            id: `item-${idx}`,
            product_name: parseOptionalString(item.name || item.product_name || item.product),
            batch: parseOptionalString(item.batch),
            expiry: parseOptionalString(item.expiry),
            hsn: parseOptionalString(item.hsn),
            pack: parseOptionalString(item.pack),
            quantity: parseOptionalFloat(qty),
            free_quantity: parseOptionalFloat(item.free_quantity),
            mrp: parseOptionalFloat(item.mrp),
            rate: parseOptionalFloat(item.rate),
            discount: parseOptionalFloat(item.discount),
            gst_percent: parseOptionalFloat(item.gst_percent),
            amount: parseOptionalFloat(item.amount)
          };
        });
      } else if (detail.metadata?.llm_extraction?.items) {
        const rawLlmItems = detail.metadata.llm_extraction.items;
        parsedItems = rawLlmItems.map((item: any, idx: number) => {
          const qty = item.qty !== undefined ? item.qty : item.quantity;
          return {
            id: `item-${idx}`,
            product_name: parseOptionalString(item.product_name || item.name),
            batch: parseOptionalString(item.batch),
            expiry: parseOptionalString(item.expiry),
            hsn: parseOptionalString(item.hsn_code || item.hsn),
            pack: parseOptionalString(item.pack),
            quantity: parseOptionalFloat(qty),
            free_quantity: parseOptionalFloat(item.free_quantity),
            mrp: parseOptionalFloat(item.mrp),
            rate: parseOptionalFloat(item.rate),
            discount: parseOptionalFloat(item.discount),
            gst_percent: parseOptionalFloat(item.gst_percent),
            amount: parseOptionalFloat(item.amount)
          };
        });
      } else if (Array.isArray(detail.structured_tables) && detail.structured_tables.length > 0) {
        const mainTbl = selectMainTable(detail);
        if (mainTbl && Array.isArray(mainTbl.cells)) {
          const uniqueRows = Array.from(new Set(mainTbl.cells.map((c: any) => c.row_id || c.row_index || 0))).sort((a: any, b: any) => a - b);
          
          parsedItems = uniqueRows.slice(1).map((rowId: any, idx: number) => {
            const rowCells = mainTbl.cells.filter((c: any) => (c.row_id ?? c.row_index) === rowId);
            
            const cellTextFor = (label: string) => {
              const cell = rowCells.find((c: any) => c.semantic_label === label || c.label === label);
              return cell ? cell.text : '';
            };

            const qtyText = cellTextFor('quantity') || cellTextFor('quantity_pcs');
            const rateText = cellTextFor('unit_price') || cellTextFor('rate');
            const amountText = cellTextFor('row_total') || cellTextFor('amount');
            const mrpText = cellTextFor('mrp');
            const discountText = cellTextFor('discount');
            const gstText = cellTextFor('gst_percent');
            const freeQtyText = cellTextFor('free_quantity');

            return {
              id: `item-${idx}`,
              product_name: parseOptionalString(cellTextFor('product_name') || cellTextFor('product')),
              batch: parseOptionalString(cellTextFor('batch_no') || cellTextFor('batch')),
              expiry: parseOptionalString(cellTextFor('expiry_date') || cellTextFor('expiry')),
              hsn: parseOptionalString(cellTextFor('hsn_code') || cellTextFor('hsn')),
              pack: parseOptionalString(cellTextFor('pack')),
              quantity: parseOptionalFloat(qtyText),
              free_quantity: parseOptionalFloat(freeQtyText),
              mrp: parseOptionalFloat(mrpText),
              rate: parseOptionalFloat(rateText),
              discount: parseOptionalFloat(discountText),
              gst_percent: parseOptionalFloat(gstText),
              amount: parseOptionalFloat(amountText)
            };
          });
        }
      }

      setLineItems(parsedItems);
    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Failed to parse invoice details.');
    } finally {
      setIsLoading(false);
    }
  }, [runId]);

  // Handle header field edits
  const handleHeaderChange = (key: keyof InvoiceHeader, value: any) => {
    setHeader((prev) => ({
      ...prev,
      [key]: value
    }));
  };

  // Handle line item field edits and auto-recompute amount totals
  const handleItemChange = (itemId: string, key: keyof TableLineItem, value: any) => {
    setLineItems((prev) =>
      prev.map((item) => {
        if (item.id !== itemId) return item;

        const updatedItem = { ...item, [key]: value };

        // Auto-recalculate row amount if Quantity/Rate/Discount changes
        if (key === 'quantity' || key === 'rate' || key === 'discount') {
          const qty = key === 'quantity' ? parseOptionalFloat(value) : getLineItemQty(item);
          const rate = key === 'rate' ? parseOptionalFloat(value) : item.rate;
          const disc = key === 'discount' ? parseOptionalFloat(value) : item.discount;
          
          if (qty !== null && rate !== null) {
            updatedItem.amount = parseFloat((qty * rate - (disc || 0)).toFixed(2));
          } else {
            updatedItem.amount = null;
          }
        }

        return updatedItem;
      })
    );
  };

  // Append a fresh, empty line item row
  const handleAddRow = () => {
    const newRow: TableLineItem = {
      id: `item-${Date.now()}`,
      product_name: '',
      batch: '',
      expiry: '',
      hsn: '',
      pack: '',
      quantity: null,
      free_quantity: null,
      mrp: null,
      rate: null,
      discount: null,
      gst_percent: null,
      amount: null
    };
    setLineItems((prev) => [...prev, newRow]);
  };

  // Delete line item row
  const handleDeleteRow = (itemId: string) => {
    setLineItems((prev) => prev.filter((item) => item.id !== itemId));
    if (selectedItemId === itemId) {
      setSelectedItemId(null);
    }
  };

  // Dynamic calculations: Line Total
  const computedSubtotal = parseFloat(
    lineItems.reduce((sum, item) => sum + (getLineItemAmount(item) || 0), 0).toFixed(2)
  );

  // Dynamic calculations: GST Total (sum of CGST + SGST + IGST)
  const cgstVal = parseOptionalFloat(header.cgst);
  const sgstVal = parseOptionalFloat(header.sgst);
  const igstVal = parseOptionalFloat(header.igst);

  const hasGstValues = cgstVal !== null || sgstVal !== null || igstVal !== null;
  const computedGstTotal = hasGstValues
    ? parseFloat(((cgstVal || 0) + (sgstVal || 0) + (igstVal || 0)).toFixed(2))
    : null;

  // Math validation logic (ensures we don't calculate false mismatches)
  const missingAmountsCount = lineItems.filter(item => getLineItemAmount(item) === '').length;
  const hasMissingGrandTotal = header.grand_total === null || header.grand_total === undefined || String(header.grand_total) === '';

  let mathStatus: 'matched' | 'mismatch' | 'missing_fields' = 'matched';
  let mathStatusMessage = 'Sum of lines matches grand total';

  if (missingAmountsCount > 0) {
    mathStatus = 'missing_fields';
    mathStatusMessage = 'Needs Review: Missing item amounts';
  } else if (hasMissingGrandTotal) {
    mathStatus = 'missing_fields';
    mathStatusMessage = 'Needs Review: Missing grand total';
  } else {
    // Both inclusive-tax and exclusive-tax validation sums are validated with 2.0 Rs tolerance
    const gstPortion = computedGstTotal || 0;
    const discountPortion = parseOptionalFloat(header.discount) || 0;
    const computedGrandTotal = computedSubtotal + gstPortion - discountPortion;
    const difference = Math.abs((parseOptionalFloat(header.grand_total) || 0) - computedGrandTotal);
    const differenceExcludeTax = Math.abs((parseOptionalFloat(header.grand_total) || 0) - computedSubtotal);

    const matches = difference <= 2.0 || differenceExcludeTax <= 2.0;

    if (matches) {
      mathStatus = 'matched';
      mathStatusMessage = 'Sum of lines matches grand total';
    } else {
      mathStatus = 'mismatch';
      mathStatusMessage = 'Items sum mismatch';
    }
  }

  // Save changes to localStorage (Draft)
  const handleSaveDraft = () => {
    try {
      const rawDetailStr = localStorage.getItem(`ocr_workbench_run_detail_${runId}`);
      if (rawDetailStr) {
        const detail = JSON.parse(rawDetailStr);
        detail.invoice_number = header.invoice_number;
        detail.invoice_date = header.invoice_date;
        detail.seller_name = header.seller_name;
        detail.buyer_name = header.buyer_name;
        detail.subtotal = header.subtotal;
        detail.discount = header.discount;
        detail.grand_total = header.grand_total;
        detail.line_items = lineItems;
        detail.cgst = header.cgst;
        detail.sgst = header.sgst;
        detail.igst = header.igst;
        localStorage.setItem(`ocr_workbench_run_detail_${runId}`, JSON.stringify(detail));
      }

      // Update the Runs summary status to match draft state
      const storedRuns = localStorage.getItem('ocr_workbench_runs');
      if (storedRuns) {
        const parsedRuns = JSON.parse(storedRuns);
        const updatedRuns = parsedRuns.map((r: any) => {
          if (r.run_id === runId) {
            return {
              ...r,
              confidence: confidence / 100,
              status: 'needs_review'
            };
          }
          return r;
        });
        localStorage.setItem('ocr_workbench_runs', JSON.stringify(updatedRuns));
      }

      alert('Draft saved successfully.');
    } catch (e) {
      alert('Failed to save draft: ' + String(e));
    }
  };

  // Mark invoice as Verified
  const handleMarkAsVerified = () => {
    try {
      // 1. Update run details
      const rawDetailStr = localStorage.getItem(`ocr_workbench_run_detail_${runId}`);
      if (rawDetailStr) {
        const detail = JSON.parse(rawDetailStr);
        detail.invoice_number = header.invoice_number;
        detail.invoice_date = header.invoice_date;
        detail.seller_name = header.seller_name;
        detail.buyer_name = header.buyer_name;
        detail.subtotal = header.subtotal;
        detail.discount = header.discount;
        detail.grand_total = header.grand_total;
        detail.line_items = lineItems;
        detail.cgst = header.cgst;
        detail.sgst = header.sgst;
        detail.igst = header.igst;
        localStorage.setItem(`ocr_workbench_run_detail_${runId}`, JSON.stringify(detail));
      }

      // 2. Set Runs summary status to 'verified'
      const storedRuns = localStorage.getItem('ocr_workbench_runs');
      if (storedRuns) {
        const parsedRuns = JSON.parse(storedRuns);
        const updatedRuns = parsedRuns.map((r: any) => {
          if (r.run_id === runId) {
            return {
              ...r,
              status: 'verified'
            };
          }
          return r;
        });
        localStorage.setItem('ocr_workbench_runs', JSON.stringify(updatedRuns));
      }

      // 3. Save SKUs to local Inventory database (safe conversion to avoid NaNs)
      const storedInventory = localStorage.getItem('pharmaflow_inventory');
      let inventory = storedInventory ? JSON.parse(storedInventory) : [];

      lineItems.forEach((item) => {
        if (!item.product_name.trim()) return;

        const qty = parseFloat(getLineItemQty(item) as any) || 0;
        const mrp = parseFloat(getLineItemMRP(item) as any) || 0;
        const gst = parseFloat(item.gst_percent as any) || 0;

        // Check if matching SKU is already in inventory
        const existingIdx = inventory.findIndex(
          (inv: any) =>
            inv.product.toLowerCase().trim() === item.product_name.toLowerCase().trim() &&
            inv.batch.toLowerCase().trim() === (item.batch || 'N/A').toLowerCase().trim()
        );

        if (existingIdx >= 0) {
          inventory[existingIdx].quantity += qty;
          inventory[existingIdx].source_invoice = header.invoice_number || runId || 'Unknown';
        } else {
          inventory.push({
            id: `inv-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
            product: item.product_name,
            batch: item.batch || 'N/A',
            expiry: item.expiry || 'N/A',
            quantity: qty,
            mrp: mrp || parseFloat(item.rate as any) || 0,
            gst: gst,
            source_invoice: header.invoice_number || runId || 'Unknown'
          });
        }
      });

      localStorage.setItem('pharmaflow_inventory', JSON.stringify(inventory));

      // 4. Redirect to history
      navigate('/history');
    } catch (e) {
      alert('Failed to verify invoice: ' + String(e));
    }
  };

  // Export inline items as simple CSV/Excel mockup
  const handleExportExcel = () => {
    let csvContent = 'data:text/csv;charset=utf-8,';
    csvContent += 'Product Name,Batch,Expiry,HSN,Pack,Qty,MRP,Rate,Discount,GST %,Amount\n';
    lineItems.forEach((item) => {
      const row = [
        item.product_name,
        item.batch,
        item.expiry,
        item.hsn,
        item.pack,
        getLineItemQty(item),
        getLineItemMRP(item),
        item.rate,
        item.discount,
        item.gst_percent,
        getLineItemAmount(item)
      ]
        .map((val) => `"${String(val ?? '').replace(/"/g, '""')}"`)
        .join(',');
      csvContent += row + '\n';
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `Invoice_${header.invoice_number || 'export'}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Get source image
  const getSourceImage = () => {
    if (!runId) return '';
    return getInvoiceImageUrl(runId, runSummary?.filename || 'invoice.jpg');
  };

  // Find currently active item in side drawer details form
  const selectedItem = lineItems.find(item => item.id === selectedItemId) || null;

  if (isLoading) {
    return (
      <div className="py-24 text-center space-y-4">
        <RefreshCw className="animate-spin text-[#1b5dfc] mx-auto" size={40} />
        <p className="text-gray-500 font-medium">Loading invoice extraction data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white p-8 rounded-2xl border border-red-200 shadow-sm max-w-lg mx-auto text-center space-y-4 mt-12">
        <AlertTriangle className="text-red-500 mx-auto" size={48} />
        <h3 className="text-lg font-bold text-[#0f172a]">Extraction Error</h3>
        <p className="text-gray-500 text-sm">{error}</p>
        <button
          onClick={() => navigate('/upload')}
          className="bg-[#1b5dfc] text-white px-4 py-2 rounded-xl text-xs font-semibold cursor-pointer"
        >
          Return to Upload
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top action header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#0f172a]">
            Reviewing Invoice {header.invoice_number ? `#${header.invoice_number}` : ''}
          </h2>
          
          {/* Badge: Extraction Confidence */}
          <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold border ${
            confidence >= 85
              ? 'bg-green-50 text-green-700 border-green-200'
              : 'bg-amber-50 text-amber-700 border-amber-200'
          }`}>
            Confidence: {confidence}%
          </span>
          
          {/* Badge: Math Validation Status */}
          <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold border ${
            mathStatus === 'matched'
              ? 'bg-green-50 text-green-700 border-green-200'
              : mathStatus === 'missing_fields'
                ? 'bg-amber-50 text-amber-700 border-amber-200'
                : 'bg-red-50 text-red-700 border-red-200'
          }`}>
            Math: {mathStatusMessage}
          </span>
          
          {/* Badge: Critical Missing Fields Count */}
          {getMissingFieldsCount() > 0 && (
            <span className="px-2.5 py-1 rounded-full text-[10px] font-bold border bg-red-50 text-red-700 border-red-200 animate-pulse flex items-center space-x-1">
              <AlertTriangle size={10} />
              <span>Missing Fields: {getMissingFieldsCount()}</span>
            </span>
          )}
        </div>
        
        <div className="flex items-center space-x-3">
          <button
            onClick={handleExportExcel}
            className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 flex items-center space-x-1.5 shadow-sm transition-colors cursor-pointer"
          >
            <FileSpreadsheet size={14} className="text-green-600" />
            <span>Export Excel</span>
          </button>
          <button
            onClick={handleMarkAsVerified}
            className="bg-[#1b5dfc] hover:bg-[#154ecb] text-white font-semibold px-4 py-2 rounded-xl text-xs flex items-center space-x-1.5 shadow-md shadow-blue-500/10 transition-colors cursor-pointer"
          >
            <CheckCircle size={14} />
            <span>Mark as Verified</span>
          </button>
        </div>
      </div>

      {/* Two Panel Layout Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
        
        {/* Left Scan Preview Panel (Col Span 5) */}
        <div className="lg:col-span-5 bg-white rounded-2xl border border-[#e2e8f0] p-4 shadow-sm flex flex-col justify-between space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-gray-100">
            <span className="text-xs font-bold text-gray-500 uppercase tracking-wider">Original Scan</span>
            <div className="flex items-center space-x-2 bg-slate-50 p-1 rounded-lg border border-gray-200">
              <button
                onClick={() => setZoom((z) => Math.min(3, z + 0.15))}
                className="p-1 hover:bg-white text-gray-600 hover:text-gray-900 rounded transition-colors"
                title="Zoom In"
              >
                <ZoomIn size={14} />
              </button>
              <button
                onClick={() => setZoom((z) => Math.max(0.5, z - 0.15))}
                className="p-1 hover:bg-white text-gray-600 hover:text-gray-900 rounded transition-colors"
                title="Zoom Out"
              >
                <ZoomOut size={14} />
              </button>
              <button
                onClick={() => setZoom(1)}
                className="text-[10px] font-bold text-gray-500 px-1 hover:text-gray-800"
                title="Reset Zoom"
              >
                100%
              </button>
              <div className="w-px h-3 bg-gray-200" />
              <button
                onClick={() => setRotation((r) => (r + 90) % 360)}
                className="p-1 hover:bg-white text-gray-600 hover:text-gray-900 rounded transition-colors"
                title="Rotate 90°"
              >
                <RotateCw size={14} />
              </button>
            </div>
          </div>

          {/* Scanner Viewport */}
          <div className="bg-[#f8fafc] border border-slate-100 rounded-xl overflow-hidden min-h-[400px] flex items-center justify-center p-4 relative custom-scrollbar">
            <div 
              className="transition-transform duration-200 flex items-center justify-center origin-center"
              style={{
                transform: `scale(${zoom}) rotate(${rotation}deg)`
              }}
            >
              <img
                src={getSourceImage()}
                alt="Invoice Scan"
                className="max-h-[500px] object-contain shadow-md rounded"
                onError={(e) => {
                  console.error('Image source loading issue:', e);
                }}
              />
            </div>
          </div>

          <div className="text-[10px] text-gray-400 flex items-center space-x-1">
            <Info size={12} className="text-gray-400" />
            <span>Mouse scroll and drag inside the panel is disabled. Use toolbar buttons to zoom/rotate.</span>
          </div>
        </div>

        {/* Right Extracted Editor Panel (Col Span 7) with absolute slide-drawer container */}
        <div className="lg:col-span-7 bg-white rounded-2xl border border-[#e2e8f0] shadow-sm flex flex-col justify-between overflow-hidden relative">
          <div className="p-6 space-y-6">
            
            {/* 1. Header Metadata Section */}
            <div className="space-y-4">
              <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider border-b border-gray-100 pb-2">
                Invoice Details
              </h3>
              
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
                {/* Invoice Date */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-gray-400 block">Invoice Date *</span>
                  <input
                    type="text"
                    value={header.invoice_date}
                    placeholder="—"
                    onChange={(e) => handleHeaderChange('invoice_date', e.target.value)}
                    className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-1.5 text-xs text-[#0f172a] font-medium focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                      isCriticalHeaderMissing('invoice_date') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                    }`}
                  />
                </div>

                {/* Invoice Number */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-gray-400 block">Invoice Number *</span>
                  <input
                    type="text"
                    value={header.invoice_number}
                    placeholder="—"
                    onChange={(e) => handleHeaderChange('invoice_number', e.target.value)}
                    className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-1.5 text-xs text-[#0f172a] font-medium focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                      isCriticalHeaderMissing('invoice_number') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                    }`}
                  />
                </div>

                {/* Seller Name */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-gray-400 block">Seller *</span>
                  <input
                    type="text"
                    value={header.seller_name}
                    placeholder="—"
                    onChange={(e) => handleHeaderChange('seller_name', e.target.value)}
                    className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-1.5 text-xs text-[#0f172a] font-medium focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                      isCriticalHeaderMissing('seller_name') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                    }`}
                  />
                </div>

                {/* Buyer Name */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-gray-400 block">Buyer</span>
                  <input
                    type="text"
                    value={header.buyer_name}
                    placeholder="—"
                    onChange={(e) => handleHeaderChange('buyer_name', e.target.value)}
                    className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-[#0f172a] font-medium focus:outline-none focus:bg-white focus:border-blue-500"
                  />
                </div>

                {/* Grand Total */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-gray-400 block">Grand Total *</span>
                  <input
                    type="number"
                    step="any"
                    value={header.grand_total ?? ''}
                    placeholder="—"
                    onChange={(e) => handleHeaderChange('grand_total', e.target.value === '' ? null : parseFloat(e.target.value))}
                    className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-1.5 text-xs text-[#0f172a] font-medium focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                      isCriticalHeaderMissing('grand_total') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                    }`}
                  />
                </div>
              </div>
            </div>

            {/* 2. Line Items Table */}
            <div className="space-y-3">
              <div className="flex items-center justify-between border-b border-gray-100 pb-2">
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                  Line Items ({lineItems.length})
                </h3>
                <button
                  onClick={handleAddRow}
                  className="text-xs font-semibold text-[#1b5dfc] hover:text-[#154ecb] flex items-center space-x-1.5 cursor-pointer"
                >
                  <Plus size={14} />
                  <span>Add Row</span>
                </button>
              </div>

              {/* Simplified Table Container (only Product Name, HSN, Qty, MRP, Amount, Action) */}
              <div className="border border-[#e2e8f0] rounded-xl overflow-hidden max-h-[350px] overflow-y-auto custom-scrollbar">
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="bg-[#f8fafc] border-b border-[#e2e8f0] text-gray-500 font-semibold text-[10px] uppercase tracking-wider sticky top-0 z-10">
                    <tr>
                      <th className="p-3 pl-4" style={{ width: '40%' }}>Product Name</th>
                      <th className="p-3" style={{ width: '14%' }}>HSN</th>
                      <th className="p-3 text-right" style={{ width: '10%' }}>Qty</th>
                      <th className="p-3 text-right" style={{ width: '14%' }}>MRP</th>
                      <th className="p-3 text-right" style={{ width: '16%' }}>Amount</th>
                      <th className="p-3 text-center pr-4" style={{ width: '6%' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#e2e8f0] bg-white">
                    {lineItems.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="text-center py-12 text-gray-400 font-medium">
                          No line items found. Click "Add Row" to append items.
                        </td>
                      </tr>
                    ) : (
                      lineItems.map((item) => {
                        return (
                          <tr
                            key={item.id}
                            className={`hover:bg-[#f8fafc]/50 transition-colors ${
                              isCriticalItemMissing(item, 'product_name') ||
                              isCriticalItemMissing(item, 'hsn') ||
                              isCriticalItemMissing(item, 'quantity') ||
                              isCriticalItemMissing(item, 'amount')
                                ? 'bg-amber-50/10'
                                : ''
                            }`}
                          >
                            {/* Product Name */}
                            <td className="p-2 pl-4">
                              <input
                                type="text"
                                value={item.product_name}
                                placeholder="—"
                                onChange={(e) => handleItemChange(item.id, 'product_name', e.target.value)}
                                className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                                  isCriticalItemMissing(item, 'product_name') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                                }`}
                              />
                            </td>

                            {/* HSN */}
                            <td className="p-2">
                              <input
                                type="text"
                                value={item.hsn}
                                placeholder="—"
                                onChange={(e) => handleItemChange(item.id, 'hsn', e.target.value)}
                                className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                                  isCriticalItemMissing(item, 'hsn') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                                }`}
                              />
                            </td>

                            {/* Qty */}
                            <td className="p-2 text-right">
                              <input
                                type="number"
                                value={getLineItemQty(item) ?? ''}
                                placeholder="—"
                                onChange={(e) => handleItemChange(item.id, 'quantity', e.target.value === '' ? null : parseFloat(e.target.value))}
                                className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-right text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                                  isCriticalItemMissing(item, 'quantity') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                                }`}
                              />
                            </td>

                            {/* MRP */}
                            <td className="p-2 text-right">
                              <input
                                type="number"
                                step="any"
                                value={getLineItemMRP(item) ?? ''}
                                placeholder="—"
                                onChange={(e) => handleItemChange(item.id, 'mrp', e.target.value === '' ? null : parseFloat(e.target.value))}
                                className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-right text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                                  isCriticalItemMissing(item, 'mrp') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                                }`}
                              />
                            </td>

                            {/* Amount */}
                            <td className="p-2 text-right font-semibold">
                              <input
                                type="number"
                                step="any"
                                value={getLineItemAmount(item) ?? ''}
                                placeholder="—"
                                onChange={(e) => handleItemChange(item.id, 'amount', e.target.value === '' ? null : parseFloat(e.target.value))}
                                className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-right text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors font-semibold ${
                                  isCriticalItemMissing(item, 'amount') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                                }`}
                              />
                            </td>

                            {/* Action (Details Panel & Delete) */}
                            <td className="p-2 text-center pr-4">
                              <div className="flex items-center justify-center space-x-1.5">
                                <button
                                  onClick={() => setSelectedItemId(item.id)}
                                  className="px-2.5 py-1.5 bg-[#f4f5fa] hover:bg-[#e2e8f0] text-[#1b5dfc] rounded-lg transition-colors cursor-pointer text-xs font-semibold"
                                  title="View/Edit Secondary Fields"
                                >
                                  Details
                                </button>
                                <button
                                  onClick={() => handleDeleteRow(item.id)}
                                  className="p-1.5 text-gray-400 hover:text-red-500 rounded-lg transition-colors cursor-pointer"
                                  title="Delete Row"
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>

          </div>

          {/* Sticky Totals Footer Summary Bar */}
          <div className="bg-[#f8fafc] border-t border-[#e2e8f0] p-6 flex flex-col xl:flex-row items-stretch xl:items-center justify-between gap-6 z-10">
            
            {/* 1. Subtotal / GST Totals */}
            <div className="flex flex-wrap items-center gap-6">
              <div className="space-y-0.5">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Subtotal</span>
                <span className="text-sm font-bold text-[#0f172a]">{formatCurrency(header.subtotal)}</span>
              </div>

              <div className="space-y-0.5">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Line Total</span>
                <span className="text-sm font-bold text-gray-500">{formatCurrency(computedSubtotal)}</span>
              </div>

              {header.discount !== null && header.discount !== 0 && (
                <div className="space-y-0.5">
                  <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Discount</span>
                  <span className="text-sm font-bold text-red-600">-{formatCurrency(header.discount)}</span>
                </div>
              )}
              
              <div className="space-y-0.5">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">GST Total</span>
                <span className="text-sm font-bold text-[#0f172a]">{formatCurrency(computedGstTotal)}</span>
              </div>

              <div className="space-y-0.5">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Grand Total</span>
                <span className="text-base font-extrabold text-[#1b5dfc]">{formatCurrency(header.grand_total)}</span>
              </div>
            </div>

            {/* 2. Math status indicators & verify actions */}
            <div className="flex flex-wrap items-center gap-4">
              
              {/* Math status badge */}
              <div
                className={`flex items-center space-x-1.5 px-3 py-2 rounded-xl text-[10px] font-bold ${
                  mathStatus === 'matched'
                    ? 'bg-green-50 text-green-700 border border-green-200'
                    : 'bg-amber-50 text-amber-700 border border-amber-200'
                }`}
              >
                <Calculator size={14} className={mathStatus === 'matched' ? 'text-green-600' : 'text-amber-600'} />
                <div className="leading-tight text-left">
                  <span className="block font-bold">
                    {mathStatus === 'matched' ? 'Math Status: Matched' : 'Math Status: Needs Review'}
                  </span>
                  <span className="block font-normal text-[9px] text-gray-500">
                    {mathStatusMessage}
                  </span>
                </div>
              </div>

              {/* Controls */}
              <div className="flex items-center space-x-2 shrink-0">
                <button
                  onClick={handleSaveDraft}
                  className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2.5 rounded-xl text-xs border border-gray-200 shadow-sm transition-colors cursor-pointer"
                >
                  Save Draft
                </button>
                <button
                  onClick={handleMarkAsVerified}
                  className="bg-[#1b5dfc] hover:bg-[#154ecb] text-white font-semibold px-4 py-2.5 rounded-xl text-xs shadow-md shadow-blue-500/10 transition-colors cursor-pointer"
                >
                  Mark as Verified
                </button>
              </div>

            </div>

          </div>

          {/* Slide-over Side Drawer details panel for secondary line-item attributes */}
          <div className={`absolute top-0 right-0 h-full w-full sm:w-[450px] bg-white border-l border-gray-200 shadow-2xl z-30 transition-transform duration-300 transform flex flex-col ${selectedItemId ? 'translate-x-0' : 'translate-x-full'}`}>
            {/* Drawer Header */}
            <div className="p-4 border-b border-gray-200 flex items-center justify-between bg-slate-50">
              <div>
                <h4 className="font-bold text-sm text-[#0f172a]">Edit Line Item Details</h4>
                <p className="text-[10px] text-gray-400">Configure secondary and primary fields for verification.</p>
              </div>
              <button
                onClick={() => setSelectedItemId(null)}
                className="text-gray-400 hover:text-gray-600 p-1.5 rounded hover:bg-gray-100 transition-colors cursor-pointer"
                title="Close Drawer"
              >
                <X size={16} />
              </button>
            </div>

            {/* Drawer Body Form */}
            {selectedItem && (
              <div className="flex-1 overflow-y-auto p-5 space-y-4 custom-scrollbar text-xs">
                {/* 2-Column form layout */}
                <div className="grid grid-cols-2 gap-4">
                  {/* Product Name (Span 2) */}
                  <div className="col-span-2 space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Product Name *</label>
                    <input
                      type="text"
                      value={selectedItem.product_name || ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'product_name', e.target.value)}
                      placeholder="—"
                      className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 ${
                        isCriticalItemMissing(selectedItem, 'product_name') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                      }`}
                    />
                  </div>

                  {/* HSN */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">HSN Code *</label>
                    <input
                      type="text"
                      value={selectedItem.hsn || ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'hsn', e.target.value)}
                      placeholder="—"
                      className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 ${
                        isCriticalItemMissing(selectedItem, 'hsn') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                      }`}
                    />
                  </div>

                  {/* Pack */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Pack Size</label>
                    <input
                      type="text"
                      value={selectedItem.pack || ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'pack', e.target.value)}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* Batch */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Batch Number</label>
                    <input
                      type="text"
                      value={selectedItem.batch || ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'batch', e.target.value)}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* Expiry */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Expiry Date</label>
                    <input
                      type="text"
                      value={selectedItem.expiry || ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'expiry', e.target.value)}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* Quantity */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Quantity *</label>
                    <input
                      type="number"
                      value={getLineItemQty(selectedItem) ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'quantity', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 ${
                        isCriticalItemMissing(selectedItem, 'quantity') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                      }`}
                    />
                  </div>

                  {/* Free Quantity */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Free Quantity</label>
                    <input
                      type="number"
                      value={selectedItem.free_quantity ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'free_quantity', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* MRP */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">MRP (Rs)</label>
                    <input
                      type="number"
                      step="any"
                      value={getLineItemMRP(selectedItem) ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'mrp', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* Rate */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Purchase Rate</label>
                    <input
                      type="number"
                      step="any"
                      value={selectedItem.rate ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'rate', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* Discount */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Row Discount</label>
                    <input
                      type="number"
                      step="any"
                      value={selectedItem.discount ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'discount', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* GST % */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">GST %</label>
                    <input
                      type="number"
                      value={selectedItem.gst_percent ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'gst_percent', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* Amount */}
                  <div className="col-span-2 space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Total Amount *</label>
                    <input
                      type="number"
                      step="any"
                      value={getLineItemAmount(selectedItem) ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'amount', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-xs font-semibold text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 ${
                        isCriticalItemMissing(selectedItem, 'amount') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                      }`}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

        </div>

      </div>
    </div>
  );
};

export default InvoiceReviewPage;
