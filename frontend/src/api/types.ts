export interface RunSummary {
  run_id: string;
  filename: string;
  timestamp: string;
  status: 'safe_for_erp' | 'needs_review' | 'failed' | 'verified';
  confidence: number;
  token_coverage: number;
  representability_score: number;
  selected_table_id: string;
  selected_table_shape: string; // e.g. "16 Rows x 8 Columns"
  selected_table_available?: boolean;
  selected_candidate_id?: string | null;
  no_valid_table_candidate_reason?: string;
  missing_fields: string[];
  row_math_status: 'pass' | 'fail' | 'unmeasurable';
  is_demo?: boolean;
  backend_invoice_id?: string;
  diagnostics_run_id?: string;
  storage_warning?: string;
  extraction_engine?: string;
  // Denormalized display fields sourced directly from the backend Invoice
  // record, so list views don't need a per-row detail fetch.
  seller_name?: string | null;
  grand_total?: number | null;
  invoice_number?: string | null;
  invoice_date?: string | null;
  image_url?: string | null;
}

export interface OCRBlock {
  block_id: string;
  text: string;
  confidence: number;
  bbox: [number, number, number, number] | null; // [x_min, y_min, x_max, y_max] in absolute or relative pixels
  normalized_bbox?: [number, number, number, number] | null; // [x_min, y_min, x_max, y_max] normalized (0 to 1)
  assigned_row_id?: number;
  assigned_col_id?: number;
  assigned_cell_id?: string;
  status: 'mapped' | 'orphan' | 'ambiguous' | 'merged' | 'split_candidate' | 'low_confidence' | 'missing_geometry';
  warnings?: string[];
}

export interface TableCell {
  cell_id: string;
  row_id: number;
  col_id: number;
  text: string;
  confidence: number;
  semantic_label: string;
  row_role?: string;
  role?: string;
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
  bbox?: [number, number, number, number] | null;
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
  bbox?: [number, number, number, number] | null;
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
  content_url?: string;
  download_url?: string;
}

export interface CanonicalLineItem {
  name: string | null;
  pack: string | null;
  batch: string | null;
  expiry: string | null;
  hsn: string | null;
  quantity: number | null;
  free_quantity: number | null;
  mrp: number | null;
  rate: number | null;
  discount: number | null;
  gst_percent: number | null;
  amount: number | null;
  confidence: number | null;
}

// --- Catalogue -------------------------------------------------------------

// One raw spelling an invoice printed. Several of these resolving to the same
// Product is what a merge actually is.
export interface ProductAlias {
  id: string;
  raw_name: string;
  normalized_name: string;
  status: 'new' | 'confirmed';
  times_seen: number;
  first_seen?: string;
  last_seen?: string;
}

export interface ProductFlag {
  code: string;
  severity: 'high' | 'medium' | 'low';
  field: string | null;
  message: string;
}

// A single invoice line that fed this product — the evidence behind a merge.
export interface ProductObservation {
  id: string;
  alias_name: string | null;
  alias_id: string | null;
  batch_number: string | null;
  expiry_date: string | null;
  quantity: number | null;
  free_quantity: number | null;
  mrp: number | null;
  rate: number | null;
  discount: number | null;
  discount_percent: number | null;
  gst_percent: number | null;
  amount: number | null;
  hsn: string | null;
  invoice_id: string;
  invoice_number: string | null;
  invoice_date: string | null;
  seller_name: string | null;
}

