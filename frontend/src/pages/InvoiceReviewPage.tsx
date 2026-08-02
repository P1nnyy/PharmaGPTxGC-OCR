import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useRun } from '../context/RunContext';
import {
  ZoomIn,
  ZoomOut,
  RotateCw,
  Plus,
  Trash2,
  CheckCircle,
  FileSpreadsheet,
  AlertTriangle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  Eye,
  Maximize2,
  X,
  Lock,
  Pencil
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
  roundoff: number | null;
  seller_gstin?: string;
  seller_address?: string;
  seller_phone?: string;
  drug_license?: string;
  buyer_gstin?: string;
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
  discount_percent: number | null;
  gst_percent: number | null;
  amount: number | null;
  is_suggested_amount?: boolean;
  bounding_box?: number[];
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

// Helper: Formats a signed currency value (e.g. roundoff), showing an
// explicit +/- since the sign itself is meaningful, unlike other totals.
const formatSignedCurrency = (value: any): string => {
  const num = toNumberOrNull(value);
  if (num === null) return '—';
  const sign = num < 0 ? '-' : num > 0 ? '+' : '';
  return `${sign}₹${Math.abs(num).toFixed(2)}`;
};

const formatQuantityOrDash = (value: any): string => {
  const num = toNumberOrNull(value);
  if (num === null) return '—';
  return num.toFixed(2);
};

// Read-only display for a verified/locked line item cell: an empty field
// means the source invoice genuinely never had that value (not that we
// failed to extract something still fixable), so it's shown as "N/A"
// rather than the "—" edit-mode placeholder that invites the user to type.
const ReadOnlyCell: React.FC<{ value: string | number | null | undefined; align?: 'left' | 'right'; bold?: boolean }> = ({ value, align = 'left', bold = false }) => {
  const isEmpty = value === null || value === undefined || value === '';
  return (
    <div
      className={`w-full min-h-[38px] flex items-center px-3 py-2 text-sm rounded-lg ${
        align === 'right' ? 'justify-end text-right' : ''
      } ${bold ? 'font-bold' : ''} ${isEmpty ? 'text-gray-400 italic' : 'text-[#0f172a]'}`}
    >
      {isEmpty ? 'N/A' : value}
    </div>
  );
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

// Helper: the quantity shown in the Qty column — what actually arrived,
// billed plus free. A "2.75 + 0.25" scheme line means 3 units on the shelf,
// so 3 is the number the reviewer is checking against the physical delivery.
// Returns null (not 0) when nothing is known, so the cell stays blank and
// keeps its missing-field flag.
const getDisplayQty = (item: TableLineItem): number | null => {
  if (item.quantity === null || item.quantity === undefined) {
    return item.free_quantity ?? null;
  }
  return parseFloat((item.quantity + (item.free_quantity ?? 0)).toFixed(4));
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

// (parseOptionalFloat was removed; use toNumberOrNull directly)

export const InvoiceReviewPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { refreshRuns } = useRun();

  // Zoom & Rotation Preview State for the original scan
  const [zoom, setZoom] = useState(1);
  // Rotation is tracked per page, not once per invoice. Sheets of the same
  // invoice are frequently photographed at different angles - on a real
  // two-page bill Azure reported 89.4 deg for page 1 and -0.1 deg for page 2 -
  // so one shared value would leave every page but the first sideways. Keeping
  // it per page also means a manual correction survives paging away and back.
  const [pageRotations, setPageRotations] = useState<number[]>([]);

  // Image dragging/panning state
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // Track actual rendered image size for correct clamp math
  // These are updated on image load and viewport resize via ResizeObserver
  const [imgRenderedW, setImgRenderedW] = useState(0);
  const [imgRenderedH, setImgRenderedH] = useState(0);

  // Raw engine metadata state
  const [rawEngineMetadata, setRawEngineMetadata] = useState<any>(null);

  // Ref for scanner viewport element (overflow:hidden container)
  const viewportRef = useRef<HTMLDivElement>(null);
  // Ref for the actual <img> tag to read rendered dimensions
  const imgRef = useRef<HTMLImageElement>(null);

  // Full-screen Image Lightbox Modal Overlay state
  const [isFullscreenLightboxOpen, setIsFullscreenLightboxOpen] = useState(false);

  // Lightbox has its own independent zoom/pan (separate from the inline preview)
  const [lightboxZoom, setLightboxZoom] = useState(1);
  const [lightboxPanX, setLightboxPanX] = useState(0);
  const [lightboxPanY, setLightboxPanY] = useState(0);
  const [isLightboxDragging, setIsLightboxDragging] = useState(false);
  const [lightboxDragStart, setLightboxDragStart] = useState({ x: 0, y: 0 });
  const lightboxContainerRef = useRef<HTMLDivElement>(null);
  const lightboxImgRef = useRef<HTMLImageElement>(null);
  const lightboxZoomRef = useRef(1);
  useEffect(() => { lightboxZoomRef.current = lightboxZoom; }, [lightboxZoom]);

  const openLightbox = () => {
    setLightboxZoom(1);
    setLightboxPanX(0);
    setLightboxPanY(0);
    setIsFullscreenLightboxOpen(true);
  };

  // Expandable Metadata toggle state
  const [isDetailsExpanded, setIsDetailsExpanded] = useState(false);

  // Track active line item row for Human-like Scan Zooming & Highlighting
  const [activeRowId, setActiveRowId] = useState<string | null>(null);
  const [highlightedRowId, setHighlightedRowId] = useState<string | null>(null);

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
    grand_total: null,
    roundoff: null,
    seller_gstin: '',
    seller_address: '',
    seller_phone: '',
    drug_license: '',
    buyer_gstin: ''
  });

  const [lineItems, setLineItems] = useState<TableLineItem[]>([]);
  const [confidence, setConfidence] = useState(85);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [invoiceStatus, setInvoiceStatus] = useState<'needs_review' | 'verified'>('needs_review');
  const [imageUrl, setImageUrl] = useState<string>('');
  // Multi-page invoices carry one presigned URL per page, in page order.
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [activePage, setActivePage] = useState(0);

  const rotation = pageRotations[activePage] ?? 0;
  const setRotation = (next: number | ((current: number) => number)) => {
    setPageRotations((prev) => {
      const updated = [...prev];
      const current = updated[activePage] ?? 0;
      updated[activePage] = typeof next === 'function' ? next(current) : next;
      return updated;
    });
  };
  const [isSaving, setIsSaving] = useState(false);

  // Verified invoices load locked — editing them (add/delete/edit line items,
  // header fields) requires an explicit unlock click so a saved record can't
  // be casually altered just by opening it from history.
  const [isLocked, setIsLocked] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showUnlockConfirm, setShowUnlockConfirm] = useState(false);

  // ID of the line item currently active in the details side drawer
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);

  // -------------------------------------------------------------------
  // ZOOM MATH: clamp pan using layout dimensions (clientWidth/clientHeight)
  // to avoid exponential scaling bugs from getBoundingClientRect().
  // When rotated 90° or 270°, width and height swap.
  // -------------------------------------------------------------------
  const getClampLimits = useCallback(
    (currentZoom: number) => {
      const vW = viewportRef.current?.clientWidth || 700;
      const vH = viewportRef.current?.clientHeight || 340;
      const natW = imgRef.current?.clientWidth || imgRenderedW || vW;
      const natH = imgRef.current?.clientHeight || imgRenderedH || vH;
      
      const normRot = ((Math.round(rotation / 90) * 90) % 360 + 360) % 360;
      const effW = (normRot === 90 || normRot === 270) ? natH : natW;
      const effH = (normRot === 90 || normRot === 270) ? natW : natH;
      
      const maxPanX = Math.max(0, (effW * currentZoom - vW) / 2);
      const maxPanY = Math.max(0, (effH * currentZoom - vH) / 2);
      return { maxPanX, maxPanY };
    },
    [imgRenderedW, imgRenderedH, rotation]
  );

  const clampPan = useCallback(
    (rawX: number, rawY: number, currentZoom: number) => {
      if (currentZoom <= 1.0) return { panX: 0, panY: 0 };
      const { maxPanX, maxPanY } = getClampLimits(currentZoom);
      return {
        panX: Math.max(-maxPanX, Math.min(maxPanX, rawX)),
        panY: Math.max(-maxPanY, Math.min(maxPanY, rawY)),
      };
    },
    [getClampLimits]
  );

  // Capture layout image dimensions on load and on viewport resize
  const captureImgDimensions = useCallback(() => {
    const img = imgRef.current;
    if (!img) return;
    if (img.clientWidth > 0) {
      setImgRenderedW(img.clientWidth);
      setImgRenderedH(img.clientHeight);
    }
  }, []);

  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    const ro = new ResizeObserver(captureImgDimensions);
    ro.observe(vp);
    return () => ro.disconnect();
  }, [captureImgDimensions]);

  const headerStackRef = useRef<HTMLDivElement>(null);


  // -------------------------------------------------------------------
  // Mouse Wheel / Trackpad Gesture: any wheel scroll while hovered over the
  // image always zooms in/out (panning is via click-drag once zoomed in).
  // -------------------------------------------------------------------
  const zoomRef = useRef(zoom);
  useEffect(() => { zoomRef.current = zoom; }, [zoom]);

  const handleWheelReact = useCallback((e: React.WheelEvent<HTMLDivElement> | WheelEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.deltaY === 0) return;

    const delta = -e.deltaY * 0.012;
    setZoom((prev) => {
      const next = Math.min(10.0, Math.max(0.5, prev + delta));
      if (next <= 1.0) {
        setPanX(0);
        setPanY(0);
      } else {
        setPanX((px) => {
          const { maxPanX } = getClampLimits(next);
          return Math.max(-maxPanX, Math.min(maxPanX, px));
        });
        setPanY((py) => {
          const { maxPanY } = getClampLimits(next);
          return Math.max(-maxPanY, Math.min(maxPanY, py));
        });
      }
      return next;
    });
  }, [getClampLimits]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => handleWheelReact(e);
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, [isLoading, handleWheelReact]);

  // ESC Key Listener for Full-screen Lightbox Modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsFullscreenLightboxOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);



  // -------------------------------------------------------------------
  // Mouse click-drag panning handlers
  // -------------------------------------------------------------------
  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (zoom <= 1) return;
    setIsDragging(true);
    setDragStart({ x: e.clientX - panX, y: e.clientY - panY });
    e.preventDefault();
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDragging || zoom <= 1) return;
    const rawX = e.clientX - dragStart.x;
    const rawY = e.clientY - dragStart.y;
    const { panX: cx, panY: cy } = clampPan(rawX, rawY, zoom);
    setPanX(cx);
    setPanY(cy);
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const getCursorClass = () => {
    if (zoom <= 1) return 'cursor-default';
    return isDragging ? 'cursor-grabbing' : 'cursor-grab';
  };

  // -------------------------------------------------------------------
  // Lightbox zoom/pan — same wheel-always-zooms + drag-to-pan behavior as
  // the inline preview, scoped to the fullscreen modal's own state.
  // -------------------------------------------------------------------
  const getLightboxClampLimits = useCallback(
    (currentZoom: number) => {
      const vW = lightboxContainerRef.current?.clientWidth || window.innerWidth;
      const vH = lightboxContainerRef.current?.clientHeight || window.innerHeight;
      const natW = lightboxImgRef.current?.clientWidth || vW;
      const natH = lightboxImgRef.current?.clientHeight || vH;

      const normRot = ((Math.round(rotation / 90) * 90) % 360 + 360) % 360;
      const effW = (normRot === 90 || normRot === 270) ? natH : natW;
      const effH = (normRot === 90 || normRot === 270) ? natW : natH;

      const maxPanX = Math.max(0, (effW * currentZoom - vW) / 2);
      const maxPanY = Math.max(0, (effH * currentZoom - vH) / 2);
      return { maxPanX, maxPanY };
    },
    [rotation]
  );

  const handleLightboxWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.deltaY === 0) return;

    const delta = -e.deltaY * 0.012;
    setLightboxZoom((prev) => {
      const next = Math.min(10.0, Math.max(1.0, prev + delta));
      if (next <= 1.0) {
        setLightboxPanX(0);
        setLightboxPanY(0);
      } else {
        setLightboxPanX((px) => {
          const { maxPanX } = getLightboxClampLimits(next);
          return Math.max(-maxPanX, Math.min(maxPanX, px));
        });
        setLightboxPanY((py) => {
          const { maxPanY } = getLightboxClampLimits(next);
          return Math.max(-maxPanY, Math.min(maxPanY, py));
        });
      }
      return next;
    });
  }, [getLightboxClampLimits]);

  useEffect(() => {
    if (!isFullscreenLightboxOpen) return;
    const el = lightboxContainerRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => handleLightboxWheel(e);
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, [isFullscreenLightboxOpen, handleLightboxWheel]);

  const handleLightboxMouseDown = (e: React.MouseEvent) => {
    if (lightboxZoomRef.current <= 1) return;
    setIsLightboxDragging(true);
    setLightboxDragStart({ x: e.clientX - lightboxPanX, y: e.clientY - lightboxPanY });
    e.preventDefault();
    e.stopPropagation();
  };

  const handleLightboxMouseMove = (e: React.MouseEvent) => {
    if (!isLightboxDragging || lightboxZoomRef.current <= 1) return;
    const rawX = e.clientX - lightboxDragStart.x;
    const rawY = e.clientY - lightboxDragStart.y;
    const { maxPanX, maxPanY } = getLightboxClampLimits(lightboxZoomRef.current);
    setLightboxPanX(Math.max(-maxPanX, Math.min(maxPanX, rawX)));
    setLightboxPanY(Math.max(-maxPanY, Math.min(maxPanY, rawY)));
  };

  const handleLightboxMouseUp = () => setIsLightboxDragging(false);

  const getLightboxCursorClass = () => {
    if (lightboxZoom <= 1) return 'cursor-zoom-in';
    return isLightboxDragging ? 'cursor-grabbing' : 'cursor-grab';
  };

  // -------------------------------------------------------------------
  // Row click: set active row (auto-zoom disabled as requested)
  // -------------------------------------------------------------------
  const handleRowClick = (itemId: string, _rowIndex?: number) => {
    setActiveRowId(itemId);
  };

  // Missing Fields Anchor Routing (Offset-Aware)
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
      const isMissingName = isCriticalItemMissing(item, 'product_name');
      const isMissingBatch = isCriticalItemMissing(item, 'batch');
      const isMissingHsn = isCriticalItemMissing(item, 'hsn');
      const isMissingQty = isCriticalItemMissing(item, 'quantity');
      const isMissingMrp = isCriticalItemMissing(item, 'mrp');
      const isMissingAmount = isCriticalItemMissing(item, 'amount');

      if (isMissingName || isMissingBatch || isMissingHsn || isMissingQty || isMissingMrp || isMissingAmount) {
        const rowEl = document.getElementById(`item-row-${item.id}`);
        if (rowEl) {
          rowEl.scrollIntoView({ behavior: 'smooth', block: 'center' });

          setHighlightedRowId(item.id);
          window.setTimeout(() => setHighlightedRowId(null), 2500);

          const targetInputId = isMissingName ? `item-name-${item.id}`
            : isMissingBatch ? `item-batch-${item.id}`
            : isMissingHsn ? `item-hsn-${item.id}`
            : isMissingQty ? `item-quantity-${item.id}`
            : isMissingMrp ? `item-mrp-${item.id}`
            : `item-amount-${item.id}`;

          const inputEl = document.getElementById(targetInputId);
          if (inputEl) {
            inputEl.focus();
          }
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
  // Not every invoice format prints an MRP column at all. Treating a blank
  // MRP as missing unconditionally would flag every row on those invoices,
  // so it only counts when the invoice clearly has the column — i.e. at
  // least one row carries a value.
  const invoiceHasMrpColumn = React.useMemo(
    () => lineItems.some((item) => isPresent(item.mrp)),
    [lineItems]
  );

  const isCriticalItemMissing = (item: TableLineItem, field: keyof TableLineItem) => {
    let val: any = item[field];
    if (field === 'quantity') {
      val = getBilledQty(item);
    } else if (field === 'amount') {
      val = getItemAmount(item);
    } else if (field === 'mrp') {
      if (!invoiceHasMrpColumn) return false;
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
      if (isCriticalItemMissing(item, 'mrp')) count++;
      if (isCriticalItemMissing(item, 'amount')) count++;
    });

    return count;
  };

  // Load invoice details from the backend (Neo4j is the source of truth —
  // every tab/device fetches the same record, so nothing goes stale across tabs).
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    setZoom(1);
    setPageRotations([]);
    setPanX(0);
    setPanY(0);
    setIsDragging(false);

    (async () => {
      try {
        const detail: any = await apiClient.getInvoiceDetail(runId);
        if (cancelled) return;

        setRawEngineMetadata(detail);
        setInvoiceStatus(detail.status === 'verified' ? 'verified' : 'needs_review');
        setIsLocked(detail.status === 'verified');
        // Fall back to the single image_url for invoices saved before
        // multi-page support, which have no image_urls array.
        const pageUrls: string[] = Array.isArray(detail.image_urls) && detail.image_urls.length > 0
          ? detail.image_urls
          : (detail.image_url ? [detail.image_url] : []);
        setImageUrls(pageUrls);
        setImageUrl(pageUrls[0] || '');
        setActivePage(0);

        setHeader({
          invoice_number: detail.invoice_number || '',
          invoice_date: detail.invoice_date || '',
          seller_name: detail.seller_name || detail.seller?.name || '',
          buyer_name: detail.buyer_name || '',
          subtotal: detail.subtotal ?? null,
          discount: detail.discount ?? null,
          cgst: detail.cgst ?? null,
          sgst: detail.sgst ?? null,
          igst: detail.igst ?? null,
          grand_total: detail.grand_total ?? null,
          roundoff: detail.roundoff ?? null,
          seller_gstin: detail.seller_gstin || detail.seller?.gstin || '',
          seller_address: detail.seller_address || detail.seller?.address || '',
          seller_phone: detail.seller_phone || detail.seller?.phone || '',
          drug_license: detail.drug_license || detail.seller?.drug_license || '',
          buyer_gstin: detail.buyer_gstin || '',
        });

        // ---- Auto Rotation from Azure Page Angles ----
        // One angle per page so each sheet is uprighted on its own terms.
        // Records saved before per-page angles existed only carry a single
        // page_angle; applying it to page 1 and leaving the rest unrotated is
        // the best available guess for those.
        const toCssRotation = (raw: any): number => {
          const parsed = parseFloat(String(raw));
          if (isNaN(parsed)) return 0;
          // Azure reports counter-clockwise; CSS rotates clockwise.
          const normalized = ((-parsed % 360) + 360) % 360;
          return (Math.round(normalized / 90) * 90) % 360;
        };

        const anglesFromDetail: any[] = Array.isArray(detail.page_angles) && detail.page_angles.length > 0
          ? detail.page_angles
          : [detail.page_angle];
        const initialRotations = pageUrls.map((_, i) => toCssRotation(anglesFromDetail[i]));
        setPageRotations(initialRotations);

        if (detail.confidence !== undefined && detail.confidence !== null) {
          setConfidence(Math.round((toNumberOrNull(detail.confidence) ?? 0.85) * 100));
        }

        // ---- Line Items ----
        const itemsArr: any[] = detail.line_items || [];
        const parsedItems: TableLineItem[] = itemsArr.map((item: any, idx: number) => {
          const amount = toNumberOrNull(getAmountFromItem(item));
          const rate = toNumberOrNull(item.rate);
          const qty = toNumberOrNull(item.quantity);

          // Amounts the invoice didn't state are derived server-side, using a
          // formula inferred from the rows this invoice DID state — the
          // relationship between qty/rate/discount and amount differs per
          // distributor, so it can't be assumed here. is_estimated_amount
          // marks those so they're labelled rather than shown as extracted.
          const is_suggested_amount = Boolean(item.is_estimated_amount);
          const finalAmount = amount;

          return {
            id: item.id ?? `item-${idx + 1}`,
            product_name: parseOptionalString(item.product_name),
            batch: parseOptionalString(item.batch_number ?? item.batch),
            expiry: parseOptionalString(item.expiry_date ?? item.expiry),
            hsn: parseOptionalString(item.hsn),
            pack: parseOptionalString(item.pack),
            quantity: qty,
            free_quantity: toNumberOrNull(item.free_quantity),
            mrp: toNumberOrNull(item.mrp),
            rate: rate,
            discount: toNumberOrNull(item.discount),
            discount_percent: toNumberOrNull(item.discount_percent),
            gst_percent: toNumberOrNull(item.gst_percent),
            amount: finalAmount,
            is_suggested_amount: is_suggested_amount,
            bounding_box: Array.isArray(item.bounding_box) ? item.bounding_box : undefined,
          };
        });

        setLineItems(parsedItems);
        setHeader((prev) => {
          if (!isPresent(prev.subtotal) && parsedItems.length > 0) {
            const sum = parsedItems.reduce((acc, it) => acc + (it.amount || 0), 0);
            return { ...prev, subtotal: sum > 0 ? parseFloat(sum.toFixed(2)) : null };
          }
          return prev;
        });
      } catch (err: any) {
        if (!cancelled) {
          console.error(err);
          setError(err.message || 'Failed to load invoice details.');
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
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
      discount_percent: null,
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

  const roundoff = toNumberOrNull(header.roundoff);

  // Math validation logic (ensures we don't calculate false mismatches)
  const isSuggestedAmtPresent = lineItems.some(item => item.is_suggested_amount);
  const isAnyAmountMissing = lineItems.some(item => !isPresent(getItemAmount(item)));
  const hasMissingGrandTotal = !isPresent(header.grand_total);
  const effectiveSubtotal = isPresent(header.subtotal) ? toNumberOrNull(header.subtotal) : computedSubtotal;
  const hasMissingSubtotal = !isPresent(effectiveSubtotal);

  let mathStatus: 'matched' | 'mismatch' | 'missing_fields';
  let mathStatusMessage: string;

  if (isAnyAmountMissing) {
    mathStatus = 'missing_fields';
    mathStatusMessage = 'Missing item amounts';
  } else if (isSuggestedAmtPresent) {
    // Present, but worked out rather than read off the page. Saying "missing"
    // here contradicts the amounts visible in the table right beside it, and
    // sends the reviewer looking for a blank that isn't there — the thing
    // actually worth their attention is that these are derived.
    mathStatus = 'missing_fields';
    mathStatusMessage = 'Item amounts derived — verify';
  } else if (hasMissingGrandTotal || hasMissingSubtotal) {
    mathStatus = 'missing_fields';
    mathStatusMessage = 'Needs manual review';
  } else {
    const subVal = effectiveSubtotal;
    const discVal = discountVal !== null ? discountVal : 0;
    const gstTotal = computedGstTotal !== null ? computedGstTotal : 0;
    const rOff = roundoff !== null ? roundoff : 0;
    const grandVal = toNumberOrNull(header.grand_total) || 0;

    let isFormulaMatched = true;
    if (subVal !== null) {
      const calculatedGrand = subVal - discVal + gstTotal + rOff;
      if (Math.abs(calculatedGrand - grandVal) > 2.0) {
        isFormulaMatched = false;
      }
    }

    let isLineTotalMatched = true;
    if (subVal !== null && computedSubtotal !== null) {
      const diffWithSubtotal = Math.abs(computedSubtotal - subVal);
      const diffWithTaxable = Math.abs(computedSubtotal - (subVal - discVal));
      // Some invoice formats print a per-item "Amount" that's already
      // tax-inclusive (Taxable + CGST + SGST for that line), rather than a
      // pre-tax gross figure - there, line items sum to grand_total (minus
      // roundoff) instead of to subtotal or the taxable amount. Line items
      // aren't wrong just because they don't match one particular formula;
      // matching any of the three is a genuine reconciliation.
      const diffWithGrandTotal = Math.abs(computedSubtotal - (grandVal - rOff));
      if (diffWithSubtotal > 2.0 && diffWithTaxable > 2.0 && diffWithGrandTotal > 2.0) {
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

  // Builds the PATCH payload shared by Save Draft / Mark as Verified — the
  // backend is the single source of truth, so both actions just persist the
  // current edited state there instead of to this browser's localStorage.
  const buildUpdatePayload = (status?: 'needs_review' | 'verified') => ({
    invoice_number: header.invoice_number || null,
    invoice_date: header.invoice_date || null,
    seller_name: header.seller_name || null,
    seller_gstin: header.seller_gstin || null,
    seller_address: header.seller_address || null,
    seller_phone: header.seller_phone || null,
    drug_license: header.drug_license || null,
    subtotal: effectiveSubtotal,
    discount: header.discount,
    cgst: header.cgst,
    sgst: header.sgst,
    igst: header.igst,
    grand_total: header.grand_total,
    roundoff: header.roundoff,
    ...(status ? { status } : {}),
    line_items: lineItems.map((item) => ({
      name: item.product_name || null,
      pack: item.pack || null,
      batch: item.batch || null,
      expiry: item.expiry || null,
      hsn: item.hsn || null,
      quantity: item.quantity,
      free_quantity: item.free_quantity,
      mrp: item.mrp,
      rate: item.rate,
      discount: item.discount,
      discount_percent: item.discount_percent,
      gst_percent: item.gst_percent,
      amount: item.amount,
      is_estimated_amount: item.is_suggested_amount ?? false,
      bounding_box: item.bounding_box ?? null,
    })),
  });

  // Save changes without changing verification status
  const handleSaveDraft = async () => {
    if (!runId) return;
    setIsSaving(true);
    try {
      await apiClient.updateInvoice(runId, buildUpdatePayload());
      await refreshRuns();
      alert('Draft saved successfully.');
    } catch (e: any) {
      alert('Failed to save draft: ' + (e.message || String(e)));
    } finally {
      setIsSaving(false);
    }
  };

  // Mark invoice as Verified
  const handleMarkAsVerified = async () => {
    if (!runId) return;
    setIsSaving(true);
    try {
      await apiClient.updateInvoice(runId, buildUpdatePayload('verified'));
      setInvoiceStatus('verified');

      // Keep the local inventory rollup (not yet migrated to the backend)
      // in sync with the verified line items.
      const storedInventory = localStorage.getItem('pharmaflow_inventory');
      const inventory = storedInventory ? JSON.parse(storedInventory) : [];

      lineItems.forEach((item) => {
        if (!item.product_name.trim()) return;

        const totalQty = getReceivedQty(item);
        const mrp = item.mrp || 0;
        const gst = item.gst_percent || 0;

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
      await refreshRuns();
      navigate('/history');
    } catch (e: any) {
      alert('Failed to verify invoice: ' + (e.message || String(e)));
    } finally {
      setIsSaving(false);
    }
  };

  // Permanently delete this invoice from the backend
  const handleDeleteInvoice = async () => {
    if (!runId) return;
    setIsDeleting(true);
    try {
      await apiClient.deleteInvoice(runId);
      await refreshRuns();
      navigate('/history');
    } catch (e: any) {
      alert('Failed to delete invoice: ' + (e.message || String(e)));
      setIsDeleting(false);
      setShowDeleteConfirm(false);
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

  // Get source image — a presigned R2 URL from the backend, refreshed on every
  // load. For a multi-page invoice this is whichever page is being viewed.
  const getSourceImage = () => {
    return imageUrls[activePage] ?? imageUrl;
  };

  const pageCount = imageUrls.length;
  const isMultiPage = pageCount > 1;

  // Changing page resets the view transform: zoom/pan from one page means
  // nothing on the next, which may be a different size or orientation.
  const goToPage = (index: number) => {
    if (index < 0 || index >= pageCount) return;
    setActivePage(index);
    // Zoom and pan are position-specific and meaningless on another sheet,
    // but rotation belongs to the page and is preserved.
    setZoom(1);
    setPanX(0);
    setPanY(0);
  };

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
    <div className="space-y-3">

      {/* ===================================================================
          SCROLLABLE TITLE ROW — not sticky, scrolls away to reclaim space
          ================================================================ */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-1">
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 className="text-lg font-bold text-[#0f172a]">
            Reviewing Invoice {header.invoice_number ? `#${header.invoice_number}` : ''}
          </h2>

          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
            confidence >= 85
              ? 'bg-green-50 text-green-700 border-green-200'
              : 'bg-amber-50 text-amber-700 border-amber-200'
          }`}>
            Confidence: {confidence}%
          </span>

          {invoiceStatus === 'verified' && (
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold border bg-green-50 text-green-700 border-green-200 flex items-center space-x-1">
              <CheckCircle size={10} />
              <span>Verified</span>
            </span>
          )}

          {isLocked && (
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold border bg-slate-100 text-slate-600 border-slate-200 flex items-center space-x-1">
              <Lock size={10} />
              <span>Locked</span>
            </span>
          )}

          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
            mathStatus === 'matched'
              ? 'bg-green-50 text-green-700 border-green-200'
              : mathStatus === 'missing_fields'
                ? 'bg-amber-50 text-amber-700 border-amber-200'
                : 'bg-red-50 text-red-700 border-red-200'
          }`}>
            Math: {mathStatusMessage}
          </span>

          {getMissingFieldsCount() > 0 && (
            <span
              onClick={handleScrollToFirstMissing}
              className="px-2 py-0.5 rounded-full text-[10px] font-bold border bg-red-50 text-red-700 border-red-200 animate-pulse flex items-center space-x-1 cursor-pointer hover:bg-red-100 transition-colors"
              title="Click to jump to first missing field"
            >
              <AlertTriangle size={10} />
              <span>Missing Fields: {getMissingFieldsCount()}</span>
            </span>
          )}
        </div>

        <div className="flex items-center space-x-2.5">
          <button
            onClick={() => setShowDeleteConfirm(true)}
            title="Delete this invoice"
            className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-xl transition-colors cursor-pointer"
          >
            <Trash2 size={15} />
          </button>
          <button
            onClick={handleExportExcel}
            className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-3 py-1.5 rounded-xl text-xs border border-gray-200 flex items-center space-x-1.5 shadow-xs transition-colors cursor-pointer"
          >
            <FileSpreadsheet size={13} className="text-green-600" />
            <span>Export Excel</span>
          </button>
          {isLocked ? (
            <button
              onClick={() => setShowUnlockConfirm(true)}
              className="bg-white hover:bg-amber-50 text-amber-700 font-semibold px-3 py-1.5 rounded-xl text-xs border border-amber-200 flex items-center space-x-1.5 shadow-xs transition-colors cursor-pointer"
            >
              <Pencil size={13} />
              <span>Edit Invoice</span>
            </button>
          ) : (
            <>
              <button
                onClick={handleSaveDraft}
                disabled={isSaving}
                className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-3 py-1.5 rounded-xl text-xs border border-gray-200 shadow-xs transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSaving ? 'Saving…' : 'Save Draft'}
              </button>
              <button
                onClick={handleMarkAsVerified}
                disabled={isSaving || invoiceStatus === 'verified'}
                className={`font-semibold px-3.5 py-1.5 rounded-xl text-xs flex items-center space-x-1.5 shadow-md transition-colors ${
                  invoiceStatus === 'verified'
                    ? 'bg-green-50 text-green-700 border border-green-200 cursor-default shadow-none'
                    : 'bg-[#1b5dfc] hover:bg-[#154ecb] text-white shadow-blue-500/10 cursor-pointer disabled:opacity-50'
                }`}
              >
                <CheckCircle size={13} />
                <span>{invoiceStatus === 'verified' ? 'Verified' : isSaving ? 'Saving…' : 'Mark as Verified'}</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* Unlock Confirmation Dialog — editing a verified invoice takes a
          deliberate extra step so it can't happen by accident */}
      {showUnlockConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs">
          <div className="bg-white rounded-2xl border border-gray-200 p-6 max-w-md w-full mx-4 shadow-xl space-y-4">
            <div className="flex items-start space-x-3">
              <div className="p-2 bg-amber-50 text-amber-600 rounded-xl shrink-0">
                <Lock size={22} />
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-bold text-[#0f172a]">Edit this verified invoice?</h3>
                <p className="text-xs text-gray-500 leading-normal">
                  This invoice was already verified. Unlocking lets you add, remove, or change line items and header
                  fields. Only do this if you're sure the correction is needed.
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end space-x-2 pt-2 border-t border-gray-100">
              <button
                onClick={() => setShowUnlockConfirm(false)}
                className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setIsLocked(false);
                  setShowUnlockConfirm(false);
                }}
                className="bg-amber-600 hover:bg-amber-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md shadow-amber-500/10 transition-colors cursor-pointer"
              >
                Unlock & Edit
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===================================================================
          STICKY HEADER BLOCK — sticks when it reaches top of <main>
          Contains: scan preview + quick summary side-by-side
          The SaaSLayout <main> has overflow-y-auto so sticky:top-0 works
          inside that scroll container.
          ================================================================ */}
      <div
        ref={headerStackRef}
        className="sticky top-0 z-30 bg-[#f4f5fa] pt-1 pb-3 flex flex-col gap-3 border-b border-slate-200 shadow-sm"
        style={{
          marginLeft: '-1.5rem',
          marginRight: '-1.5rem',
          paddingLeft: '1.5rem',
          paddingRight: '1.5rem',
          maxHeight: 'calc(100vh - 88px)',
        }}
      >
        {/* Two Panel Layout Grid */}
        <div className="shrink-0 grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">

          {/* Left Scan Preview Panel (8 of 12 columns) */}
          <div className="lg:col-span-8 bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-xs flex flex-col">
            {/* Dark Header bar */}
            <div className="bg-slate-900 text-white px-3.5 py-2 flex items-center justify-between shrink-0">
              <div className="flex items-center space-x-3 min-w-0">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-200">ORIGINAL SCAN</span>
                {isMultiPage && (
                  <div className="flex items-center space-x-1 shrink-0">
                    <button
                      onClick={() => goToPage(activePage - 1)}
                      disabled={activePage === 0}
                      className="p-1 rounded text-slate-300 hover:bg-slate-800 hover:text-white transition-colors cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                      title="Previous page"
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <span className="text-[10px] font-semibold text-slate-300 tabular-nums px-1">
                      Page {activePage + 1} / {pageCount}
                    </span>
                    <button
                      onClick={() => goToPage(activePage + 1)}
                      disabled={activePage >= pageCount - 1}
                      className="p-1 rounded text-slate-300 hover:bg-slate-800 hover:text-white transition-colors cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                      title="Next page"
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                )}
              </div>
              <div className="flex items-center space-x-2">
                <button
                  onClick={() => setZoom((z) => Math.min(10.0, z + 0.25))}
                  className="p-1 hover:bg-slate-800 text-slate-300 hover:text-white rounded transition-colors cursor-pointer"
                  title="Zoom In"
                >
                  <ZoomIn size={14} />
                </button>
                <button
                  onClick={() => {
                    setZoom((z) => {
                      const newZoom = Math.max(0.5, z - 0.25);
                      if (newZoom <= 1) { setPanX(0); setPanY(0); }
                      return newZoom;
                    });
                  }}
                  className="p-1 hover:bg-slate-800 text-slate-300 hover:text-white rounded transition-colors cursor-pointer"
                  title="Zoom Out"
                >
                  <ZoomOut size={14} />
                </button>
                <button
                  onClick={() => { setZoom(1); setPanX(0); setPanY(0); }}
                  className="text-[10px] font-bold text-slate-400 px-1 hover:text-white cursor-pointer"
                  title="Reset Zoom"
                >
                  100%
                </button>
                <div className="w-px h-3 bg-slate-700" />
                <button
                  onClick={() => {
                    setRotation((r) => (r + 90) % 360);
                    setPanX(0);
                    setPanY(0);
                  }}
                  className="p-1 hover:bg-slate-800 text-slate-300 hover:text-white rounded transition-colors cursor-pointer"
                  title="Rotate 90°"
                >
                  <RotateCw size={14} />
                </button>
                <div className="w-px h-3 bg-slate-700" />
                <button
                  onClick={openLightbox}
                  className="p-1 hover:bg-slate-800 text-slate-300 hover:text-white rounded transition-colors cursor-pointer"
                  title="Expand Full Image"
                >
                  <Maximize2 size={14} />
                </button>
              </div>
            </div>

            {/* Viewport Box */}
            <div
              ref={viewportRef}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              onDoubleClick={openLightbox}
              className={`bg-slate-100 overflow-hidden flex-1 flex items-center justify-center relative select-none ${getCursorClass()}`}
              style={{ minHeight: '340px', maxHeight: '460px' }}
            >
              <div
                style={{
                  transform: `translate(${panX}px, ${panY}px) scale(${zoom}) rotate(${rotation}deg)`,
                  transformOrigin: 'center center',
                  transition: 'transform 0.15s ease-out',
                  willChange: 'transform',
                }}
              >
                <img
                  ref={imgRef}
                  src={getSourceImage()}
                  alt="Invoice Scan"
                  onLoad={captureImgDimensions}
                  draggable={false}
                  style={{
                    maxHeight: '440px',
                    maxWidth: '100%',
                    objectFit: 'contain',
                    display: 'block',
                    borderRadius: '4px',
                    boxShadow: '0 2px 12px rgba(0,0,0,0.18)',
                    userSelect: 'none',
                    pointerEvents: 'none',
                  }}
                  onError={(e) => {
                    console.error('Image source loading issue:', e);
                  }}
                />
              </div>
            </div>
          </div>

          {/* Right Quick Summary Card (4 of 12 columns) */}
          <div className="lg:col-span-4 bg-[#f8fafc] rounded-2xl border border-slate-200/80 p-4 shadow-xs flex flex-col justify-between space-y-4">
            <h3 className="text-sm font-bold text-slate-800 border-b border-slate-200/60 pb-2">
              Quick Summary
            </h3>

            {/* Metrics List */}
            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-gray-500 font-medium">Subtotal</span>
                <span className="font-semibold text-slate-800">{formatCurrencyOrDash(effectiveSubtotal)}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-500 font-medium">Tax ({header.cgst !== null || header.sgst !== null || header.igst !== null ? 'GST' : '12%'}) +</span>
                <span className="font-semibold text-slate-800">{formatCurrencyOrDash(computedGstTotal)}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-500 font-medium">Discount -</span>
                <span className="font-semibold text-slate-800">{formatCurrencyOrDash(discountVal)}</span>
              </div>

              {roundoff !== null && (
                <div className="flex items-center justify-between">
                  <span className="text-gray-500 font-medium">Round Off</span>
                  <span className="font-semibold text-slate-800">{formatSignedCurrency(roundoff)}</span>
                </div>
              )}

              <div className="border-t border-slate-200/80 pt-2 flex items-center justify-between">
                <span className="font-bold text-slate-900 text-sm">Grand Total</span>
                <span className="font-extrabold text-[#1b5dfc] text-base">{formatCurrencyOrDash(header.grand_total)}</span>
              </div>
            </div>

            {/* Summary Footer & Embedded View Invoice Details Button */}
            <div className="border-t border-slate-200/80 pt-3 space-y-2">
              <div className="space-y-1 text-[11px]">
                <div className="flex items-center justify-between">
                  <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wider">DATE</span>
                  <span className="font-semibold text-slate-700">{header.invoice_date || '—'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wider">SELLER</span>
                  <span className="font-semibold text-slate-700 truncate max-w-[140px] text-right" title={header.seller_name}>
                    {header.seller_name || '—'}
                  </span>
                </div>
              </div>

              {/* View Invoice Details Toggle Button */}
              <button
                type="button"
                onClick={() => setIsDetailsExpanded(!isDetailsExpanded)}
                className="w-full mt-2 bg-[#eef2ff] hover:bg-[#e0e7ff] text-[#1b5dfc] font-semibold text-xs py-2 rounded-xl border border-blue-200/60 transition-colors shadow-xs flex items-center justify-center space-x-1.5 cursor-pointer"
              >
                <Eye size={13} />
                <span>{isDetailsExpanded ? 'Hide Details' : 'View Invoice Details'}</span>
                {isDetailsExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </button>
            </div>
          </div>
        </div>

        {/* Full-width Expandable Invoice Details Metadata Panel */}
        <div className={`shrink-0 transition-all duration-300 ease-in-out overflow-hidden ${
          isDetailsExpanded ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0'
        }`}>
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-xs space-y-3">
            <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider border-b border-gray-100 pb-2">
              All Invoice Metadata
            </h4>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              {/* Invoice Date */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">INVOICE DATE</span>
                <input
                  id="header-invoice_date"
                  type="text"
                  value={header.invoice_date}
                  onChange={(e) => handleHeaderChange('invoice_date', e.target.value)}
                  placeholder="—"
                  disabled={isLocked}
                  className={`w-full bg-[#f8fafc] border rounded-lg px-2.5 py-1.5 text-xs font-semibold text-[#0f172a] disabled:opacity-60 disabled:cursor-not-allowed ${
                    isCriticalHeaderMissing('invoice_date') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                  }`}
                />
              </div>

              {/* Invoice Number */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">INVOICE NUMBER</span>
                <input
                  id="header-invoice_number"
                  type="text"
                  value={header.invoice_number}
                  onChange={(e) => handleHeaderChange('invoice_number', e.target.value)}
                  placeholder="—"
                  disabled={isLocked}
                  className={`w-full bg-[#f8fafc] border rounded-lg px-2.5 py-1.5 text-xs font-semibold text-[#1b5dfc] disabled:opacity-60 disabled:cursor-not-allowed ${
                    isCriticalHeaderMissing('invoice_number') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                  }`}
                />
              </div>

              {/* Seller Name */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">SELLER NAME</span>
                <input
                  id="header-seller_name"
                  type="text"
                  value={header.seller_name}
                  onChange={(e) => handleHeaderChange('seller_name', e.target.value)}
                  placeholder="—"
                  disabled={isLocked}
                  className={`w-full bg-[#f8fafc] border rounded-lg px-2.5 py-1.5 text-xs font-semibold text-[#0f172a] disabled:opacity-60 disabled:cursor-not-allowed ${
                    isCriticalHeaderMissing('seller_name') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                  }`}
                />
              </div>

              {/* Seller Phone */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">SELLER PHONE</span>
                <input
                  type="text"
                  value={header.seller_phone || ''}
                  onChange={(e) => handleHeaderChange('seller_phone', e.target.value)}
                  placeholder="—"
                  disabled={isLocked}
                  className="w-full bg-[#f8fafc] border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs text-[#0f172a] disabled:opacity-60 disabled:cursor-not-allowed"
                />
              </div>

              {/* GST No. */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">GST NO.</span>
                <input
                  type="text"
                  value={header.seller_gstin || ''}
                  onChange={(e) => handleHeaderChange('seller_gstin', e.target.value)}
                  placeholder="—"
                  disabled={isLocked}
                  className={`w-full bg-[#f8fafc] border rounded-lg px-2.5 py-1.5 text-xs text-[#0f172a] disabled:opacity-60 disabled:cursor-not-allowed ${
                    !header.seller_gstin ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                  }`}
                />
              </div>

              {/* Drug Lic. Number */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">DRUG LIC. NUMBER</span>
                <input
                  type="text"
                  value={header.drug_license || ''}
                  onChange={(e) => handleHeaderChange('drug_license', e.target.value)}
                  placeholder="—"
                  disabled={isLocked}
                  className={`w-full bg-[#f8fafc] border rounded-lg px-2.5 py-1.5 text-xs text-[#0f172a] disabled:opacity-60 disabled:cursor-not-allowed ${
                    !header.drug_license ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                  }`}
                />
              </div>

              {/* Address */}
              <div className="col-span-2 space-y-1">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">ADDRESS</span>
                <input
                  type="text"
                  value={header.seller_address || ''}
                  onChange={(e) => handleHeaderChange('seller_address', e.target.value)}
                  placeholder="—"
                  disabled={isLocked}
                  className={`w-full bg-[#f8fafc] border rounded-lg px-2.5 py-1.5 text-xs text-[#0f172a] disabled:opacity-60 disabled:cursor-not-allowed ${
                    !header.seller_address ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                  }`}
                />
              </div>
            </div>
          </div>
        </div>

        {/* ===================================================================
            LINE ITEMS CARD — title bar + table merged into one seamless,
            flex-1 card so it fills whatever space remains under the sticky
            scan/summary section, with only the row body scrolling internally.
            ================================================================ */}
        <div className="flex-1 min-h-0 flex flex-col bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden mb-8">
          <div className="shrink-0 p-4 flex items-center justify-between border-b border-[#e2e8f0]">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
              Line Items Review ({lineItems.length})
            </h3>
            <button
              onClick={handleAddRow}
              disabled={isLocked}
              className="text-xs font-semibold text-[#1b5dfc] hover:text-[#154ecb] flex items-center space-x-1.5 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-[#1b5dfc]"
            >
              <Plus size={14} />
              <span>Add Row</span>
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-auto custom-scrollbar">
          <table className="w-full min-w-[1160px] text-left text-xs border-collapse">
            <thead
              className="sticky top-0 z-20 bg-[#f8fafc] text-gray-500 font-semibold text-[10px] uppercase tracking-wider shadow-xs border-b border-[#e2e8f0]"
            >
              <tr>
                <th className="p-3 pl-5 text-center min-w-[64px]">Sr.</th>
                <th className="p-3 pl-5 min-w-[320px]">Product Name</th>
                <th className="p-3 min-w-[140px]">Batch No.</th>
                <th className="p-3 min-w-[110px]">HSN</th>
                <th className="p-3 text-right min-w-[135px]">Qty</th>
                <th className="p-3 text-right min-w-[115px]">MRP</th>
                <th className="p-3 text-right min-w-[130px]">Amount</th>
                {!isLocked && (
                  <th className="p-3 text-center pr-5 min-w-[120px]">Action</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0] bg-white">
              {lineItems.length === 0 ? (
                <tr>
                  <td colSpan={isLocked ? 7 : 8} className="text-center py-12 text-gray-400 font-medium">
                    No line items found. Click "Add Row" to append items.
                  </td>
                </tr>
              ) : (
                lineItems.map((item, index) => {
                  const billedQty = getBilledQty(item);
                  const freeQty = getFreeQty(item);
                  const hasFreeQty = freeQty !== null && freeQty > 0;
                  const receivedQty = billedQty !== null ? billedQty + (freeQty ?? 0) : null;

                  // Row has any missing critical field → amber tint
                  const hasMissing =
                    isCriticalItemMissing(item, 'product_name') ||
                    isCriticalItemMissing(item, 'batch') ||
                    isCriticalItemMissing(item, 'hsn') ||
                    isCriticalItemMissing(item, 'quantity') ||
                    isCriticalItemMissing(item, 'mrp') ||
                    isCriticalItemMissing(item, 'amount');

                  return (
                    <tr
                      key={item.id}
                      id={`item-row-${item.id}`}
                      onClick={() => handleRowClick(item.id, index)}
                      className={`cursor-pointer transition-all duration-200 ${
                        item.id === activeRowId
                          ? 'bg-blue-50/70 shadow-[inset_3px_0_0_#3b82f6]'
                          : item.id === highlightedRowId
                            ? 'bg-amber-100/90 shadow-[inset_3px_0_0_#f59e0b] animate-pulse'
                            : hasMissing
                              ? 'bg-amber-50/40 shadow-[inset_3px_0_0_#fbbf24] hover:bg-amber-50/70'
                              : 'hover:bg-[#f8fafc]/90'
                      }`}
                    >
                      <td className="p-3 pl-5 align-top text-center">
                        <span className="inline-flex h-8 min-w-8 items-center justify-center rounded-lg bg-slate-50 px-2 text-xs font-bold text-gray-500">
                          {index + 1}
                        </span>
                      </td>

                      <td className="p-3 pl-5 align-top">
                        {isLocked ? (
                          <ReadOnlyCell value={item.product_name} />
                        ) : (
                          <input
                            id={`item-name-${item.id}`}
                            type="text"
                            value={item.product_name}
                            placeholder={hasMissing && !item.product_name ? 'Enter product name...' : '—'}
                            onFocus={() => handleRowClick(item.id, index)}
                            onChange={(e) => handleItemChange(item.id, 'product_name', e.target.value)}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                              isCriticalItemMissing(item, 'product_name') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                        )}
                      </td>

                      <td className="p-3 align-top">
                        {isLocked ? (
                          <ReadOnlyCell value={item.batch} />
                        ) : (
                          <input
                            id={`item-batch-${item.id}`}
                            type="text"
                            value={item.batch}
                            placeholder="—"
                            onFocus={() => handleRowClick(item.id, index)}
                            onChange={(e) => handleItemChange(item.id, 'batch', e.target.value)}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                              isCriticalItemMissing(item, 'batch') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                        )}
                      </td>

                      <td className="p-3 align-top">
                        {isLocked ? (
                          <ReadOnlyCell value={item.hsn} />
                        ) : (
                          <input
                            id={`item-hsn-${item.id}`}
                            type="text"
                            value={item.hsn}
                            placeholder="—"
                            onFocus={() => handleRowClick(item.id, index)}
                            onChange={(e) => handleItemChange(item.id, 'hsn', e.target.value)}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                              isCriticalItemMissing(item, 'hsn') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                        )}
                      </td>

                      <td className="p-3 align-top text-right">
                        <div className="space-y-1">
                          {isLocked ? (
                            <ReadOnlyCell value={getDisplayQty(item)} align="right" bold />
                          ) : (
                            <input
                              id={`item-quantity-${item.id}`}
                              type="number"
                              step="any"
                              value={getDisplayQty(item) ?? ''}
                              placeholder="—"
                              onFocus={() => handleRowClick(item.id, index)}
                              // The field shows what arrived (billed + free), so an
                              // edit is a correction to that total; the free portion
                              // is held steady and the billed quantity absorbs the
                              // change. With no free quantity this is a plain edit.
                              onChange={(e) => {
                                if (e.target.value === '') {
                                  handleItemChange(item.id, 'quantity', null);
                                  return;
                                }
                                const total = parseFloat(e.target.value);
                                if (Number.isNaN(total)) return;
                                const free = item.free_quantity ?? 0;
                                handleItemChange(
                                  item.id,
                                  'quantity',
                                  parseFloat((total - free).toFixed(4))
                                );
                              }}
                              className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-right font-extrabold focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                                isCriticalItemMissing(item, 'quantity') ? 'border-amber-300 bg-amber-50/50 text-amber-700' : 'border-gray-200 text-[#0f172a]'
                              }`}
                            />
                          )}
                          {hasFreeQty && (
                            <div className="text-[10px] text-gray-500 whitespace-nowrap text-right">
                              {formatQuantityOrDash(billedQty)} billed + {formatQuantityOrDash(freeQty)} free = {formatQuantityOrDash(receivedQty)}
                            </div>
                          )}
                        </div>
                      </td>

                      <td className="p-3 align-top text-right">
                        {isLocked ? (
                          <ReadOnlyCell value={item.mrp ?? null} align="right" />
                        ) : (
                          <input
                            id={`item-mrp-${item.id}`}
                            type="number"
                            step="any"
                            value={item.mrp ?? ''}
                            placeholder="—"
                            onFocus={() => handleRowClick(item.id, index)}
                            onChange={(e) => handleItemChange(item.id, 'mrp', e.target.value === '' ? null : parseFloat(e.target.value))}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-right text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors ${
                              isCriticalItemMissing(item, 'mrp') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                        )}
                      </td>

                      <td className="p-3 align-top text-right">
                        {isLocked ? (
                          <ReadOnlyCell value={getItemAmount(item) ?? null} align="right" bold />
                        ) : (
                          <input
                            id={`item-amount-${item.id}`}
                            type="number"
                            step="any"
                            value={getItemAmount(item) ?? ''}
                            placeholder="—"
                            onFocus={() => handleRowClick(item.id, index)}
                            onChange={(e) => handleItemChange(item.id, 'amount', e.target.value === '' ? null : parseFloat(e.target.value))}
                            className={`w-full min-h-[38px] bg-[#f8fafc] border rounded-lg px-3 py-2 text-sm text-right text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-colors font-bold ${
                              isCriticalItemMissing(item, 'amount') ? 'border-amber-300 bg-amber-50/50' : 'border-gray-200'
                            }`}
                          />
                        )}
                        {item.is_suggested_amount && (
                          <div className="text-[10px] text-amber-600 mt-1 font-semibold">Suggested</div>
                        )}
                      </td>

                      {!isLocked && (
                        <td className="p-3 pr-5 align-top text-center">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteRow(item.id);
                            }}
                            className="p-2 text-gray-400 hover:text-red-500 rounded-lg transition-colors cursor-pointer"
                            title="Delete Row"
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
      </div>
      {/* END STICKY HEADER BLOCK */}

      {/* Delete Invoice Confirmation Dialog */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs">
          <div className="bg-white rounded-2xl border border-gray-200 p-6 max-w-md w-full mx-4 shadow-xl space-y-4">
            <div className="flex items-start space-x-3">
              <div className="p-2 bg-red-50 text-red-600 rounded-xl shrink-0">
                <Trash2 size={22} />
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-bold text-[#0f172a]">Delete this invoice?</h3>
                <p className="text-xs text-gray-500 leading-normal">
                  This permanently removes invoice {header.invoice_number ? `#${header.invoice_number}` : ''} and its scanned image. This cannot be undone.
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end space-x-2 pt-2 border-t border-gray-100">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                disabled={isDeleting}
                className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm transition-colors cursor-pointer disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteInvoice}
                disabled={isDeleting}
                className="bg-red-600 hover:bg-red-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md shadow-red-500/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isDeleting ? 'Deleting…' : 'Delete Invoice'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===================================================================
          FULLSCREEN LIGHTBOX MODAL
          - Applies current rotation to the full-res image
          - Wheel always zooms; drag pans once zoomed in
          - Backdrop click closes; image click does not
          ================================================================ */}
      {isFullscreenLightboxOpen && (
        <div
          ref={lightboxContainerRef}
          onClick={() => setIsFullscreenLightboxOpen(false)}
          onMouseDown={handleLightboxMouseDown}
          onMouseMove={handleLightboxMouseMove}
          onMouseUp={handleLightboxMouseUp}
          onMouseLeave={handleLightboxMouseUp}
          className={`fixed inset-0 z-50 bg-black/90 backdrop-blur-md flex items-center justify-center p-4 select-none ${getLightboxCursorClass()}`}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="relative max-w-7xl max-h-[92vh] w-full flex flex-col items-center justify-center space-y-3 overflow-hidden"
          >
            <button
              onClick={() => setIsFullscreenLightboxOpen(false)}
              className="absolute -top-2 right-2 text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-700 p-2.5 rounded-full cursor-pointer transition-colors shadow-lg border border-slate-700 z-10"
              title="Close Fullscreen View (Esc)"
            >
              <X size={18} />
            </button>
            <img
              ref={lightboxImgRef}
              src={getSourceImage()}
              alt="Full Resolution Invoice Scan"
              draggable={false}
              style={{
                transform: `translate(${lightboxPanX}px, ${lightboxPanY}px) scale(${lightboxZoom}) rotate(${rotation}deg)`,
                transformOrigin: 'center center',
                transition: isLightboxDragging ? 'none' : 'transform 0.1s ease-out',
              }}
              className="max-h-[86vh] max-w-full object-contain rounded-lg shadow-2xl border border-slate-800"
            />
            <div className="text-xs text-slate-300 bg-slate-900/80 px-4 py-1.5 rounded-full border border-slate-700 flex items-center space-x-2">
              {rotation !== 0 && (
                <>
                  <span className="text-slate-400">Rotated {rotation}°</span>
                  <span className="text-slate-500">•</span>
                </>
              )}
              <span className="text-slate-400">Scroll to zoom, drag to pan</span>
              <span className="text-slate-500">•</span>
              <span className="text-slate-400">Press ESC or click backdrop to close</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default InvoiceReviewPage;
