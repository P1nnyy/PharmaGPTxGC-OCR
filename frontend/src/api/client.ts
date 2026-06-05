import type {
  RunSummary,
  OCRBlock,
  CandidateTable,
  SelectedTable,
  SemanticColumn,
  RowMathResult,
  QualityGate,
  Artifact,
  TableCell
} from './types';
import { normalizeBBox } from '../utils/geometry';

// Gating flag for mock / demo data
export const ENABLE_MOCK_DATA = import.meta.env.VITE_ENABLE_MOCK_DATA === 'true';

// Helper to generate a timestamp in ISO format
const getTimestamp = (offsetHours = 0) => {
  const date = new Date();
  date.setHours(date.getHours() - offsetHours);
  return date.toISOString();
};

// Helper to cache uploaded image as base64 in sessionStorage
async function cacheImageLocal(runId: string, file: File): Promise<void> {
  try {
    const base64 = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = error => reject(error);
      reader.readAsDataURL(file);
    });
    sessionStorage.setItem(`ocr_workbench_image_${runId}`, base64);
  } catch (e) {
    console.warn('Failed to cache image in sessionStorage:', e);
  }
}

function cacheProcessedImageLocal(runId: string, dataUrl?: string): void {
  if (!dataUrl || typeof dataUrl !== 'string') return;
  try {
    sessionStorage.setItem(`ocr_workbench_processed_image_${runId}`, dataUrl);
  } catch (e) {
    console.warn('Failed to cache processed image in sessionStorage:', e);
  }
}

function sanitizeForLocalStorage(value: any): any {
  if (Array.isArray(value)) {
    return value.map(sanitizeForLocalStorage);
  }

  if (value && typeof value === 'object') {
    const out: Record<string, any> = {};

    for (const [key, val] of Object.entries(value)) {
      const lowerKey = key.toLowerCase();

      if (
        lowerKey.includes('data_url') ||
        lowerKey.includes('base64') ||
        lowerKey.includes('image_data')
      ) {
        out[key] = `<redacted ${String(val).length} chars>`;
      } else {
        out[key] = sanitizeForLocalStorage(val);
      }
    }

    return out;
  }

  return value;
}

// Retrieves the cached image URL if present, otherwise returns mock SVG representation
export const getInvoiceImageUrl = (runId: string, filename: string): string => {
  const cached = sessionStorage.getItem(`ocr_workbench_image_${runId}`);
  if (cached) {
    return cached;
  }
  return getInvoiceImageSvgUrl(filename);
};

export const getProcessedInvoiceImageUrl = (runId: string): string | null => {
  return sessionStorage.getItem(`ocr_workbench_processed_image_${runId}`);
};

// Generates a mock invoice image as an SVG data URL matching coordinates
export const getInvoiceImageSvgUrl = (filename: string, _overlayMode?: string): string => {
  const isGenome = filename.toLowerCase().includes('genome');
  const title = isGenome ? "GENOME PHARMACEUTICALS" : "SHIVAM DRUGS HOUSE / DISTRIBUTORS";
  const address = isGenome ? "1200 Westlake Ave N, Seattle, WA 98109" : "Pathankot, Punjab, India";
  
  const svg = `
<svg width="800" height="1000" viewBox="0 0 800 1000" xmlns="http://www.w3.org/2000/svg">
  <rect width="800" height="1000" fill="#f5f6f8" />
  
  <!-- Paper shadow and borders -->
  <rect x="2" y="2" width="796" height="996" rx="4" fill="none" stroke="#d1d5db" stroke-width="2"/>
  <line x1="20" y1="180" x2="780" y2="180" stroke="#9ca3af" stroke-width="1.5" stroke-dasharray="4"/>
  
  <!-- Header -->
  <g transform="translate(50, 50)">
    <rect x="0" y="0" width="300" height="35" fill="#e5e7eb" rx="3" opacity="0.6"/>
    <text x="10" y="25" font-family="monospace" font-size="20" font-weight="bold" fill="#1f2937">${title}</text>
    <text x="10" y="55" font-family="sans-serif" font-size="11" fill="#4b5563">Address: ${address}</text>
    <text x="10" y="70" font-family="sans-serif" font-size="11" fill="#4b5563">GSTIN: 03AADEM6639C1ZM | Type: Regular</text>
  </g>
  
  <g transform="translate(480, 50)">
    <text x="0" y="20" font-family="monospace" font-size="12" font-weight="bold" fill="#1f2937">INVOICE NO: TBL_UUID_99120-X</text>
    <text x="0" y="40" font-family="sans-serif" font-size="11" fill="#4b5563">Date: 2026-06-03</text>
    <text x="0" y="55" font-family="sans-serif" font-size="11" fill="#4b5563">Challan No: CH_8874102</text>
    <text x="0" y="70" font-family="sans-serif" font-size="11" fill="#4b5563">DL No: 20-B-140404, 21-B-140405</text>
  </g>

  <!-- Table Headers -->
  <g transform="translate(40, 220)">
    <!-- Header background -->
    <rect x="0" y="0" width="720" height="30" fill="#1f2937" rx="3"/>
    
    <text x="10" y="20" font-family="monospace" font-size="11" font-weight="bold" fill="#f9fafb">#</text>
    <text x="40" y="20" font-family="monospace" font-size="11" font-weight="bold" fill="#f9fafb">PRODUCT / DESCRIPTION</text>
    <text x="300" y="20" font-family="monospace" font-size="11" font-weight="bold" fill="#f9fafb">BATCH</text>
    <text x="400" y="20" font-family="monospace" font-size="11" font-weight="bold" fill="#f9fafb">EXPIRY</text>
    <text x="480" y="20" font-family="monospace" font-size="11" font-weight="bold" fill="#f9fafb">QTY</text>
    <text x="530" y="20" font-family="monospace" font-size="11" font-weight="bold" fill="#f9fafb">RATE</text>
    <text x="590" y="20" font-family="monospace" font-size="11" font-weight="bold" fill="#f9fafb">DISC%</text>
    <text x="650" y="20" font-family="monospace" font-size="11" font-weight="bold" fill="#f9fafb">AMOUNT</text>
  </g>
  
  <!-- Table Rows -->
  <g transform="translate(40, 260)">
    <!-- Row 1 -->
    <text x="10" y="20" font-family="monospace" font-size="11" fill="#374151">01</text>
    <text x="40" y="20" font-family="monospace" font-size="11" fill="#111827" font-weight="bold">Amoxicillin 500mg Cap (100)</text>
    <text x="300" y="20" font-family="monospace" font-size="11" fill="#374151">BN-99212</text>
    <text x="400" y="20" font-family="monospace" font-size="11" fill="#374151">12/2028</text>
    <text x="480" y="20" font-family="monospace" font-size="11" fill="#374151">12</text>
    <text x="530" y="20" font-family="monospace" font-size="11" fill="#374151">42.00</text>
    <text x="590" y="20" font-family="monospace" font-size="11" fill="#374151">8.0%</text>
    <text x="650" y="20" font-family="monospace" font-size="11" fill="#111827">$504.00</text>
    
    <line x1="0" y1="35" x2="720" y2="35" stroke="#e5e7eb" stroke-width="1"/>

    <!-- Row 2 -->
    <text x="10" y="60" font-family="monospace" font-size="11" fill="#374151">02</text>
    <text x="40" y="60" font-family="monospace" font-size="11" fill="#111827" font-weight="bold">Ciprofloxacin 250mg Tab (20)</text>
    <text x="300" y="60" font-family="monospace" font-size="11" fill="#ef4444" font-weight="bold">BN-????</text>
    <text x="400" y="60" font-family="monospace" font-size="11" fill="#374151">05/2027</text>
    <text x="480" y="60" font-family="monospace" font-size="11" fill="#374151">5</text>
    <text x="530" y="60" font-family="monospace" font-size="11" fill="#374151">125.50</text>
    <text x="590" y="60" font-family="monospace" font-size="11" fill="#374151">8.0%</text>
    <text x="650" y="60" font-family="monospace" font-size="11" fill="#111827">$627.50</text>
    
    <line x1="0" y1="75" x2="720" y2="75" stroke="#e5e7eb" stroke-width="1"/>

    <!-- Row 3 -->
    <text x="10" y="100" font-family="monospace" font-size="11" fill="#374151">03</text>
    <text x="40" y="100" font-family="monospace" font-size="11" fill="#111827" font-weight="bold">Ibuprofen 400mg (50)</text>
    <text x="300" y="100" font-family="monospace" font-size="11" fill="#374151">BN-8812</text>
    <text x="400" y="100" font-family="monospace" font-size="11" fill="#374151">08/2028</text>
    <text x="480" y="100" font-family="monospace" font-size="11" fill="#374151">20</text>
    <text x="530" y="100" font-family="monospace" font-size="11" fill="#374151">15.20</text>
    <text x="590" y="100" font-family="monospace" font-size="11" fill="#374151">8.0%</text>
    <text x="650" y="100" font-family="monospace" font-size="11" fill="#111827">$304.00</text>
    
    <line x1="0" y1="115" x2="720" y2="115" stroke="#e5e7eb" stroke-width="1"/>

    <!-- Row 4 -->
    <text x="10" y="140" font-family="monospace" font-size="11" fill="#374151">04</text>
    <text x="40" y="140" font-family="monospace" font-size="11" fill="#111827" font-weight="bold">Omeprazole 20mg (30)</text>
    <text x="300" y="140" font-family="monospace" font-size="11" fill="#374151">BN-4451</text>
    <text x="400" y="140" font-family="monospace" font-size="11" fill="#374151">11/2026</text>
    <text x="480" y="140" font-family="monospace" font-size="11" fill="#374151">10</text>
    <text x="530" y="140" font-family="monospace" font-size="11" fill="#374151">8.90</text>
    <text x="590" y="140" font-family="monospace" font-size="11" fill="#374151">8.0%</text>
    <text x="650" y="140" font-family="monospace" font-size="11" fill="#111827">$89.00</text>
    
    <line x1="0" y1="155" x2="720" y2="155" stroke="#e5e7eb" stroke-width="1"/>
  </g>

  <!-- Footer Rescue / Bottom Summary -->
  <g transform="translate(450, 550)">
    <rect x="-20" y="-10" width="310" height="180" fill="#f3f4f6" stroke="#d1d5db" rx="4"/>
    <text x="0" y="20" font-family="monospace" font-size="11" fill="#4b5563">GROSS TOTAL:</text>
    <text x="150" y="20" font-family="monospace" font-size="11" font-weight="bold" text-anchor="end" fill="#1f2937">1524.50</text>
    
    <text x="0" y="45" font-family="monospace" font-size="11" fill="#4b5563">CGST Total (9%):</text>
    <text x="150" y="45" font-family="monospace" font-size="11" font-weight="bold" text-anchor="end" fill="#1f2937">121.96</text>
    
    <text x="0" y="70" font-family="monospace" font-size="11" fill="#4b5563">SGST Total (9%):</text>
    <text x="150" y="70" font-family="monospace" font-size="11" font-weight="bold" text-anchor="end" fill="#1f2937">121.96</text>

    <text x="0" y="95" font-family="monospace" font-size="11" fill="#ef4444">DISCOUNT (TD%):</text>
    <text x="150" y="95" font-family="monospace" font-size="11" font-weight="bold" text-anchor="end" fill="#ef4444">-121.96</text>
    
    <line x1="-10" y1="115" x2="160" y2="115" stroke="#d1d5db" stroke-width="1"/>
    
    <text x="0" y="135" font-family="monospace" font-size="12" font-weight="bold" fill="#111827">NET AMT PAYABLE:</text>
    <text x="150" y="135" font-family="monospace" font-size="13" font-weight="bold" text-anchor="end" fill="#111827">$1646.46</text>
  </g>

  <!-- Left Bottom Terms/Signatures -->
  <g transform="translate(50, 750)">
    <text x="0" y="20" font-family="sans-serif" font-size="10" fill="#6b7280" font-weight="bold">TERMS &amp; CONDITIONS</text>
    <text x="0" y="35" font-family="sans-serif" font-size="9" fill="#9ca3af">1. All disputes subject to Pathankot Jurisdiction.</text>
    <text x="0" y="50" font-family="sans-serif" font-size="9" fill="#9ca3af">2. Interest @ 24% will be charged if not paid within due date.</text>
    
    <rect x="0" y="80" width="250" height="50" fill="none" stroke="#d1d5db" stroke-dasharray="3" rx="3"/>
    <text x="10" y="100" font-family="monospace" font-size="9" fill="#ef4444">AMBIGUOUS TEXT: "FOR SHIVAM DRUGS HOUSE"</text>
    <text x="10" y="115" font-family="monospace" font-size="9" fill="#9ca3af">OCR Confidence: 12.4% (Treated as anomaly)</text>
  </g>

  <g transform="translate(520, 800)">
    <line x1="0" y1="0" x2="180" y2="0" stroke="#9ca3af" stroke-width="1"/>
    <text x="90" y="15" font-family="sans-serif" font-size="10" fill="#4b5563" text-anchor="middle">Authorised Signatory</text>
  </g>

  <!-- Debug indicators directly rendered on background (simulated) -->
  <g transform="translate(50, 950)">
    <text x="0" y="15" font-family="monospace" font-size="11" fill="#0284c7" font-weight="bold">DEBUG PREVIEW MODE // ENGINE_V3_STABLE // CUDA-12.8</text>
  </g>
</svg>
`;

  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
};