export interface Product {
  id: string;
  identity_key: string;
  canonical_name: string | null;
  // Catalogue level
  brand: string | null;
  strength: string | null;
  form: string | null;
  pack_size: string | null;
  pack_multiplier: number | null;
  base_unit: string | null;
  manufacturer: string | null;
  hsn: string | null;
  schedule: string | null;
  notes: string | null;
  // Which fields a human actually approved, as opposed to the parser guessing.
  confirmed_fields: string[];
  review_status: 'needs_review' | 'confirmed';
  // Parser confidence, kept per field so the UI can show what to double-check.
  brand_confidence?: number;
  strength_confidence?: number;
  form_confidence?: number;
  pack_size_confidence?: number;
  pack_multiplier_confidence?: number;
  base_unit_confidence?: number;
  // Aggregated invoice evidence
  aliases: ProductAlias[];
  observed_mrps: number[];
  observed_rates: number[];
  observed_hsns: string[];
  observed_gst: number[];
  vendors: string[];
  times_seen: number;
  invoice_count: number;
  batch_count: number;
  total_quantity: number;
  total_base_units: number | null;
  first_seen?: string;
  last_seen?: string;
  // Derived
  flags: ProductFlag[];
  completeness: number;
  needs_attention: boolean;
  // Only present on the detail fetch.
  observations?: ProductObservation[];
}

// --- Catalogue enrichment (public drug-listing lookup) ---------------------

export interface MatchCandidate {
  slug: string;
  source: string;
  url: string;
  display: string;
  listing_brand: string;
  listing_strength: string | null;
  listing_form: string | null;
  score: number;
  brand_score: number;
  // True only when BOTH sides stated a strength and they agree. A false here
  // is the difference between "we checked" and "nobody said".
  strength_verified: boolean;
  form_agrees: boolean;
  reasons: string[];
}

export interface ProductFacts {
  source: string;
  source_url: string;
  listing_name: string | null;
  brand: string | null;
  strength: string | null;
  form: string | null;
  pack_size: string | null;
  pack_multiplier: number | null;
  base_unit: string | null;
  manufacturer: string | null;
  composition: string | null;
  listed_mrp: number | null;
  prescription_note: string | null;
  // Fields the source does not publish at all, so the UI can say so rather
  // than implying the listing asserted a blank.
  unavailable: string[];
}

export interface FieldSuggestion {
  field: string;
  current: string | null;
  suggested: string | null;
  agrees: boolean;
  confirmed: boolean;
}

export interface Suggestion {
  match: MatchCandidate;
  facts: ProductFacts | null;
  fields: FieldSuggestion[];
  high_confidence: boolean;
}

export interface EnrichmentResult {
  product_id: string;
  query: string;
  suggestions: Suggestion[];
  // An empty suggestion list means very different things depending on this:
  // ok | no_query | no_index | no_match
  status: string;
  message: string | null;
}

export interface ProductSummary {
  total: number;
  needs_review: number;
  needs_attention: number;
  missing_pack_multiplier: number;
  missing_hsn: number;
  price_conflicts: number;
}

export interface ProductListResponse {
  products: Product[];
  summary: ProductSummary;
}

export interface CanonicalInvoice {
  invoice_number: string | null;
  invoice_date: string | null;
  seller_name: string | null;
  buyer_name: string | null;
  subtotal: number | null;
  discount: number | null;
  cgst: number | null;
  sgst: number | null;
  igst: number | null;
  grand_total: number | null;
  line_items: CanonicalLineItem[];
  confidence: number | null;
  extraction_engine: string;
  raw_engine_metadata?: any;
}

/**
 * An item type: what a product IS, plus the units it can be measured in.
 *
 * This vocabulary used to be hardcoded in five places — the parser's form
 * table, its single-container set, and three lists in the UI — which had to
 * be edited together and had already drifted apart. It is data now, so a
 * pharmacy can add what it actually stocks.
 */
export interface ItemType {
  id: string;
  name: string;
  /** The unit a single dispensable item is counted in. Always one of supported_units. */
  base_unit: string;
  supported_units: string[];
  /** True when pack size means "one container of this size", not a count. */
  single_container: boolean;
  /** Words in a product name that suggest this type. Optional. */
  keywords: string[];
  /** Seeded types can be switched off, but never renamed or deleted. */
  builtin: boolean;
  active: boolean;
  sort_order?: number;
}

export interface ItemTypesResponse {
  item_types: ItemType[];
  known_units: string[];
  count_units: string[];
  measure_units: string[];
}
