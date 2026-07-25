// Footer/bank/tax/metadata text patterns for penalizing non-item regions
const FOOTER_PHRASES = /\b(bank\s*detail|account|ifsc|neft|rtgs|branch|upi|terms?\s*(?:and|&)\s*condition|subject\s*to|disclaimer|e\.?\s*&?\s*o\.?\s*e|signature|authorised|stamp|for\s*m\/s|goods\s*once\s*sold|cheque|self|bearer|original\s*copy|duplicate\s*copy)\b/i;

export function isSelectedTableUnavailable(detail: any): boolean {
  if (!detail || typeof detail !== 'object') return false;
  if (detail.extraction_engine === 'azure_document_intelligence') return false;
  const metadata = detail.metadata || {};
  const metrics = detail.metrics || metadata.metrics || {};
  const candidateTables = detail.candidate_tables || metadata.candidate_tables;
  return (
    detail.selected_table_available === false ||
    metadata.selected_table_available === false ||
    metrics.selected_table_available === false ||
    detail.fast_fail_reason === 'no_valid_table_candidate' ||
    metadata.fast_fail_reason === 'no_valid_table_candidate' ||
    metrics.no_valid_table_candidate === true ||
    candidateTables?.selected_table_available === false ||
    (
      candidateTables &&
      Object.prototype.hasOwnProperty.call(candidateTables, 'selected_candidate_id') &&
      candidateTables.selected_candidate_id === null
    )
  );
}

export function noValidTableReason(detail: any): string | undefined {
  if (!isSelectedTableUnavailable(detail)) return undefined;
  const metadata = detail?.metadata || {};
  const metrics = detail?.metrics || metadata.metrics || {};
  const reason = (
    detail?.fast_fail_reason ||
    metadata.fast_fail_reason ||
    metrics.table_sanity?.selected_reason ||
    detail?.candidate_tables?.table_sanity?.selected_reason ||
    metadata.candidate_tables?.table_sanity?.selected_reason ||
    'no_valid_table_candidate'
  );
  return reason === 'no_valid_candidate' ? 'no_valid_table_candidate' : reason;
}

function countUniqueCellAxis(cells: any, axis: 'row' | 'col'): number {
  if (!Array.isArray(cells) || cells.length === 0) return 0;
  return new Set(cells.map((cell: any) => String(axis === 'row' ? (cell.row_index ?? cell.row_id ?? cell.row ?? 0) : (cell.col_index ?? cell.col_id ?? cell.col ?? 0)))).size;
}

function resolveTableDimension(value: any, cells: any, axis: 'row' | 'col'): number {
  if (Array.isArray(value)) return value.length;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const numericValue = Number(value);
    if (Number.isFinite(numericValue)) return numericValue;
  }
  if (value && typeof value === 'object') {
    return Object.keys(value).length;
  }
  return countUniqueCellAxis(cells, axis);
}

export function tableRows(table: any): number {
  return resolveTableDimension(table?.rows, table?.cells, 'row');
}

export function tableCols(table: any): number {
  const colSource = table?.columns ?? table?.cols;
  return resolveTableDimension(colSource, table?.cells, 'col');
}

/**
 * Selects the main medicine/item table from normalized detail.
 */
export function selectMainTable(detail: any): any {
  if (isSelectedTableUnavailable(detail)) {
    return null;
  }

  const tables: any[] = detail?.structured_tables;
  if (!Array.isArray(tables) || tables.length === 0) {
    return detail?.selected_table || detail?.main_table || null;
  }

  const byId: Record<string, any> = {};
  for (const t of tables) {
    if (t.table_id) byId[t.table_id] = t;
  }

  const findById = (id: string | undefined | null): any | null => {
    if (!id || id === 'unknown') return null;
    return byId[id] ?? null;
  };

  if (detail.selected_table?.table_id) {
    const match = findById(detail.selected_table.table_id);
    if (match) return match;
  }

  const metrics = detail.metrics || detail.metadata?.metrics;
  if (metrics?.selected_main_table_id) {
    const match = findById(metrics.selected_main_table_id);
    if (match) return match;
  }

  if (Array.isArray(metrics?.main_table_candidate_scores) && metrics.main_table_candidate_scores.length > 0) {
    const topId = metrics.main_table_candidate_scores[0]?.table_id;
    const match = findById(topId);
    if (match) return match;
  }

  let bestTable: any = null;
  let bestScore = -Infinity;

  for (const t of tables) {
    const rows = tableRows(t);
    const cols = tableCols(t);
    const cellCount = Array.isArray(t.cells) ? t.cells.length : 0;

    let score = 0;
    if (rows >= 2) score += 50;
    if (cols >= 4) score += 50;
    if (cellCount >= 8) score += 30;
    score += Math.min(rows * 5, 100);
    score += Math.min(cols * 3, 30);

    if (t.region_type === 'medicine_table') score += 200;

    const sampleText = (t.sample || '') + ' ' +
      (Array.isArray(t.cells) ? t.cells.map((c: any) => c.text || '').join(' ') : '');

    if (/\b(batch|lot)\b/i.test(sampleText)) score += 30;
    if (/\b(exp(?:iry)?|mfg)\b/i.test(sampleText)) score += 30;
    if (/\b(hsn|sac)\b/i.test(sampleText)) score += 20;
    if (/\d+\.\d{2}/.test(sampleText)) score += 15;
    if (/\d{2}\/\d{2,4}/.test(sampleText)) score += 10;

    if (FOOTER_PHRASES.test(sampleText)) score -= 200;
    if (t.region_type && /footer|bank|tax|metadata|header|summary/i.test(t.region_type)) score -= 150;

    if (rows <= 1) score -= 80;
    if (cols <= 1) score -= 80;

    if (score > bestScore) {
      bestScore = score;
      bestTable = t;
    }
  }

  return bestTable || tables[0];
}