// Prefilled local run records reflecting files found in local_runs/
const initialRuns: RunSummary[] = [
  {
    run_id: 'RUN_20260603_213604_1',
    filename: '38e5c640-96c4-4268-b092-58de09e63216.JPG',
    timestamp: getTimestamp(48),
    status: 'needs_review',
    confidence: 0.897,
    token_coverage: 0.942,
    representability_score: 0.865,
    selected_table_id: 'ITEMS_001',
    selected_table_shape: '4 Rows x 8 Columns',
    missing_fields: ['subtotal'],
    row_math_status: 'unmeasurable',
    is_demo: true
  },
  {
    run_id: 'RUN_20260603_213604_2',
    filename: '49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG',
    timestamp: getTimestamp(46),
    status: 'needs_review',
    confidence: 0.915,
    token_coverage: 0.912,
    representability_score: 0.720,
    selected_table_id: 'ITEMS_002',
    selected_table_shape: '2 Rows x 6 Columns',
    missing_fields: ['grand_total'],
    row_math_status: 'unmeasurable',
    is_demo: true
  },
  {
    run_id: 'RUN_20260603_213604_3',
    filename: '7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG',
    timestamp: getTimestamp(44),
    status: 'needs_review',
    confidence: 0.765,
    token_coverage: 0.824,
    representability_score: 0.584,
    selected_table_id: 'ITEMS_003',
    selected_table_shape: '9 Rows x 7 Columns',
    missing_fields: ['subtotal', 'grand_total'],
    row_math_status: 'unmeasurable',
    is_demo: true
  },
  {
    run_id: 'RUN_20260603_213604_4',
    filename: '7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG',
    timestamp: getTimestamp(40),
    status: 'safe_for_erp',
    confidence: 0.965,
    token_coverage: 0.985,
    representability_score: 0.984,
    selected_table_id: 'ITEMS_004',
    selected_table_shape: '11 Rows x 8 Columns',
    missing_fields: [],
    row_math_status: 'pass',
    is_demo: true
  },
  {
    run_id: 'RUN_20260603_213604_5',
    filename: '9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG',
    timestamp: getTimestamp(36),
    status: 'needs_review',
    confidence: 0.814,
    token_coverage: 0.875,
    representability_score: 0.652,
    selected_table_id: 'ITEMS_005',
    selected_table_shape: '6 Rows x 8 Columns',
    missing_fields: ['subtotal', 'grand_total'],
    row_math_status: 'unmeasurable',
    is_demo: true
  },
  {
    run_id: 'RUN_20260603_213604_6',
    filename: 'caf60269-bcd3-43e9-ad8c-2293eefbdbcb.JPG',
    timestamp: getTimestamp(32),
    status: 'needs_review',
    confidence: 0.826,
    token_coverage: 0.892,
    representability_score: 0.620,
    selected_table_id: 'ITEMS_006',
    selected_table_shape: '10 Rows x 7 Columns',
    missing_fields: ['subtotal', 'grand_total'],
    row_math_status: 'unmeasurable',
    is_demo: true
  },
  {
    run_id: 'RUN_20260603_213604_7',
    filename: 'cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG',
    timestamp: getTimestamp(28),
    status: 'failed',
    confidence: 0.450,
    token_coverage: 0.650,
    representability_score: 0.350,
    selected_table_id: 'ITEMS_007',
    selected_table_shape: '6 Rows x 4 Columns',
    missing_fields: ['subtotal', 'cgst', 'sgst'],
    row_math_status: 'fail',
    is_demo: true
  }
];

// Helper to clear storage
export function clearWorkbenchRunStorage() {
  localStorage.removeItem('ocr_workbench_runs');
  for (let i = localStorage.length - 1; i >= 0; i--) {
    const key = localStorage.key(i);
    if (key && key.startsWith('ocr_workbench_run_detail_')) {
      localStorage.removeItem(key);
    }
  }
}

// Helper to retrieve detailed backend run data
export const getDetailsData = (runId: string): any | null => {
  const saved = localStorage.getItem(`ocr_workbench_run_detail_${runId}`);
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch {
      return null;
    }
  }
  return null;
};

/**
 * Extracts a numeric index from a row/col identifier.
 * Handles: finite number, numeric string "14", prefixed string "row_14" / "col_0".
 * Returns null if extraction fails.
 */
function extractIndex(value: any, _prefix: 'row' | 'col'): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    // Direct numeric string: "14", "0"
    if (/^\d+$/.test(value)) return Number(value);
    // Prefixed: "row_14", "col_0", "r_2", "c_5"
    const match = value.match(/(\d+)$/);
    if (match) return Number(match[1]);
  }
  return null;
}

/**
 * Builds a dense TableCell[][] grid from backend cells that use string IDs
 * like row_id="row_14", col_id="col_0". Maps sparse row/col keys to dense
 * 0-based indexes so the resulting 2D array has no gaps.
 *
 * For Abka heuristic_region_6:
 *   row_14, row_15 → dense rows 0, 1
 *   col_0..col_5   → dense cols 0..5
 */
function buildDenseTableGrid(rawCells: any[]): TableCell[][] {
  if (!Array.isArray(rawCells) || rawCells.length === 0) return [];

  // ----- Collect all unique raw row and col keys -----
  const rowKeySet = new Set<string>();
  const colKeySet = new Set<string>();

  for (const cell of rawCells) {
    const rawRow = String(cell.row_index ?? cell.row_id ?? '0');
    const rawCol = String(cell.col_index ?? cell.col_id ?? '0');
    rowKeySet.add(rawRow);
    colKeySet.add(rawCol);
  }

  // ----- Sort keys by their extracted numeric index -----
  const sortByIndex = (a: string, b: string, prefix: 'row' | 'col'): number => {
    const ia = extractIndex(a, prefix);
    const ib = extractIndex(b, prefix);
    if (ia !== null && ib !== null) return ia - ib;
    if (ia !== null) return -1;
    if (ib !== null) return 1;
    return a.localeCompare(b);
  };

  const sortedRowKeys = [...rowKeySet].sort((a, b) => sortByIndex(a, b, 'row'));
  const sortedColKeys = [...colKeySet].sort((a, b) => sortByIndex(a, b, 'col'));

  // ----- Map raw keys to dense 0-based indexes -----
  const rowToDense: Record<string, number> = {};
  sortedRowKeys.forEach((key, idx) => { rowToDense[key] = idx; });

  const colToDense: Record<string, number> = {};
  sortedColKeys.forEach((key, idx) => { colToDense[key] = idx; });

  const numRows = sortedRowKeys.length;
  const numCols = sortedColKeys.length;

  // ----- Initialize empty grid -----
  const grid: TableCell[][] = Array.from({ length: numRows }, (_, r) =>
    Array.from({ length: numCols }, (_, c) => ({
      cell_id: `c_${r}_${c}`,
      row_id: r,
      col_id: c,
      text: '',
      confidence: 1.0,
      semantic_label: '',
      bbox: [0, 0, 0, 0] as [number, number, number, number],
      normalized_bbox: [0, 0, 0, 0] as [number, number, number, number],
      source_blocks: [] as string[],
      status: 'good' as const,
      warnings: [] as string[],
    }))
  );

  // ----- Populate grid with actual cell data -----
  for (const cell of rawCells) {
    const rawRow = String(cell.row_index ?? cell.row_id ?? '0');
    const rawCol = String(cell.col_index ?? cell.col_id ?? '0');
    const denseRow = rowToDense[rawRow] ?? 0;
    const denseCol = colToDense[rawCol] ?? 0;

    const conf = cell.confidence ?? cell.assignment_confidence ?? 1.0;
    const bbox = normalizeBBox(cell) || [0, 0, 0, 0] as [number, number, number, number];
    const nbbox = normalizeBBox(cell.normalized_bbox) || bbox;

    const status: 'good' | 'warning' | 'error' =
      cell.status || (conf < 0.6 ? 'error' : conf < 0.85 ? 'warning' : 'good');

    grid[denseRow][denseCol] = {
      cell_id: cell.cell_id || `c_${denseRow}_${denseCol}`,
      row_id: denseRow,
      col_id: denseCol,
      text: cell.text || '',
      confidence: conf,
      semantic_label: cell.semantic_label || cell.label || '',
      row_role: cell.row_role,
      role: cell.role,
      bbox: bbox as [number, number, number, number],
      normalized_bbox: nbbox as [number, number, number, number],
      source_blocks: cell.mapped_block_ids || cell.source_blocks || [],
      status,
      warnings: cell.warnings || [],
    };
  }

  return grid;
}

