import type { RunSummary, OCRBlock, SelectedTable, CandidateTable, SemanticColumn, QualityGate, RowMathResult, Artifact } from './types';
import {
  cacheImageLocal,
  cacheProcessedImageLocal,
  getStoredRuns,
  saveStoredRuns,
  buildTrimmedRunDetail,
  sanitizeForLocalStorage,
  clearWorkbenchRunStorage,
  getDetailsData,
  getInvoiceImageUrl,
  getProcessedInvoiceImageUrl
} from './storage';
import { normalizeBackendDiagnostics, normalizeInvoiceConfidence } from './normalizer';
import { isSelectedTableUnavailable, selectMainTable, noValidTableReason, tableRows, tableCols } from './table_selection';
import {
  getRun,
  getOCRBlocks,
  getCandidateTables,
  getSelectedTable,
  getSemanticMapping,
  getQualityGate,
  getRowMath,
  getArtifacts,
  getArtifactContent,
  downloadArtifact,
  downloadArtifactBundle,
  copyDebugSummary
} from './getters';

export const ENABLE_MOCK_DATA = import.meta.env.VITE_ENABLE_MOCK_DATA === 'true';

// Export storage, selection, normalizer, and getter helpers for backward compatibility
export {
  getInvoiceImageUrl,
  getProcessedInvoiceImageUrl,
  getDetailsData,
  clearWorkbenchRunStorage,
  selectMainTable,
  isSelectedTableUnavailable,
  noValidTableReason,
  normalizeBackendDiagnostics,
  getRun,
  getOCRBlocks,
  getCandidateTables,
  getSelectedTable,
  getSemanticMapping,
  getQualityGate,
  getRowMath,
  getArtifacts,
  getArtifactContent,
  downloadArtifact,
  downloadArtifactBundle,
  copyDebugSummary
};

