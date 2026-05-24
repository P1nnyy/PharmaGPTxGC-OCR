import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
from models.layout_models import OCRBlock, TableRegion, TableCell
from core.logger import logger

class OrphanToken(BaseModel):
    """Represents a token that was not successfully mapped to any table cell."""
    text: str
    polygon: List[Tuple[float, float]] = Field(default_factory=list)
    confidence: Optional[float] = None
    geometry: Optional[Dict[str, float]] = None

class TokenCoverageReport(BaseModel):
    """Structure for exporting token mapping and alignment coverage metrics."""
    total_tokens: int
    mapped_tokens: int
    unmapped_tokens: int
    misaligned_tokens: int
    coverage_percentage: float
    orphan_count: int
    orphan_tokens: List[OrphanToken]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"json_encoders": {datetime: lambda dt: dt.isoformat()}}

    def to_json(self) -> str:
        """Export the token coverage report as a serialized JSON string."""
        return self.model_dump_json(indent=2)

class TokenCoverageError(ValueError):
    """Exception raised when OCR token coverage falls below the required threshold."""
    pass

class TokenMappingValidator:
    """Validator class to compute OCR-to-cell assignment metrics and enforce minimum coverage gates."""
    
    def __init__(self, threshold: float = 0.95):
        """
        Initialize the TokenMappingValidator.
        
        Args:
            threshold: Required coverage threshold as a float (e.g. 0.95 for 95%).
        """
        self.threshold = threshold

    def validate(self, blocks: List[OCRBlock], regions: List[TableRegion]) -> TokenCoverageReport:
        """
        Validates token coverage across all mapped table regions and returns a coverage report.
        
        Args:
            blocks: Full list of OCRBlocks passed to the pipeline.
            regions: List of TableRegions containing cells with their assigned mapped_block_ids.
            
        Returns:
            TokenCoverageReport object containing computed coverage metrics and orphan logs.
        """
        # Filter blocks to only include those that have valid IDs and normalized geometry
        valid_blocks = [b for b in blocks if b.id and b.normalized_geometry]
        total_tokens = len(valid_blocks)
        
        # Gather all mapped block IDs from all table cells in all regions
        mapped_ids = set()
        block_to_cell = {}
        for r in regions:
            for c in r.cells:
                for b_id in c.mapped_block_ids:
                    if b_id:
                        mapped_ids.add(b_id)
                        block_to_cell[b_id] = c
                        
        mapped_blocks = [b for b in valid_blocks if b.id in mapped_ids]
        mapped_count = len(mapped_blocks)
        
        unmapped_blocks = [b for b in valid_blocks if b.id not in mapped_ids]
        unmapped_count = len(unmapped_blocks)
        
        # Calculate misalignment
        # A mapped block is considered misaligned if its fit score to the assigned cell is low (< 0.60)
        from services.layout_pipeline.ioa_mapping import _compute_ioa, is_numeric_like, _compute_weighted_candidate_score
        
        misaligned_count = 0
        for block in mapped_blocks:
            cell = block_to_cell[block.id]
            is_num = is_numeric_like(block.text)
            pad_size = 1.5 if is_num else 3.0
            
            ioa = _compute_ioa(block.normalized_geometry, cell.geometry, pad=pad_size)
            score = _compute_weighted_candidate_score(block, cell, ioa, is_num=is_num)
            
            if score < 0.60:
                misaligned_count += 1
                
        coverage_percentage = (mapped_count / total_tokens * 100.0) if total_tokens > 0 else 100.0
        orphan_count = unmapped_count
        
        # Populate orphan tokens
        orphan_tokens = []
        for b in unmapped_blocks:
            geom_dict = {
                "min_x": b.normalized_geometry.min_x,
                "max_x": b.normalized_geometry.max_x,
                "min_y": b.normalized_geometry.min_y,
                "max_y": b.normalized_geometry.max_y,
            } if b.normalized_geometry else None
            
            orphan_tokens.append(OrphanToken(
                text=b.text,
                polygon=b.polygon or [],
                confidence=b.confidence,
                geometry=geom_dict
            ))
            
        report = TokenCoverageReport(
            total_tokens=total_tokens,
            mapped_tokens=mapped_count,
            unmapped_tokens=unmapped_count,
            misaligned_tokens=misaligned_count,
            coverage_percentage=round(coverage_percentage, 2),
            orphan_count=orphan_count,
            orphan_tokens=orphan_tokens,
            timestamp=datetime.utcnow()
        )
        
        # Log all unmapped tokens with their properties (text, geometry, confidence)
        if orphan_count > 0:
            logger.warning(f"[TOKEN VALIDATOR] Found {orphan_count} orphan tokens:")
            for idx, o in enumerate(report.orphan_tokens):
                logger.warning(
                    f"  Orphan {idx+1}: text='{o.text}', confidence={o.confidence}, geometry={o.geometry}"
                )
                
        return report