// ----- Footer/bank/tax/metadata text patterns for penalizing non-item regions -----
const FOOTER_PHRASES = /\b(bank\s*detail|account|ifsc|neft|rtgs|branch|upi|terms?\s*(?:and|&)\s*condition|subject\s*to|disclaimer|e\.?\s*&?\s*o\.?\s*e|signature|authorised|stamp|for\s*m\/s|goods\s*once\s*sold|cheque|self|bearer|original\s*copy|duplicate\s*copy)\b/i;

/**
 * Selects the main medicine/item table from the normalized diagnostics object.
 * Priority chain:
 *  1. detail.selected_table.table_id (explicit backend selection)
 *  2. detail.metrics.selected_main_table_id (metric-level selection)
 *  3. detail.metrics.main_table_candidate_scores[0].table_id (ranked candidates)
 *  4. detail.metrics.tsr_candidate_decision.selected mapped to structured table
 *  5. Heuristic scoring across structured_tables
 *  6. structured_tables[0] fallback
 *
 * Returns the table object from structured_tables, or null if none found.
 */
export function selectMainTable(detail: any): any {
  const tables: any[] = detail?.structured_tables;
  if (!Array.isArray(tables) || tables.length === 0) {
    // Fall through to other shapes
    return detail?.selected_table || detail?.main_table || null;
  }

  // Build a quick lookup by table_id
  const byId: Record<string, any> = {};
  for (const t of tables) {
    if (t.table_id) byId[t.table_id] = t;
  }

  const findById = (id: string | undefined | null): any | null => {
    if (!id || id === 'unknown') return null;
    return byId[id] ?? null;
  };

  // ---------- 1. Explicit backend selection ----------
  if (detail.selected_table?.table_id) {
    const match = findById(detail.selected_table.table_id);
    if (match) return match;
  }

  // ---------- 2. metrics.selected_main_table_id ----------
  const metrics = detail.metrics || detail.metadata?.metrics;
  if (metrics?.selected_main_table_id) {
    const match = findById(metrics.selected_main_table_id);
    if (match) return match;
  }

  // ---------- 3. metrics.main_table_candidate_scores[0] ----------
  if (Array.isArray(metrics?.main_table_candidate_scores) && metrics.main_table_candidate_scores.length > 0) {
    const topId = metrics.main_table_candidate_scores[0]?.table_id;
    const match = findById(topId);
    if (match) return match;
  }

  // ---------- 4. tsr_candidate_decision.selected ----------
  const tsrDecision = detail.tsr_candidate_decision || metrics?.tsr_candidate_decision;
  if (tsrDecision?.selected) {
    // tsr_candidate_decision.selected is a source key like "heuristic_anchor",
    // not a table_id directly. But the candidate may reference a table_id.
    const cand = tsrDecision.candidates?.[tsrDecision.selected];
    if (cand?.table_id) {
      const match = findById(cand.table_id);
      if (match) return match;
    }
    // Also try matching the selected key itself as a table_id prefix
    const match = findById(tsrDecision.selected);
    if (match) return match;
  }

  // ---------- 5. Heuristic scoring ----------
  let bestTable: any = null;
  let bestScore = -Infinity;

  for (const t of tables) {
    const rows = t.rows ?? (Array.isArray(t.cells) ? new Set(t.cells.map((c: any) => c.row_index ?? c.row_id ?? 0)).size : 0);
    const cols = t.cols ?? t.columns ?? (Array.isArray(t.cells) ? new Set(t.cells.map((c: any) => c.col_index ?? c.col_id ?? 0)).size : 0);
    const cellCount = Array.isArray(t.cells) ? t.cells.length : 0;

    let score = 0;

    // Dimensional bonuses
    if (rows >= 2) score += 50;
    if (cols >= 4) score += 50;
    if (cellCount >= 8) score += 30;
    score += Math.min(rows * 5, 100);   // row count bonus, capped
    score += Math.min(cols * 3, 30);    // col count bonus, capped

    // Medicine table type bonus
    if (t.region_type === 'medicine_table') score += 200;

    // Sample text evidence
    const sampleText = (t.sample || '') + ' ' +
      (Array.isArray(t.cells) ? t.cells.map((c: any) => c.text || '').join(' ') : '');

    if (/\b(batch|lot)\b/i.test(sampleText)) score += 30;
    if (/\b(exp(?:iry)?|mfg)\b/i.test(sampleText)) score += 30;
    if (/\b(hsn|sac)\b/i.test(sampleText)) score += 20;
    if (/\d+\.\d{2}/.test(sampleText)) score += 15;  // money-like decimals
    if (/\d{2}\/\d{2,4}/.test(sampleText)) score += 10; // date-like

    // Penalize footer/bank/tax/metadata regions
    if (FOOTER_PHRASES.test(sampleText)) score -= 200;
    if (t.region_type && /footer|bank|tax|metadata|header|summary/i.test(t.region_type)) score -= 150;

    // Penalize single-row or single-column tables
    if (rows <= 1) score -= 80;
    if (cols <= 1) score -= 80;

    if (score > bestScore) {
      bestScore = score;
      bestTable = t;
    }
  }

  // ---------- 6. Ultimate fallback ----------
  return bestTable || tables[0];
}

// Normalizes and preserves multi-path backend diagnostics formats
export function normalizeBackendDiagnostics(backendData: any): any {
  if (!backendData || typeof backendData !== 'object') {
    return {};
  }

  // Preserve all raw keys by cloning the top-level structure
  const res: any = { ...backendData };

  // Make sure we have a metadata object to store fallback normalized results
  if (!res.metadata) {
    res.metadata = {};
  }

  // Resolve OCR blocks
  const blocks = 
    backendData.blocks || 
    backendData.ocr_blocks || 
    backendData.metadata?.blocks || 
    backendData.metadata?.ocr_blocks || 
    backendData.reconstruction?.blocks || 
    backendData.raw_ocr?.blocks;
  if (blocks) {
    res.blocks = blocks;
    res.metadata.blocks = blocks;
  }

  // Resolve Structured Tables
  const structured_tables = 
    backendData.structured_tables || 
    backendData.metadata?.structured_tables || 
    backendData.reconstructed_tables || 
    backendData.metadata?.reconstructed_tables || 
    backendData.tables || 
    backendData.metadata?.tables;
  if (structured_tables) {
    res.structured_tables = structured_tables;
    res.metadata.structured_tables = structured_tables;
  }

  // Resolve Candidate Table Decision
  const tsr_candidate_decision = 
    backendData.tsr_candidate_decision || 
    backendData.metadata?.tsr_candidate_decision || 
    backendData.metrics?.tsr_candidate_decision || 
    backendData.metadata?.metrics?.tsr_candidate_decision || 
    backendData.routing_diagnostics || 
    backendData.metadata?.routing_diagnostics || 
    backendData.table_candidates || 
    backendData.metadata?.table_candidates;
  if (tsr_candidate_decision) {
    res.tsr_candidate_decision = tsr_candidate_decision;
    res.metadata.tsr_candidate_decision = tsr_candidate_decision;
  }

  // Resolve Semantic Data
  const semantic_columns = 
    backendData.table_semantics || 
    backendData.metadata?.table_semantics || 
    backendData.semantic_columns || 
    backendData.metadata?.semantic_columns || 
    backendData.column_semantics || 
    backendData.metadata?.column_semantics || 
    backendData.structured_tables?.[0]?.metadata?.column_semantics ||
    selectMainTable(backendData)?.metadata?.column_semantics;
  if (semantic_columns) {
    res.semantic_columns = semantic_columns;
    res.metadata.semantic_columns = semantic_columns;
  }

  // Resolve Financial Reconciliation
  const financial_reconciliation = 
    backendData.financial_reconciliation || 
    backendData.metadata?.financial_reconciliation || 
    backendData.metrics?.financial_reconciliation || 
    backendData.metadata?.metrics?.financial_reconciliation;
  if (financial_reconciliation) {
    res.financial_reconciliation = financial_reconciliation;
    res.metadata.financial_reconciliation = financial_reconciliation;
  }

  const processed_image =
    backendData.processed_image ||
    backendData.metadata?.processed_image ||
    backendData.metadata?.image_processing?.processed_image;
  if (processed_image) {
    res.processed_image = processed_image;
    res.metadata.processed_image = processed_image;
  }

  // Resolve Quality Gate
  const quality_gate = 
    backendData.quality_gate || 
    backendData.metadata?.quality_gate || 
    backendData.canonical_invoice?.quality_gate || 
    backendData.metadata?.canonical_invoice?.quality_gate;
  if (quality_gate) {
    res.quality_gate = quality_gate;
    res.metadata.quality_gate = quality_gate;
  }

  // Dev mode logging
  if (import.meta.env.DEV) {
    console.log('[DEV] Raw Backend Data Keys:', Object.keys(backendData));
    console.log('[DEV] Raw Metadata Keys:', Object.keys(backendData.metadata || {}));
    console.log('[DEV] Normalized OCR blocks count:', res.blocks?.length || 0);
    console.log('[DEV] Normalized Structured Tables count:', res.structured_tables?.length || 0);
    
    let candCount = 0;
    if (res.tsr_candidate_decision?.candidates) {
      candCount = Object.keys(res.tsr_candidate_decision.candidates).length;
    } else if (Array.isArray(res.tsr_candidate_decision)) {
      candCount = res.tsr_candidate_decision.length;
    } else if (res.tsr_candidate_decision?.table_regions) {
      candCount = res.tsr_candidate_decision.table_regions.length;
    }
    console.log('[DEV] Normalized Candidate Tables count:', candCount);

    let semanticCount = 0;
    if (Array.isArray(res.semantic_columns)) {
      semanticCount = res.semantic_columns.length;
    } else if (res.semantic_columns && typeof res.semantic_columns === 'object') {
      semanticCount = Object.keys(res.semantic_columns).length;
    }
    console.log('[DEV] Normalized Semantic Columns count:', semanticCount);
    console.log('[DEV] Normalized Quality Gate present:', !!res.quality_gate);
  }

  return res;
}

// Helper to store Runs in local storage to keep state across page refreshes
const getStoredRuns = (): RunSummary[] => {
  const saved = localStorage.getItem('ocr_workbench_runs');
  if (saved) {
    try {
      let runs: RunSummary[] = JSON.parse(saved);
      if (!ENABLE_MOCK_DATA) {
        const containsDemo = runs.some(r => r.run_id.startsWith('RUN_20260603_213604_'));
        if (containsDemo) {
          clearWorkbenchRunStorage();
          runs = [];
        }
      }
      return runs;
    } catch {
      return ENABLE_MOCK_DATA ? initialRuns : [];
    }
  }
  if (ENABLE_MOCK_DATA) {
    localStorage.setItem('ocr_workbench_runs', JSON.stringify(initialRuns));
    return initialRuns;
  }
  return [];
};

const saveStoredRuns = (runs: RunSummary[]) => {
  localStorage.setItem('ocr_workbench_runs', JSON.stringify(runs));
};

