import type { RunSummary } from './types';

// Helper to cache uploaded image as base64 in sessionStorage
export async function cacheImageLocal(runId: string, file: File): Promise<void> {
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

export function cacheProcessedImageLocal(runId: string, dataUrl?: string): void {
  if (!dataUrl || typeof dataUrl !== 'string') return;
  try {
    sessionStorage.setItem(`ocr_workbench_processed_image_${runId}`, dataUrl);
  } catch (e) {
    console.warn('Failed to cache processed image in sessionStorage:', e);
  }
}

export function sanitizeForLocalStorage(value: any): any {
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

export function buildTrimmedRunDetail(detail: any, warning: string): any {
  const metadata = detail?.metadata || {};
  const diagnostics = metadata.diagnostics || detail?.diagnostics;
  const artifacts = metadata.artifacts || diagnostics?.artifacts || detail?.artifacts || [];
  return sanitizeForLocalStorage({
    invoice_id: detail?.invoice_id,
    backend_invoice_id: detail?.backend_invoice_id || detail?.invoice_id,
    cached: detail?.cached,
    text: detail?.text ? String(detail.text).slice(0, 5000) : '',
    diagnostics_run_id: metadata.diagnostics_run_id || diagnostics?.diagnostics_run_id || diagnostics?.run_id,
    storage_warning: warning,
    metadata: {
      diagnostics_run_id: metadata.diagnostics_run_id || diagnostics?.diagnostics_run_id || diagnostics?.run_id,
      diagnostics,
      artifacts,
      processed_image: metadata.processed_image,
      quality_gate: metadata.quality_gate,
      coordinate_space_violation: metadata.coordinate_space_violation,
    },
    diagnostics,
    artifacts,
    quality_gate: detail?.quality_gate || metadata.quality_gate,
    processed_image: detail?.processed_image || metadata.processed_image,
  });
}

// Retrieves the cached image URL if present
export const getInvoiceImageUrl = (runId: string, _filename: string): string => {
  const cached = sessionStorage.getItem(`ocr_workbench_image_${runId}`);
  if (cached) {
    return cached;
  }
  return '';
};

export const getProcessedInvoiceImageUrl = (runId: string): string | null => {
  return sessionStorage.getItem(`ocr_workbench_processed_image_${runId}`);
};

export function clearWorkbenchRunStorage() {
  localStorage.removeItem('ocr_workbench_runs');
  for (let i = localStorage.length - 1; i >= 0; i--) {
    const key = localStorage.key(i);
    if (key && key.startsWith('ocr_workbench_run_detail_')) {
      localStorage.removeItem(key);
    }
  }
}

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

export const getStoredRuns = (): RunSummary[] => {
  const saved = localStorage.getItem('ocr_workbench_runs');
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch {
      return [];
    }
  }
  return [];
};

export const saveStoredRuns = (runs: RunSummary[]): void => {
  localStorage.setItem('ocr_workbench_runs', JSON.stringify(runs));
};
