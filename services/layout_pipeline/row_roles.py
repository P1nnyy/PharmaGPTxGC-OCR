import re
from typing import Dict, Any, List

from core.logger import logger
from models.layout_models import TableRegion, TableCell


HEADER_RE = re.compile(r"\b(PRODUCT|ITEM|BATCH|EXP|HSN|MRP|RATE|QTY|AMOUNT|VALUE|T\.?D%?)\b", re.I)
FOOTER_RE = re.compile(
    r"\b(SUB\s*TOTAL|GRAND\s*TOTAL|TOTAL|ROUND(?:OFF)?|DISCOUNT|NET\s*(?:AMT|AMOUNT|PAYABLE)?)\b"
    r"|(?:\b(?:RS\.?|RUPEES)\b.*\bONLY\b)",
    re.I,
)
TAX_RE = re.compile(r"\b(CGST|SGST|IGST|GST|CESS|TAXABLE|TAX)\b", re.I)
METADATA_RE = re.compile(r"\b(GSTIN|GST\s+NO|INVOICE\s+NO|D\.?L\.?\s*NO|TRANSPORT|TERMS|CONDITIONS|ADDRESS|PHONE)\b", re.I)
MONEY_RE = re.compile(r"\b\d+[\d,]*\.\d{2}\b")
ALPHA_RE = re.compile(r"[A-Za-z]{3,}")


def _row_text(cells: List[TableCell]) -> str:
    return " ".join(c.text for c in cells if c.text).strip()


def classify_row_roles(region: TableRegion) -> Dict[str, Any]:
    cells_by_row = {}
    for cell in region.cells:
        cells_by_row.setdefault(cell.row_id, []).append(cell)

    counts = {
        "item_rows_count": 0,
        "header_rows_count": 0,
        "footer_rows_count": 0,
        "tax_rows_count": 0,
        "metadata_rows_count": 0,
        "unknown_rows_count": 0,
    }
    row_roles = {}

    for row in region.rows:
        cells = cells_by_row.get(row.row_id, [])
        text = _row_text(cells)
        upper = text.upper()
        money_count = len(MONEY_RE.findall(text))
        alpha_count = len(ALPHA_RE.findall(text))
        populated_count = len([c for c in cells if c.text.strip()])

        if HEADER_RE.search(upper) and populated_count >= 3:
            role = "header_row"
        elif FOOTER_RE.search(upper):
            role = "footer_summary_row"
        elif TAX_RE.search(upper):
            role = "tax_summary_row"
        elif METADATA_RE.search(upper) and money_count < 2:
            role = "metadata_row"
        elif money_count >= 1 and alpha_count >= 1:
            role = "item_row"
        elif money_count >= 2 and populated_count >= 3:
            role = "item_row"
        else:
            role = "unknown_row"

        row.row_role = role
        row_roles[row.row_id] = role

        if role == "item_row":
            counts["item_rows_count"] += 1
        elif role == "header_row":
            counts["header_rows_count"] += 1
        elif role == "footer_summary_row":
            counts["footer_rows_count"] += 1
        elif role == "tax_summary_row":
            counts["tax_rows_count"] += 1
        elif role == "metadata_row":
            counts["metadata_rows_count"] += 1
        else:
            counts["unknown_rows_count"] += 1

    logger.info(
        f"[ROW ROLES] table={region.table_id} item={counts['item_rows_count']} "
        f"header={counts['header_rows_count']} footer={counts['footer_rows_count']} "
        f"tax={counts['tax_rows_count']} metadata={counts['metadata_rows_count']} "
        f"unknown={counts['unknown_rows_count']}"
    )
    return {
        **counts,
        "row_roles": row_roles,
    }