// Mock OCR blocks coordinate map.
// These bounding boxes line up with the SVG invoice layout defined above!
// normalized_bbox format: [x_min, y_min, x_max, y_max] from 0 to 1.
// In absolute pixels relative to 800x1000: [x_min_px, y_min_px, x_max_px, y_max_px].
const getMockOCRBlocks = (_runId: string): OCRBlock[] => {
  return [
    // Header block
    {
      block_id: 'blk_001',
      text: 'GENOME PHARMACEUTICALS',
      confidence: 0.998,
      bbox: [60, 60, 350, 95],
      normalized_bbox: [0.075, 0.06, 0.4375, 0.095],
      status: 'mapped',
    },
    {
      block_id: 'blk_002',
      text: 'COMMERCIAL INVOICE',
      confidence: 0.995,
      bbox: [60, 105, 250, 120],
      normalized_bbox: [0.075, 0.105, 0.3125, 0.12],
      status: 'mapped',
    },
    {
      block_id: 'blk_003',
      text: 'INVOICE NO: TBL_UUID_99120-X',
      confidence: 0.999,
      bbox: [480, 70, 750, 85],
      normalized_bbox: [0.6, 0.07, 0.9375, 0.085],
      status: 'mapped',
    },
    // Row 1 OCR blocks
    {
      block_id: 'blk_row1_num',
      text: '01',
      confidence: 0.994,
      bbox: [50, 275, 75, 290],
      normalized_bbox: [0.0625, 0.275, 0.09375, 0.29],
      assigned_row_id: 1,
      assigned_col_id: 0,
      assigned_cell_id: 'c_01_0',
      status: 'mapped',
    },
    {
      block_id: 'blk_row1_desc',
      text: 'Amoxicillin 500mg Cap (100)',
      confidence: 0.995,
      bbox: [80, 275, 320, 290],
      normalized_bbox: [0.1, 0.275, 0.4, 0.29],
      assigned_row_id: 1,
      assigned_col_id: 1,
      assigned_cell_id: 'c_01_1',
      status: 'mapped',
    },
    {
      block_id: 'blk_row1_batch',
      text: 'BN-99212',
      confidence: 0.985,
      bbox: [340, 275, 410, 290],
      normalized_bbox: [0.425, 0.275, 0.5125, 0.29],
      assigned_row_id: 1,
      assigned_col_id: 2,
      assigned_cell_id: 'c_01_2',
      status: 'mapped',
    },
    {
      block_id: 'blk_row1_expiry',
      text: '12/2028',
      confidence: 0.991,
      bbox: [440, 275, 500, 290],
      normalized_bbox: [0.55, 0.275, 0.625, 0.29],
      assigned_row_id: 1,
      assigned_col_id: 3,
      assigned_cell_id: 'c_01_3',
      status: 'mapped',
    },
    {
      block_id: 'blk_row1_qty',
      text: '12',
      confidence: 0.998,
      bbox: [520, 275, 545, 0.29],
      normalized_bbox: [0.65, 0.275, 0.681, 0.29],
      assigned_row_id: 1,
      assigned_col_id: 4,
      assigned_cell_id: 'c_01_4',
      status: 'mapped',
    },
    {
      block_id: 'blk_row1_rate',
      text: '42.00',
      confidence: 0.996,
      bbox: [570, 275, 620, 290],
      normalized_bbox: [0.7125, 0.275, 0.775, 0.29],
      assigned_row_id: 1,
      assigned_col_id: 5,
      assigned_cell_id: 'c_01_5',
      status: 'mapped',
    },
    {
      block_id: 'blk_row1_disc',
      text: '8.0%',
      confidence: 0.984,
      bbox: [630, 275, 670, 290],
      normalized_bbox: [0.7875, 0.275, 0.8375, 0.29],
      assigned_row_id: 1,
      assigned_col_id: 6,
      assigned_cell_id: 'c_01_6',
      status: 'mapped',
    },
    {
      block_id: 'blk_row1_amt',
      text: '$504.00',
      confidence: 0.997,
      bbox: [690, 275, 750, 290],
      normalized_bbox: [0.8625, 0.275, 0.9375, 0.29],
      assigned_row_id: 1,
      assigned_col_id: 7,
      assigned_cell_id: 'c_01_7',
      status: 'mapped',
    },

    // Row 2 OCR blocks - contains BN-???? anomaly
    {
      block_id: 'blk_row2_num',
      text: '02',
      confidence: 0.994,
      bbox: [50, 315, 75, 330],
      normalized_bbox: [0.0625, 0.315, 0.09375, 0.33],
      assigned_row_id: 2,
      assigned_col_id: 0,
      assigned_cell_id: 'c_02_0',
      status: 'mapped',
    },
    {
      block_id: 'blk_row2_desc',
      text: 'Ciprofloxacin 250mg Tab (20)',
      confidence: 0.998,
      bbox: [80, 315, 318, 340],
      normalized_bbox: [0.1, 0.318, 0.398, 0.34],
      assigned_row_id: 2,
      assigned_col_id: 1,
      assigned_cell_id: 'c_02_1',
      status: 'mapped',
    },
    {
      block_id: 'blk_row2_batch',
      text: 'BN-????',
      confidence: 0.410,
      bbox: [340, 315, 410, 330],
      normalized_bbox: [0.425, 0.315, 0.5125, 0.33],
      assigned_row_id: 2,
      assigned_col_id: 2,
      assigned_cell_id: 'c_02_2',
      status: 'low_confidence',
      warnings: ['Contains ambiguous question mark characters', 'Low engine classification score'],
    },
    {
      block_id: 'blk_row2_expiry',
      text: '05/2027',
      confidence: 0.991,
      bbox: [440, 315, 500, 330],
      normalized_bbox: [0.55, 0.315, 0.625, 0.33],
      assigned_row_id: 2,
      assigned_col_id: 3,
      assigned_cell_id: 'c_02_3',
      status: 'mapped',
    },
    {
      block_id: 'blk_row2_qty',
      text: '5',
      confidence: 0.998,
      bbox: [520, 315, 545, 330],
      normalized_bbox: [0.65, 0.315, 0.681, 0.33],
      assigned_row_id: 2,
      assigned_col_id: 4,
      assigned_cell_id: 'c_02_4',
      status: 'mapped',
    },
    {
      block_id: 'blk_row2_rate',
      text: '125.50',
      confidence: 0.998,
      bbox: [570, 315, 620, 330],
      normalized_bbox: [0.7125, 0.315, 0.775, 0.33],
      assigned_row_id: 2,
      assigned_col_id: 5,
      assigned_cell_id: 'c_02_5',
      status: 'mapped',
    },
    {
      block_id: 'blk_row2_disc',
      text: '8.0%',
      confidence: 0.980,
      bbox: [630, 315, 670, 330],
      normalized_bbox: [0.7875, 0.315, 0.8375, 0.33],
      assigned_row_id: 2,
      assigned_col_id: 6,
      assigned_cell_id: 'c_02_6',
      status: 'mapped',
    },
    {
      block_id: 'blk_row2_amt',
      text: '$627.50',
      confidence: 0.998,
      bbox: [690, 315, 750, 0.33],
      normalized_bbox: [0.8625, 0.315, 0.9375, 0.33],
      assigned_row_id: 2,
      assigned_col_id: 7,
      assigned_cell_id: 'c_02_7',
      status: 'mapped',
    },

    // Orphan / Ambiguous block in terms section
    {
      block_id: 'blk_orphan_1',
      text: 'FOR SHIVAM DRUGS HOUSE',
      confidence: 0.124,
      bbox: [60, 845, 240, 860],
      normalized_bbox: [0.075, 0.845, 0.3, 0.86],
      status: 'orphan',
      warnings: ['OCR read score below threshold (0.15)', 'Unassigned to any table column boundary', 'Potential stamp overlap'],
    },
    {
      block_id: 'blk_orphan_2',
      text: 'SMILE',
      confidence: 0.520,
      bbox: [720, 970, 770, 985],
      normalized_bbox: [0.9, 0.97, 0.9625, 0.985],
      status: 'orphan',
      warnings: ['Unassigned water mark text'],
    }
  ];
};

// Mock candidate tables - TSR extraction candidates
const getMockCandidateTables = (_runId: string): CandidateTable[] => {
  return [
    {
      table_id: 'T_ID_001A',
      source_engine: 'PPStructure',
      rows: 4,
      cols: 8,
      x_coverage: 98.2,
      y_coverage: 95.5,
      cell_count: 32,
      non_empty_cells: 32,
      score: 0.994,
      labels: ['item_table', 'pharma_layout'],
      selected: true,
      representability_score: 0.984,
      preview_cells: [
        ['#', 'PRODUCT', 'BATCH', 'EXPIRY', 'QTY', 'RATE', 'DISC', 'AMOUNT'],
        ['01', 'Amoxicillin Cap', 'BN-99212', '12/2028', '12', '42.00', '8%', '$504.0'],
        ['02', 'Ciprofloxacin Tab', 'BN-????', '05/2027', '5', '125.50', '8%', '$627.5'],
      ]
    },
    {
      table_id: 'T_ID_001B',
      source_engine: 'TATR',
      rows: 2,
      cols: 2,
      x_coverage: 42.1,
      y_coverage: 20.4,
      cell_count: 4,
      non_empty_cells: 4,
      score: 0.410,
      labels: ['header_metadata'],
      selected: false,
      rejection_reason: 'Coverage below threshold (0.60) and fails pharma-grid heuristic',
      representability_score: 0.320,
      preview_cells: [
        ['INVOICE NO', 'TBL_UUID_99120-X'],
        ['Date', '2026-06-03']
      ]
    },
    {
      table_id: 'T_ID_002A',
      source_engine: 'Heuristic_TSR',
      rows: 4,
      cols: 8,
      x_coverage: 82.4,
      y_coverage: 78.6,
      cell_count: 32,
      non_empty_cells: 26,
      score: 0.842,
      labels: ['item_table'],
      selected: false,
      rejection_reason: 'Spatial overlap with selected primary table T_ID_001A (PPStructure)',
      representability_score: 0.810,
      preview_cells: [
        ['#', 'PRODUCT / DESC', 'BATCH', 'EXPIRY', 'QTY', 'RATE', 'DISC', 'AMOUNT'],
        ['01', 'Amoxicillin Cap', '', '12/2028', '12', '42.00', '8%', '']
      ]
    },
    {
      table_id: 'T_ID_003X',
      source_engine: 'TATR',
      rows: 1,
      cols: 1,
      x_coverage: 12.0,
      y_coverage: 5.0,
      cell_count: 1,
      non_empty_cells: 1,
      score: 0.120,
      labels: ['isolated_text_block'],
      selected: false,
      rejection_reason: 'Insignificant region size',
      representability_score: 0.120,
      preview_cells: [['FOR SHIVAM DRUGS HOUSE']]
    }
  ];
};

