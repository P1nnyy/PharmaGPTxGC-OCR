"""
Table Classification and Routing Engine.

Detects functionality of different table instances within the same document.
Resolves multi-table confusion by separating Product Line Items from Free Goods,
GST summaries, and Credit Notes.
"""

import re
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from core.logger import logger
from models.layout_models import TableRegion, RegionType


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
    Heuristic classifier applying voting weight strategy over multiple signals:
    - Density profile (Row counts)
    - Keyword profiles in text
    - Numeric profile (zeros/negatives)
    - Geometric area dominance
    """

    @staticmethod
    def classify_single_region(region: TableRegion) -> TableType:
        """Runs categorical profiling on a single materialized TableRegion."""
        row_count = len(region.rows)
        cell_count = len(region.cells)
        
        # Safety gate
        if row_count == 0 or cell_count == 0:
            return TableType.METADATA_TABLE

        # Accumulate full table text for regex scanning
        full_text = " ".join([c.text for c in region.cells if c.text]).upper()
        
        # 1. Credit Note Check
        if any(kw in full_text for kw in ("CREDIT NOTE", "CR NOTE", "RETURNED GOODS")):
            return TableType.CREDIT_NOTE_TABLE

        # 2. GST Summary Check
        # Signals: Short table, has GST percentages, lacks verbose drug names
        has_gst_percent = bool(re.search(r'\d+(\.\d+)?\s*%', full_text))
        has_tax_label = any(kw in full_text for kw in ("CGST", "SGST", "IGST", "TAX RATE", "TAXABLE VALUE"))
        
        if has_tax_label and row_count <= 5:
            # Verify it doesn't look like a massive product list
            if "TAB" not in full_text and "INJ" not in full_text and "ML" not in full_text:
                 return TableType.GST_SUMMARY_TABLE

        # 3. Scheme Table Check
        # Signals: Explicit header or abundance of zero amounts
        if any(kw in full_text for kw in ("SCHEME", "FREE GOOD", "INITIATIVE", "BONUS")):
            # Extra safeguard: if the header area of this table clearly demarcates scheme
            return TableType.SCHEME_TABLE

        # Count approximate decimals looking like currency amounts
        amount_matches = re.findall(r'\d+\.\d{2}', full_text)
        if len(amount_matches) > 0:
            zero_amount_count = amount_matches.count("0.00")
            # If huge proportion are explicitly zeroes, it's likely a free items table
            if zero_amount_count / len(amount_matches) > 0.7:
                return TableType.SCHEME_TABLE

        # 4. Main Table Check (Default for primary grids)
        # Signals: largest row counts, multiple textual names
        if row_count > 3 and len(full_text) > 50:
            return TableType.MAIN_INVOICE_TABLE

        return TableType.METADATA_TABLE

    def classify_region_list(self, regions: List[TableRegion]) -> List[TableType]:
        """Processes bulk of regions through classifier."""
        results = []
        
        # Map initial raw guesses
        raw_guesses = [self.classify_single_region(r) for r in regions]
        
        # Contextual refinement: Ensure at most ONE Main Table based on density if multiple guessed
        main_candidates = [i for i, t in enumerate(raw_guesses) if t == TableType.MAIN_INVOICE_TABLE]
        if len(main_candidates) > 1:
             # Pick candidate with maximum area/cell richness
             scored = []
             for idx in main_candidates:
                 reg = regions[idx]
                 score = len(reg.cells) * len(reg.rows)
                 scored.append((idx, score))
             scored.sort(key=lambda x: x[1], reverse=True)
             
             best_idx = scored[0][0]
             # Downgrade other candidate main tables to metadata or scheme depending on content
             for idx in main_candidates:
                 if idx != best_idx:
                     raw_guesses[idx] = TableType.SCHEME_TABLE if "FREE" in regions[idx].model_dump_json().upper() else TableType.METADATA_TABLE

        return raw_guesses


# --- MANDATED API SIGNATURES ---

def classify_tables(table_bboxes: list[dict], ocr_blocks: list[dict]) -> list[TableType]:
    """
    Mandated basic bounding box classifier.
    Used if pure raw list dict pass-through is required.
    Currently maps each to a default guess pending deeper reconstruction logic.
    Note: Preferred pipeline uses rich region classification.
    """
    results = []
    for b in table_bboxes:
        # Simple fallback to size heuristic for raw bounds
        if b.get("rows", 0) > 4:
             results.append(TableType.MAIN_INVOICE_TABLE)
        else:
             results.append(TableType.METADATA_TABLE)
    return results


def route_tables(regions: List[TableRegion], classifications: List[TableType]) -> InvoiceTableBundle:
    """
    Distributes list of classified regions into structured bucket model.
    Mandated method fulfilling Step 4 requirements.
    """
    bundle = InvoiceTableBundle()
    
    for region, ttype in zip(regions, classifications):
        # Update internal region tag for downstream serializers
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
            
    logger.info(f"Routing Complete: Main={1 if bundle.main_table else 0}, GST_Sum={len(bundle.gst_summary)}, Schemes={len(bundle.scheme_items)}")
    return bundle
