import { isSelectedTableUnavailable, selectMainTable } from './table_selection';

export function normalizeInvoiceConfidence(detail: any, fallback?: number): number {
  if (detail?.extraction_engine === 'azure_document_intelligence') {
    const value = detail?.confidence;
    const num = typeof value === 'number' ? value : Number(value);
    if (Number.isFinite(num)) return Math.max(0, Math.min(1, num));
    return fallback ?? 0.85;
  }
  if (isSelectedTableUnavailable(detail)) return 0;
  const qg = detail?.quality_gate || detail?.metadata?.quality_gate;
  const qgStatus = String(qg?.status || qg?.status_effective || '').toLowerCase();
  if (qgStatus === 'failed' && (qg?.confidence === null || qg?.confidence === undefined)) {
    return 0;
  }
  const candidates = [
    qg?.confidence,
    detail?.confidence,
    detail?.invoice_confidence,
    detail?.metadata?.invoice_confidence,
    fallback,
  ];
  for (const value of candidates) {
    const num = typeof value === 'number' ? value : Number(value);
    if (Number.isFinite(num)) return Math.max(0, Math.min(1, num));
  }
  return 0.85;
}

// Normalizes and preserves multi-path backend diagnostics formats
export function normalizeBackendDiagnostics(backendData: any): any {
  if (!backendData || typeof backendData !== 'object') {
    return {};
  }

  const res: any = { ...backendData };

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

  const candidate_tables =
    backendData.candidate_tables ||
    backendData.metadata?.candidate_tables ||
    backendData.metrics?.candidate_tables ||
    backendData.metadata?.metrics?.candidate_tables;
  if (candidate_tables) {
    res.candidate_tables = candidate_tables;
    res.metadata.candidate_tables = candidate_tables;
  }

  // Resolve Clean Item Rows
  const item_rows_clean =
    backendData.item_rows_clean ||
    backendData.metadata?.item_rows_clean;
  if (item_rows_clean) {
    res.item_rows_clean = item_rows_clean;
    res.metadata.item_rows_clean = item_rows_clean;
  }

  // Resolve Invoice Totals & Tax Summary
  const invoice_totals =
    backendData.invoice_totals ||
    backendData.metadata?.invoice_totals;
  if (invoice_totals) {
    res.invoice_totals = invoice_totals;
    res.metadata.invoice_totals = invoice_totals;
  }

  const tax_summary =
    backendData.tax_summary ||
    backendData.metadata?.tax_summary;
  if (tax_summary) {
    res.tax_summary = tax_summary;
    res.metadata.tax_summary = tax_summary;
  }

  // Resolve Line Items
  const line_items =
    backendData.line_items ||
    backendData.metadata?.line_items ||
    backendData.metadata?.llm_extraction?.items;
  if (line_items) {
    res.line_items = line_items;
    res.metadata.line_items = line_items;
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

  return res;
}