// Mock Selected Table structure
const getMockSelectedTable = (_runId: string): SelectedTable => {
  const cells: TableCell[][] = [
    // Header Row
    [
      { cell_id: 'c_h_0', row_id: 0, col_id: 0, text: '#', confidence: 0.999, semantic_label: 'row_index', bbox: [50, 220, 75, 250], normalized_bbox: [0.0625, 0.22, 0.09375, 0.25], source_blocks: [], status: 'good' },
      { cell_id: 'c_h_1', row_id: 0, col_id: 1, text: 'PRODUCT / DESCRIPTION', confidence: 0.998, semantic_label: 'product_name', bbox: [80, 220, 320, 250], normalized_bbox: [0.1, 0.22, 0.4, 0.25], source_blocks: [], status: 'good' },
      { cell_id: 'c_h_2', row_id: 0, col_id: 2, text: 'BATCH', confidence: 0.998, semantic_label: 'batch_no', bbox: [330, 220, 420, 250], normalized_bbox: [0.4125, 0.22, 0.525, 0.25], source_blocks: [], status: 'good' },
      { cell_id: 'c_h_3', row_id: 0, col_id: 3, text: 'EXPIRY', confidence: 0.997, semantic_label: 'expiry_date', bbox: [430, 220, 500, 250], normalized_bbox: [0.5375, 0.22, 0.625, 0.25], source_blocks: [], status: 'good' },
      { cell_id: 'c_h_4', row_id: 0, col_id: 4, text: 'QTY', confidence: 0.999, semantic_label: 'quantity', bbox: [510, 220, 550, 250], normalized_bbox: [0.6375, 0.22, 0.6875, 0.25], source_blocks: [], status: 'good' },
      { cell_id: 'c_h_5', row_id: 0, col_id: 5, text: 'RATE', confidence: 0.999, semantic_label: 'unit_price', bbox: [560, 220, 620, 250], normalized_bbox: [0.7, 0.22, 0.775, 0.25], source_blocks: [], status: 'good' },
      { cell_id: 'c_h_6', row_id: 0, col_id: 6, text: 'DISC%', confidence: 0.996, semantic_label: 'discount_rate', bbox: [630, 220, 670, 250], normalized_bbox: [0.7875, 0.22, 0.8375, 0.25], source_blocks: [], status: 'good' },
      { cell_id: 'c_h_7', row_id: 0, col_id: 7, text: 'AMOUNT', confidence: 0.999, semantic_label: 'row_total', bbox: [680, 220, 760, 250], normalized_bbox: [0.85, 0.22, 0.95, 0.25], source_blocks: [], status: 'good' }
    ],
    // Row 1
    [
      { cell_id: 'c_01_0', row_id: 1, col_id: 0, text: '01', confidence: 0.994, semantic_label: 'row_index', bbox: [50, 275, 75, 290], normalized_bbox: [0.0625, 0.275, 0.09375, 0.29], source_blocks: ['blk_row1_num'], status: 'good' },
      { cell_id: 'c_01_1', row_id: 1, col_id: 1, text: 'Amoxicillin 500mg Cap (100)', confidence: 0.995, semantic_label: 'product_name', bbox: [80, 275, 320, 290], normalized_bbox: [0.1, 0.275, 0.4, 0.29], source_blocks: ['blk_row1_desc'], status: 'good' },
      { cell_id: 'c_01_2', row_id: 1, col_id: 2, text: 'BN-99212', confidence: 0.985, semantic_label: 'batch_no', bbox: [340, 275, 410, 290], normalized_bbox: [0.425, 0.275, 0.5125, 0.29], source_blocks: ['blk_row1_batch'], status: 'good' },
      { cell_id: 'c_01_3', row_id: 1, col_id: 3, text: '12/2028', confidence: 0.991, semantic_label: 'expiry_date', bbox: [440, 275, 500, 290], normalized_bbox: [0.55, 0.275, 0.625, 0.29], source_blocks: ['blk_row1_expiry'], status: 'good' },
      { cell_id: 'c_01_4', row_id: 1, col_id: 4, text: '12', confidence: 0.998, semantic_label: 'quantity', bbox: [520, 275, 545, 290], normalized_bbox: [0.65, 0.275, 0.681, 0.29], source_blocks: ['blk_row1_qty'], status: 'good' },
      { cell_id: 'c_01_5', row_id: 1, col_id: 5, text: '42.00', confidence: 0.996, semantic_label: 'unit_price', bbox: [570, 275, 620, 290], normalized_bbox: [0.7125, 0.275, 0.775, 0.29], source_blocks: ['blk_row1_rate'], status: 'good' },
      { cell_id: 'c_01_6', row_id: 1, col_id: 6, text: '8.0%', confidence: 0.984, semantic_label: 'discount_rate', bbox: [630, 275, 670, 290], normalized_bbox: [0.7875, 0.275, 0.8375, 0.29], source_blocks: ['blk_row1_disc'], status: 'good' },
      { cell_id: 'c_01_7', row_id: 1, col_id: 7, text: '504.00', confidence: 0.997, semantic_label: 'row_total', bbox: [690, 275, 750, 290], normalized_bbox: [0.8625, 0.275, 0.9375, 0.29], source_blocks: ['blk_row1_amt'], status: 'good' }
    ],
    // Row 2 - containing low confidence / review needed
    [
      { cell_id: 'c_02_0', row_id: 2, col_id: 0, text: '02', confidence: 0.994, semantic_label: 'row_index', bbox: [50, 315, 75, 330], normalized_bbox: [0.0625, 0.315, 0.09375, 0.33], source_blocks: ['blk_row2_num'], status: 'good' },
      { cell_id: 'c_02_1', row_id: 2, col_id: 1, text: 'Ciprofloxacin 250mg Tab (20)', confidence: 0.998, semantic_label: 'product_name', bbox: [80, 315, 318, 340], normalized_bbox: [0.1, 0.318, 0.398, 0.34], source_blocks: ['blk_row2_desc'], status: 'good' },
      { cell_id: 'c_02_2', row_id: 2, col_id: 2, text: 'BN-????', confidence: 0.410, semantic_label: 'batch_no', bbox: [340, 315, 410, 330], normalized_bbox: [0.425, 0.315, 0.5125, 0.33], source_blocks: ['blk_row2_batch'], status: 'error', warnings: ['Non-alphanumeric characters detected (?, ?)', 'OCR Engine raw confidence 41%'] },
      { cell_id: 'c_02_3', row_id: 2, col_id: 3, text: '05/2027', confidence: 0.991, semantic_label: 'expiry_date', bbox: [440, 315, 500, 330], normalized_bbox: [0.55, 0.315, 0.625, 0.33], source_blocks: ['blk_row2_expiry'], status: 'good' },
      { cell_id: 'c_02_4', row_id: 2, col_id: 4, text: '5', confidence: 0.998, semantic_label: 'quantity', bbox: [520, 315, 545, 330], normalized_bbox: [0.65, 0.315, 0.681, 0.33], source_blocks: ['blk_row2_qty'], status: 'good' },
      { cell_id: 'c_02_5', row_id: 2, col_id: 5, text: '125.50', confidence: 0.998, semantic_label: 'unit_price', bbox: [570, 315, 620, 330], normalized_bbox: [0.7125, 0.315, 0.775, 0.33], source_blocks: ['blk_row2_rate'], status: 'good' },
      { cell_id: 'c_02_6', row_id: 2, col_id: 6, text: '8.0%', confidence: 0.980, semantic_label: 'discount_rate', bbox: [630, 315, 670, 330], normalized_bbox: [0.7875, 0.315, 0.8375, 0.33], source_blocks: ['blk_row2_disc'], status: 'good' },
      { cell_id: 'c_02_7', row_id: 2, col_id: 7, text: '627.50', confidence: 0.998, semantic_label: 'row_total', bbox: [690, 315, 750, 330], normalized_bbox: [0.8625, 0.315, 0.9375, 0.33], source_blocks: ['blk_row2_amt'], status: 'good' }
    ]
  ];

  return {
    table_id: 'ITEMS_001',
    rows: 4,
    cols: 8,
    x_coverage: 98.2,
    non_empty_cells: 32,
    representability_score: 0.984,
    required_fields_present: ['product_name', 'quantity', 'unit_price', 'row_total', 'batch_no', 'expiry_date'],
    required_fields_missing: ['subtotal'],
    cells
  };
};

// Mock semantic column models
const getMockSemanticMapping = (_runId: string): SemanticColumn[] => {
  return [
    {
      col_id: 0,
      predicted_type: 'row_index',
      confidence: 0.999,
      header_text: '#',
      sample_values: ['01', '02', '03', '04'],
      competing_candidates: [
        { type: 'row_index', confidence: 0.999 },
        { type: 'product_id', confidence: 0.120 }
      ],
      conflict_resolution_reason: 'Resolved by pattern-matching grid index rules'
    },
    {
      col_id: 1,
      predicted_type: 'product_name',
      confidence: 0.997,
      header_text: 'PRODUCT / DESCRIPTION',
      sample_values: ['Amoxicillin 500mg Cap (100)', 'Ciprofloxacin 250mg Tab (20)'],
      competing_candidates: [
        { type: 'product_name', confidence: 0.997 },
        { type: 'line_comment', confidence: 0.230 }
      ],
      conflict_resolution_reason: 'Resolved via semantic text categorization and layout length'
    },
    {
      col_id: 2,
      predicted_type: 'batch_no',
      confidence: 0.884,
      header_text: 'BATCH',
      sample_values: ['BN-99212', 'BN-????', 'BN-8812'],
      competing_candidates: [
        { type: 'batch_no', confidence: 0.884 },
        { type: 'unknown_metadata', confidence: 0.350 }
      ],
      warnings: ['Column contains low confidence values in Row 2 ("BN-????")'],
      conflict_resolution_reason: 'Regex header check match: "BATCH" / "B.NO"'
    },
    {
      col_id: 3,
      predicted_type: 'expiry_date',
      confidence: 0.992,
      header_text: 'EXPIRY',
      sample_values: ['12/2028', '05/2027', '08/2028'],
      competing_candidates: [
        { type: 'expiry_date', confidence: 0.992 },
        { type: 'manufacturing_date', confidence: 0.480 }
      ],
      conflict_resolution_reason: 'Format mm/yyyy matched and header matches "EXP"'
    },
    {
      col_id: 4,
      predicted_type: 'quantity',
      confidence: 0.998,
      header_text: 'QTY',
      sample_values: ['12', '5', '20', '10'],
      competing_candidates: [
        { type: 'quantity', confidence: 0.998 },
        { type: 'free_qty', confidence: 0.050 }
      ],
      conflict_resolution_reason: 'All integer fields matching quantity distribution shape'
    },
    {
      col_id: 5,
      predicted_type: 'unit_price',
      confidence: 0.995,
      header_text: 'RATE',
      sample_values: ['42.00', '125.50', '15.20'],
      competing_candidates: [
        { type: 'unit_price', confidence: 0.995 },
        { type: 'mrp', confidence: 0.740 }
      ],
      conflict_resolution_reason: 'Header check matching "RATE" / "PRICE"'
    },
    {
      col_id: 6,
      predicted_type: 'discount_rate',
      confidence: 0.950,
      header_text: 'DISC%',
      sample_values: ['8.0%', '8.0%', '8.0%'],
      competing_candidates: [
        { type: 'discount_rate', confidence: 0.950 },
        { type: 'gst_rate', confidence: 0.120 }
      ],
      conflict_resolution_reason: 'Header check matching "DISC%" / "DISCOUNT"'
    },
    {
      col_id: 7,
      predicted_type: 'row_total',
      confidence: 0.998,
      header_text: 'AMOUNT',
      sample_values: ['504.00', '627.50', '304.00'],
      competing_candidates: [
        { type: 'row_total', confidence: 0.998 },
        { type: 'subtotal_amount', confidence: 0.140 }
      ],
      conflict_resolution_reason: 'Verified by row mathematical correlation (qty * rate - disc = amount)'
    }
  ];
};

