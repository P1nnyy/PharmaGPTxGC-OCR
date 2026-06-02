import re
from typing import Any, Dict, List, Optional, Set, Tuple

def sanitize_rows_for_semantic_inference(rows: List[Any], cells: Optional[List[Any]] = None, row_roles: Optional[Dict[str, str]] = None) -> dict:
    """
    Sanitizes reconstructed table rows before semantic column inference to prevent
    footer/tax leakage from poisoning item column classification.
    """
    if row_roles is None:
        row_roles = {}
    
    # Group cells by row_id to construct text for each row
    row_texts = {}
    if cells:
        cells_by_row = {}
        for cell in cells:
            row_id = getattr(cell, "row_id", None) if not isinstance(cell, dict) else cell.get("row_id")
            if row_id is not None:
                cells_by_row.setdefault(row_id, []).append(cell)
        for row_id, r_cells in cells_by_row.items():
            # Sort cells horizontally by center_x
            def get_center_x(c):
                if isinstance(c, dict):
                    geom = c.get("geometry")
                    if isinstance(geom, dict):
                        return float(geom.get("center_x") or 0.0)
                    return 0.0
                else:
                    geom = getattr(c, "geometry", None)
                    if geom:
                        return float(getattr(geom, "center_x", 0.0) or 0.0)
                    return 0.0
            sorted_cells = sorted(
                r_cells,
                key=get_center_x
            )
            def get_text(c):
                if isinstance(c, dict):
                    return c.get("text", "") or ""
                else:
                    return getattr(c, "text", "") or ""
            row_texts[row_id] = " ".join(get_text(c) for c in sorted_cells).strip()
            
    item_rows = []
    excluded_rows = []
    excluded_row_ids = []
    issues = []
    excluded_examples = []
    
    # Compiled pattern for explicit footer/tax labels
    FOOTER_TAX_LABELS_RE = re.compile(
        r"\b(?:subtotal|sub\s+total|taxable|cgst|sgst|igst|gst|round\s+off|grand\s+total|net\s+amount|invoice\s+amount|amount\s+payable|total\s+amount)\b",
        re.IGNORECASE
    )
    
    # Compiled pattern for tax summary style: e.g., CGST 2.500 or SGST 2.500
    TAX_SUMMARY_STYLE_RE = re.compile(
        r"\b(?:CGST|SGST|IGST|GST)\b.*\b\d+(?:\.\d+)?\b",
        re.IGNORECASE
    )
    
    excluded_roles = {"footer_summary_row", "tax_summary_row", "metadata_row", "noise_row"}
    
    for row in rows:
        row_id = getattr(row, "row_id", None) if not isinstance(row, dict) else row.get("row_id")
        role = row_roles.get(row_id) or (getattr(row, "row_role", "unknown_row") if not isinstance(row, dict) else row.get("row_role", "unknown_row"))
        text = row_texts.get(row_id) or (getattr(row, "text", "") if not isinstance(row, dict) else row.get("text", "")) or ""
        
        exclude = False
        reason = ""
        
        if role in excluded_roles:
            exclude = True
            reason = f"explicit_role_{role}"
        elif FOOTER_TAX_LABELS_RE.search(text):
            exclude = True
            reason = "matched_footer_tax_labels"
        elif TAX_SUMMARY_STYLE_RE.search(text):
            exclude = True
            reason = "matched_tax_summary_style"
            
        if exclude:
            excluded_rows.append(row)
            excluded_row_ids.append(row_id)
            issues.append({
                "row_id": row_id,
                "text": text,
                "reason": reason
            })
            if len(excluded_examples) < 10:
                excluded_examples.append({
                    "row_id": row_id,
                    "text": text[:100],
                    "reason": reason
                })
        else:
            item_rows.append(row)
            
    metrics = {
        "input_row_count": len(rows),
        "item_row_count": len(item_rows),
        "excluded_count": len(excluded_rows),
        "excluded_examples": excluded_examples
    }
    
    return {
        "item_rows": item_rows,
        "excluded_rows": excluded_rows,
        "excluded_row_ids": excluded_row_ids,
        "issues": issues,
        "metrics": metrics
    }
