from typing import List, Dict, Any
from core.logger import logger

def serialize_to_markdown(reconstructed_rows: List[Dict[str, Any]]) -> str:
    """
    Converts reconstructed rows stream into logically sectioned Markdown.
    Aggregates continuous classifications into semantic headers and valid GFM tables.
    """
    if not reconstructed_rows:
        return ""
        
    # Step 1: Group contiguous rows of the same classification type
    segments = []
    if reconstructed_rows:
        current_cls = reconstructed_rows[0].get("classification", "Unknown")
        current_grp = [reconstructed_rows[0]]
        
        for row in reconstructed_rows[1:]:
            row_cls = row.get("classification", "Unknown")
            if row_cls == current_cls:
                current_grp.append(row)
            else:
                segments.append((current_cls, current_grp))
                current_cls = row_cls
                current_grp = [row]
        if current_grp:
            segments.append((current_cls, current_grp))
            
    md_output = []
    
    # Mapping for canonical semantic headers
    CLASS_HEADERS = {
        "header": "# Invoice Metadata",
        "medicine_table": "# Medicine Items",
        "table": "# Medicine Items",
        "totals": "# Totals",
        "footer": "# Footer"
    }
    
    for cls_raw, grp in segments:
        cls = cls_raw.lower()
        header = CLASS_HEADERS.get(cls, f"# Section: {cls_raw.capitalize()}")
        md_output.append(f"\n{header}\n")
        
        # Render Tabular Content for Tables
        if "table" in cls or "medicine" in cls:
            # Gather all unique column IDs across the group to establish table headers
            col_ids = set()
            for r in grp:
                col_ids.update(r.get("columns", {}).keys())
            
            # Attempt basic alphabetic or numerical sorting of column IDs to keep them linear
            try:
                sorted_cols = sorted(list(col_ids), key=lambda x: int(x.split('_')[-1]) if '_' in x else 0)
            except:
                sorted_cols = sorted(list(col_ids))
                
            if not sorted_cols:
                # Fallback if no distinct columns detected: just output flat rows
                for r in grp:
                    text = " ".join([b.get("text", "") for b in r.get("blocks", [])])
                    md_output.append(f"{text}  ")
                continue

            # Construct Markdown Table
            header_line = "| " + " | ".join(sorted_cols) + " |"
            sep_line = "| " + " | ".join(["---"] * len(sorted_cols)) + " |"
            md_output.append(header_line)
            md_output.append(sep_line)
            
            for r in grp:
                cols_dict = r.get("columns", {})
                row_vals = [cols_dict.get(cid, "").strip() for cid in sorted_cols]
                # Clean multiple internal whitespaces inside cells
                row_vals = [" ".join(v.split()) for v in row_vals]
                md_output.append("| " + " | ".join(row_vals) + " |")
        
        else:
            # Non-tabular content, render as flat line pairs preserving local adjacency
            for r in grp:
                # If the row is explicitly keyed in columns dict, format as pseudo key-value
                c_dict = r.get("columns", {})
                if c_dict and len(c_dict) > 1:
                    vals = [v.strip() for v in c_dict.values() if v.strip()]
                    text_line = " : ".join(vals)
                else:
                    # Rejoin blocks based on extraction order
                    text_line = " ".join([b.get("text", "") for b in r.get("blocks", [])])
                
                md_output.append(f"{text_line}  ")
                
    return "\n".join(md_output)
