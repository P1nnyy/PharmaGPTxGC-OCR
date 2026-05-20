import re
from typing import Dict, Any, List

from core.logger import logger
from models.layout_models import TableRegion, TableCell


HEADER_RE = re.compile(r"\b(PRODUCT|ITEM|BATCH|EXP|HSN|MRP|RATE|QTY|AMOUNT|VALUE|T\.?D%?)\b", re.I)
FOOTER_RE = re.compile(
    r"\b(SUB\s*TOTAL|SUBTOTAL|GRAND\s*TOTAL|TOTAL|ROUND\s*OFF|ROUNDOFF|DISCOUNT|"
    r"LESS\s+TD|TRADE\s+DISCOUNT|LESS\s+TRADE\s+DISCOUNT|CR\s*/?\s*DR|CR\s+NOTE|DR\s+NOTE|"
    r"NET\s*(?:AMT|AMOUNT|PAYABLE)?|AMOUNT\s+IN\s+WORDS)\b"
    r"|(?:\b(?:RS\.?|RUPEES|INR)\b.*\b(?:ONLY|PAISE)\b)",
    re.I,
)
TAX_RE = re.compile(r"\b(CGST|SGST|IGST|GST|CESS|TAXABLE|TAX)\b", re.I)
METADATA_RE = re.compile(r"\b(GSTIN|GST\s+NO|INVOICE\s+NO|D\.?L\.?\s*NO|TRANSPORT|TERMS|CONDITIONS|ADDRESS|PHONE)\b", re.I)
MONEY_RE = re.compile(r"\b\d+[\d,]*[\.,]\d{2}\b")
ALPHA_RE = re.compile(r"[A-Za-z]{3,}")
HSN_RE = re.compile(r"\b\d{6,8}\b")
EXPIRY_RE = re.compile(r"\b\d{1,2}[/-]\d{2,4}\b")
BATCH_RE = re.compile(r"\b(?=[A-Z0-9-]{5,20}\b)(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]+\b", re.I)
QTY_RE = re.compile(r"\b\d+(?:\.\d+)?(?:\+\d+(?:\.\d+)?)?\s*(?:S|PCS?|STRIPS?|TAB|CAP|ML|MG)?\b", re.I)
PRODUCT_MARKER_RE = re.compile(
    r"\b(TAB(?:S)?|CAP(?:S)?|INJ|SYP|SYRUP|SUSP|DROPS?|CREAM|OINT|GEL|"
    r"LOTION|SOLUTION|SOAP|ML|MG|GM|MCG|DT|XR|SR|MR)\b",
    re.I,
)


def _row_text(cells: List[TableCell]) -> str:
    return " ".join(c.text for c in cells if c.text).strip()


def _is_right_heavy_sparse_summary_row(region: TableRegion, row: Any, cells: List[TableCell], text: str, money_count: int, alpha_count: int) -> bool:
    populated = [cell for cell in cells if (cell.text or "").strip()]
    if money_count < 2 or len(populated) > 4:
        return False
    if PRODUCT_MARKER_RE.search(text or "") or alpha_count >= 3:
        return False
    if not region.geometry or not row.geometry:
        return False

    table_span_x = max(1.0, region.geometry.max_x - region.geometry.min_x)
    table_span_y = max(1.0, region.geometry.max_y - region.geometry.min_y)
    row_min_x = min((cell.geometry.min_x for cell in populated if cell.geometry), default=row.geometry.min_x)
    row_right_ratio = (row_min_x - region.geometry.min_x) / table_span_x
    row_y_ratio = (row.geometry.center_y - region.geometry.min_y) / table_span_y
    return row_right_ratio >= 0.45 and row_y_ratio >= 0.55


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
        header_label_count = len(HEADER_RE.findall(upper))
        has_product_text = alpha_count >= 2
        right_heavy_summary = _is_right_heavy_sparse_summary_row(region, row, cells, text, money_count, alpha_count)
        table_evidence_count = sum(
            bool(signal)
            for signal in (
                money_count >= 1,
                HSN_RE.search(upper),
                EXPIRY_RE.search(upper),
                BATCH_RE.search(upper),
                QTY_RE.search(upper),
                TAX_RE.search(upper),
            )
        )
        populated_count = len([c for c in cells if c.text.strip()])

        if FOOTER_RE.search(upper) or right_heavy_summary:
            role = "footer_summary_row"
        elif has_product_text and money_count >= 1 and table_evidence_count >= 2:
            role = "item_row"
        elif HEADER_RE.search(upper) and header_label_count >= 2 and money_count == 0 and populated_count >= 3:
            role = "header_row"
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
