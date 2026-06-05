export interface RunSummary {
  run_id: string;
  filename: string;
  timestamp: string;
  status: 'safe_for_erp' | 'needs_review' | 'failed';
  confidence: number;
  token_coverage: number;
  representability_score: number;
  selected_table_id: string;
  selected_table_shape: string; // e.g. "16 Rows x 8 Columns"
  missing_fields: string[];
  row_math_status: 'pass' | 'fail' | 'unmeasurable';
}

export interface OCRBlock {
  block_id: string;
  text: string;
  confidence: number;
  bbox: [number, number, number, number]; // [x_min, y_min, x_max, y_max] in absolute or relative pixels
  normalized_bbox: [number, number, number, number]; // [x_min, y_min, x_max, y_max] normalized (0 to 1)
  assigned_row_id?: number;
  assigned_col_id?: number;
  assigned_cell_id?: string;
  status: 'mapped' | 'orphan' | 'ambiguous' | 'merged' | 'split_candidate' | 'low_confidence';
  warnings?: string[];
}

export interface TableCell {
  cell_id: string;
  row_id: number;
  col_id: number;
  text: string;
  confidence: number;
  semantic_label: string;
  bbox: [number, number, number, number];
  normalized_bbox: [number, number, number, number];
  source_blocks: string[]; // block_ids
  warnings?: string[];
  status: 'good' | 'warning' | 'error' | 'empty';
}

export interface CandidateTable {
  table_id: string;
  source_engine: string; // e.g. "TATR", "PPStructure", "Heuristic"
  rows: number;
  cols: number;
  x_coverage: number; // percentage
  y_coverage: number; // percentage
  cell_count: number;
  non_empty_cells: number;
  score: number; // confidence score
  labels: string[];
  selected: boolean;
  rejection_reason?: string;
  representability_score: number;
  preview_cells: string[][]; // 2D grid preview text
}

export interface SelectedTable {
  table_id: string;
  rows: number;
  cols: number;
  x_coverage: number;
  non_empty_cells: number;
  representability_score: number;
  required_fields_present: string[];
  required_fields_missing: string[];
  cells: TableCell[][]; // 2D array of TableCell
}

export interface SemanticColumn {
  col_id: number;
  predicted_type: string; // e.g. "product", "batch", "expiry", "qty", "rate", etc.
  confidence: number;
  header_text: string;
  sample_values: string[];
  competing_candidates: Array<{ type: string; confidence: number }>;
  conflict_resolution_reason?: string;
  warnings?: string[];
}

export interface RowMathResult {
  row_id: number;
  product: string;
  qty: number;
  rate: number;
  discount: number; // percentage or value
  gst: number; // percentage
  expected_amount: number;
  actual_amount: number;
  difference: number;
  status: 'pass' | 'fail' | 'unmeasurable';
  reason?: string;
  formula_used: string;
}

export interface QualityGate {
  safe_for_erp: boolean;
  status_effective: 'safe_for_erp' | 'needs_review' | 'failed';
  confidence: number;
  reasons: string[];
  missing_fields: string[];
  footer_status: string; // description of footer rescue status
  row_math_status: 'pass' | 'fail' | 'unmeasurable';
  checklist: Array<{
    name: string;
    status: 'pass' | 'warning' | 'fail';
    explanation: string;
  }>;
}

export interface Artifact {
  name: string;
  type: string; // e.g. "image", "json", "csv", "markdown", "zip"
  path: string;
  size: string; // e.g. "145 KB"
  created_at: string;
}
