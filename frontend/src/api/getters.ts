import type { RunSummary, OCRBlock, SelectedTable, CandidateTable, SemanticColumn, QualityGate, RowMathResult, Artifact } from './types';
import { getDetailsData, getStoredRuns } from './storage';
import { selectMainTable } from './table_selection';

export function getRun(runId: string): RunSummary | null {
  const runs = getStoredRuns();
  return runs.find(r => r.run_id === runId) || null;
}

export function getOCRBlocks(runId: string): OCRBlock[] {
  const detail = getDetailsData(runId);
  if (!detail) return [];
  return detail.blocks || detail.metadata?.blocks || [];
}

export function getCandidateTables(runId: string): CandidateTable[] {
  const detail = getDetailsData(runId);
  if (!detail) return [];
  const cands = detail.candidate_tables || detail.metadata?.candidate_tables;
  if (Array.isArray(cands)) return cands;
  if (cands && typeof cands === 'object') {
    return Object.values(cands);
  }
  return [];
}

export function getSelectedTable(runId: string): SelectedTable | null {
  const detail = getDetailsData(runId);
  if (!detail) return null;
  return detail.selected_table || selectMainTable(detail) || null;
}

export function getSemanticMapping(runId: string): SemanticColumn[] {
  const detail = getDetailsData(runId);
  if (!detail) return [];
  const mapping = detail.semantic_columns || detail.metadata?.semantic_columns;
  if (Array.isArray(mapping)) return mapping;
  return [];
}

export function getQualityGate(runId: string): QualityGate | null {
  const detail = getDetailsData(runId);
  if (!detail) return null;
  return detail.quality_gate || detail.metadata?.quality_gate || null;
}

export function getRowMath(runId: string): RowMathResult[] {
  const detail = getDetailsData(runId);
  if (!detail) return [];
  const math = detail.row_math || detail.metadata?.row_math;
  if (Array.isArray(math)) return math;
  if (math && typeof math === 'object') return [math];
  return [];
}

export function getArtifacts(runId: string): Artifact[] {
  const detail = getDetailsData(runId);
  if (!detail) return [];
  return detail.artifacts || detail.metadata?.artifacts || [];
}

export async function getArtifactContent(runId: string, artifactName: string): Promise<string> {
  const detail = getDetailsData(runId);
  if (!detail) return 'Run details unavailable';
  const artifact = getArtifacts(runId).find((a: any) => a.name === artifactName || a.id === artifactName);
  if (artifact && (artifact as any).content) {
    return (artifact as any).content;
  }
  return JSON.stringify(detail, null, 2);
}

export function downloadArtifact(runId: string, artifactArg: any): void {
  const detail = getDetailsData(runId);
  const name = typeof artifactArg === 'string' ? artifactArg : (artifactArg?.name || artifactArg?.filename || 'artifact');
  const content = typeof artifactArg === 'object' && artifactArg?.content ? artifactArg.content : JSON.stringify(detail || {}, null, 2);
  const blob = new Blob([content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name.endsWith('.json') ? name : `${name}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export async function downloadArtifactBundle(runId: string): Promise<void> {
  const detail = getDetailsData(runId);
  const content = JSON.stringify(detail || {}, null, 2);
  const blob = new Blob([content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `run_bundle_${runId}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export function copyDebugSummary(runId: string): void {
  const detail = getDetailsData(runId);
  const text = JSON.stringify(detail || {}, null, 2);
  void navigator.clipboard.writeText(text);
}
