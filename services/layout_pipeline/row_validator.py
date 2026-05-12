"""
Row-Level Validation Engine.

Post-assignment validator that operates on the populated cell graph.
Integrates geometric, semantic, and financial signals to assess row stability.

Responsibilities:
- Row completeness check (expected column types present)
- Semantic type validation (cross-check cell content vs column classifier type)
- Financial sanity (qty × rate ≈ amount)
- Row isolation (mark unstable rows without deleting them)
- Duplicate row detection
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from models.layout_models import TableRegion, TableCell, RowRegion
from core.logger import logger
from decimal import Decimal
from services.qty_parser import parse_quantity
from services.financial_reconciler import DiscountAwareVerifier


def _parse_numeric(text: str) -> Optional[float]:
    """Attempt to extract a single float from a text value."""
    if not text:
        return None
    cleaned = re.sub(r'[₹$,\s]', '', text.strip())
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_numeric_cell(text: str) -> bool:
    """Check if cell text is numeric-like."""
    if not text:
        return False
    cleaned = text.replace(' ', '').replace('₹', '').replace(',', '')
    return bool(re.search(r'^\d+\.?\d*$', cleaned))


class RowValidator:
    """
    Validates populated rows against structural, semantic, and financial expectations.
    
    Does NOT delete rows. Marks unstable rows with stability < 0.5 so downstream
    consumers can choose to isolate them from aggregate calculations.
    """
    
    # Financial tolerance for qty × rate ≈ amount verification
    AMOUNT_TOLERANCE = 1.0  # ±₹1.00
    
    # Minimum stability threshold for a row to be considered "isolated"
    ISOLATION_THRESHOLD = 0.5
    
    def __init__(self, semantic_column_cache: Optional[Dict[str, Any]] = None):
        """
        Args:
            semantic_column_cache: Column type classifications from SemanticColumnClassifier.
                                  Format: {table_id: {col_id: {"type": "AMOUNT"|"QTY"|"RATE"|...}}}
        """
        self.semantic_cache = semantic_column_cache or {}
    
    def validate_table(self, region: TableRegion) -> Dict[str, Any]:
        """
        Run all validation passes on a single table region.
        Modifies RowRegion.stability in-place.
        Returns diagnostic summary.
        """
        results = {
            "table_id": region.table_id,
            "total_rows": len(region.rows),
            "isolated_rows": 0,
            "financial_passes": 0,
            "financial_failures": 0,
            "incomplete_rows": 0,
            "duplicate_suspects": 0,
            "semantic_mismatches": 0,
            "row_diagnostics": []
        }
        
        # Build cell lookup: row_id -> [cells]
        cells_by_row = {}
        for cell in region.cells:
            if cell.row_id not in cells_by_row:
                cells_by_row[cell.row_id] = []
            cells_by_row[cell.row_id].append(cell)
        
        # Get column semantic types for this table
        table_semantics = self.semantic_cache.get(region.table_id, {})
        
        # === Pass 1: Row Completeness + Semantic Validation ===
        for row in region.rows:
            row_cells = cells_by_row.get(row.row_id, [])
            populated_cells = [c for c in row_cells if c.text.strip()]
            
            diag = {
                "row_id": row.row_id,
                "cell_count": len(row_cells),
                "populated_count": len(populated_cells),
                "penalties": [],
                "financial_check": None
            }
            
            stability = 1.0
            
            # Completeness: a row with zero populated cells is degenerate
            if not populated_cells:
                stability *= 0.1
                diag["penalties"].append("empty_row")
                results["incomplete_rows"] += 1
            elif len(populated_cells) == 1 and len(row_cells) > 3:
                # Only one cell populated out of many columns — likely orphan
                stability *= 0.4
                diag["penalties"].append("sparse_row")
                results["incomplete_rows"] += 1
            
            # Semantic type validation
            for cell in populated_cells:
                col_meta = table_semantics.get(cell.col_id, {})
                col_type = col_meta.get("type", "UNKNOWN") if isinstance(col_meta, dict) else "UNKNOWN"
                
                cell_is_numeric = _is_numeric_cell(cell.text)
                
                # Numeric content in a text-only column
                if col_type in ("DRUG_NAME", "TEXT") and cell_is_numeric:
                    stability *= 0.85
                    diag["penalties"].append(f"semantic_mismatch:{cell.col_id}")
                    results["semantic_mismatches"] += 1
                
                # Text content in a numeric column
                if col_type in ("AMOUNT", "RATE", "QTY", "TAX") and not cell_is_numeric and cell.text.strip():
                    # Allow header-like text (the first row often has column labels)
                    if not re.search(r'(AMOUNT|RATE|QTY|TAX|GST|TOTAL|PRICE|QUANTITY)', cell.text.upper()):
                        stability *= 0.85
                        diag["penalties"].append(f"semantic_mismatch:{cell.col_id}")
                        results["semantic_mismatches"] += 1
                
                # Penalize cells assigned via global fallback
                if cell.assignment_strategy == "global_fallback":
                    stability *= 0.7
                    diag["penalties"].append(f"global_fallback:{cell.col_id}")
            
            # === Pass 2: Financial Sanity (qty × rate ≈ amount) ===
            qty_val, rate_val, amount_val, disc_val = None, None, None, None
            
            for cell in populated_cells:
                col_meta = table_semantics.get(cell.col_id, {})
                col_type = col_meta.get("type", "").upper() if isinstance(col_meta, dict) else str(col_meta).upper()
                
                if col_type == "QUANTITY" or col_type == "QTY":
                    qty_parsed = parse_quantity(cell.text)
                    qty_val = Decimal(str(qty_parsed.billed_qty))
                elif col_type == "RATE":
                    parsed_num = _parse_numeric(cell.text)
                    rate_val = Decimal(str(parsed_num)) if parsed_num is not None else None
                elif col_type == "AMOUNT":
                    parsed_num = _parse_numeric(cell.text)
                    amount_val = Decimal(str(parsed_num)) if parsed_num is not None else None
                elif "DISCOUNT" in col_type or "DISC" in col_type:
                    parsed_num = _parse_numeric(cell.text)
                    disc_val = Decimal(str(parsed_num)) if parsed_num is not None else None
            
            if qty_val is not None and rate_val is not None and amount_val is not None:
                # Integrate global discount verifier engine
                verifier = DiscountAwareVerifier()
                success, formula = verifier.verify_row_math(qty_val, rate_val, amount_val, disc_val)
                
                if success:
                    diag["financial_check"] = "PASS"
                    results["financial_passes"] += 1
                else:
                    diag["financial_check"] = f"FAIL (formula: {formula})"
                    results["financial_failures"] += 1
                    # Derive simple delta for penalization
                    expected = qty_val * rate_val
                    discrepancy = float(abs(expected - amount_val))
                    
                    # Scale penalty by discrepancy magnitude
                    if discrepancy > float(amount_val) * 0.5 if amount_val else True:
                        stability *= 0.3  # Catastrophic mismatch
                    else:
                        stability *= 0.6  # Moderate mismatch
                    diag["penalties"].append("financial_inconsistency")
            
            # Clamp and commit stability
            row.stability = round(max(0.05, min(1.0, stability)), 3)
            row.assigned_token_count = sum(len(c.mapped_block_ids) for c in row_cells)
            
            if row.stability < self.ISOLATION_THRESHOLD:
                results["isolated_rows"] += 1
                logger.debug(f"[ROW ISOLATED] {row.row_id} stability={row.stability} penalties={diag['penalties']}")
            
            diag["stability"] = row.stability
            results["row_diagnostics"].append(diag)
        
        # === Pass 3: Duplicate Row Detection ===
        amount_rows = {}  # amount_value -> [row_ids]
        for row in region.rows:
            row_cells = cells_by_row.get(row.row_id, [])
            for cell in row_cells:
                col_meta = table_semantics.get(cell.col_id, {})
                col_type = col_meta.get("type", "UNKNOWN") if isinstance(col_meta, dict) else "UNKNOWN"
                if col_type == "AMOUNT":
                    val = _parse_numeric(cell.text)
                    if val is not None and val > 0:
                        key = round(val, 2)
                        if key not in amount_rows:
                            amount_rows[key] = []
                        amount_rows[key].append(row.row_id)
        
        for amount, row_ids in amount_rows.items():
            if len(row_ids) > 1:
                results["duplicate_suspects"] += len(row_ids)
                logger.debug(f"[DUPLICATE SUSPECT] Amount {amount} appears in rows: {row_ids}")
                # Penalize duplicate rows (but don't isolate — could be legitimate)
                for r in region.rows:
                    if r.row_id in row_ids:
                        r.stability = round(r.stability * 0.9, 3)
        
        logger.info(
            f"RowValidator [{region.table_id}]: "
            f"rows={results['total_rows']}, isolated={results['isolated_rows']}, "
            f"financial_pass={results['financial_passes']}, financial_fail={results['financial_failures']}, "
            f"semantic_mismatches={results['semantic_mismatches']}"
        )
        
        return results
    
    def validate_all(self, regions: List[TableRegion]) -> Dict[str, Any]:
        """Run validation across all table regions."""
        all_results = {}
        for region in regions:
            all_results[region.table_id] = self.validate_table(region)
        return all_results
