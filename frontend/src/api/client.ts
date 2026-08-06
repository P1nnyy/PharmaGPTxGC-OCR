import type { RunSummary, OCRBlock, SelectedTable, CandidateTable, SemanticColumn, QualityGate, RowMathResult, Artifact, Product, ProductListResponse, EnrichmentResult, ItemType, ItemTypesResponse } from './types';
import {
  clearWorkbenchRunStorage,
  getDetailsData,
  getInvoiceImageUrl,
  getProcessedInvoiceImageUrl
} from './storage';
import { normalizeBackendDiagnostics } from './normalizer';
import { isSelectedTableUnavailable, selectMainTable, noValidTableReason } from './table_selection';
import {
  getRun as getLegacyRun,
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
  getLegacyRun,
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

// Maps a backend Invoice record (from GET/PATCH /invoices) into the RunSummary
// shape the list-view pages (Dashboard, Invoice History) already render.
function mapInvoiceToRunSummary(inv: any): RunSummary {
  return {
    run_id: inv.id,
    filename: inv.invoice_number || inv.id,
    timestamp: inv.created_at || new Date().toISOString(),
    status: inv.status === 'verified' ? 'verified' : 'needs_review',
    confidence: inv.confidence ?? 0,
    token_coverage: 1.0,
    representability_score: 1.0,
    selected_table_id: 'AZURE_TABLE',
    selected_table_shape: '—',
    missing_fields: [],
    row_math_status: 'pass',
    is_demo: false,
    backend_invoice_id: inv.id,
    extraction_engine: inv.extraction_engine,
    seller_name: inv.seller_name ?? null,
    grand_total: inv.grand_total ?? null,
    invoice_number: inv.invoice_number ?? null,
    invoice_date: inv.invoice_date ?? null,
    image_url: inv.image_url ?? null
  };
}

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

    const response = await fetch('/upload-invoice?reconstruct=true&extract=true', {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || 'Upload failed');
    }

    const backendData = await response.json();

    if (!backendData.persisted || !backendData.graph_invoice_id) {
      throw new Error(
        backendData.persist_error ||
        'Invoice was extracted but could not be saved. Check server storage configuration.'
      );
    }

    // Build the result directly from this response instead of re-fetching —
    // Neo4j Aura can have a brief replication lag right after a write, where an
    // immediate GET for the same id 404s even though the save succeeded. The
    // upload response already carries everything the caller needs (it's only
    // used for run_id/navigation; the review page does its own fresh fetch).
    return mapInvoiceToRunSummary({ ...backendData, id: backendData.graph_invoice_id });
  },

  /**
   * Uploads several images as the pages of ONE invoice, in the given order.
   *
   * confirmedSingleOrder reflects the user having confirmed in the dialog that
   * these pages belong to a single order. The backend independently checks the
   * extracted pages against each other and answers 409 if they disagree, so a
   * mistaken confirmation surfaces as a conflict rather than a merged invoice.
   * Retrying with force=true accepts them anyway.
   */
  async uploadInvoicePages(
    files: File[],
    options: { force?: boolean } = {}
  ): Promise<RunSummary> {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    const params = new URLSearchParams({ confirmed_single_order: 'true' });
    if (options.force) params.set('force', 'true');

    const response = await fetch(`/upload-invoice-multipage?${params.toString()}`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      // A 409 carries the structured page-mismatch report; keep it attached so
      // the caller can show which pages disagreed rather than a bare message.
      const detail = err.detail;
      if (response.status === 409 && detail && typeof detail === 'object') {
        const conflictError: any = new Error(detail.message || 'These pages do not belong to the same invoice.');
        conflictError.isPageMismatch = true;
        conflictError.consistency = detail.consistency;
        conflictError.pages = detail.pages;
        throw conflictError;
      }
      throw new Error(
        typeof detail === 'string' ? detail : detail?.message || 'Multi-page upload failed'
      );
    }

    const backendData = await response.json();

    if (!backendData.persisted || !backendData.graph_invoice_id) {
      throw new Error(
        backendData.persist_error ||
        'Invoice was extracted but could not be saved. Check server storage configuration.'
      );
    }

    return mapInvoiceToRunSummary({ ...backendData, id: backendData.graph_invoice_id });
  },

  async runOCR(fileOrRunId: File | string): Promise<RunSummary> {
    if (typeof fileOrRunId === 'string') {
      const existing = await this.getRun(fileOrRunId);
      if (existing) return existing;
      throw new Error(`Run ${fileOrRunId} not found.`);
    }
    return this.uploadInvoice(fileOrRunId);
  },

  async rerunReconstruction(runId: string): Promise<void> {
    console.log('Re-running layout reconstruction for run:', runId);
  },

  async getRuns(): Promise<RunSummary[]> {
    const response = await fetch('/invoices');
    if (!response.ok) return [];
    const data = await response.json();
    return data.map(mapInvoiceToRunSummary);
  },

  async getRun(runId: string): Promise<RunSummary | null> {
    try {
      return await this.getInvoiceDetail(runId);
    } catch {
      return null;
    }
  },

  // Full invoice detail (header + line_items + seller + presigned image_url),
  // mapped into RunSummary shape. Used by the review page and by getRun().
  //
  // Retries a couple of times on 404: Neo4j Aura can have a brief replication
  // lag right after a write (e.g. just-navigated-here from an upload), where a
  // read for the same id 404s for a few hundred ms even though the write
  // already succeeded. A genuinely missing/deleted invoice still 404s for good
  // after these few short retries.
  async getInvoiceDetail(invoiceId: string, attempt = 0): Promise<RunSummary> {
    const response = await fetch(`/invoices/${invoiceId}`);
    if (!response.ok) {
      if (response.status === 404 && attempt < 3) {
        await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
        return this.getInvoiceDetail(invoiceId, attempt + 1);
      }
      throw new Error(`Invoice ${invoiceId} not found.`);
    }
    const data = await response.json();
    return { ...mapInvoiceToRunSummary(data), ...data, run_id: data.id };
  },

  async updateInvoice(invoiceId: string, payload: Record<string, any>): Promise<any> {
    const response = await fetch(`/invoices/${invoiceId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update invoice.');
    }
    return response.json();
  },

  async deleteInvoice(invoiceId: string): Promise<void> {
    const response = await fetch(`/invoices/${invoiceId}`, { method: 'DELETE' });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to delete invoice.');
    }
  },

  // --- Catalogue ----------------------------------------------------------

  async getProducts(params?: { status?: string; search?: string }): Promise<ProductListResponse> {
    const query = new URLSearchParams();
    if (params?.status && params.status !== 'all') query.set('status', params.status);
    if (params?.search) query.set('search', params.search);
    const suffix = query.toString() ? `?${query}` : '';

    const response = await fetch(`/products${suffix}`);
    if (!response.ok) {
      throw new Error('Failed to load products.');
    }
    return response.json();
  },

  async getProduct(productId: string): Promise<Product> {
    const response = await fetch(`/products/${productId}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to load product.');
    }
    return response.json();
  },

  // Resolves to either the saved product or a duplicate the edit revealed.
  // The conflict is returned rather than thrown because it is a decision for
  // the user, not a failure: two records turned out to describe one item, and
  // combining them is their call to make.
  async updateProduct(
    productId: string,
    payload: Record<string, any>
  ): Promise<{ status: 'ok' | 'conflict'; product: Product; conflict?: Product }> {
    const response = await fetch(`/products/${productId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to save product.');
    }
    return response.json();
  },

  // ---- Item types: the catalogue's vocabulary ----------------------------
  // What a product can be, and the units it may be measured in. Read from the
  // server rather than hardcoded in the UI, so a pharmacy stocking something
  // the original list never anticipated can say so without a code change.

  async listItemTypes(includeInactive = false): Promise<ItemTypesResponse> {
    const response = await fetch(`/item-types?include_inactive=${includeInactive}`);
    if (!response.ok) throw new Error('Failed to load item types.');
    return response.json();
  },

  async createItemType(payload: Record<string, any>): Promise<ItemType> {
    const response = await fetch('/item-types', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create item type.');
    }
    return response.json();
  },

  async updateItemType(typeId: string, payload: Record<string, any>): Promise<ItemType> {
    const response = await fetch(`/item-types/${typeId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to save item type.');
    }
    return response.json();
  },

  async deleteItemType(typeId: string): Promise<void> {
    const response = await fetch(`/item-types/${typeId}`, { method: 'DELETE' });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      // The server explains why (built-in, or still in use) — surface that
      // rather than a generic failure, since the reason names the way out.
      throw new Error(err.detail || 'Failed to delete item type.');
    }
  },

  // Looks the product up against public drug listings. Read-only: it returns
  // what a listing claims, and applying any of it still goes through
  // updateProduct with the user choosing. Slower than other calls because it
  // fetches the matched listing pages.
  async enrichProduct(productId: string, fetchTop = 2): Promise<EnrichmentResult> {
    const response = await fetch(`/products/${productId}/enrich?fetch_top=${fetchTop}`, {
      method: 'POST'
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Lookup failed.');
    }
    return response.json();
  },

  async mergeProducts(sourceIds: string[], targetId: string): Promise<Product> {
    const response = await fetch('/products/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_ids: sourceIds, target_id: targetId })
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to merge products.');
    }
    return (await response.json()).product;
  },

  async splitAlias(aliasId: string, overrides: Record<string, any>): Promise<Product> {
    const response = await fetch(`/products/aliases/${aliasId}/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(overrides)
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to split product.');
    }
    return (await response.json()).product;
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
