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


def _quantity_parse_succeeded(parsed) -> bool:
    return parsed.parse_method not in ("empty", "unparsed")


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
            "structural_failures": 0,
            "missing_semantic_columns": [],
            "incomplete_rows": 0,
            "duplicate_suspects": 0,
            "semantic_mismatches": 0,
            "qty_parse_success_count": 0,
            "qty_parse_failure_count": 0,
            "qty_parse_extracted_expression": [],
            "qty_parse_rejected_reason": [],
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
        semantic_types = {
            str(meta.get("type", "") if isinstance(meta, dict) else meta).upper()
            for col_id, meta in table_semantics.items()
            if not str(col_id).startswith("_")
        }
        required_semantics = {
            "quantity": ("QUANTITY", "QTY"),
            "rate": ("RATE",),
            "amount": ("AMOUNT",),
        }
        missing_semantic_columns = [
            name for name, aliases in required_semantics.items()
            if not any(alias in semantic_types for alias in aliases)
        ]
        if missing_semantic_columns:
            results["missing_semantic_columns"] = missing_semantic_columns
            logger.warning(
                f"[STRUCTURAL VALIDATION] Missing semantic columns for table {region.table_id}: "
                f"{missing_semantic_columns}"
            )

        # === Pass 1: Row Completeness + Semantic Validation ===
        for row in region.rows:
            row_cells = cells_by_row.get(row.row_id, [])
            populated_cells = [c for c in row_cells if c.text.strip()]
            row_role = getattr(row, "row_role", "unknown_row")

            diag = {
                "row_id": row.row_id,
                "row_role": row_role,
                "cell_count": len(row_cells),
                "populated_count": len(populated_cells),
                "penalties": [],
                "financial_check": None,
                "structural_check": None,
                "qty_parse_extracted_expression": [],
                "qty_parse_rejected_reason": []
            }
            
            stability = 1.0
            qty_parse_cache = {}

            def _get_qty_parse(cell: TableCell):
                key = id(cell)
                if key not in qty_parse_cache:
                    qty_parse_cache[key] = parse_quantity(cell.text)
                return qty_parse_cache[key]
            
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
                col_type = str(col_type).upper()
                
                cell_is_numeric = _is_numeric_cell(cell.text)
                if col_type in ("QTY", "QUANTITY", "FREE_QUANTITY"):
                    cell_is_numeric = cell_is_numeric or _quantity_parse_succeeded(_get_qty_parse(cell))
                
                # Numeric content in a text-only column
                if col_type in ("DRUG_NAME", "PRODUCT", "TEXT") and cell_is_numeric:
                    stability *= 0.85
                    diag["penalties"].append(f"semantic_mismatch:{cell.col_id}")
                    results["semantic_mismatches"] += 1
                
                # Text content in a numeric column
                if col_type in (
                    "AMOUNT",
                    "RATE",
                    "QTY",
                    "QUANTITY",
                    "FREE_QUANTITY",
                    "MRP",
                    "DISCOUNT",
                    "TAXABLE_VALUE",
                    "GST",
                    "TAX",
                ) and not cell_is_numeric and cell.text.strip():
                    # Allow header-like text (the first row often has column labels)
                    if not re.search(r'(AMOUNT|RATE|QTY|TAX|GST|TOTAL|PRICE|QUANTITY)', cell.text.upper()):
                        stability *= 0.85
                        diag["penalties"].append(f"semantic_mismatch:{cell.col_id}")
                        results["semantic_mismatches"] += 1
                
                # Penalize cells assigned via global fallback
                if cell.assignment_strategy == "global_fallback":
                    stability *= 0.7
                    diag["penalties"].append(f"global_fallback:{cell.col_id}")
                if getattr(cell, "semantic_outlier", False):
                    stability *= 0.85
                    diag["penalties"].append(f"semantic_outlier:{cell.col_id}")

            # === Pass 2: Financial Sanity (qty × rate ≈ amount) ===
            qty_val, rate_val, amount_val, disc_val = None, None, None, None

            if row_role != "item_row":
                diag["structural_check"] = f"SKIP non_item_role:{row_role}"
            elif missing_semantic_columns:
                diag["structural_check"] = f"FAIL missing_semantic_columns:{','.join(missing_semantic_columns)}"
                diag["penalties"].append("missing_semantic_columns")
                results["structural_failures"] += 1
                stability *= 0.6
            else:
                diag["structural_check"] = "PASS"

            if diag["structural_check"] == "PASS":
                for cell in populated_cells:
                    if getattr(cell, "semantic_outlier", False):
                        continue
                    col_meta = table_semantics.get(cell.col_id, {})
                    col_type = col_meta.get("type", "").upper() if isinstance(col_meta, dict) else str(col_meta).upper()

                    if col_type == "QUANTITY" or col_type == "QTY":
                        qty_parsed = _get_qty_parse(cell)
                        if _quantity_parse_succeeded(qty_parsed):
                            results["qty_parse_success_count"] += 1
                            if qty_parsed.qty_parse_extracted_expression:
                                diag["qty_parse_extracted_expression"].append(qty_parsed.qty_parse_extracted_expression)
                                results["qty_parse_extracted_expression"].append({
                                    "row_id": row.row_id,
                                    "col_id": cell.col_id,
                                    "raw": cell.text,
                                    "expression": qty_parsed.qty_parse_extracted_expression,
                                })
                            qty_val = Decimal(str(qty_parsed.billed_qty))
                        else:
                            results["qty_parse_failure_count"] += 1
                            rejected_reason = qty_parsed.qty_parse_rejected_reason or "unparsed_quantity"
                            diag["qty_parse_rejected_reason"].append(rejected_reason)
                            results["qty_parse_rejected_reason"].append({
                                "row_id": row.row_id,
                                "col_id": cell.col_id,
                                "raw": cell.text,
                                "reason": rejected_reason,
                            })
                    elif col_type == "RATE":
                        parsed_num = _parse_numeric(cell.text)
                        rate_val = Decimal(str(parsed_num)) if parsed_num is not None else None
                    elif col_type == "AMOUNT":
                        parsed_num = _parse_numeric(cell.text)
                        amount_val = Decimal(str(parsed_num)) if parsed_num is not None else None
                    elif "DISCOUNT" in col_type or "DISC" in col_type:
                        parsed_num = _parse_numeric(cell.text)
                        disc_val = Decimal(str(parsed_num)) if parsed_num is not None else None

            if diag["structural_check"] == "PASS" and qty_val is not None and rate_val is not None and amount_val is not None:
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
            elif diag["structural_check"] == "PASS":
                diag["structural_check"] = "FAIL incomplete_qty_rate_amount_values"
                diag["penalties"].append("incomplete_qty_rate_amount_values")
                results["structural_failures"] += 1
                stability *= 0.75
            
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
            if getattr(row, "row_role", "unknown_row") != "item_row":
                continue
            row_cells = cells_by_row.get(row.row_id, [])
            for cell in row_cells:
                if getattr(cell, "semantic_outlier", False):
                    continue
                col_meta = table_semantics.get(cell.col_id, {})
                col_type = col_meta.get("type", "UNKNOWN") if isinstance(col_meta, dict) else "UNKNOWN"
                col_type = str(col_type).upper()
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
            f"structural_fail={results['structural_failures']}, "
            f"missing_semantic_columns={results['missing_semantic_columns']}, "
            f"semantic_mismatches={results['semantic_mismatches']}"
        )
        
        return results
    
    def validate_all(self, regions: List[TableRegion]) -> Dict[str, Any]:
        """Run validation across all table regions."""
        all_results = {}
        for region in regions:
            all_results[region.table_id] = self.validate_table(region)
        return all_results
