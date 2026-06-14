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
  is_suggested_amount?: boolean;
}

// Helper: Check if a value is present (non-empty string, non-null, non-undefined)
const isPresent = (value: any): boolean => {
  return value !== null && value !== undefined && String(value).trim() !== '';
};

// Helper: Safely parses numeric fields, cleaning currency symbols, returning null on missing/empty values
const toNumberOrNull = (value: any): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const cleaned = String(value).replace(/[₹$,]/g, '').trim();
  if (cleaned === '') return null;
  const num = parseFloat(cleaned);
  return isNaN(num) ? null : num;
};

// Helper: Formats currency displays, returning "—" for missing values
const formatCurrencyOrDash = (value: any): string => {
  const num = toNumberOrNull(value);
  if (num === null) return '—';
  return `₹${num.toFixed(2)}`;
};

const formatQuantityOrDash = (value: any): string => {
  const num = toNumberOrNull(value);
  if (num === null) return '—';
  return num.toFixed(2);
};

// Helper: Billed quantity
const getBilledQty = (item: TableLineItem): number | null => {
  return item.quantity;
};

// Helper: Free quantity
const getFreeQty = (item: TableLineItem): number | null => {
  return item.free_quantity;
};

// Helper: Billed Qty + Free Qty
const getReceivedQty = (item: TableLineItem): number => {
  const billed = item.quantity ?? 0;
  const free = item.free_quantity ?? 0;
  return billed + free;
};

// Helper: Numeric line item amount
const getItemAmount = (item: TableLineItem): number | null => {
  return item.amount;
};

// Helper: Safely extracts amount from various backend fallback keys
const getAmountFromItem = (item: any): any => {
  if (item.amount !== undefined && item.amount !== null && item.amount !== '') return item.amount;
  if (item.line_total !== undefined && item.line_total !== null && item.line_total !== '') return item.line_total;
  if (item.net_amount !== undefined && item.net_amount !== null && item.net_amount !== '') return item.net_amount;
  if (item.value !== undefined && item.value !== null && item.value !== '') return item.value;
  if (item.raw?.amount !== undefined && item.raw?.amount !== null && item.raw?.amount !== '') return item.raw.amount;
  return null;
};

// Helper: Safely normalizes string values, returning empty string on missing/null
const parseOptionalString = (val: any): string => {
  if (val === null || val === undefined) return '';
  return String(val).trim();
};

// Legacy helper compatibility mappings
const parseOptionalFloat = toNumberOrNull;

