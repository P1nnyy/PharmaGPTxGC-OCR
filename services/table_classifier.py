"""
Table Classification and Routing Engine.
Enhanced with deterministic dominant-table scoring based on Positive/Negative signal profiles.
Fulfills Task 1 & 2 requirements.
"""

import re
import structlog
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from models.layout_models import TableRegion, RegionType

log = structlog.get_logger()

class TableType(str, Enum):
    MAIN_INVOICE_TABLE = "MAIN_INVOICE_TABLE"
    GST_SUMMARY_TABLE = "GST_SUMMARY_TABLE"
    SCHEME_TABLE = "SCHEME_TABLE"
    CREDIT_NOTE_TABLE = "CREDIT_NOTE_TABLE"
    METADATA_TABLE = "METADATA_TABLE"
    UNKNOWN = "UNKNOWN"

class InvoiceTableBundle(BaseModel):
    """Routing container holding organized categorized table groups."""
    main_table: Optional[TableRegion] = None
    gst_summary: List[TableRegion] = Field(default_factory=list)
    scheme_items: List[TableRegion] = Field(default_factory=list)
    credit_notes: List[TableRegion] = Field(default_factory=list)
    metadata_tables: List[TableRegion] = Field(default_factory=list)

class TableClassifier:
    """
    Deterministic dominant-table scorer utilizing positive numeric flow 
    and negative metadata penalties.
    """

    def compute_dominance_score(self, region: TableRegion) -> float:
        """
        Generates absolute weight scoring of a table region's likelihood 
        of being the Primary Invoice Table.
        """
        cells = [c for c in region.cells if c.text and c.text.strip()]
        full_text = " ".join([c.text for c in cells]).upper()
        
        if not cells or not region.rows:
            return -1000.0 # Dead region
            
        score = 0.0
        
        # --- POSITIVE SIGNALS ---
        
        # 1. Row Volume Weight (Base anchor)
        row_count = len(region.rows)
        score += min(row_count * 10, 150) # Up to +150 for long grids
        
        # 2. Repeated numeric alignment (financial nature)
        decimal_matches = re.findall(r'\b\d+\.\d{2}\b', full_text)
        score += len(decimal_matches) * 5.0
        
        # 3. Medicine-length text and common endings (TAB, CAP, INJ)
        medicine_markers = len(re.findall(r'\b(TAB|CAP|INJ|SYP|ML|MG|GM)\b', full_text))
        score += medicine_markers * 15.0
        
        # 4. GST/Tax percentages present in grid
        gst_markers = len(re.findall(r'\d+(\.\d+)?\s*%', full_text))
        score += gst_markers * 8.0
        
        # 5. Quantity-like structures (Packs, combo qty)
        from services.qty_parser import is_compound_quantity
        qty_combos = sum(1 for c in cells if is_compound_quantity(c.text))
        score += qty_combos * 20.0
        
        
        # --- NEGATIVE SIGNALS (Poisons) ---
        
        # 1. IFSC / Bank account codes 
        if re.search(r'\b[A-Z]{4}0[A-Z0-9]{6}\b', full_text): # Standard IFSC pattern
            score -= 300.0
            
        # 2. Bank Metadata Keywords
        if any(kw in full_text for kw in ["IFSC", "BANK", "A/C", "ACCOUNT NO", "BRANCH"]):
            score -= 200.0
            
        # 3. Phone numbers / Contact info
        phone_matches = re.findall(r'\b\d{10}\b|\b\d{5}-\d{5}\b', full_text)
        score -= len(phone_matches) * 50.0
        
        # 4. Address / Footer Density
        if any(kw in full_text for kw in ["REGD OFFICE", "T&C", "TERMS", "SUBJECT TO"]):
            score -= 150.0
            
        # 5. Heavy text prose density without decimals
        if len(full_text) > 200 and len(decimal_matches) < 2:
            score -= 100.0
            
        return score

    def classify_single_region(self, region: TableRegion) -> TableType:
        """Backup heuristic categorize for non-dominant auxiliary routing."""
        cells = [c for c in region.cells if c.text and c.text.strip()]
        full_text = " ".join([c.text for c in cells]).upper()
        
        # 1. Credit Note Explicit
        if any(kw in full_text for kw in ("CREDIT NOTE", "CR NOTE", "RETURNED GOODS")):
            return TableType.CREDIT_NOTE_TABLE
            
        # 2. GST Summary specific profiling
        has_tax_label = any(kw in full_text for kw in ("CGST", "SGST", "IGST", "TAXABLE VALUE"))
        if has_tax_label and len(region.rows) <= 5 and "TAB" not in full_text:
            return TableType.GST_SUMMARY_TABLE
            
        # 3. Scheme Table specifically
        if any(kw in full_text for kw in ("SCHEME", "FREE GOOD", "BONUS", "INITIATIVE")):
            return TableType.SCHEME_TABLE
            
        # Default check for tiny metadata
        if len(region.rows) < 3:
            return TableType.METADATA_TABLE
            
        return TableType.UNKNOWN

    def classify_region_list(self, regions: List[TableRegion]) -> List[TableType]:
        """Process bulk list, promoting absolute HIGHEST scorer to MAIN."""
        if not regions:
            return []
            
        scores = []
        for i, r in enumerate(regions):
            s = self.compute_dominance_score(r)
            scores.append((i, s))
            
        # Sort by descending score
        scores.sort(key=lambda x: x[1], reverse=True)
        
        classifications = [TableType.UNKNOWN] * len(regions)
        
        # Assign highest scorer as MAIN_INVOICE_TABLE (Gate logic: score must be positive or reasonable)
        top_idx, top_score = scores[0]
        if top_score > 20.0: # Minimum competence threshold
             classifications[top_idx] = TableType.MAIN_INVOICE_TABLE
             log.info("dominant_table_selected", table_index=top_idx, score=top_score)
        else:
             log.warning("no_dominant_table_met_threshold", max_score=top_score)
             
        # Classify all others as auxiliaries
        for i in range(len(regions)):
            if classifications[i] == TableType.MAIN_INVOICE_TABLE:
                continue
            # Resolve remaining buckets
            aux_type = self.classify_single_region(regions[i])
            classifications[i] = aux_type if aux_type != TableType.UNKNOWN else TableType.METADATA_TABLE
            
        return classifications

def route_tables(regions: List[TableRegion], classifications: List[TableType]) -> InvoiceTableBundle:
    """Routes table outputs into clean isolated containers."""
    bundle = InvoiceTableBundle()
    
    for region, ttype in zip(regions, classifications):
        region.source_engine = f"classified_{ttype.value}"
        
        if ttype == TableType.MAIN_INVOICE_TABLE:
            bundle.main_table = region
        elif ttype == TableType.GST_SUMMARY_TABLE:
            bundle.gst_summary.append(region)
        elif ttype == TableType.SCHEME_TABLE:
            bundle.scheme_items.append(region)
        elif ttype == TableType.CREDIT_NOTE_TABLE:
            bundle.credit_notes.append(region)
        else:
            bundle.metadata_tables.append(region)
            
    log.info("table_routing_finalized", 
             has_main=bundle.main_table is not None, 
             scheme_count=len(bundle.scheme_items),
             gst_count=len(bundle.gst_summary))
             
    return bundle
