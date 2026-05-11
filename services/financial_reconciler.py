"""
In-Pipeline Financial Reconciler.

Extracts from the live cell graph and performs deterministic accounting validation:
- Subtotal derivation from individual row amounts
- GST computation verification
- Grand total reconciliation
- Discrepancy reporting

This module runs INSIDE the reconstruction pipeline, not as a post-hoc script.
The validation script (validate_invoice_math.py) calls this same engine on persisted JSON.
"""

import re
from typing import List, Dict, Any, Optional
from models.layout_models import TableRegion, TableCell
from core.logger import logger


def _parse_financial_value(text: str) -> Optional[float]:
    """Parse a financial string into a float. Handles ₹, commas, whitespace."""
    if not text:
        return None
    cleaned = re.sub(r'[₹$,\s]', '', text.strip())
    # Remove trailing non-numeric noise (e.g. "1234.56%")
    cleaned = re.sub(r'[^0-9.]', '', cleaned)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


class ReconciliationResult:
    """Result of financial reconciliation for a single table."""
    
    def __init__(self):
        self.derived_subtotal: float = 0.0
        self.parsed_subtotal: Optional[float] = None
        self.parsed_gst: Optional[float] = None
        self.parsed_grand_total: Optional[float] = None
        self.expected_grand_total: Optional[float] = None
        self.subtotal_match: bool = False
        self.grand_total_match: bool = False
        self.subtotal_discrepancy: float = 0.0
        self.grand_total_discrepancy: float = 0.0
        self.row_amounts: List[Dict[str, Any]] = []
        self.confidence: float = 0.0
        self.warnings: List[str] = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "derived_subtotal": round(self.derived_subtotal, 2),
            "parsed_subtotal": round(self.parsed_subtotal, 2) if self.parsed_subtotal is not None else None,
            "parsed_gst": round(self.parsed_gst, 2) if self.parsed_gst is not None else None,
            "parsed_grand_total": round(self.parsed_grand_total, 2) if self.parsed_grand_total is not None else None,
            "expected_grand_total": round(self.expected_grand_total, 2) if self.expected_grand_total is not None else None,
            "subtotal_match": self.subtotal_match,
            "grand_total_match": self.grand_total_match,
            "subtotal_discrepancy": round(self.subtotal_discrepancy, 2),
            "grand_total_discrepancy": round(self.grand_total_discrepancy, 2),
            "confidence": round(self.confidence, 3),
            "row_amount_count": len(self.row_amounts),
            "warnings": self.warnings
        }


