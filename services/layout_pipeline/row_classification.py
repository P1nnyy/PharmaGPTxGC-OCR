import re
from typing import List
from models.layout_models import ReconstructedRow

def classify_rows(rows: List[ReconstructedRow]) -> List[ReconstructedRow]:
    """Phase 4: Contextual Row Classification"""
    for row in rows:
        text = " ".join([b.text for b in row.blocks]).upper()
        
        has_price = bool(re.search(r'\b\d+\.\d{2}\b', text))
        has_date = bool(re.search(r'\b\d{2}[-/]\d{2,4}\b', text))
        has_hsn = bool(re.search(r'\b\d{4,8}\b', text))
        has_med_keyword = bool(re.search(r'\b(TABS?|CAPS?|INJ|MG|ML|TABLETS?|CAPSULES?|SYRUPS?|OINTS?|\d+\'S)\b', text))
        
        if "TOTAL" in text or "AMOUNT" in text or "TAX" in text or "GST" in text:
            row.classification = "Totals"
        elif has_med_keyword or (has_price and (has_hsn or has_date)):
            row.classification = "Medicine Table Row"
        elif "INVOICE" in text or "DATE" in text or "PARTY" in text:
            row.classification = "Header"
        else:
            row.classification = "Unknown"
            
    return rows
