import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { buildInvoiceChecks, deriveImpliedAdjustment, type CheckStatus } from './invoiceChecks';
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
  // The quantity total printed in the footer. Evidence, not an editable
  // figure: it is what the rows are checked against.
  total_quantity?: number | null;
  seller_gstin?: string;
  seller_address?: string;
  seller_phone?: string;
  drug_license?: string;
  buyer_gstin?: string;
  // The rows behind `discount`, when the invoice printed more than one -
  // Mahajan Medicos states a "1st Discount" and a "2nd Discount" as separate
  // footer lines. Read-only: editing the total in Discount - does not rewrite
  // this, since it is evidence of what was found, not a value to keep in
  // sync. Empty when the invoice states a single figure.
  discount_breakdown?: { label: string; amount: number }[];
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
  // Set by the backend when billed + free lands short of a whole pack.
  // Advisory only — nothing is applied until the reviewer accepts it.
  quantity_suggestion?: {
    field: string;
    current: number;
    suggested: number;
    total_before: number;
    total_after: number;
    reason: string;
    billed_verified: boolean;
  } | null;
  // How this row found its catalogue item. Carried so the reviewer can see
  // WHY a row was filled in for them - an auto-applied value with no visible
  // justification is just an unexplained value.
  match_tier?: string | null;
  match_status?: string | null;
  match_note?: string | null;
  match_times_seen?: number | null;
}

// Chip colours, matching the Confidence/Verified badges already on this bar.
// 'unknown' is deliberately grey rather than amber: a check whose inputs the
// invoice never printed has not failed, and colouring it as a warning teaches
// the reviewer to ignore warnings.
const CHECK_STYLES: Record<CheckStatus, string> = {
  pass: 'bg-green-50 text-green-700 border-green-200',
  fail: 'bg-red-50 text-red-700 border-red-200',
  warn: 'bg-amber-50 text-amber-700 border-amber-200',
  unknown: 'bg-slate-50 text-slate-500 border-slate-200',
};

const CHECK_DOTS: Record<CheckStatus, string> = {
  pass: 'bg-green-500',
  fail: 'bg-red-500',
  warn: 'bg-amber-500',
  unknown: 'bg-slate-300',
};

/**
 * One editable figure in the totals block.
 *
 * Right-aligned and borderless until touched, so the block still reads as a
 * summary rather than a form - the reviewer's eye should land on the numbers,
 * not on five input boxes.
 *
 * Shows two decimal places at rest — "10.00" rather than "10" — so every
 * figure in the block reads as money, whether or not it happens to be a whole
 * number. Only at rest: while the field is focused it shows exactly what was
 * typed, because reformatting on every keystroke would rewrite "149.0" to
 * "149.00" mid-edit and fight the cursor as a decimal is being typed.
 */
const TotalsInput: React.FC<{
  value: any;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}> = ({ value, onChange, placeholder = '—', className = '' }) => {
  const [focused, setFocused] = useState(false);
  const display = focused
    ? (value ?? '')
    : (() => {
        const num = toNumberOrNull(value);
        return num === null ? '' : num.toFixed(2);
      })();
  return (
    <input
      type="text"
      inputMode="decimal"
      value={display}
      placeholder={placeholder}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onChange={(e) => onChange(e.target.value)}
      className={`w-24 bg-transparent text-right font-semibold text-slate-800 rounded-md px-1.5 py-0.5 border border-transparent hover:border-slate-300 focus:border-[#1b5dfc] focus:bg-white focus:outline-none transition-colors ${className}`}
    />
  );
};

const ordinal = (n: number): string => {
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th'
    : ['th', 'st', 'nd', 'rd'][n % 10] ?? 'th';
  return `${n}${suffix}`;
};

/**
 * Says why a row was matched to a catalogue item.
 *
 * Auto-applying a value is only defensible if the reviewer can see what it
 * rests on, so the badge names the evidence ("4th purchase from this vendor")
 * rather than just asserting confidence. The amber variant is the opposite
 * case: the vendor changed something, and the row is asking rather than
 * telling.
 */
