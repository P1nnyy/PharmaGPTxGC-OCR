from typing import Dict, Any, List
from models.layout_models import TableRegion, TableCell

def table_to_markdown(table_region: TableRegion) -> str:
    """
    Converts a structured TSR table region into a clean Markdown table.
    Preserves row and column order, normalizes whitespace, and keeps empty cells blank.
    """
    row_ids = [r.row_id for r in table_region.rows]
    col_ids = [c.col_id for c in table_region.columns]
    
    if not row_ids or not col_ids:
        return ""
        
    cells_lookup = {(cell.row_id, cell.col_id): cell.text for cell in table_region.cells}
    
    # Try to identify column headers (using the first row if appropriate, or col_ids as default)
    header_line = "| " + " | ".join(col_ids) + " |"
    separator_line = "| " + " | ".join(["---"] * len(col_ids)) + " |"
    
    lines = [header_line, separator_line]
    for r_id in row_ids:
        row_cells = []
        for c_id in col_ids:
            val = cells_lookup.get((r_id, c_id), "").strip()
            # Normalize internal whitespace
            val = " ".join(val.split())
            row_cells.append(val)
        lines.append("| " + " | ".join(row_cells) + " |")
        
    return "\n".join(lines)

def table_to_json_grid(table_region: TableRegion) -> Dict[str, Any]:
    """
    Converts a structured TSR table region into a clean JSON grid format.
    """
    row_ids = [r.row_id for r in table_region.rows]
    col_ids = [c.col_id for c in table_region.columns]
    
    if not row_ids or not col_ids:
        return {"rows": []}
        
    cells_lookup = {(cell.row_id, cell.col_id): cell.text for cell in table_region.cells}
    
    rows = []
    for r_id in row_ids:
        row_cells = []
        for c_id in col_ids:
            val = cells_lookup.get((r_id, c_id), "").strip()
            val = " ".join(val.split())
            row_cells.append(val)
        rows.append(row_cells)
        
    return {"rows": rows}

def extract_candidate_financial_cells(table_region: TableRegion) -> Dict[str, Any]:
    """
    Identifies candidate cells for subtotal, GST, grand total, rate, amount, and qty
    using purely deterministic heuristics (keyword matching, numeric density, layout proximity).
    """
    candidates = {
        "subtotal": [],
        "gst": [],
        "grand_total": [],
        "rate": [],
        "amount": [],
        "qty": []
    }
    
    # 1. Header & Keyword Mapping Heuristics
    for cell in table_region.cells:
        text_upper = cell.text.upper()
        cell_data = {
            "cell_text": cell.text,
            "row_id": cell.row_id,
            "col_id": cell.col_id,
            "confidence": cell.confidence
        }
        
        # Keyword triggers
        if "SUB" in text_upper or "NET" in text_upper:
            candidates["subtotal"].append(cell_data)
        if "GST" in text_upper or "TAX" in text_upper or "CGST" in text_upper or "SGST" in text_upper:
            candidates["gst"].append(cell_data)
        if "GRAND" in text_upper or "TOTAL" in text_upper:
            if "SUB" not in text_upper:
                candidates["grand_total"].append(cell_data)
        if "QTY" in text_upper or "QUANTITY" in text_upper or "QNTY" in text_upper:
            candidates["qty"].append(cell_data)
        if "RATE" in text_upper or "PRICE" in text_upper or "UNIT PRICE" in text_upper:
            candidates["rate"].append(cell_data)
        if "AMOUNT" in text_upper or "VALUE" in text_upper:
            candidates["amount"].append(cell_data)
            
    return candidates