export const apiClient = {
  async checkHealth(): Promise<{ status: string; gpu_available?: boolean; gpu_name?: string; cuda_version?: string }> {
    try {
      const response = await fetch('/health');
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn('Backend health check failed:', e);
    }
    return { status: 'offline', gpu_available: false };
  },

  async uploadInvoice(file: File): Promise<RunSummary> {
    const formData = new FormData();
    formData.append('file', file);

    let backendData: any;
    const response = await fetch('/upload-invoice?reconstruct=true&extract=true', {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || 'Upload failed');
    }

    backendData = await response.json();

    const normalizedDetail = normalizeBackendDiagnostics(backendData);
    const backendInvoiceId = backendData?.invoice_id || normalizedDetail?.invoice_id;
    const diagnostics =
      normalizedDetail.metadata?.diagnostics ||
      normalizedDetail.diagnostics ||
      {};
    const diagnosticsRunId =
      normalizedDetail.metadata?.diagnostics_run_id ||
      diagnostics.diagnostics_run_id ||
      diagnostics.run_id ||
      backendInvoiceId;

    normalizedDetail.backend_invoice_id = backendInvoiceId;
    normalizedDetail.diagnostics_run_id = diagnosticsRunId;

    const runs = getStoredRuns();
    const newRunId = `RUN_${Date.now()}`;
    
    const isAzure = normalizedDetail?.extraction_engine === 'azure_document_intelligence';
    const tableUnavailable = isAzure ? false : isSelectedTableUnavailable(normalizedDetail);
    const conf = normalizeInvoiceConfidence(normalizedDetail);
    const isSafe = isAzure ? (conf >= 0.85) : (!tableUnavailable && normalizedDetail.quality_gate?.safe_for_erp);
    
    const newRun: RunSummary = {
      run_id: newRunId,
      filename: file.name,
      timestamp: new Date().toISOString(),
      status: isSafe ? 'safe_for_erp' : 'needs_review',
      confidence: conf,
      token_coverage: isAzure ? 1.0 : (normalizedDetail.metadata?.token_coverage ?? 0.920),
      representability_score: isAzure ? 1.0 : (normalizedDetail.metadata?.reconstruction_score ?? 0.850),
      selected_table_id: isAzure ? 'AZURE_TABLE' : (selectMainTable(normalizedDetail)?.table_id || '—'),
      selected_table_shape: isAzure
        ? `${normalizedDetail.line_items?.length || 0} Items`
        : `${tableRows(selectMainTable(normalizedDetail))} Rows x ${tableCols(selectMainTable(normalizedDetail))} Columns`,
      missing_fields: normalizedDetail.quality_gate?.missing_fields || [],
      row_math_status: normalizedDetail.quality_gate?.row_math_status || 'pass',
      is_demo: false,
      backend_invoice_id: backendInvoiceId,
      diagnostics_run_id: diagnosticsRunId,
      selected_table_available: !tableUnavailable,
      extraction_engine: normalizedDetail?.extraction_engine
    };

    await cacheImageLocal(newRunId, file);
    cacheProcessedImageLocal(newRunId, normalizedDetail.metadata?.processed_image?.processed_image_data_url);

    try {
      localStorage.setItem(`ocr_workbench_run_detail_${newRunId}`, JSON.stringify(normalizedDetail));
    } catch (error) {
      const warning = `Run completed, but payload was trimmed: ${error instanceof Error ? error.message : String(error)}`;
      const trimmed = buildTrimmedRunDetail(normalizedDetail, warning);
      localStorage.setItem(`ocr_workbench_run_detail_${newRunId}`, JSON.stringify(trimmed));
    }

    try {
      localStorage.setItem(`ocr_workbench_raw_backend_${newRunId}`, JSON.stringify(sanitizeForLocalStorage(backendData)));
    } catch {}

    runs.unshift(newRun);
    saveStoredRuns(runs);

    return newRun;
  },

  async runOCR(fileOrRunId: File | string): Promise<RunSummary> {
    if (typeof fileOrRunId === 'string') {
      const existing = this.getRun(fileOrRunId);
      if (existing) return existing;
      throw new Error(`Run ${fileOrRunId} not found.`);
    }
    return this.uploadInvoice(fileOrRunId);
  },

  async rerunReconstruction(runId: string): Promise<void> {
    console.log('Re-running layout reconstruction for run:', runId);
  },

  async getRuns(): Promise<RunSummary[]> {
    return getStoredRuns();
  },

  getRun(runId: string): RunSummary | null {
    return getRun(runId);
  },

  getOCRBlocks(runId: string): OCRBlock[] {
    return getOCRBlocks(runId);
  },

  getCandidateTables(runId: string): CandidateTable[] {
    return getCandidateTables(runId);
  },

  getSelectedTable(runId: string): SelectedTable | null {
    return getSelectedTable(runId);
  },

  getSemanticMapping(runId: string): SemanticColumn[] {
    return getSemanticMapping(runId);
  },

  getQualityGate(runId: string): QualityGate | null {
    return getQualityGate(runId);
  },

  getRowMath(runId: string): RowMathResult[] {
    return getRowMath(runId);
  },

  getArtifacts(runId: string): Artifact[] {
    return getArtifacts(runId);
  },

  async getArtifactContent(runId: string, artifactName: string): Promise<string> {
    return getArtifactContent(runId, artifactName);
  },

  downloadArtifact(runId: string, artifactArg: any): void {
    downloadArtifact(runId, artifactArg);
  },

  async downloadArtifactBundle(runId: string): Promise<void> {
    return downloadArtifactBundle(runId);
  },

  copyDebugSummary(runId: string): void {
    copyDebugSummary(runId);
  },

  async clearBackendCache(): Promise<{ message: string; cleared_keys_count: number }> {
    const response = await fetch('/clear-cache', { method: 'POST' });
    if (!response.ok) {
      throw new Error('Failed to clear backend cache.');
    }
    return await response.json();
  },

  clearWorkbenchRunStorage() {
    clearWorkbenchRunStorage();
  }
};