export const InvoiceReviewPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { runs } = useRun();

  // Selected Run Summary metadata
  const runSummary = runs.find((r) => r.run_id === runId) || null;

  // Zoom & Rotation Preview State for the original scan
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);

  // Image dragging/panning state
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // Raw engine metadata state
  const [rawEngineMetadata, setRawEngineMetadata] = useState<any>(null);

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

  // Mouse handlers for click-drag panning scan image
  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (zoom <= 1) return;
    setIsDragging(true);
    setDragStart({ x: e.clientX - panX, y: e.clientY - panY });
    e.preventDefault();
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDragging || zoom <= 1) return;
    const newPanX = e.clientX - dragStart.x;
    const newPanY = e.clientY - dragStart.y;
    setPanX(newPanX);
    setPanY(newPanY);
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const getCursorClass = () => {
    if (zoom <= 1) return 'cursor-default';
    return isDragging ? 'cursor-grabbing' : 'cursor-grab';
  };

  // Scroll to and focus the first missing critical field
  const handleScrollToFirstMissing = () => {
    const headerFields: (keyof InvoiceHeader)[] = ['invoice_date', 'invoice_number', 'seller_name', 'grand_total'];
    for (const field of headerFields) {
      if (isCriticalHeaderMissing(field)) {
        const el = document.getElementById(`header-${field}`);
        if (el) {
          el.focus();
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }
      }
    }

    for (const item of lineItems) {
      if (isCriticalItemMissing(item, 'product_name')) {
        const el = document.getElementById(`item-name-${item.id}`);
        if (el) {
          el.focus();
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }
      }
      if (isCriticalItemMissing(item, 'batch')) {
        const el = document.getElementById(`item-batch-${item.id}`);
        if (el) {
          el.focus();
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }
      }
      if (isCriticalItemMissing(item, 'hsn')) {
        const el = document.getElementById(`item-hsn-${item.id}`);
        if (el) {
          el.focus();
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }
      }
      if (isCriticalItemMissing(item, 'quantity')) {
        setSelectedItemId(item.id);
        window.setTimeout(() => {
          const el = document.getElementById(`item-quantity-${item.id}`);
          if (el) {
            el.focus();
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }, 0);
        return;
      }
      if (isCriticalItemMissing(item, 'amount')) {
        const el = document.getElementById(`item-amount-${item.id}`);
        if (el) {
          el.focus();
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }
      }
    }
  };

  // Check if critical header fields are missing
  const isCriticalHeaderMissing = (field: keyof InvoiceHeader) => {
    const val = header[field];
    return val === null || val === undefined || val === '';
  };

  // Check if critical line item fields are missing
  const isCriticalItemMissing = (item: TableLineItem, field: keyof TableLineItem) => {
    let val: any = item[field];
    if (field === 'quantity') {
      val = getBilledQty(item);
    } else if (field === 'amount') {
      val = getItemAmount(item);
    }
    return val === null || val === undefined || String(val).trim() === '';
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
      if (isCriticalItemMissing(item, 'batch')) count++;
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
    setZoom(1);
    setRotation(0);
    setPanX(0);
    setPanY(0);
    setIsDragging(false);

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
      setRawEngineMetadata(detail.raw_engine_metadata || null);

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
          const qty = toNumberOrNull(item.quantity !== undefined ? item.quantity : item.qty);
          const rate = toNumberOrNull(item.rate);
          const rawAmount = getAmountFromItem(item);
          let amount = toNumberOrNull(rawAmount);
          let is_suggested_amount = false;

          if (amount === null && qty !== null && rate !== null) {
            const disc = toNumberOrNull(item.discount) || 0;
            amount = parseFloat((qty * rate - disc).toFixed(2));
            is_suggested_amount = true;
          }

          return {
            id: `item-${idx}`,
            product_name: parseOptionalString(item.name || item.product_name || item.product),
            batch: parseOptionalString(item.batch),
            expiry: parseOptionalString(item.expiry),
            hsn: parseOptionalString(item.hsn),
            pack: parseOptionalString(item.pack),
            quantity: qty,
            free_quantity: toNumberOrNull(item.free_quantity),
            mrp: toNumberOrNull(item.mrp),
            rate: rate,
            discount: toNumberOrNull(item.discount),
            gst_percent: toNumberOrNull(item.gst_percent),
            amount: amount,
            is_suggested_amount: is_suggested_amount
          };
        });
      } else if (detail.metadata?.llm_extraction?.items) {
        const rawLlmItems = detail.metadata.llm_extraction.items;
        parsedItems = rawLlmItems.map((item: any, idx: number) => {
          const qty = toNumberOrNull(item.qty !== undefined ? item.qty : item.quantity);
          const rate = toNumberOrNull(item.rate);
          const rawAmount = getAmountFromItem(item);
          let amount = toNumberOrNull(rawAmount);
          let is_suggested_amount = false;

          if (amount === null && qty !== null && rate !== null) {
            const disc = toNumberOrNull(item.discount) || 0;
            amount = parseFloat((qty * rate - disc).toFixed(2));
            is_suggested_amount = true;
          }

          return {
            id: `item-${idx}`,
            product_name: parseOptionalString(item.product_name || item.name),
            batch: parseOptionalString(item.batch),
            expiry: parseOptionalString(item.expiry),
            hsn: parseOptionalString(item.hsn_code || item.hsn),
            pack: parseOptionalString(item.pack),
            quantity: qty,
            free_quantity: toNumberOrNull(item.free_quantity),
            mrp: toNumberOrNull(item.mrp),
            rate: rate,
            discount: toNumberOrNull(item.discount),
            gst_percent: toNumberOrNull(item.gst_percent),
            amount: amount,
            is_suggested_amount: is_suggested_amount
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
            const amountText = cellTextFor('row_total') || cellTextFor('amount') || cellTextFor('value');
            const mrpText = cellTextFor('mrp');
            const discountText = cellTextFor('discount');
            const gstText = cellTextFor('gst_percent');
            const freeQtyText = cellTextFor('free_quantity');

            const qty = toNumberOrNull(qtyText);
            const rate = toNumberOrNull(rateText);
            let amount = toNumberOrNull(amountText);
            let is_suggested_amount = false;

            if (amount === null && qty !== null && rate !== null) {
              const disc = toNumberOrNull(discountText) || 0;
              amount = parseFloat((qty * rate - disc).toFixed(2));
              is_suggested_amount = true;
            }

            return {
              id: `item-${idx}`,
              product_name: parseOptionalString(cellTextFor('product_name') || cellTextFor('product')),
              batch: parseOptionalString(cellTextFor('batch_no') || cellTextFor('batch')),
              expiry: parseOptionalString(cellTextFor('expiry_date') || cellTextFor('expiry')),
              hsn: parseOptionalString(cellTextFor('hsn_code') || cellTextFor('hsn')),
              pack: parseOptionalString(cellTextFor('pack')),
              quantity: qty,
              free_quantity: toNumberOrNull(freeQtyText),
              mrp: toNumberOrNull(mrpText),
              rate: rate,
              discount: toNumberOrNull(discountText),
              gst_percent: toNumberOrNull(gstText),
              amount: amount,
              is_suggested_amount: is_suggested_amount
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

        // Auto-recalculate row amount if Quantity/Rate/Discount changes and amount was missing/suggested
        if (key === 'quantity' || key === 'rate' || key === 'discount') {
          const qty = key === 'quantity' ? toNumberOrNull(value) : item.quantity;
          const rate = key === 'rate' ? toNumberOrNull(value) : item.rate;
          const disc = key === 'discount' ? toNumberOrNull(value) : item.discount;
          
          if (item.amount === null || item.is_suggested_amount) {
            if (qty !== null && rate !== null) {
              updatedItem.amount = parseFloat((qty * rate - (disc || 0)).toFixed(2));
              updatedItem.is_suggested_amount = true;
            } else {
              updatedItem.amount = null;
              updatedItem.is_suggested_amount = false;
            }
          }
        } else if (key === 'amount') {
          // User explicitly edited amount, so it is no longer suggested
          updatedItem.is_suggested_amount = false;
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

  // Prefer header discount, then fall back to metadata discount fields
  const discountVal = header.discount !== null
    ? header.discount
    : toNumberOrNull(rawEngineMetadata?.discount ?? rawEngineMetadata?.summary?.discount ?? rawEngineMetadata?.total_discount);

  // Dynamic calculations: Line Total
  const presentAmounts = lineItems
    .map(item => getItemAmount(item))
    .filter((amt): amt is number => amt !== null && amt !== undefined);

  const computedSubtotal = presentAmounts.length > 0
    ? parseFloat(presentAmounts.reduce((sum, amt) => sum + amt, 0).toFixed(2))
    : null;

  // Dynamic calculations: GST Total (sum of CGST + SGST + IGST)
  const cgstVal = toNumberOrNull(header.cgst);
  const sgstVal = toNumberOrNull(header.sgst);
  const igstVal = toNumberOrNull(header.igst);

  const hasGstValues = cgstVal !== null || sgstVal !== null || igstVal !== null;
  const computedGstTotal = hasGstValues
    ? parseFloat(((cgstVal || 0) + (sgstVal || 0) + (igstVal || 0)).toFixed(2))
    : null;

  // Extract roundoff safely from raw metadata
  const roundoffVal = rawEngineMetadata?.roundoff ?? rawEngineMetadata?.round_off ?? null;
  const roundoff = toNumberOrNull(roundoffVal);

  // Math validation logic (ensures we don't calculate false mismatches)
  const isSuggestedAmtPresent = lineItems.some(item => item.is_suggested_amount);
  const isAnyAmountMissing = lineItems.some(item => !isPresent(getItemAmount(item)));
  const hasMissingGrandTotal = !isPresent(header.grand_total);
  const hasMissingSubtotal = !isPresent(header.subtotal);

  let mathStatus: 'matched' | 'mismatch' | 'missing_fields';
  let mathStatusMessage: string;

  if (isAnyAmountMissing || isSuggestedAmtPresent) {
    mathStatus = 'missing_fields';
    mathStatusMessage = 'Missing item amounts';
  } else if (hasMissingGrandTotal || hasMissingSubtotal) {
    mathStatus = 'missing_fields';
    mathStatusMessage = 'Needs manual review';
  } else {
    const subVal = toNumberOrNull(header.subtotal);
    const discVal = discountVal !== null ? discountVal : 0;
    const gstTotal = computedGstTotal !== null ? computedGstTotal : 0;
    const rOff = roundoff !== null ? roundoff : 0;
    const grandVal = toNumberOrNull(header.grand_total) || 0;

    // Check 1: Vendor Formula (Subtotal - Discount + GST Total + Roundoff = Grand Total)
    let isFormulaMatched = true;
    if (subVal !== null) {
      const calculatedGrand = subVal - discVal + gstTotal + rOff;
      if (Math.abs(calculatedGrand - grandVal) > 2.0) {
        isFormulaMatched = false;
      }
    }

    // Check 2: Line Total comparison with Subtotal
    let isLineTotalMatched = true;
    if (subVal !== null && computedSubtotal !== null) {
      const diffWithSubtotal = Math.abs(computedSubtotal - subVal);
      const diffWithTaxable = Math.abs(computedSubtotal - (subVal - discVal));
      if (diffWithSubtotal > 2.0 && diffWithTaxable > 2.0) {
        isLineTotalMatched = false;
      }
    }

    if (!isFormulaMatched) {
      if (subVal !== null && discountVal === null && Math.abs(subVal + gstTotal + rOff - grandVal) > 2.0) {
        mathStatus = 'mismatch';
        mathStatusMessage = 'Missing discount';
      } else {
        mathStatus = 'mismatch';
        mathStatusMessage = 'Formula mismatch';
      }
    } else if (!isLineTotalMatched) {
      mathStatus = 'mismatch';
      mathStatusMessage = 'Line total differs from subtotal';
    } else {
      mathStatus = 'matched';
      mathStatusMessage = 'Matched';
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
      const inventory = storedInventory ? JSON.parse(storedInventory) : [];

      lineItems.forEach((item) => {
        if (!item.product_name.trim()) return;

        const totalQty = getReceivedQty(item);
        const mrp = item.mrp || 0;
        const gst = item.gst_percent || 0;

        // Check if matching SKU is already in inventory
        const existingIdx = inventory.findIndex(
          (inv: any) =>
            inv.product.toLowerCase().trim() === item.product_name.toLowerCase().trim() &&
            inv.batch.toLowerCase().trim() === (item.batch || 'N/A').toLowerCase().trim()
        );

        if (existingIdx >= 0) {
          inventory[existingIdx].quantity += totalQty;
          inventory[existingIdx].source_invoice = header.invoice_number || runId || 'Unknown';
        } else {
          inventory.push({
            id: `inv-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
            product: item.product_name,
            batch: item.batch || 'N/A',
            expiry: item.expiry || 'N/A',
            quantity: totalQty,
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
        getBilledQty(item),
        item.mrp,
        item.rate,
        item.discount,
        item.gst_percent,
        getItemAmount(item)
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
            <span
              onClick={handleScrollToFirstMissing}
              className="px-2.5 py-1 rounded-full text-[10px] font-bold border bg-red-50 text-red-700 border-red-200 animate-pulse flex items-center space-x-1 cursor-pointer hover:bg-red-100 transition-colors"
            >
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
            onClick={handleSaveDraft}
            className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm transition-colors cursor-pointer"
          >
            Save Draft
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
                className="p-1 hover:bg-white text-gray-600 hover:text-gray-900 rounded transition-colors cursor-pointer"
                title="Zoom In"
              >
                <ZoomIn size={14} />
              </button>
              <button
                onClick={() => {
                  setZoom((z) => {
                    const newZoom = Math.max(0.5, z - 0.15);
                    if (newZoom <= 1) {
                      setPanX(0);
                      setPanY(0);
                    }
                    return newZoom;
                  });
                }}
                className="p-1 hover:bg-white text-gray-600 hover:text-gray-900 rounded transition-colors cursor-pointer"
                title="Zoom Out"
              >
                <ZoomOut size={14} />
              </button>
              <button
                onClick={() => {
                  setZoom(1);
                  setPanX(0);
                  setPanY(0);
                }}
                className="text-[10px] font-bold text-gray-500 px-1 hover:text-gray-800 cursor-pointer"
                title="Reset Zoom"
              >
                100%
              </button>
              <div className="w-px h-3 bg-gray-200" />
              <button
                onClick={() => {
                  setRotation((r) => (r + 90) % 360);
                  setPanX(0);
                  setPanY(0);
                }}
                className="p-1 hover:bg-white text-gray-600 hover:text-gray-900 rounded transition-colors cursor-pointer"
                title="Rotate 90°"
              >
                <RotateCw size={14} />
              </button>
            </div>
          </div>

          {/* Scanner Viewport */}
          <div 
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            className={`bg-[#f8fafc] border border-slate-100 rounded-xl overflow-hidden min-h-[400px] flex items-center justify-center p-4 relative custom-scrollbar ${getCursorClass()}`}
          >
            <div 
              className={`flex items-center justify-center origin-center ${isDragging ? '' : 'transition-transform duration-200'}`}
              style={{
                transform: `translate(${panX}px, ${panY}px) scale(${zoom}) rotate(${rotation}deg)`
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
            <span>Zoom in to drag/pan the invoice. Use toolbar buttons to zoom/rotate.</span>
          </div>
        </div>

        {/* Right Invoice Details and Totals Panel */}
        <div className="lg:col-span-7 bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden relative">
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
                    id="header-invoice_date"
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
                    id="header-invoice_number"
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
                    id="header-seller_name"
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
                    id="header-buyer_name"
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
                    id="header-grand_total"
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

            {/* 2. Standardized Totals Breakdown Card */}
            <div className="space-y-3">
              <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 space-y-4 mt-6">
                <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                  <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                    Totals Breakdown
                  </h4>
                  <span className="text-[10px] text-gray-400 font-semibold uppercase tracking-wider">
                    Standardized Formula
                  </span>
                </div>

                {/* Formula Display */}
                <div className="bg-white border border-slate-100 rounded-lg p-3 text-center shadow-sm">
                  <span className="text-[10px] text-gray-400 font-semibold block mb-1.5 uppercase tracking-wider">Formula</span>
                  <div className="text-xs sm:text-sm font-bold text-gray-700 flex flex-wrap items-center justify-center gap-1">
                    <span>{formatCurrencyOrDash(header.subtotal)}</span>
                    <span className="text-gray-400 font-normal text-[10px]">(Subtotal)</span>
                    <span className="mx-1 text-gray-400">-</span>
                    <span className={discountVal !== null && discountVal > 0 ? "text-red-500" : "text-gray-700"}>
                      {formatCurrencyOrDash(discountVal)}
                    </span>
                    <span className="text-gray-400 font-normal text-[10px]">(Discount)</span>
                    <span className="mx-1 text-gray-400">+</span>
                    <span className="text-green-600">{formatCurrencyOrDash(computedGstTotal)}</span>
                    <span className="text-gray-400 font-normal text-[10px]">(GST Total)</span>
                    {roundoff !== null && roundoff !== 0 && (
                      <>
                        <span className="mx-1 text-gray-400">{roundoff >= 0 ? '+' : '-'}</span>
                        <span className="text-gray-600">{formatCurrencyOrDash(Math.abs(roundoff))}</span>
                        <span className="text-gray-400 font-normal text-[10px]">(Adjustment)</span>
                      </>
                    )}
                    <span className="mx-2 text-gray-400">=</span>
                    <span className="text-[#1b5dfc] font-extrabold text-base">{formatCurrencyOrDash(header.grand_total)}</span>
                  </div>
                </div>

                {/* Totals Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs pt-1">
                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-gray-400 block uppercase tracking-wider">Subtotal</span>
                    <span className="text-sm font-bold text-gray-900">{formatCurrencyOrDash(header.subtotal)}</span>
                  </div>

                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-gray-400 block uppercase tracking-wider">Discount</span>
                    <span className="text-sm font-bold text-red-500">{formatCurrencyOrDash(discountVal)}</span>
                  </div>

                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-gray-400 block uppercase tracking-wider">GST Total</span>
                    <span className="text-sm font-bold text-gray-900">{formatCurrencyOrDash(computedGstTotal)}</span>
                    {hasGstValues && (
                      <div className="text-[9px] text-gray-400 leading-tight space-y-0.5 mt-1">
                        {header.cgst !== null && <div>CGST: {formatCurrencyOrDash(header.cgst)}</div>}
                        {header.sgst !== null && <div>SGST: {formatCurrencyOrDash(header.sgst)}</div>}
                        {header.igst !== null && <div>IGST: {formatCurrencyOrDash(header.igst)}</div>}
                      </div>
                    )}
                  </div>

                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-gray-400 block uppercase tracking-wider">Grand Total</span>
                    <span className="text-sm font-extrabold text-[#1b5dfc]">{formatCurrencyOrDash(header.grand_total)}</span>
                  </div>

                  {/* Line Total (Separate) */}
                  <div className="space-y-1 border-t border-slate-200 pt-3 col-span-2">
                    <span className="text-[10px] font-semibold text-gray-400 block uppercase tracking-wider">Line Items Total</span>
                    <span className="text-sm font-bold text-gray-600">{formatCurrencyOrDash(computedSubtotal)}</span>
                    <span className="text-[9px] text-gray-400 block">Sum of item amounts listed in the table.</span>
                  </div>

                  {/* Roundoff / Adjustment (if present) */}
                  {roundoff !== null && roundoff !== 0 && (
                    <div className="space-y-1 border-t border-slate-200 pt-3 col-span-2">
                      <span className="text-[10px] font-semibold text-gray-400 block uppercase tracking-wider">Adjustment / Roundoff</span>
                      <span className="text-sm font-bold text-gray-600">{formatCurrencyOrDash(roundoff)}</span>
                      <span className="text-[9px] text-gray-400 block">Extracted from raw engine metadata.</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

          </div>

          {/* Slide-over Side Drawer details panel for secondary line-item attributes */}
          <div className={`fixed top-0 right-0 h-screen w-full sm:w-[450px] bg-white border-l border-gray-200 shadow-2xl z-50 transition-transform duration-300 transform flex flex-col ${selectedItemId ? 'translate-x-0' : 'translate-x-full'}`}>
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
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Batch Number *</label>
                    <input
                      type="text"
                      value={selectedItem.batch || ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'batch', e.target.value)}
                      placeholder="—"
                      className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                        isCriticalItemMissing(selectedItem, 'batch') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                      }`}
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

                  {/* Billed Qty */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Billed Qty *</label>
                    <input
                      id={`item-quantity-${selectedItem.id}`}
                      type="number"
                      value={getBilledQty(selectedItem) ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'quantity', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className={`w-full bg-[#f8fafc] border rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 ${
                        isCriticalItemMissing(selectedItem, 'quantity') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                      }`}
                    />
                  </div>

                  {/* Free Qty */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Free Qty</label>
                    <input
                      type="number"
                      value={getFreeQty(selectedItem) ?? ''}
                      onChange={(e) => handleItemChange(selectedItem.id, 'free_quantity', e.target.value === '' ? null : parseFloat(e.target.value))}
                      placeholder="—"
                      className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500"
                    />
                  </div>

                  {/* Total Received Qty (read-only) */}
                  <div className="col-span-2 space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">Total Received Qty</label>
                    <input
                      type="text"
                      readOnly
                      value={getReceivedQty(selectedItem)}
                      className="w-full bg-slate-100 border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-600 font-semibold focus:outline-none"
                    />
                    <span className="text-[10px] text-gray-500 block mt-1">
                      Free quantity is included in received stock but not billed amount.
                    </span>
                  </div>

                  {/* MRP */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">MRP (Rs)</label>
                    <input
                      type="number"
                      step="any"
                      value={selectedItem.mrp ?? ''}
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
                      value={getItemAmount(selectedItem) ?? ''}
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

      {/* Full-width Line Items Review table */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden">
        <div className="p-5 border-b border-gray-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
              Line Items Review ({lineItems.length})
            </h3>
          </div>
          <button
            onClick={handleAddRow}
            className="text-xs font-semibold text-[#1b5dfc] hover:text-[#154ecb] flex items-center space-x-1.5 cursor-pointer"
          >
            <Plus size={14} />
            <span>Add Row</span>
          </button>
        </div>

        <div className="overflow-x-auto custom-scrollbar">
          <div className="max-h-[560px] overflow-y-auto custom-scrollbar">
            <table className="w-full min-w-[1160px] text-left text-xs border-collapse">
              <thead className="bg-[#f8fafc] border-b border-[#e2e8f0] text-gray-500 font-semibold text-[10px] uppercase tracking-wider sticky top-0 z-10">
                <tr>
                  <th className="p-3 pl-5 text-center min-w-[64px]">Sr.</th>
                  <th className="p-3 pl-5 min-w-[320px]">Product Name</th>
                  <th className="p-3 min-w-[140px]">Batch No.</th>
                  <th className="p-3 min-w-[110px]">HSN</th>
                  <th className="p-3 text-right min-w-[135px]">Qty</th>
                  <th className="p-3 text-right min-w-[115px]">MRP</th>
                  <th className="p-3 text-right min-w-[130px]">Amount</th>
                  <th className="p-3 text-center pr-5 min-w-[120px]">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e2e8f0] bg-white">
                {lineItems.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-gray-400 font-medium">
                      No line items found. Click "Add Row" to append items.
                    </td>
                  </tr>
                ) : (
                  lineItems.map((item, index) => {
                    const billedQty = getBilledQty(item);
                    const freeQty = getFreeQty(item);
                    const hasFreeQty = freeQty !== null;
                    const receivedQty = billedQty !== null ? billedQty + (freeQty ?? 0) : null;

                    return (
                      <tr
                        key={item.id}
                        className={`hover:bg-[#f8fafc]/70 transition-colors ${
                          isCriticalItemMissing(item, 'product_name') ||
                          isCriticalItemMissing(item, 'batch') ||
                          isCriticalItemMissing(item, 'hsn') ||
                          isCriticalItemMissing(item, 'quantity') ||
                          isCriticalItemMissing(item, 'amount')
                            ? 'bg-amber-50/20'
                            : ''
                        }`}
                      >
                        <td className="p-3 pl-5 align-top text-center">
                          <span className="inline-flex h-8 min-w-8 items-center justify-center rounded-lg bg-slate-50 px-2 text-xs font-bold text-gray-500">
                            {index + 1}
                          </span>
                        </td>

                        <td className="p-3 pl-5 align-top">
                          <input
                            id={`item-name-${item.id}`}
                            type="text"
                            value={item.product_name}
                            placeholder="—"
                            onChange={(e) => handleItemChange(item.id, 'product_name', e.target.value)}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                              isCriticalItemMissing(item, 'product_name') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                        </td>

                        <td className="p-3 align-top">
                          <input
                            id={`item-batch-${item.id}`}
                            type="text"
                            value={item.batch}
                            placeholder="—"
                            onChange={(e) => handleItemChange(item.id, 'batch', e.target.value)}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                              isCriticalItemMissing(item, 'batch') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                        </td>

                        <td className="p-3 align-top">
                          <input
                            id={`item-hsn-${item.id}`}
                            type="text"
                            value={item.hsn}
                            placeholder="—"
                            onChange={(e) => handleItemChange(item.id, 'hsn', e.target.value)}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                              isCriticalItemMissing(item, 'hsn') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                        </td>

                        <td className="p-3 align-top text-right">
                          <div className="space-y-1">
                            <div
                              className={`text-sm ${
                                billedQty === null ? 'text-amber-700 font-bold' : 'text-[#0f172a] font-extrabold'
                              }`}
                            >
                              {hasFreeQty ? formatQuantityOrDash(receivedQty) : formatQuantityOrDash(billedQty)}
                            </div>
                            {hasFreeQty && (
                              <div className="text-[10px] text-gray-500 whitespace-nowrap">
                                {formatQuantityOrDash(billedQty)} billed + {formatQuantityOrDash(freeQty)} free
                              </div>
                            )}
                          </div>
                        </td>

                        <td className="p-3 align-top text-right">
                          <input
                            id={`item-mrp-${item.id}`}
                            type="number"
                            step="any"
                            value={item.mrp ?? ''}
                            placeholder="—"
                            onChange={(e) => handleItemChange(item.id, 'mrp', e.target.value === '' ? null : parseFloat(e.target.value))}
                            className="w-full min-h-[38px] bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-sm text-right text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors"
                          />
                        </td>

                        <td className="p-3 align-top text-right">
                          <input
                            id={`item-amount-${item.id}`}
                            type="number"
                            step="any"
                            value={getItemAmount(item) ?? ''}
                            placeholder="—"
                            onChange={(e) => handleItemChange(item.id, 'amount', e.target.value === '' ? null : parseFloat(e.target.value))}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-right text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors font-bold ${
                              isCriticalItemMissing(item, 'amount') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                          {item.is_suggested_amount && (
                            <div className="text-[10px] text-amber-600 mt-1 font-semibold">Suggested</div>
                          )}
                        </td>

                        <td className="p-3 pr-5 align-top text-center">
                          <div className="flex items-center justify-center space-x-1.5">
                            <button
                              onClick={() => setSelectedItemId(item.id)}
                              className="px-3 py-2 bg-[#f4f5fa] hover:bg-[#e2e8f0] text-[#1b5dfc] rounded-lg transition-colors cursor-pointer text-xs font-semibold"
                              title="View/Edit Secondary Fields"
                            >
                              Details
                            </button>
                            <button
                              onClick={() => handleDeleteRow(item.id)}
                              className="p-2 text-gray-400 hover:text-red-500 rounded-lg transition-colors cursor-pointer"
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
    </div>
  );
};

export default InvoiceReviewPage;
