import json
import os
import re
from typing import Any, Dict, List, Optional

from models.layout_models import OCRBlock, TableRegion


GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b")
FOOTER_ANCHOR_RE = re.compile(r"\b(SUB\s*TOTAL|GRAND\s*TOTAL|SGST|CGST|IGST|ROUND\s*OFF|DISCOUNT)\b", re.I)


def _block_text(blocks: List[OCRBlock]) -> str:
    return " ".join((block.text or "").strip() for block in blocks if block.text)


def _detect_vendor_key(blocks: List[OCRBlock]) -> Dict[str, Optional[str]]:
    full_text = _block_text(blocks)
    gstin_match = GSTIN_RE.search(full_text.upper())
    name = None
    for block in blocks[:20]:
        text = (block.text or "").strip()
        if len(text) >= 8 and re.search(r"[A-Za-z]{4,}", text) and not re.search(r"\b(INVOICE|GST|PHONE|DL|DATE)\b", text, re.I):
            name = text[:80]
            break
    gstin = gstin_match.group(0) if gstin_match else None
    return {
        "vendor_gstin": gstin,
        "vendor_name_hint": name,
        "vendor_key": gstin or name,
    }


def _prior_cache_path() -> str:
    return os.path.join("forensic_runs", "vendor_priors.json")


def _load_cache() -> Dict[str, Any]:
    path = _prior_cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    path = _prior_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, sort_keys=True)


def _row_heights(table: Optional[TableRegion]) -> List[float]:
    if not table:
        return []
    return [
        round(float(row.geometry.max_y - row.geometry.min_y), 3)
        for row in table.rows
        if row.geometry
    ]


def build_vendor_template_prior(blocks: List[OCRBlock], main_table: Optional[TableRegion], tables: List[TableRegion]) -> Dict[str, Any]:
    identity = _detect_vendor_key(blocks)
    vendor_key = identity.get("vendor_key")
    cache = _load_cache()
    cache_hit = bool(vendor_key and vendor_key in cache)

    column_x_bands = []
    if main_table:
        for col in main_table.columns:
            if col.geometry:
                column_x_bands.append({
                    "col_id": col.col_id,
                    "min_x": round(float(col.geometry.min_x), 3),
                    "max_x": round(float(col.geometry.max_x), 3),
                })

    footer_start_y = None
    grand_total_anchor = None
    for table in tables:
        for row in table.rows:
            row_cells = [cell for cell in table.cells if cell.row_id == row.row_id]
            row_text = " ".join(cell.text for cell in row_cells if cell.text)
            if FOOTER_ANCHOR_RE.search(row_text):
                y_value = row.geometry.min_y if row.geometry else None
                if y_value is not None:
                    footer_start_y = min(float(y_value), footer_start_y) if footer_start_y is not None else float(y_value)
                if "GRAND" in row_text.upper() and row.geometry:
                    grand_total_anchor = {
                        "table_id": table.table_id,
                        "row_id": row.row_id,
                        "center_y": round(float(row.geometry.center_y), 3),
                    }

    current = {
        **identity,
        "cache_hit": cache_hit,
        "column_x_bands": column_x_bands,
        "footer_start_y": round(footer_start_y, 3) if footer_start_y is not None else None,
        "grand_total_anchor": grand_total_anchor,
        "row_height_distribution": _row_heights(main_table),
        "prior_used_as_soft_constraint": False,
    }
    if vendor_key:
        cache[vendor_key] = {
            "column_x_bands": column_x_bands,
            "footer_start_y": current["footer_start_y"],
            "grand_total_anchor": grand_total_anchor,
            "row_height_distribution": current["row_height_distribution"],
        }
        _save_cache(cache)
        current["cached_prior_path"] = _prior_cache_path()
    return current