// Mock row mathematical audit results (reconciliation check)
const getMockRowMath = (_runId: string): RowMathResult[] => {
  return [
    {
      row_id: 1,
      product: 'Amoxicillin 500mg Cap (100)',
      qty: 12,
      rate: 42.00,
      discount: 8.0, // 8%
      gst: 18.0,
      expected_amount: 504.00, // wait: 12 * 42 = 504.00 (with discount: 504 * 0.92 = 463.68, but if amount field is actual 504.00, maybe rate is pre-discount or rate has formula rate * qty = 504.00)
      actual_amount: 504.00,
      difference: 0.00,
      status: 'pass',
      formula_used: 'actual_amount == qty * rate'
    },
    {
      row_id: 2,
      product: 'Ciprofloxacin 250mg Tab (20)',
      qty: 5,
      rate: 125.50,
      discount: 8.0,
      gst: 18.0,
      expected_amount: 627.50, // 5 * 125.5 = 627.50
      actual_amount: 627.50,
      difference: 0.00,
      status: 'pass',
      formula_used: 'actual_amount == qty * rate'
    },
    {
      row_id: 3,
      product: 'Ibuprofen 400mg (50)',
      qty: 20,
      rate: 15.20,
      discount: 8.0,
      gst: 18.0,
      expected_amount: 304.00, // 20 * 15.2 = 304.00
      actual_amount: 304.00,
      difference: 0.00,
      status: 'pass',
      formula_used: 'actual_amount == qty * rate'
    },
    {
      row_id: 4,
      product: 'Omeprazole 20mg (30)',
      qty: 10,
      rate: 8.90,
      discount: 8.0,
      gst: 18.0,
      expected_amount: 89.00, // 10 * 8.9 = 89.00
      actual_amount: 89.00,
      difference: 0.00,
      status: 'pass',
      formula_used: 'actual_amount == qty * rate'
    }
  ];
};

// Mock Quality Gate schema detailing ERP readiness decisions
const getMockQualityGate = (runId: string): QualityGate => {
  const isFailed = runId.includes('_7');
  const isSafe = runId.includes('_4');
  
  return {
    safe_for_erp: isSafe,
    status_effective: isSafe ? 'safe_for_erp' : (isFailed ? 'failed' : 'needs_review'),
    confidence: isSafe ? 0.965 : (isFailed ? 0.450 : 0.897),
    reasons: isSafe 
      ? ['All checks passed successfully. All key financial variables reconciled.']
      : (isFailed 
          ? ['Raw OCR confidence below threshold (0.60)', 'Row mathematical reconciliation fails on multiple line items', 'Required SGST/CGST fields are missing from footer'] 
          : ['Required footer field "subtotal" is missing', 'Low confidence character block detected: "BN-????"', 'Orphan tokens present: "FOR SHIVAM DRUGS HOUSE" (stamp overlap risk)']),
    missing_fields: isSafe ? [] : (isFailed ? ['subtotal', 'cgst', 'sgst'] : ['subtotal']),
    footer_status: isSafe ? 'Verified & Reconciled' : 'Fails checklist: subtotal missing from bottom region',
    row_math_status: isSafe ? 'pass' : (isFailed ? 'fail' : 'unmeasurable'),
    checklist: [
      {
        name: 'Image Validation & Resolution',
        status: 'pass',
        explanation: 'Image is readable, has clear resolution and layout profile dense_pharma_table.'
      },
      {
        name: 'OCR Core Completion Score',
        status: isFailed ? 'fail' : 'pass',
        explanation: isFailed ? 'Mean confidence 45% is below minimum threshold of 70%.' : 'Mean confidence above threshold (89% score).'
      },
      {
        name: 'Table Representability (TSR Grid)',
        status: isFailed ? 'fail' : (isSafe ? 'pass' : 'warning'),
        explanation: isSafe ? 'Full grid stability verified. Columns aligned.' : (isFailed ? 'Failed: Grid contains overlapping coordinates.' : 'Warning: Bounding boxes are unstable near footer boundary.')
      },
      {
        name: 'Required Column Headers Present',
        status: isSafe ? 'pass' : 'warning',
        explanation: isSafe ? 'All required columns (Product, Qty, Rate, Batch, Expiry, Total) present.' : 'Warning: Header column mapping detected missing required fields.'
      },
      {
        name: 'Row Math Reconciliation',
        status: isSafe ? 'pass' : (isFailed ? 'fail' : 'warning'),
        explanation: isSafe ? 'All line items strictly reconciled (tolerance 0.01).' : (isFailed ? 'Fails: Line amount totals do not reconcile with rate*qty.' : 'Warning: Row math unmeasurable due to OCR/batch number ambiguities.')
      },
      {
        name: 'Grand Totals Reconciled',
        status: isSafe ? 'pass' : (isFailed ? 'fail' : 'warning'),
        explanation: isSafe ? 'Grand Total matches Subtotal + CGST + SGST - Discount.' : 'Warning: Unable to verify grand total balance due to missing subtotal.'
      },
      {
        name: 'Confidence Above Threshold',
        status: isFailed ? 'fail' : 'pass',
        explanation: isFailed ? 'Confidence 0.450 is below ERP safety threshold of 0.85.' : 'Confidence level matches the configured threshold rules.'
      }
    ]
  };
};

