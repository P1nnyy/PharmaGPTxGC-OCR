"""
Phase 4: Contextual Row Classification.

Classifies each ReconstructedRow as one of:
- "Column Header"    — pharma invoice table column headers (S., Qty., Product, MRP, etc.)
- "Totals"           — footer/summary rows (TOTAL, GRAND TOTAL, DISCOUNT, etc.)
- "Medicine Table Row"— item line data rows
- "Header"           — invoice-level header (invoice no, date, party)
- "Unknown"          — unclassifiable

Key fix: column-header detection fires BEFORE the Totals rule to prevent
header keywords like "Amount" and "GST" from triggering Totals classification.
The "Column Header" classification is then treated as part of the medicine table
segment in heuristic_tsr.py segmentation, so the first product's data is not
severed from the item table.
"""

import re
import structlog
from typing import List
from models.layout_models import ReconstructedRow

log = structlog.get_logger()

# Standard pharma invoice column header keywords (case-insensitive tokens).
# These appear in the table header row above medicine line items.
_COLUMN_HEADER_KEYWORDS = re.compile(
    r"\b("
    r"S\.?|SR\.?|NO\.?|QTY\.?|QUANTITY|MFG\.?|PRODUCT|PARTICULARS|DESCRIPTION|"
    r"BATCH|EXP|EXPIRY|HSN|MRP|RATE|AMOUNT|VALUE|"
    r"T\.?D%?|DISC\.?%?|GST%?|TAX%?|FREE|PACK|UOM|UNIT"
    r")\b",
    re.I,
)

# Footer-specific keywords that distinguish Totals from Column Header rows.
# If ANY of these appear, the row is NOT a column header — it's a footer/totals row.
_FOOTER_ONLY_KEYWORDS = re.compile(
    r"\b(TOTAL|GRAND|SUB\s*TOTAL|NET\s+AMT|NET\s+AMOUNT|NET\s+PAYABLE|"
    r"DISCOUNT|ROUND\s*OFF|ROUNDOFF|PAYABLE|CR/?DR|NOTE|"
    r"BILL\s+AMOUNT|RUPEES?\b.*\bONLY)\b",
    re.I,
)


def classify_rows(rows: List[ReconstructedRow]) -> List[ReconstructedRow]:
    """Phase 4: Contextual Row Classification with column-header priority."""
    for row in rows:
        text = " ".join([b.text for b in row.blocks]).upper()

        has_price = bool(re.search(r'\b\d+\.\d{2}\b', text))
        has_date = bool(re.search(r'\b\d{2}[-/]\d{2,4}\b', text))
        has_hsn = bool(re.search(r'\b\d{4,8}\b', text))
        has_med_keyword = bool(re.search(
            r'\b(TABS?|CAPS?|INJ|MG|ML|TABLETS?|CAPSULES?|SYRUPS?|OINTS?|\d+\'S)\b', text
        ))

        # Count how many column-header keywords are present
        col_header_hits = len(_COLUMN_HEADER_KEYWORDS.findall(text))
        has_footer_keyword = bool(_FOOTER_ONLY_KEYWORDS.search(text))

        # ── RULE 1: Column Header row (NEW — fires BEFORE Totals) ──
        # A row with >=3 column-header keywords and NO footer-specific keywords
        # is a table column header, not a totals/footer row.
        # This row may also contain the first product's text due to Y-overlap
        # in row clustering — that is acceptable; it will be placed in the
        # same segment as the medicine table rows by heuristic_tsr.py.
        if col_header_hits >= 3 and not has_footer_keyword:
            row.classification = "Column Header"
            log.debug(
                "header_boundary_chosen",
                row_index=row.row_index,
                col_header_hits=col_header_hits,
                text_preview=text[:100],
            )
        elif "TOTAL" in text or ("AMOUNT" in text and has_footer_keyword) or "TAX" in text:
            # ── RULE 2: Totals row (NARROWED — requires footer context for "AMOUNT") ──
            # Pure "AMOUNT" alone no longer triggers Totals; it needs a footer keyword
            # companion like "TOTAL", "GRAND", "NET", "DISCOUNT", etc.
            row.classification = "Totals"
        elif "GST" in text and has_footer_keyword:
            # GST in a footer context (e.g. "SGST 2.5", "CGST") → Totals
            row.classification = "Totals"
        elif has_med_keyword or (has_price and (has_hsn or has_date)):
            row.classification = "Medicine Table Row"
        elif "INVOICE" in text or "DATE" in text or "PARTY" in text:
            row.classification = "Header"
        else:
            row.classification = "Unknown"

    return rows