class FinancialReconciler:
    """
    Deterministic financial validator for invoice tables.
    
    Operates on the live cell graph (populated TableRegions) to verify:
    1. Sum of row amounts ≈ parsed subtotal
    2. Subtotal + GST ≈ parsed grand total
    
    Does NOT auto-correct. Reports discrepancies with confidence scores.
    """
    
    # Tolerance for matching derived vs. parsed values
    MATCH_TOLERANCE = 2.0  # ±₹2.00
    
    def __init__(self, semantic_column_cache: Optional[Dict[str, Any]] = None):
        self.semantic_cache = semantic_column_cache or {}
    
    def reconcile_table(self, region: TableRegion) -> ReconciliationResult:
        """
        Perform financial reconciliation on a single table.
        Uses semantic column types to identify amount/qty/rate/gst columns.
        """
        result = ReconciliationResult()
        table_semantics = self.semantic_cache.get(region.table_id, {})
        
        # Build cell lookup
        cells_by_row = {}
        for cell in region.cells:
            if cell.row_id not in cells_by_row:
                cells_by_row[cell.row_id] = []
            cells_by_row[cell.row_id].append(cell)
        
        # Identify column roles from semantic cache
        amount_cols = set()
        gst_cols = set()
        subtotal_cells = []
        grand_total_cells = []
        
        for col_id, meta in table_semantics.items():
            col_type = meta.get("type", "UNKNOWN") if isinstance(meta, dict) else "UNKNOWN"
            if col_type == "AMOUNT":
                amount_cols.add(col_id)
            elif col_type in ("TAX", "GST"):
                gst_cols.add(col_id)
        
        # Scan all cells for subtotal/grand total keywords
        for cell in region.cells:
            text_upper = cell.text.upper().strip()
            if any(kw in text_upper for kw in ("SUB TOTAL", "SUBTOTAL", "SUB-TOTAL", "NET AMOUNT")):
                subtotal_cells.append(cell)
            elif any(kw in text_upper for kw in ("GRAND TOTAL", "TOTAL AMOUNT", "BILL AMOUNT")):
                grand_total_cells.append(cell)
            elif "TOTAL" in text_upper and "SUB" not in text_upper:
                grand_total_cells.append(cell)
        
        # Collect row-level amounts (from stable rows only)
        row_amount_sum = 0.0
        for row in region.rows:
            if row.stability < 0.5:
                # Isolated rows excluded from summation
                continue
            
            row_cells = cells_by_row.get(row.row_id, [])
            for cell in row_cells:
                if cell.col_id in amount_cols:
                    val = _parse_financial_value(cell.text)
                    if val is not None and val > 0:
                        row_amount_sum += val
                        result.row_amounts.append({
                            "row_id": row.row_id,
                            "col_id": cell.col_id,
                            "value": val,
                            "stability": row.stability
                        })
        
        result.derived_subtotal = row_amount_sum
        
        # Try to find parsed subtotal from adjacent cells
        for st_cell in subtotal_cells:
            # Look for a numeric value in the same row, in an amount column
            st_row_cells = cells_by_row.get(st_cell.row_id, [])
            for rc in st_row_cells:
                if rc.col_id in amount_cols or rc != st_cell:
                    val = _parse_financial_value(rc.text)
                    if val is not None and val > 0 and result.parsed_subtotal is None:
                        result.parsed_subtotal = val
        
        # Try to find parsed GST
        gst_sum = 0.0
        for cell in region.cells:
            if cell.col_id in gst_cols:
                val = _parse_financial_value(cell.text)
                if val is not None and val > 0:
                    gst_sum += val
        if gst_sum > 0:
            result.parsed_gst = gst_sum
        
        # Try to find parsed grand total
        for gt_cell in grand_total_cells:
            gt_row_cells = cells_by_row.get(gt_cell.row_id, [])
            for rc in gt_row_cells:
                val = _parse_financial_value(rc.text)
                if val is not None and val > 0 and result.parsed_grand_total is None:
                    result.parsed_grand_total = val
        
        # === Reconciliation ===
        
        # 1. Subtotal check
        if result.parsed_subtotal is not None and result.derived_subtotal > 0:
            result.subtotal_discrepancy = abs(result.derived_subtotal - result.parsed_subtotal)
            result.subtotal_match = result.subtotal_discrepancy <= self.MATCH_TOLERANCE
            if not result.subtotal_match:
                result.warnings.append(
                    f"Subtotal mismatch: derived={result.derived_subtotal:.2f}, parsed={result.parsed_subtotal:.2f}"
                )
        
        # 2. Grand total check
        if result.parsed_grand_total is not None:
            base = result.parsed_subtotal or result.derived_subtotal
            gst = result.parsed_gst or 0.0
            result.expected_grand_total = base + gst
            
            result.grand_total_discrepancy = abs(result.expected_grand_total - result.parsed_grand_total)
            result.grand_total_match = result.grand_total_discrepancy <= self.MATCH_TOLERANCE
            if not result.grand_total_match:
                result.warnings.append(
                    f"Grand total mismatch: expected={result.expected_grand_total:.2f}, parsed={result.parsed_grand_total:.2f}"
                )
        
        # 3. Sanity checks
        if result.derived_subtotal == 0 and len(result.row_amounts) == 0:
            result.warnings.append("No row amounts found — amount column may be misclassified")
        
        if result.parsed_gst is not None and result.derived_subtotal > 0:
            gst_ratio = result.parsed_gst / result.derived_subtotal
            if gst_ratio > 0.5:
                result.warnings.append(f"GST ratio suspiciously high: {gst_ratio:.1%}")
        
        # Compute reconciliation confidence
        confidence = 0.5  # Base
        if result.subtotal_match:
            confidence += 0.25
        if result.grand_total_match:
            confidence += 0.25
        if result.warnings:
            confidence -= 0.1 * len(result.warnings)
        result.confidence = max(0.0, min(1.0, confidence))
        
        logger.info(
            f"Financial Reconciler [{region.table_id}]: "
            f"derived_subtotal={result.derived_subtotal:.2f}, "
            f"subtotal_match={result.subtotal_match}, grand_total_match={result.grand_total_match}, "
            f"confidence={result.confidence:.2f}"
        )
        
        return result
    
    def reconcile_all(self, regions: List[TableRegion]) -> Dict[str, Dict[str, Any]]:
        """Run reconciliation across all table regions."""
        all_results = {}
        for region in regions:
            result = self.reconcile_table(region)
            all_results[region.table_id] = result.to_dict()
        return all_results