// Mock Artifact outputs for file list
const getMockArtifacts = (runId: string, filename: string): Artifact[] => {
  return [
    {
      name: `${filename}`,
      type: 'image',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/test_images/${filename}`,
      size: '1.4 MB',
      created_at: getTimestamp(1)
    },
    {
      name: 'ocr_blocks_raw.json',
      type: 'json',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/ocr_blocks_raw.json`,
      size: '124 KB',
      created_at: getTimestamp(1)
    },
    {
      name: 'candidate_tables.json',
      type: 'json',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/candidate_tables.json`,
      size: '42 KB',
      created_at: getTimestamp(1)
    },
    {
      name: 'selected_table_grid.csv',
      type: 'csv',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/selected_table_grid.csv`,
      size: '4 KB',
      created_at: getTimestamp(1)
    },
    {
      name: 'selected_table_grid.md',
      type: 'markdown',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/selected_table_grid.md`,
      size: '6 KB',
      created_at: getTimestamp(1)
    },
    {
      name: 'semantic_mapping.json',
      type: 'json',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/semantic_mapping.json`,
      size: '18 KB',
      created_at: getTimestamp(1)
    },
    {
      name: 'row_math_audit.json',
      type: 'json',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/row_math_audit.json`,
      size: '8 KB',
      created_at: getTimestamp(1)
    },
    {
      name: 'quality_gate_checks.json',
      type: 'json',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/quality_gate_checks.json`,
      size: '11 KB',
      created_at: getTimestamp(1)
    },
    {
      name: 'full_diagnostics_bundle.zip',
      type: 'zip',
      path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/full_diagnostics_bundle.zip`,
      size: '1.6 MB',
      created_at: getTimestamp(1)
    }
  ];
};

// API Client object implementing all required methods
export const apiClient = {
  // Checks if backend service is available
  async checkHealth() {
    try {
      const response = await fetch('/health');
      if (response.ok) {
        return await response.json();
      }
    } catch {
      // Offline fallback
    }
    return { status: 'offline', gpu_available: false };
  },

  // Calls the actual /upload-invoice route in the backend
  async uploadInvoice(file: File) {
    const formData = new FormData();
    formData.append('file', file);

    try {
      // reconstruct & extract must be query params (FastAPI reads them as
      // Query(...) not Form(...)). Without these, backend skips TSR/extraction.
      const response = await fetch('/upload-invoice?reconstruct=true&extract=true', {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Upload failed');
      }

      const backendData = await response.json();
      const normalizedDetail = normalizeBackendDiagnostics(backendData);
      
      // Successfully uploaded. Add a new run to our store.
      const runs = getStoredRuns();
      const newRunId = `RUN_${Date.now()}`;
      
      const isSafe = normalizedDetail.quality_gate?.safe_for_erp ?? (normalizedDetail.metadata?.quality_gate?.safe_for_erp ?? false);
      const conf = normalizedDetail.quality_gate?.confidence ?? (normalizedDetail.invoice_confidence ?? 0.880);
      const tokCov = normalizedDetail.metadata?.token_coverage ?? 0.920;
      const repScore = normalizedDetail.metadata?.reconstruction_score ?? 0.850;
      
      const newRun: RunSummary = {
        run_id: newRunId,
        filename: file.name,
        timestamp: new Date().toISOString(),
        status: isSafe ? 'safe_for_erp' : 'needs_review',
        confidence: conf,
        token_coverage: tokCov,
        representability_score: repScore,
        // Use backend-ranked main table instead of structured_tables[0]
        selected_table_id: (() => {
          const mainTbl = selectMainTable(normalizedDetail);
          return mainTbl?.table_id || 'ITEMS_001';
        })(),
        selected_table_shape: (() => {
          const mainTbl = selectMainTable(normalizedDetail);
          if (!mainTbl) return '0 Rows x 0 Columns';
          const rows = mainTbl.rows ?? (Array.isArray(mainTbl.cells) ? new Set(mainTbl.cells.map((c: any) => c.row_index ?? c.row_id ?? 0)).size : 0);
          const cols = mainTbl.cols ?? mainTbl.columns ?? (Array.isArray(mainTbl.cells) ? new Set(mainTbl.cells.map((c: any) => c.col_index ?? c.col_id ?? 0)).size : 0);
          return `${rows} Rows x ${cols} Columns`;
        })(),
        missing_fields: normalizedDetail.quality_gate?.missing_fields || (normalizedDetail.metadata?.quality_gate?.missing_fields || []),
        row_math_status: normalizedDetail.quality_gate?.row_math_status || (normalizedDetail.metadata?.quality_gate?.row_math_status || 'pass'),
        is_demo: false
      };

      // Cache the uploaded image file locally
      await cacheImageLocal(newRunId, file);
      const processedImageDataUrl = normalizedDetail.metadata?.processed_image?.processed_image_data_url;
      cacheProcessedImageLocal(newRunId, processedImageDataUrl);
      if (normalizedDetail.metadata?.processed_image) {
        delete normalizedDetail.metadata.processed_image.processed_image_data_url;
      }
      if (normalizedDetail.processed_image) {
        delete normalizedDetail.processed_image.processed_image_data_url;
      }

      // Store the normalized diagnostics details
      localStorage.setItem(`ocr_workbench_run_detail_${newRunId}`, JSON.stringify(normalizedDetail));

      // Also store raw backend response for debugging
      localStorage.setItem(
        `ocr_workbench_raw_backend_${newRunId}`,
        JSON.stringify(sanitizeForLocalStorage(backendData))
      );

      runs.unshift(newRun);
      saveStoredRuns(runs);

      return newRun;
    } catch (error) {
      console.warn('Backend call failed, simulating client upload:', error);
      
      if (!ENABLE_MOCK_DATA) {
        return null;
      }
      
      // Mock success upload if backend is offline and ENABLE_MOCK_DATA=true
      const runs = getStoredRuns();
      const newRunId = `RUN_${Date.now()}`;
      
      const newRun: RunSummary = {
        run_id: newRunId,
        filename: file.name,
        timestamp: new Date().toISOString(),
        status: 'needs_review',
        confidence: 0.880,
        token_coverage: 0.940,
        representability_score: 0.850,
        selected_table_id: 'ITEMS_001',
        selected_table_shape: '4 Rows x 8 Columns',
        missing_fields: ['subtotal'],
        row_math_status: 'unmeasurable',
        is_demo: true
      };

      // Cache the uploaded image file locally in mock fallback too
      await cacheImageLocal(newRunId, file);

      runs.unshift(newRun);
      saveStoredRuns(runs);
      
      return newRun;
    }
  },

  // Simulates OCR processing execution
  async runOCR(runId: string) {
    const runs = getStoredRuns();
    const run = runs.find(r => r.run_id === runId);
    if (!run) {
      throw new Error('Run not found');
    }
    if (!run.is_demo) {
      throw new Error('Not implemented for backend yet');
    }

    await new Promise((resolve) => setTimeout(resolve, 1500));
    run.confidence = Math.min(1.0, parseFloat((run.confidence + 0.02).toFixed(3)));
    run.token_coverage = Math.min(1.0, parseFloat((run.token_coverage + 0.01).toFixed(3)));
    saveStoredRuns(runs);
    return { success: true };
  },

  // Simulates Re-run reconstruction pipeline
  async rerunReconstruction(runId: string) {
    const runs = getStoredRuns();
    const run = runs.find(r => r.run_id === runId);
    if (!run) {
      throw new Error('Run not found');
    }
    if (!run.is_demo) {
      throw new Error('Not implemented for backend yet');
    }

    await new Promise((resolve) => setTimeout(resolve, 1200));
    run.representability_score = Math.min(1.0, parseFloat((run.representability_score + 0.03).toFixed(3)));
    saveStoredRuns(runs);
    return { success: true };
  },

  // Gets the full list of run records
  async getRuns() {
    return getStoredRuns();
  },

  // Gets a single run record by its unique ID
  async getRun(runId: string) {
    const runs = getStoredRuns();
    const run = runs.find(r => r.run_id === runId);
    if (!run) {
      clearWorkbenchRunStorage();
      throw new Error('Run not found');
    }
    return run;
  },

  // Gets the OCR blocks for an image page
  async getOCRBlocks(runId: string): Promise<OCRBlock[]> {
    const detail = getDetailsData(runId);
    if (detail && detail.blocks) {
      return detail.blocks.map((block: any) => {
        const bbox = normalizeBBox(block);
        const normBbox = block.normalized_bbox ? normalizeBBox({ bbox: block.normalized_bbox }) : null;
        return {
          ...block,
          bbox,
          normalized_bbox: normBbox || bbox,
          status: bbox ? (block.status || 'mapped') : 'missing_geometry'
        };
      });
    }
    const run = getStoredRuns().find(r => r.run_id === runId);
    if (run?.is_demo && ENABLE_MOCK_DATA) {
      return getMockOCRBlocks(runId);
    }
    return [];
  },

  // Gets Candidate TSR Tables
  async getCandidateTables(runId: string): Promise<CandidateTable[]> {
    const detail = getDetailsData(runId);
    if (detail) {
      const run = getStoredRuns().find(r => r.run_id === runId);
      if (run?.is_demo && ENABLE_MOCK_DATA) {
        return getMockCandidateTables(runId);
      }

      const candidates: CandidateTable[] = [];
      const decision = 
        detail.tsr_candidate_decision || 
        detail.metrics?.tsr_candidate_decision || 
        detail.candidate_tables || 
        detail.table_candidates || 
        detail.routing_diagnostics || 
        (detail.routing_diagnostics?.candidates ? { candidates: detail.routing_diagnostics.candidates, selected: detail.routing_diagnostics.selected } : null);

      if (decision) {
        if (decision.candidates && typeof decision.candidates === 'object') {
          for (const [key, cand] of Object.entries(decision.candidates)) {
            const c = cand as any;
            if (!c.available && key !== 'ppstructure') continue;
            candidates.push({
              table_id: key,
              source_engine: c.source || key,
              rows: c.rows || 0,
              cols: c.columns || 0,
              x_coverage: c.x_coverage || 0,
              y_coverage: c.y_coverage || 0,
              cell_count: c.cells || 0,
              non_empty_cells: c.non_empty_cells || c.cells || 0,
              score: c.score || c.confidence || 0,
              labels: c.labels || [key],
              selected: decision.selected === key,
              rejection_reason: c.blocked_by?.join(', ') || null,
              representability_score: c.score || c.confidence || 0,
              preview_cells: c.preview_cells || [],
              bbox: normalizeBBox(c)
            });
          }
        } else if (Array.isArray(decision)) {
          decision.forEach((c: any, index: number) => {
            candidates.push({
              table_id: c.table_id || `cand_${index}`,
              source_engine: c.source_engine || c.source || 'backend_candidate',
              rows: c.rows || 0,
              cols: c.columns || c.cols || 0,
              x_coverage: c.x_coverage || 0,
              y_coverage: c.y_coverage || 0,
              cell_count: c.cell_count || c.cells || 0,
              non_empty_cells: c.non_empty_cells || c.cells || 0,
              score: c.score || c.confidence || 0.90,
              labels: c.labels || [c.table_id || `cand_${index}`],
              selected: c.selected ?? (index === 0),
              rejection_reason: c.rejection_reason || c.blocked_by?.join(', ') || null,
              representability_score: c.score || c.confidence || 0.90,
              preview_cells: c.preview_cells || [],
              bbox: normalizeBBox(c)
            });
          });
        } else if (decision.table_regions && Array.isArray(decision.table_regions)) {
          decision.table_regions.forEach((c: any, index: number) => {
            candidates.push({
              table_id: c.table_id || `region_${index}`,
              source_engine: c.source_engine || c.source || 'routing_table_region',
              rows: c.rows || 0,
              cols: c.columns || c.cols || 0,
              x_coverage: c.x_coverage || 0,
              y_coverage: c.y_coverage || 0,
              cell_count: c.cell_count || c.cells || 0,
              non_empty_cells: c.non_empty_cells || c.cells || 0,
              score: c.score || c.confidence || 0.90,
              labels: c.labels || [c.table_id || `region_${index}`],
              selected: c.selected ?? (index === 0),
              rejection_reason: c.rejection_reason || null,
              representability_score: c.score || c.confidence || 0.90,
              preview_cells: c.preview_cells || [],
              bbox: normalizeBBox(c)
            });
          });
        }
      }

      if (candidates.length === 0) {
        const structured_tables = 
          detail.structured_tables || 
          detail.selected_table || 
          detail.main_table || 
          detail.tables || 
          detail.reconstructed_tables;
        
        if (Array.isArray(structured_tables)) {
          // Use selectMainTable to determine which table_id is the selected one
          const mainTable = selectMainTable(detail);
          const mainTableId = mainTable?.table_id;
          structured_tables.forEach((table: any, index: number) => {
            const tableId = table.table_id || `table_${index + 1}`;
            candidates.push({
              table_id: tableId,
              source_engine: table.source_engine || 'backend_structured_table',
              rows: table.rows || 0,
              cols: table.cols || table.columns || 0,
              x_coverage: table.x_coverage || 100,
              y_coverage: table.y_coverage || 100,
              cell_count: table.cell_count || table.cells?.length || 0,
              non_empty_cells: table.non_empty_cells || table.cells?.length || 0,
              score: table.score || table.confidence || 1.0,
              labels: [tableId],
              selected: mainTableId ? (tableId === mainTableId) : (index === 0),
              rejection_reason: undefined,
              representability_score: table.representability_score || 1.0,
              preview_cells: (table.cells || []).slice(0, 10).map((cell: any) => ({
                row_id: cell.row_index ?? cell.row_id ?? 0,
                col_id: cell.col_index ?? cell.col_id ?? 0,
                text: cell.text || ''
              })),
              bbox: normalizeBBox(table)
            });
          });
        } else if (structured_tables && typeof structured_tables === 'object') {
          const table = structured_tables;
          candidates.push({
            table_id: table.table_id || 'table_1',
            source_engine: table.source_engine || 'backend_structured_table',
            rows: table.rows || 0,
            cols: table.cols || table.columns || 0,
            x_coverage: table.x_coverage || 100,
            y_coverage: table.y_coverage || 100,
            cell_count: table.cell_count || table.cells?.length || 0,
            non_empty_cells: table.non_empty_cells || table.cells?.length || 0,
            score: table.score || table.confidence || 1.0,
            labels: [table.table_id || 'table_1'],
            selected: true,
            rejection_reason: undefined,
            representability_score: table.representability_score || 1.0,
            preview_cells: (table.cells || []).slice(0, 10).map((cell: any) => ({
              row_id: cell.row_index ?? cell.row_id ?? 0,
              col_id: cell.col_index ?? cell.col_id ?? 0,
              text: cell.text || ''
            })),
            bbox: normalizeBBox(table)
          });
        }
      }

      return candidates;
    }
    if (ENABLE_MOCK_DATA) {
      return getMockCandidateTables(runId);
    }
    return [];
  },

  // Gets the final selected table structure
  async getSelectedTable(runId: string): Promise<SelectedTable | null> {
    const detail = getDetailsData(runId);
    if (detail) {
      const run = getStoredRuns().find(r => r.run_id === runId);
      if (run?.is_demo && ENABLE_MOCK_DATA) {
        return getMockSelectedTable(runId);
      }

      // Use backend-ranked main table selection instead of structured_tables[0]
      const table = selectMainTable(detail);

      if (table) {
        // Use dense grid builder to handle string IDs like "row_14", "col_0"
        const cells = buildDenseTableGrid(table.cells || []);

        return {
          table_id: table.table_id || 'ITEMS_001',
          rows: cells.length,
          cols: cells[0]?.length || 0,
          x_coverage: table.x_coverage || 100.0,
          non_empty_cells: table.non_empty_cells || table.cells?.length || 0,
          representability_score: table.representability_score || detail.reconstruction_score || 1.0,
          required_fields_present: table.required_fields_present || [],
          required_fields_missing: table.required_fields_missing || detail.quality_gate?.missing_fields || [],
          cells,
          bbox: normalizeBBox(table)
        };
      }
    }

    if (ENABLE_MOCK_DATA) {
      return getMockSelectedTable(runId);
    }
    return null;
  },

  // Gets the Column semantic mapper
  async getSemanticMapping(runId: string): Promise<SemanticColumn[]> {
    const detail = getDetailsData(runId);
    if (detail) {
      const run = getStoredRuns().find(r => r.run_id === runId);
      if (run?.is_demo && ENABLE_MOCK_DATA) {
        return getMockSemanticMapping(runId);
      }

      const rawSemantics = 
        detail.semantic_columns || 
        detail.table_semantics || 
        detail.column_semantics || 
        selectMainTable(detail)?.metadata?.column_semantics;

      if (rawSemantics) {
        if (Array.isArray(rawSemantics)) {
          return rawSemantics.map((col: any, index: number) => ({
            col_id: col.col_id ?? index,
            predicted_type: col.predicted_type || col.semantic_label || col.label || 'unknown',
            confidence: col.confidence ?? 1.0,
            header_text: col.header_text || col.text || '',
            sample_values: col.sample_values || [],
            competing_candidates: col.competing_candidates || [
              { type: col.predicted_type || col.semantic_label || col.label || 'unknown', confidence: col.confidence ?? 1.0 }
            ],
            conflict_resolution_reason: col.conflict_resolution_reason || 'Backend semantic column classification'
          }));
        } else if (typeof rawSemantics === 'object') {
          return Object.entries(rawSemantics).map(([key, val]: [string, any]) => {
            const colId = parseInt(key, 10) || 0;
            const type = typeof val === 'string' ? val : (val.label || val.type || 'unknown');
            const conf = typeof val === 'object' ? (val.confidence ?? val.score ?? 1.0) : 1.0;
            return {
              col_id: colId,
              predicted_type: type,
              confidence: conf,
              header_text: val.header_text || val.text || `Col ${colId}`,
              sample_values: val.sample_values || [],
              competing_candidates: val.competing_candidates || [{ type, confidence: conf }],
              conflict_resolution_reason: val.conflict_resolution_reason || 'Mapped from backend semantic map'
            };
          });
        }
      }

      // Use backend-ranked main table selection instead of structured_tables[0]
      const table = selectMainTable(detail);

      if (table && table.cells && Array.isArray(table.cells)) {
        // Build dense grid to handle string IDs like "row_14", "col_0"
        const denseGrid = buildDenseTableGrid(table.cells);
        if (denseGrid.length > 0 && denseGrid[0].length > 0) {
          return denseGrid[0].map((hdrCell, colIdx) => {
            const predictedType = hdrCell.semantic_label || 'unknown';
            return {
              col_id: colIdx,
              predicted_type: predictedType,
              confidence: hdrCell.confidence ?? 1.0,
              header_text: hdrCell.text || '',
              sample_values: [] as string[],
              competing_candidates: [
                { type: predictedType, confidence: hdrCell.confidence ?? 1.0 }
              ],
              conflict_resolution_reason: 'Inferred from cell headers classification'
            };
          });
        }
        return [];
      }
    }

    if (ENABLE_MOCK_DATA) {
      return getMockSemanticMapping(runId);
    }
    return [];
  },

  // Gets the Row Mathematical Reconciliation checks
  async getRowMath(runId: string): Promise<RowMathResult[]> {
    const detail = getDetailsData(runId);
    if (detail) {
      const run = getStoredRuns().find(r => r.run_id === runId);
      if (run?.is_demo && ENABLE_MOCK_DATA) {
        return getMockRowMath(runId);
      }

      const mathData = 
        detail.financial_reconciliation || 
        detail.metrics?.financial_reconciliation || 
        detail.row_math || 
        detail.row_math_repair || 
        detail.canonical_invoice?.row_math;

      if (mathData) {
        const rows = mathData.rows || (Array.isArray(mathData) ? mathData : []);
        return rows.map((r: any, idx: number) => ({
          row_id: r.row_id ?? idx,
          product: r.product_name || r.product || 'Unknown',
          qty: r.qty || r.quantity || 0,
          rate: r.rate || r.unit_price || r.rate_unit || 0,
          discount: r.discount || 0,
          gst: r.gst || r.gst_rate || 0,
          expected_amount: r.expected_amount || r.calculated_amount || 0,
          actual_amount: r.actual_amount || r.amount || 0,
          difference: r.difference || r.diff || 0,
          status: r.status || (Math.abs(r.difference || 0) < 0.01 ? 'pass' : 'fail'),
          formula_used: r.formula_used || r.formula || ''
        }));
      }
    }

    if (ENABLE_MOCK_DATA) {
      return getMockRowMath(runId);
    }
    return [];
  },

  // Gets Quality Gate ERP checklist validation
  async getQualityGate(runId: string): Promise<QualityGate | null> {
    const detail = getDetailsData(runId);
    const run = getStoredRuns().find(r => r.run_id === runId);

    if (detail) {
      if (run?.is_demo && ENABLE_MOCK_DATA) {
        return getMockQualityGate(runId);
      }

      const qg = 
        detail.quality_gate || 
        detail.metadata?.quality_gate || 
        detail.canonical_invoice?.quality_gate || 
        detail.metadata?.canonical_invoice?.quality_gate;

      if (qg) {
        return {
          safe_for_erp: qg.safe_for_erp ?? false,
          status_effective: (qg.safe_for_erp ? 'safe_for_erp' : (qg.status_effective || 'needs_review')) as 'safe_for_erp' | 'needs_review' | 'failed',
          confidence: qg.confidence ?? detail.invoice_confidence ?? run?.confidence ?? 1.0,
          reasons: qg.reasons || [],
          missing_fields: qg.missing_fields || [],
          footer_status: qg.footer_status || '',
          row_math_status: qg.row_math_status || 'unmeasurable',
          checklist: qg.checklist || []
        };
      }

      if (run) {
        return {
          safe_for_erp: run.status === 'safe_for_erp',
          status_effective: (run.status === 'safe_for_erp' ? 'safe_for_erp' : 'needs_review') as 'safe_for_erp' | 'needs_review' | 'failed',
          confidence: run.confidence,
          reasons: run.status !== 'safe_for_erp' ? ['Manual verification required. No backend quality gate parsed.'] : [],
          missing_fields: run.missing_fields || [],
          footer_status: 'Built from local run summary',
          row_math_status: run.row_math_status || 'unmeasurable',
          checklist: [
            { name: 'OCR Extraction Quality Check', status: run.confidence > 0.8 ? 'pass' : 'fail', explanation: `Confidence is ${(run.confidence * 100).toFixed(0)}%` },
            { name: 'Row Math Consistency Check', status: run.row_math_status === 'pass' ? 'pass' : 'fail', explanation: `Status is ${run.row_math_status.toUpperCase()}` }
          ]
        };
      }
    }

    if (ENABLE_MOCK_DATA) {
      return getMockQualityGate(runId);
    }
    return null;
  },

  // Gets the full directory listing of artifacts
  async getArtifacts(runId: string): Promise<Artifact[]> {
    const detail = getDetailsData(runId);
    if (detail) {
      const run = await this.getRun(runId);
      const processedImage = detail.metadata?.processed_image || detail.processed_image;
      const artifacts: Artifact[] = [
        {
          name: `${run.filename}`,
          type: 'image',
          path: `/Users/pranavgupta/PharmaGPTxGC-OCR/test_images/${run.filename}`,
          size: '1.4 MB',
          created_at: run.timestamp
        },
        {
          name: 'ocr_blocks_raw.json',
          type: 'json',
          path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/ocr_blocks_raw.json`,
          size: '124 KB',
          created_at: run.timestamp
        },
        {
          name: 'candidate_tables.json',
          type: 'json',
          path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/candidate_tables.json`,
          size: '42 KB',
          created_at: run.timestamp
        },
        {
          name: 'selected_table_grid.csv',
          type: 'csv',
          path: `/Users/pranavgupta/PharmaGPTxGC-OCR/local_runs/diagnostics_${runId}/selected_table_grid.csv`,
          size: '4 KB',
          created_at: run.timestamp
        }
      ];
      if (processedImage?.processed_image_path) {
        artifacts.splice(1, 0, {
          name: 'ocr_corrected_image.png',
          type: 'image',
          path: processedImage.processed_image_path,
          size: 'Generated',
          created_at: run.timestamp
        });
      }
      return artifacts;
    }
    const run = getStoredRuns().find(r => r.run_id === runId);
    if (run?.is_demo && ENABLE_MOCK_DATA) {
      const r = await this.getRun(runId);
      return getMockArtifacts(runId, r.filename);
    }
    return [];
  },

  // Expose the storage clearing helper
  clearWorkbenchRunStorage() {
    clearWorkbenchRunStorage();
  },

  // Calls backend to clear OCR results/scans cache
  async clearBackendCache(): Promise<{ status: string; deleted_count: number }> {
    try {
      const response = await fetch('/clear-cache', {
        method: 'POST'
      });
      if (response.ok) {
        return await response.json();
      }
      throw new Error('Failed to clear backend cache');
    } catch (error) {
      console.error('Error calling /clear-cache:', error);
      return { status: 'failed', deleted_count: 0 };
    }
  },

  // Downloads specific output artifact
  async downloadArtifact(runId: string, artifactName: string) {
    console.log(`Downloading ${artifactName} for run ${runId}`);
    
    let content = '';
    let mimeType = 'text/plain';
    
    if (artifactName.endsWith('.csv')) {
      content = 'Row,Product,Batch,Expiry,Qty,Rate,Disc,Amount\n1,AmoxicillinCap,BN-99212,12/2028,12,42.00,8%,504.00';
      mimeType = 'text/csv';
    } else if (artifactName.endsWith('.json')) {
      const data = { run_id: runId, timestamp: new Date().toISOString() };
      content = JSON.stringify(data, null, 2);
      mimeType = 'application/json';
    } else {
      content = `Debug trace output for ${artifactName}`;
    }
    
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = artifactName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  // Downloads the full diagnostics zip bundle
  async downloadArtifactBundle(runId: string) {
    const run = await this.getRun(runId);
    const bundleName = `${run.filename.split('.')[0]}_diagnostics_${runId}.zip`;
    console.log(`Downloading bundle: ${bundleName}`);
    
    const blob = new Blob([`Zip bundle content placeholder for ${runId}`], { type: 'application/zip' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = bundleName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  // Generates debug summary logs text and copies to user clipboard
  async copyDebugSummary(runId: string) {
    const run = await this.getRun(runId);
    const qg = await this.getQualityGate(runId);
    if (!qg) return '';
    
    const summary = `=== OCR WORKBENCH DEBUG SUMMARY ===
Run ID: ${run.run_id}
Filename: ${run.filename}
Timestamp: ${run.timestamp}
ERP Safety Check: ${qg.safe_for_erp ? 'SAFE FOR ERP' : 'NEEDS MANUAL REVIEW'}
Mean Confidence: ${(run.confidence * 100).toFixed(1)}%
Token Coverage: ${(run.token_coverage * 100).toFixed(1)}%
TSR Score: ${(run.representability_score * 100).toFixed(1)}%
Selected Table shape: ${run.selected_table_shape}
Missing fields: ${qg.missing_fields.join(', ') || 'None'}
Row Math Validation: ${qg.row_math_status.toUpperCase()}
Quality Failure Reasons:
${qg.reasons.map((r: string) => `  - ${r}`).join('\n')}
====================================`;
    
    await navigator.clipboard.writeText(summary);
    return summary;
  }
};
