"""
Hierarchical Confidence System.

Propagates confidence bottom-up through the document structure:

    Token → Cell → Row → Table → Invoice

Design principles:
- Row uses min() aggregation (one bad signal drags the whole row down)
- Table uses median() (resists single outlier rows)
- Isolated rows (stability < 0.5) excluded from table confidence
- Reconciliation confidence only affects invoice level
"""

import statistics
from typing import List, Dict, Any, Optional
from models.layout_models import TableRegion, TableCell, RowRegion
from core.logger import logger


class ConfidenceCompositor:
    """
    Computes hierarchical confidence for the entire invoice pipeline output.
    
    Operates post-validation, after row_validator and financial_reconciler
    have populated stability and reconciliation signals.
    """
    
    # Weights for cell-level composition
    OCR_WEIGHT = 0.20
    STRUCTURAL_WEIGHT = 0.30
    SEMANTIC_WEIGHT = 0.20
    FINANCIAL_WEIGHT = 0.30
    
    ISOLATION_THRESHOLD = 0.5
    
    def compute_cell_confidence(self, cell: TableCell, semantic_match: float = 1.0) -> float:
        """
        Composite confidence for a single cell.
        
        Args:
            cell: Populated TableCell with assignment_confidence set
            semantic_match: 0.0-1.0 score from column type validation (1.0 = correct type)
        """
        # OCR confidence: use the cell's base confidence (from TSR structural detection)
        ocr_conf = cell.confidence
        
        # Structural: assignment confidence from IoA allocator (includes tier penalty)
        structural_conf = cell.assignment_confidence
        
        # Semantic: whether cell content matches column type
        semantic_conf = semantic_match
        
        # Financial: not computed at cell level (handled at row level)
        # Use 1.0 as neutral placeholder
        financial_conf = 1.0
        
        composite = (
            ocr_conf * self.OCR_WEIGHT +
            structural_conf * self.STRUCTURAL_WEIGHT +
            semantic_conf * self.SEMANTIC_WEIGHT +
            financial_conf * self.FINANCIAL_WEIGHT
        )
        
        return round(max(0.0, min(1.0, composite)), 3)
    
    def compute_row_confidence(self, row: RowRegion, row_cells: List[TableCell],
                                financial_sanity: float = 1.0,
                                completeness: float = 1.0) -> float:
        """
        Row confidence = min(mean_cell_confidences, financial_sanity, completeness).
        
        Uses min() aggregation: one catastrophic signal should drag the row down.
        
        Args:
            row: RowRegion with stability already set by row_validator
            row_cells: Populated cells belonging to this row
            financial_sanity: 0.0-1.0 from qty×rate verification (1.0 = pass or not applicable)
            completeness: 0.0-1.0 from expected column presence (1.0 = all expected cols present)
        """
        if not row_cells:
            return 0.1
        
        populated = [c for c in row_cells if c.text.strip()]
        if not populated:
            return 0.1
        
        cell_confs = [c.assignment_confidence for c in populated]
        mean_cells = sum(cell_confs) / len(cell_confs)
        
        # min() aggregation: the weakest signal determines the ceiling
        row_conf = min(mean_cells, financial_sanity, completeness)
        
        # Factor in pre-computed stability (from row_validator penalties)
        row_conf *= row.stability
        
        return round(max(0.05, min(1.0, row_conf)), 3)
    
    def compute_table_confidence(self, region: TableRegion,
                                  row_confidences: Dict[str, float]) -> float:
        """
        Table confidence = topology_confidence × median(non-isolated row confidences).
        
        Uses median() to resist single outlier rows.
        Isolated rows (stability < threshold) are excluded from aggregation.
        
        Args:
            region: TableRegion with topology_confidence set by TSR engine
            row_confidences: {row_id: confidence} from compute_row_confidence
        """
        # Filter to non-isolated rows
        stable_confs = [
            conf for row_id, conf in row_confidences.items()
            if any(r.row_id == row_id and r.stability >= self.ISOLATION_THRESHOLD for r in region.rows)
        ]
        
        if not stable_confs:
            return round(region.topology_confidence * 0.1, 3)
        
        median_rows = statistics.median(stable_confs)
        table_conf = region.topology_confidence * median_rows
        
        return round(max(0.05, min(1.0, table_conf)), 3)
    
    def compute_invoice_confidence(self, table_confidences: List[float],
                                    reconciliation_confidence: float = 1.0) -> float:
        """
        Invoice confidence = weighted_mean(table_confidences) × reconciliation_confidence.
        
        Reconciliation (subtotal/grand total match) only affects the invoice level,
        not individual rows or tables.
        
        Args:
            table_confidences: List of per-table confidence values
            reconciliation_confidence: 0.0-1.0 from financial_reconciler
        """
        if not table_confidences:
            return 0.0
        
        # Weight by number of rows in each table (larger tables matter more)
        avg_table = sum(table_confidences) / len(table_confidences)
        
        invoice_conf = avg_table * reconciliation_confidence
        
        return round(max(0.0, min(1.0, invoice_conf)), 3)
    
    def compute_full_hierarchy(self, regions: List[TableRegion],
                                row_validation: Dict[str, Any] = None,
                                reconciliation: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Compute the complete confidence hierarchy for the entire pipeline output.
        
        Returns a structured dict with per-table, per-row, and invoice-level scores.
        """
        row_validation = row_validation or {}
        reconciliation = reconciliation or {}
        
        result = {
            "tables": {},
            "invoice_confidence": 0.0
        }
        
        table_confidences = []
        
        for region in regions:
            # Build cell lookup
            cells_by_row = {}
            for cell in region.cells:
                if cell.row_id not in cells_by_row:
                    cells_by_row[cell.row_id] = []
                cells_by_row[cell.row_id].append(cell)
            
            # Compute row confidences
            row_confs = {}
            table_row_validation = row_validation.get(region.table_id, {})
            row_diags = {d["row_id"]: d for d in table_row_validation.get("row_diagnostics", [])}
            
            for row in region.rows:
                row_cells = cells_by_row.get(row.row_id, [])
                
                # Determine financial sanity for this row
                diag = row_diags.get(row.row_id, {})
                financial_check = diag.get("financial_check")
                financial_sanity = 1.0
                if financial_check and financial_check.startswith("FAIL"):
                    financial_sanity = 0.3
                elif financial_check == "PASS":
                    financial_sanity = 1.0
                
                # Completeness: ratio of populated to total cells
                populated = len([c for c in row_cells if c.text.strip()])
                completeness = populated / max(1, len(row_cells))
                
                row_conf = self.compute_row_confidence(row, row_cells, financial_sanity, completeness)
                row_confs[row.row_id] = row_conf
            
            # Compute table confidence
            table_conf = self.compute_table_confidence(region, row_confs)
            table_confidences.append(table_conf)
            
            result["tables"][region.table_id] = {
                "table_confidence": table_conf,
                "topology_confidence": region.topology_confidence,
                "row_confidences": row_confs,
                "isolated_count": sum(1 for r in region.rows if r.stability < self.ISOLATION_THRESHOLD)
            }
        
        # Compute invoice-level confidence
        recon_confidence = 1.0
        if reconciliation:
            # Average reconciliation confidence across all tables
            recon_vals = [v.get("confidence", 1.0) for v in reconciliation.values() if isinstance(v, dict)]
            if recon_vals:
                recon_confidence = sum(recon_vals) / len(recon_vals)
        
        result["invoice_confidence"] = self.compute_invoice_confidence(table_confidences, recon_confidence)
        
        logger.info(
            f"Confidence Hierarchy: invoice={result['invoice_confidence']}, "
            f"tables={[result['tables'][t]['table_confidence'] for t in result['tables']]}"
        )
        
        return result
