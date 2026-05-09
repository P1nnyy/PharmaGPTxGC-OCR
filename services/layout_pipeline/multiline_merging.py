import re
from typing import List, Tuple
from core.logger import logger
from models.layout_models import ReconstructedRow

def merge_multiline_rows(rows: List[ReconstructedRow]) -> Tuple[List[ReconstructedRow], int]:
    """
    Phase 5.2: Multi-Line Spillover Merging
    Returns the merged rows and the number of merge operations performed.
    """
    merged_rows: List[ReconstructedRow] = []
    merge_count = 0
    
    for row in rows:
        if row.classification == "Unknown" and merged_rows:
            prev_row = merged_rows[-1]
            if prev_row.classification == "Medicine Table Row":
                text = " ".join([b.text for b in row.blocks])
                has_price = bool(re.search(r'\b\d+\.\d{2}\b', text))
                
                # If orphaned row lacks pricing, merge it up to previous medicine row
                if not has_price:
                    prev_row.blocks.extend(row.blocks)
                    for col_id, val in row.columns.items():
                        existing = prev_row.columns.get(col_id, "")
                        prev_row.columns[col_id] = (existing + " " + val).strip()
                    logger.info(f"Merged multi-line orphan into Row {prev_row.row_index}")
                    merge_count += 1
                    continue
                    
        merged_rows.append(row)
        
    return merged_rows, merge_count