const MatchBadge: React.FC<{ item: TableLineItem }> = ({ item }) => {
  if (item.match_status === 'needs_confirmation') {
    return (
      <span
        title={item.match_note || 'An indicator changed since this vendor last billed this item'}
        className="ml-2 inline-flex items-center gap-1 rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[10px] font-semibold text-amber-700 align-middle"
      >
        <AlertTriangle size={10} />
        Confirm{item.match_note ? `: ${item.match_note}` : ''}
      </span>
    );
  }
  if (item.match_tier === 'vendor_exact') {
    const seen = item.match_times_seen ?? 0;
    return (
      <span
        title={seen > 0 ? `Matched automatically — this vendor has billed this exact item ${seen} time(s) before` : undefined}
        className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 align-middle"
      >
        <CheckCircle size={10} />
        Auto-matched{seen > 0 ? ` · ${ordinal(seen + 1)} purchase` : ''}
      </span>
    );
  }
  if (item.match_tier === 'new') {
    return (
      <span
        title="Not billed before — this will be added to the catalogue"
        className="ml-2 inline-flex items-center gap-1 rounded-full bg-sky-50 border border-sky-200 px-2 py-0.5 text-[10px] font-semibold text-sky-700 align-middle"
      >
        New item
      </span>
    );
  }
  return null;
};

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
// Reveals a cell's full value on hover, but ONLY when the cell is too narrow
// to show it. Overflow is measured on the real element rather than guessed
// from a character count, because the cell is a fixed-width input in a
// proportional font - "CENTRUM ADULT JOINT&MOBILITY" and "IIIIIIIIIIIIII" are
// the same length and nothing like the same width.
//
// Deliberately not the native `title` attribute: that waits about a second,
// cannot be styled, and fires on every cell whether or not anything is
// hidden. A tooltip that appears when there is nothing more to see trains
// people to ignore it.
const TruncatedCell: React.FC<{ value: string | number | null | undefined; children: React.ReactNode }> = ({
  value,
  children
}) => {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [truncated, setTruncated] = useState(false);
  const [hovering, setHovering] = useState(false);

  const text = value === null || value === undefined ? '' : String(value);

  // Measured on enter rather than on render: column widths change with the
  // window and with the lock/unlock toggle, so a value cached at mount goes
  // stale.
  const measure = () => {
    const el = wrapRef.current?.querySelector('input, div') as HTMLElement | null;
    // +1 absorbs sub-pixel rounding, which otherwise reports a perfectly
    // fitting cell as overflowing.
    setTruncated(!!el && el.scrollWidth > el.clientWidth + 1);
  };

  return (
    <div
      ref={wrapRef}
      className="relative"
      onMouseEnter={() => {
        measure();
        setHovering(true);
      }}
      onMouseLeave={() => setHovering(false)}
    >
      {children}
      {hovering && truncated && text && (
        // pointer-events-none so the tooltip cannot swallow the click that
        // was aimed at the input underneath it.
        <div
          role="tooltip"
          className="pointer-events-none absolute left-0 top-full z-50 mt-1 max-w-md whitespace-pre-wrap break-words rounded-lg bg-[#0f172a] px-3 py-2 text-xs font-medium leading-snug text-white shadow-xl"
        >
          {text}
        </div>
      )}
    </div>
  );
};

const ReadOnlyCell: React.FC<{ value: string | number | null | undefined; align?: 'left' | 'right'; bold?: boolean }> = ({ value, align = 'left', bold = false }) => {
  const isEmpty = value === null || value === undefined || value === '';
  return (
    // `truncate` (overflow-hidden + nowrap + ellipsis) rather than letting the
    // text wrap: a wrapped cell changes row height and pushes the table
    // around, and it also makes scrollWidth equal clientWidth, so
    // TruncatedCell would never detect that anything was cut off.
    <div
      className={`w-full min-h-[38px] flex items-center px-3 py-2 text-sm rounded-lg truncate ${
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
    total_quantity: null,
    seller_gstin: '',
    seller_address: '',
    seller_phone: '',
    drug_license: '',
    buyer_gstin: ''
  });

  // What the invoice itself said was payable, kept as read so an override is
  // always visible and always reversible. The grand total is the one figure on
  // the page that decides what gets paid, so it must never change without the
  // screen saying it changed.
  const [statedGrandTotal, setStatedGrandTotal] = useState<number | null>(null);
  // The round-off the invoice itself printed, if any. Distinguishes a printed
  // round-off that stops reconciling - which means something else was misread -
  // from one a reviewer entered that has simply gone stale.
  const [statedRoundoff, setStatedRoundoff] = useState<number | null>(null);
  // True only while the grand total on screen is one we worked out, because
  // the invoice never printed one. A stated total is evidence and is left
  // alone; a derived one is arithmetic and follows its inputs.
  const [grandTotalIsDerived, setGrandTotalIsDerived] = useState(false);

  const [lineItems, setLineItems] = useState<TableLineItem[]>([]);
  // True only when the user emptied the table themselves, row by row. Gates the
  // backend's refusal to accept an empty line_items array (EmptyLineItemsError),
  // so an empty array from any other cause cannot delete a saved invoice's rows.
  const [clearedTableDeliberately, setClearedTableDeliberately] = useState(false);
  const [confidence, setConfidence] = useState(85);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [invoiceStatus, setInvoiceStatus] = useState<'needs_review' | 'verified'>('needs_review');
  const [imageUrl, setImageUrl] = useState<string>('');
  // Multi-page invoices carry one presigned URL per page, in page order.
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [activePage, setActivePage] = useState(0);
  // Whether the viewer should ease into its next transform. True while the
  // user is working on one page — rotating or zooming it, where the movement
  // is the feedback — and switched off for the frame in which a page change
  // rewrites every part of the transform at once. See goToPage.
  const [animateViewer, setAnimateViewer] = useState(true);

  useEffect(() => {
    if (animateViewer) return;
    // Two frames, not one: the first lets React commit the new transform with
    // transitions off, the second re-arms them. Re-enabling in the same frame
    // would let the browser coalesce both changes and animate anyway.
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setAnimateViewer(true));
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [animateViewer]);

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

  const matchSummary = React.useMemo(() => {
    const counted = lineItems.filter((item) => isPresent(item.match_tier));
    return {
      total: counted.length,
      auto: counted.filter((i) => i.match_tier === 'vendor_exact').length,
      confirm: counted.filter((i) => i.match_status === 'needs_confirmation').length,
      fresh: counted.filter((i) => i.match_tier === 'new').length,
    };
  }, [lineItems]);

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
          total_quantity: detail.total_quantity ?? null,
          seller_gstin: detail.seller_gstin || detail.seller?.gstin || '',
          seller_address: detail.seller_address || detail.seller?.address || '',
          seller_phone: detail.seller_phone || detail.seller?.phone || '',
          drug_license: detail.drug_license || detail.seller?.drug_license || '',
          buyer_gstin: detail.buyer_gstin || '',
          discount_breakdown: Array.isArray(detail.discount_breakdown) ? detail.discount_breakdown : [],
        });

        setStatedGrandTotal(toNumberOrNull(detail.grand_total));
        setStatedRoundoff(toNumberOrNull(detail.roundoff));
        setGrandTotalIsDerived(toNumberOrNull(detail.grand_total) === null);

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
            quantity_suggestion: item.quantity_suggestion ?? null,
            bounding_box: Array.isArray(item.bounding_box) ? item.bounding_box : undefined,
            match_tier: item.match_tier ?? null,
            match_status: item.match_status ?? null,
            match_note: item.match_note ?? null,
            match_times_seen: item.match_times_seen ?? null,
          };
        });

        setLineItems(parsedItems);
        // Fresh data on screen: any earlier intent to clear the table is spent.
        setClearedTableDeliberately(false);
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
    // Typing into the grand total is the reviewer stating what is owed, so it
    // stops being a derived figure and stops following the parts.
    if (key === 'grand_total') setGrandTotalIsDerived(false);
    setHeader((prev) => ({
      ...prev,
      [key]: value
    }));
  };

  /**
   * Edits a figure in the totals block.
   *
   * This used to carry every change through to the grand total, so that a
   * corrected subtotal would clear the red totals indicator. That traded the
   * wrong thing away: the grand total is what the supplier is owed, printed on
   * the bill and usually repeated in words, while the subtotal is a cell that
   * OCR can misread. Recomputing meant fixing a 20-paise misread quietly
   * restated the amount payable - the reviewer corrected one number and
   * silently changed what the pharmacy owed, with nothing on screen saying so.
   *
   * So a stated grand total now stands. A gap between it and the parts is a
   * real property of the invoice - usually a rounding the supplier applied and
   * did not print - and is reported by deriveImpliedAdjustment() rather than
   * papered over by moving the total. Where the invoice printed no grand total
   * at all there is nothing to protect, and it follows the parts as before.
   */
  const handleTotalsChange = (key: 'subtotal' | 'discount' | 'roundoff', raw: string) => {
    setHeader((prev) => {
      const next: any = { ...prev, [key]: raw };

      const num = (value: any) => {
        const parsed = parseFloat(String(value ?? '').replace(/[^0-9.\-]/g, ''));
        return Number.isFinite(parsed) ? parsed : 0;
      };
      const subtotal = num(next.subtotal);
      const discount = num(next.discount);
      const tax = num(prev.cgst) + num(prev.sgst) + num(prev.igst);
      const roundoff = num(next.roundoff);

      // Only when the total on screen is ours to recompute, and only when
      // there is a subtotal to build it from - deriving from an empty box
      // would put a zero where a figure read off the invoice belongs.
      if (grandTotalIsDerived && String(next.subtotal ?? '').trim() !== '') {
        next.grand_total = parseFloat((subtotal - discount + tax + roundoff).toFixed(2));
      }
      return next;
    });
  };

  /**
   * Replaces the grand total with the figure the other totals come to.
   *
   * The deliberate version of what handleTotalsChange used to do behind the
   * reviewer's back: available when the printed total is itself the misread
   * one, but taken as a decision, shown as an override, and revertible to
   * whatever the invoice stated.
   */
  const overrideGrandTotal = (value: number) => {
    setHeader((prev) => ({ ...prev, grand_total: parseFloat(value.toFixed(2)) }));
    setGrandTotalIsDerived(false);
  };

  const revertGrandTotal = () => {
    setHeader((prev) => ({ ...prev, grand_total: statedGrandTotal }));
    setGrandTotalIsDerived(statedGrandTotal === null);
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
    setLineItems((prev) => {
      const next = prev.filter((item) => item.id !== itemId);
      // Emptying the table by deleting rows is a deliberate act, and the only
      // way the backend will accept an empty line_items array. Any other route
      // to an empty array — a save racing the initial fetch, a failed reload —
      // leaves this false and is refused rather than wiping the invoice.
      if (next.length === 0) {
        setClearedTableDeliberately(true);
      }
      return next;
    });
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

  // How many rows contributed to computedSubtotal. A row with no amount makes
  // that total a floor rather than a figure, which is a different answer from
  // "the rows total the wrong thing" - the checks distinguish the two, and
  // neither goes quiet just because a row is incomplete.
  const rowsWithAmount = lineItems.filter(item => isPresent(getItemAmount(item))).length;
  const effectiveSubtotal = isPresent(header.subtotal) ? toNumberOrNull(header.subtotal) : computedSubtotal;

  // The difference between what this invoice's own figures come to and what
  // it says is payable. Suppliers round the amount due and print no round-off
  // line for it, so a grand total that reconciles with nothing on the page is
  // usually a fact about the invoice rather than a bad read - but only saying
  // so out loud makes that distinguishable from a bad read.
  const impliedAdjustment = React.useMemo(() => deriveImpliedAdjustment({
    subtotal: toNumberOrNull(effectiveSubtotal),
    discount: toNumberOrNull(discountVal),
    taxTotal: toNumberOrNull(computedGstTotal),
    roundoff: toNumberOrNull(roundoff),
    printedRoundoff: statedRoundoff,
    grandTotal: toNumberOrNull(header.grand_total),
  }), [effectiveSubtotal, discountVal, computedGstTotal, roundoff, statedRoundoff, header.grand_total]);

  // What the rows say was received, and how many of them land short of a
  // whole pack. Both read from the edited rows, so accepting a per-row
  // suggestion updates the chip in the same click.
  const quantityTally = React.useMemo(() => {
    let received = 0;
    let partPackRows = 0;
    let anyMissing = false;
    for (const item of lineItems) {
      const billed = toNumberOrNull(item.quantity);
      const free = toNumberOrNull(item.free_quantity) ?? 0;
      if (billed === null) {
        anyMissing = true;
        continue;
      }
      const rowTotal = billed + free;
      received += rowTotal;
      if (Math.abs(rowTotal - Math.round(rowTotal)) > 1e-6) partPackRows += 1;
    }
    return {
      received: anyMissing ? null : parseFloat(received.toFixed(2)),
      partPackRows,
    };
  }, [lineItems]);

  // True once the total on screen is no longer the one the invoice printed.
  const grandTotalOverridden =
    statedGrandTotal !== null &&
    toNumberOrNull(header.grand_total) !== null &&
    Math.abs((toNumberOrNull(header.grand_total) as number) - statedGrandTotal) >= 0.005;

  // How far the rows are from the subtotal printed in the footer. A footer
  // total is one OCR'd cell; the amount column is many, so a disagreement is
  // worth showing beside the subtotal itself, where it gets corrected.
  //
  // A row with no amount does not silence this. It used to: the whole
  // comparison was withheld until every row had an amount, which meant a
  // single unreadable cell hid the fact that nine rows were totalling 42.82
  // against a printed 1821.63 — and the reviewer only saw it after deleting
  // an unrelated row happened to satisfy the guard. Rows missing an amount
  // are the case where the total is MOST likely to be wrong, so the rows that
  // do have one are still totalled and the count is stated instead. What is
  // withheld is the one-click correction: an incomplete total is not a figure
  // to overwrite the subtotal with.
  const subtotalVsLines = React.useMemo(() => {
    const stated = toNumberOrNull(header.subtotal);
    if (stated === null || computedSubtotal === null) return null;
    if (rowsWithAmount === 0) return null;
    const gap = parseFloat((computedSubtotal - stated).toFixed(2));
    // With rows missing, the total is expected to fall short, so only a gap
    // too large to be those rows is worth raising. Their own amounts are
    // unknown, so the invoice's average row is the yardstick available.
    const missing = lineItems.length - rowsWithAmount;
    const slack = missing > 0 ? Math.abs(stated / lineItems.length) * missing : 0;
    if (Math.abs(gap) < 0.005) return null;
    if (missing > 0 && gap < 0 && Math.abs(gap) <= slack) return null;
    return { gap, lineTotal: computedSubtotal, counted: rowsWithAmount, missing };
  }, [header.subtotal, computedSubtotal, lineItems.length, rowsWithAmount]);

  // Each question the reviewer would otherwise ask by hand, answered
  // separately. Computed straight from what is on screen, so correcting a
  // figure flips its indicator in the same keystroke — see invoiceChecks.ts
  // for why one collapsed "Math" verdict was worse than several precise ones.
  const checks = React.useMemo(() => buildInvoiceChecks({
    // Coerced here, not trusted: these fields hold whatever the reviewer has
    // typed, so a half-entered "14." is a string until it parses.
    subtotal: toNumberOrNull(effectiveSubtotal),
    // The total of the rows that have an amount, with the count alongside, so
    // the check can say how far off they are AND that some are missing. It
    // used to be withheld entirely whenever a row lacked an amount, which put
    // the check into 'unknown' exactly when the rows were least trustworthy.
    lineTotal: computedSubtotal,
    rowsWithAmount,
    discount: toNumberOrNull(discountVal),
    taxTotal: toNumberOrNull(computedGstTotal),
    cgst: toNumberOrNull(cgstVal),
    sgst: toNumberOrNull(sgstVal),
    igst: toNumberOrNull(igstVal),
    roundoff: toNumberOrNull(roundoff),
    grandTotal: toNumberOrNull(header.grand_total),
    itemCount: lineItems.length,
    itemsWithGaps: lineItems.filter((item) =>
      isCriticalItemMissing(item, 'product_name') ||
      isCriticalItemMissing(item, 'batch') ||
      isCriticalItemMissing(item, 'hsn') ||
      isCriticalItemMissing(item, 'quantity') ||
      isCriticalItemMissing(item, 'amount')
    ).length,
    derivedAmounts: lineItems.filter((item) => item.is_suggested_amount).length,
    receivedQuantity: quantityTally.received,
    statedQuantity: toNumberOrNull(header.total_quantity),
    partPackRows: quantityTally.partPackRows,
    sellerName: header.seller_name ?? null,
    sellerGstin: header.seller_gstin ?? null,
    invoiceNumber: header.invoice_number ?? null,
    invoiceDate: header.invoice_date ?? null,
  }), [
    effectiveSubtotal, computedSubtotal, rowsWithAmount, discountVal, computedGstTotal,
    cgstVal, sgstVal, igstVal, roundoff, header.grand_total, lineItems,
    quantityTally, header.total_quantity,
    header.seller_name, header.seller_gstin, header.invoice_number, header.invoice_date,
    invoiceHasMrpColumn,
  ]);

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
    allow_empty_line_items: clearedTableDeliberately,
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
    // Turning to the next sheet is not a movement of the current one, so the
    // viewer must not animate its way there. Rotation, zoom and pan all change
    // at once here, and under a live transition the new page visibly spins and
    // slides into place - as though the paper were being turned over on the
    // desk. The next page should simply be there.
    setAnimateViewer(false);
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

          {/* One chip per question, in place of a single "Math" verdict that
              collapsed five unrelated checks into one word. Each carries its
              own numbers in the tooltip, so a red chip says what to look at
              rather than only that something is wrong. */}
          {checks.map((check) => (
            <span
              key={check.id}
              title={check.detail}
              className={`px-2 py-0.5 rounded-full text-[10px] font-bold border flex items-center space-x-1 cursor-help ${CHECK_STYLES[check.status]}`}
            >
              <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${CHECK_DOTS[check.status]}`} />
              <span>{check.label}</span>
            </span>
          ))}

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
          // Never let the pinned scan/summary panel take the whole viewport:
          // it stays put while the items scroll under it, so whatever it
          // occupies is permanently unavailable to the table. Capping it at
          // 62vh keeps at least a third of the screen on the line items at any
          // window height. On a normal laptop the panel is shorter than the cap
          // anyway, so this changes nothing there.
          maxHeight: 'min(calc(100vh - 88px), 62vh)',
          overflowY: 'auto',
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
                  // Dragging is already suppressed: easing a pan that is
                  // tracking the cursor makes the image lag behind the mouse.
                  transition: animateViewer && !isDragging ? 'transform 0.15s ease-out' : 'none',
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
                {isLocked ? (
                  <span className="font-semibold text-slate-800">{formatCurrencyOrDash(effectiveSubtotal)}</span>
                ) : (
                  <TotalsInput
                    value={header.subtotal}
                    placeholder={effectiveSubtotal !== null ? String(effectiveSubtotal) : '—'}
                    onChange={(v) => handleTotalsChange('subtotal', v)}
                  />
                )}
              </div>

              {/* The footer subtotal is a single OCR'd cell; the amount column
                  is a dozen of them. When they disagree the column is the
                  stronger witness, so the difference is stated here rather
                  than left to be noticed - a footer digit read wrong is
                  otherwise invisible behind a rounding tolerance. */}
              {/* Graded, not uniform. With every row totalled, the rows and
                  the footer are two independent readings of the same figure
                  and they disagree — something on the page was misread, and
                  this is the screen's most serious statement. With rows still
                  missing an amount the total is merely incomplete, which is a
                  different message and must not wear the same colour, or the
                  red that means "wrong" stops meaning anything. */}
              {subtotalVsLines && (
                <div
                  className={`rounded-lg border px-2.5 py-2 text-xs leading-snug ${
                    subtotalVsLines.missing > 0
                      ? 'border-amber-300 bg-amber-50 text-amber-900'
                      : 'border-rose-300 bg-rose-50 text-rose-900'
                  }`}
                >
                  <div className="flex items-start gap-1.5">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                    <div className="min-w-0 space-y-1">
                      <div className="font-bold">
                        {subtotalVsLines.missing > 0
                          ? 'Subtotal cannot be confirmed yet'
                          : "Line items don't add up to this subtotal"}
                      </div>
                      <div>
                        {subtotalVsLines.missing > 0
                          ? `${subtotalVsLines.counted} of ${lineItems.length} rows total `
                          : `${lineItems.length} rows total `}
                        <span className="font-bold">
                          {formatCurrencyOrDash(subtotalVsLines.lineTotal)}
                        </span>
                        , which is{' '}
                        <span className="font-bold">
                          {formatCurrencyOrDash(Math.abs(subtotalVsLines.gap))}
                        </span>{' '}
                        {subtotalVsLines.gap > 0 ? 'more' : 'less'} than the{' '}
                        {formatCurrencyOrDash(toNumberOrNull(header.subtotal))} above.
                      </div>
                      {/* The correction is offered only on a total every row
                          contributed to. Writing an incomplete one into the
                          subtotal would replace a figure the invoice printed
                          with a smaller one, and make the two agree by
                          lowering the invoice rather than by fixing the rows. */}
                      {subtotalVsLines.missing > 0 ? (
                        <div className="opacity-90">
                          {subtotalVsLines.missing} row
                          {subtotalVsLines.missing > 1 ? 's have' : ' has'} no amount yet — fill
                          those in before trusting either figure.
                        </div>
                      ) : (
                        !isLocked && (
                          <button
                            type="button"
                            onClick={() =>
                              handleTotalsChange('subtotal', String(subtotalVsLines.lineTotal))
                            }
                            className="font-bold underline decoration-dotted underline-offset-2 hover:opacity-70 cursor-pointer"
                          >
                            Use {formatCurrencyOrDash(subtotalVsLines.lineTotal)} from the rows
                          </button>
                        )
                      )}
                    </div>
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between">
                {/* Just "Tax". The bracket used to hold a rate, defaulting to
                    a hardcoded "12%" whenever no tax had been extracted — so
                    the one invoice where the figure was missing was also the
                    one asserting a rate, and asserting the wrong one. A single
                    rate is not a fact this row can state in any case: an
                    invoice can carry several GST slabs at once, and the amount
                    beside it is their sum. */}
                <span className="text-gray-500 font-medium">Tax +</span>
                <span className="font-semibold text-slate-800">{formatCurrencyOrDash(computedGstTotal)}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-500 font-medium">Discount -</span>
                {isLocked ? (
                  <span className="font-semibold text-slate-800">{formatCurrencyOrDash(discountVal)}</span>
                ) : (
                  <TotalsInput
                    value={header.discount}
                    onChange={(v) => handleTotalsChange('discount', v)}
                  />
                )}
              </div>

              {/* What the discount is made of, when the invoice printed more
                  than one - Mahajan Medicos states a "1st Discount" and a
                  "2nd Discount" as two separate footer rows, and summing them
                  without saying so would leave a total on screen that matches
                  no single line the reviewer can check against the paper.
                  Read-only: it is evidence of what was found, not a value to
                  keep in sync with a manual edit to the total above. */}
              {(header.discount_breakdown?.length ?? 0) > 1 && (
                <div className="text-[10px] text-gray-500 text-right -mt-1">
                  {header.discount_breakdown!
                    .map((d) => `${d.label} ${formatCurrencyOrDash(d.amount)}`)
                    .join(' + ')}
                </div>
              )}

              {(roundoff !== null || impliedAdjustment !== null || !isLocked) && (
                <div className="flex items-center justify-between">
                  <span className="text-gray-500 font-medium">
                    {roundoff === null && impliedAdjustment ? impliedAdjustment.label : 'Round Off'}
                  </span>
                  {isLocked ? (
                    // With nothing printed, the figure shown is inferred from
                    // the invoice's own grand total, so it is styled as the
                    // different kind of thing it is rather than sitting there
                    // looking like an extracted value.
                    roundoff === null && impliedAdjustment ? (
                      <span
                        className={`font-semibold italic ${
                          impliedAdjustment.kind === 'unexplained' ? 'text-rose-600' : 'text-amber-700'
                        }`}
                      >
                        {formatSignedCurrency(impliedAdjustment.requiredRoundoff)}
                      </span>
                    ) : (
                      <span
                        className={`font-semibold ${
                          impliedAdjustment?.isStale ? 'text-amber-700' : 'text-slate-800'
                        }`}
                      >
                        {formatSignedCurrency(roundoff)}
                      </span>
                    )
                  ) : (
                    <TotalsInput
                      value={header.roundoff}
                      placeholder={
                        roundoff === null && impliedAdjustment
                          ? formatSignedCurrency(impliedAdjustment.requiredRoundoff)
                          : undefined
                      }
                      className={impliedAdjustment?.isStale ? 'text-amber-700' : ''}
                      onChange={(v) => handleTotalsChange('roundoff', v)}
                    />
                  )}
                </div>
              )}

              {/* Both numbers, named. A grand total that reconciles with
                  nothing above it reads as a failed extraction; showing what
                  the invoice states beside what its own figures come to lets
                  the reviewer tell a supplier's unstated rounding apart from a
                  digit we read wrong. */}
              {impliedAdjustment && (
                <div
                  className={`rounded-lg border px-2.5 py-2 text-xs leading-snug ${
                    impliedAdjustment.kind === 'unexplained'
                      ? 'border-rose-300 bg-rose-50 text-rose-900'
                      : 'border-amber-300 bg-amber-50 text-amber-900'
                  }`}
                >
                  <div className="flex items-start gap-1.5">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                    <div className="min-w-0 space-y-1">
                      <div className="font-bold">
                        {impliedAdjustment.kind === 'unexplained'
                          ? "Grand total doesn't match the figures above"
                          : 'Grand total needs a round-off to reconcile'}
                      </div>
                      <div>
                        Invoice states{' '}
                        <span className="font-bold">
                          {formatCurrencyOrDash(impliedAdjustment.statedTotal)}
                        </span>
                        ; the figures above come to{' '}
                        <span className="font-bold">
                          {formatCurrencyOrDash(impliedAdjustment.computedTotal)}
                        </span>
                        .
                      </div>
                      <div className="opacity-90">{impliedAdjustment.note}</div>

                  {/* Two ways to close the gap, both stated. Recording it as a
                      round-off keeps the invoice's own total and makes the
                      figures reconcile; overriding replaces the printed total
                      and is the right call only when that total is itself the
                      misread one. Neither happens on its own. */}
                  {!isLocked && (
                    <div className="flex flex-wrap gap-x-3 gap-y-1 font-bold">
                      <button
                        type="button"
                        onClick={() =>
                          handleTotalsChange('roundoff', String(impliedAdjustment.requiredRoundoff))
                        }
                        className="underline decoration-dotted underline-offset-2 hover:opacity-70 cursor-pointer"
                      >
                        {impliedAdjustment.isStale ? 'Update' : 'Record'} round-off to{' '}
                        {formatSignedCurrency(impliedAdjustment.requiredRoundoff)}
                      </button>
                      {/* Only offered while the round-off box is empty. With a
                          stale value in it, "what these figures come to" is
                          contaminated by the stale figure, so overriding the
                          printed total with it would bake the error into the
                          amount payable. Clear or fix the round-off first. */}
                      {!impliedAdjustment.isStale && (
                        <button
                          type="button"
                          onClick={() => overrideGrandTotal(impliedAdjustment.computedTotal)}
                          className="underline decoration-dotted underline-offset-2 hover:opacity-70 cursor-pointer"
                        >
                          Override total with {formatCurrencyOrDash(impliedAdjustment.computedTotal)}
                        </button>
                      )}
                    </div>
                  )}
                    </div>
                  </div>
                </div>
              )}

              {/* An amount payable that no longer matches the bill is the one
                  thing on this screen that must never be silently true. It is
                  the amount that gets paid, so it is stated at the same weight
                  as the other two alerts rather than as a footnote. */}
              {grandTotalOverridden && (
                <div className="rounded-lg border border-rose-300 bg-rose-50 px-2.5 py-2 text-xs leading-snug text-rose-900">
                  <div className="flex items-start gap-1.5">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                    <div className="min-w-0 space-y-1">
                      <div className="font-bold">Grand total has been changed</div>
                      <div>
                        The invoice states{' '}
                        <span className="font-bold">{formatCurrencyOrDash(statedGrandTotal)}</span>.
                      </div>
                      {!isLocked && (
                        <button
                          type="button"
                          onClick={revertGrandTotal}
                          className="font-bold underline decoration-dotted underline-offset-2 hover:opacity-70 cursor-pointer"
                        >
                          Revert to {formatCurrencyOrDash(statedGrandTotal)}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

              <div className="border-t border-slate-200/80 pt-2 flex items-center justify-between">
                <span className="font-bold text-slate-900 text-sm">Grand Total</span>
                {isLocked ? (
                  <span className="font-extrabold text-[#1b5dfc] text-base">{formatCurrencyOrDash(header.grand_total)}</span>
                ) : (
                  <TotalsInput
                    value={header.grand_total}
                    onChange={(v) => handleHeaderChange('grand_total', v)}
                    className="text-base font-extrabold text-[#1b5dfc] w-28"
                  />
                )}
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
      </div>
      {/* END STICKY HEADER BLOCK */}

      {/* ===================================================================
          LINE ITEMS CARD — sits *outside* the sticky block on purpose.

          It used to be the sticky block's last child, which capped it at
          `calc(100vh - 88px)` minus the scan/summary grid above it. That grid
          is shrink-0, so the card was the only thing able to absorb a
          shortfall: on a short window, or when the summary grew (multi-page
          invoices add page navigation), the card's share fell to 0px and every
          row was clipped away while the shrink-0 title bar kept reporting the
          real count — "Line Items Review (16)" over an empty table.

          Sizing to content and letting <main> scroll means the row count and
          the rows visible on screen can no longer disagree, at any height.
          ================================================================ */}
      <div className="flex flex-col bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden mb-8">
          <div className="shrink-0 p-4 flex items-center justify-between border-b border-[#e2e8f0]">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2 flex-wrap">
              <span>Line Items Review ({lineItems.length})</span>
              {/* What the catalogue did on this invoice, stated up front — the
                  reviewer should learn how much was decided for them before
                  they start reading rows, not by noticing badges. */}
              {matchSummary.total > 0 && (
                <span className="normal-case tracking-normal font-medium text-[11px] text-gray-400">
                  {matchSummary.auto > 0 && (
                    <span className="text-emerald-600">{matchSummary.auto} auto-matched</span>
                  )}
                  {matchSummary.confirm > 0 && (
                    <>{matchSummary.auto > 0 && ' · '}
                      <span className="text-amber-600">{matchSummary.confirm} to confirm</span></>
                  )}
                  {matchSummary.fresh > 0 && (
                    <>{(matchSummary.auto > 0 || matchSummary.confirm > 0) && ' · '}
                      <span className="text-sky-600">{matchSummary.fresh} new</span></>
                  )}
                </span>
              )}
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
          <div className="overflow-x-auto custom-scrollbar">
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
                        <TruncatedCell value={item.product_name}>
                          {isLocked ? (
                            <span className="inline-flex items-center flex-wrap">
                              <ReadOnlyCell value={item.product_name} />
                              <MatchBadge item={item} />
                            </span>
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
                        </TruncatedCell>
                      </td>

                      <td className="p-3 align-top">
                        <TruncatedCell value={item.batch}>
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
                        </TruncatedCell>
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

                          {/* A received total that is not a whole pack. Shown
                              rather than applied: quantity feeds stock, and a
                              number nobody agreed to is what this screen
                              exists to prevent. The arithmetic is spelled out
                              so the claim can be checked, not just trusted.

                              Gated on the CURRENT total, not just on the
                              backend's suggestion: the suggestion was computed
                              when the invoice loaded, so keying off it alone
                              would leave the warning on screen after the
                              reviewer had already acted on it — or after they
                              fixed the row some other way. */}
                          {item.quantity_suggestion && !isLocked &&
                           receivedQty !== null &&
                           Math.abs(receivedQty - Math.round(receivedQty)) > 1e-6 && (
                            <div className="mt-1 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-left">
                              <div className="flex items-start gap-1.5">
                                <AlertTriangle size={11} className="mt-0.5 shrink-0 text-amber-600" />
                                <div className="min-w-0">
                                  <p className="text-[10px] font-semibold leading-snug text-amber-800">
                                    Received {formatQuantityOrDash(item.quantity_suggestion.total_before)} — not a whole pack
                                  </p>
                                  <p className="mt-0.5 text-[9px] leading-snug text-amber-700">
                                    {item.quantity_suggestion.reason}
                                  </p>
                                  <button
                                    onClick={() =>
                                      handleItemChange(
                                        item.id,
                                        'free_quantity',
                                        item.quantity_suggestion!.suggested
                                      )
                                    }
                                    className="mt-1 rounded-md border border-amber-300 bg-white px-2 py-0.5 text-[9px] font-bold text-amber-800 transition-colors hover:bg-amber-100 cursor-pointer"
                                  >
                                    Set free to {formatQuantityOrDash(item.quantity_suggestion.suggested)} → {formatQuantityOrDash(item.quantity_suggestion.total_after)}
                                  </button>
                                </div>
                              </div>
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
      {/* END LINE ITEMS CARD */}

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
