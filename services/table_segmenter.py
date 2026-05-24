"""
Table Region Segmentation and Anchor-Based Reconstruction Engine.
Specifically built to classify and route table regions by explicit header signatures,
reconstruct medicine item rows via deterministic numeric anchors (PCode, HSN, Net Amt),
and segregate tax summaries, scheme items, and credit notes.
"""

import re
import os
import json
import structlog
from typing import List, Dict, Any, Tuple, Optional
from models.layout_models import TableRegion, TableCell, RowRegion, OCRBlock

log = structlog.get_logger()


def _geom_for_block(block: OCRBlock):
    return getattr(block, "normalized_geometry", None) or getattr(block, "original_geometry", None)


def _block_text(block: OCRBlock) -> str:
    return (getattr(block, "text", None) or getattr(block, "raw_text", "") or "").strip()


def _box_debug(geom) -> Optional[Dict[str, float]]:
    if not geom:
        return None
    return {
        "min_x": float(geom.min_x),
        "max_x": float(geom.max_x),
        "min_y": float(geom.min_y),
        "max_y": float(geom.max_y),
        "center_x": float(geom.center_x),
        "center_y": float(geom.center_y),
    }


def _money_value(text: str) -> Optional[str]:
    compact = re.sub(r"\s+", "", text.strip())
    match = re.search(r"\d+(?:[.,]\d{2})", compact)
    if not match:
        return None
    value = match.group(0)
    if "," in value and "." not in value and re.search(r",\d{2}$", value):
        value = value.replace(",", ".")
    return value


def _join_tokens(tokens: List[Dict[str, Any]]) -> str:
    ordered = sorted(tokens, key=lambda t: (round(t["cy"] / 8.0), t["x"]))
    return " ".join(t["text"] for t in ordered if t["text"]).strip()


def _band_dict(left: float, right: float) -> Dict[str, float]:
    return {"min_x": round(float(left), 2), "max_x": round(float(right), 2)}


def _in_band(x: float, band: Dict[str, float], pad: float = 0.0) -> bool:
    return (band["min_x"] - pad) <= x <= (band["max_x"] + pad)


def extract_item_rows_from_ocr_blocks(
    ocr_blocks: List[OCRBlock],
    table_region_debug: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Reconstructs invoice item rows from raw OCR token coordinates.

    This intentionally avoids graph/table row text because those rows may already
    contain mixed tokens from neighboring visual rows.
    """
    debug = table_region_debug if table_region_debug is not None else {}
    for key, default in (
        ("inferred_item_column_bands", {}),
        ("raw_pcode_anchor_candidates", []),
        ("accepted_pcode_anchors", []),
        ("rejected_pcode_anchors", []),
        ("item_row_y_ranges", []),
        ("tokens_assigned_by_row_and_column", []),
        ("tokens_rejected_by_column_rule", []),
        ("clean_item_row_validation_errors", []),
        ("rejected_item_rows_with_reason", []),
    ):
        debug.setdefault(key, default)

    tokens: List[Dict[str, Any]] = []
    for idx, block in enumerate(ocr_blocks or []):
        geom = _geom_for_block(block)
        text = _block_text(block)
        if not geom or not text:
            continue
        tokens.append({
            "idx": idx,
            "id": getattr(block, "id", None) or f"ocr_{idx}",
            "text": text,
            "upper": text.upper(),
            "x": float(geom.center_x),
            "y": float(geom.center_y),
            "cx": float(geom.center_x),
            "cy": float(geom.center_y),
            "min_x": float(geom.min_x),
            "max_x": float(geom.max_x),
            "min_y": float(geom.min_y),
            "max_y": float(geom.max_y),
            "geometry": _box_debug(geom),
        })

    if not tokens:
        debug["clean_item_row_validation_errors"].append({"reason": "no_raw_ocr_tokens"})
        return []

    def header_role(token: Dict[str, Any]) -> Optional[str]:
        text = re.sub(r"[^A-Z0-9 ]+", "", token["upper"]).strip()
        if re.search(r"\bP\s*CODE\b", text) or "PCODE" in text:
            return "pcode"
        if "ITEM DESCRIPTION" in text or text == "DESCRIPTION" or ("ITEM" in text and "DESCRIPTION" in text):
            return "description"
        if text in {"HSN", "RSN"} or " HSN" in f" {text}" or " RSN" in f" {text}":
            return "hsn"
        if text == "UPC" or " UPC" in f" {text}":
            return "upc"
        if "MRP" in text:
            return "mrp"
        if text in {"QTY", "QTY"} or "QTY" in text:
            return "qty"
        if "TAXABLE" in text:
            return "taxable"
        if "NET AMT" in text or "NET AMOUNT" in text:
            return "net_amt"
        if "GROSS" in text or "GREES" in text:
            return "gross"
        if "DISC" in text:
            return "discount"
        if "CGST" in text or "COST" in text or "OSTN" in text:
            return "cgst"
        if "SGST" in text or "SGET" in text:
            return "sgst"
        return None

    header_hits = [dict(token, role=header_role(token)) for token in tokens if header_role(token)]
    if header_hits:
        y_scores: Dict[int, int] = {}
        for hit in header_hits:
            bucket = int(round(hit["cy"] / 10.0) * 10)
            y_scores[bucket] = y_scores.get(bucket, 0) + (2 if hit["role"] in {"pcode", "description", "hsn", "net_amt"} else 1)
        best_bucket = max(y_scores.items(), key=lambda item: item[1])[0]
        header_tokens = [hit for hit in header_hits if abs(hit["cy"] - best_bucket) <= 18]
        header_y = sum(hit["cy"] for hit in header_tokens) / len(header_tokens)
    else:
        header_tokens = []
        header_y = min(t["cy"] for t in tokens)

    role_centers: Dict[str, float] = {}
    for role in ("pcode", "description", "hsn", "upc", "mrp", "qty", "gross", "discount", "taxable", "cgst", "sgst", "net_amt"):
        role_tokens = [t for t in header_tokens if t["role"] == role]
        if role_tokens:
            role_centers[role] = sum(t["cx"] for t in role_tokens) / len(role_tokens)

    page_min_x = min(t["min_x"] for t in tokens)
    page_max_x = max(t["max_x"] for t in tokens)
    pcode_c = role_centers.get("pcode", 120.0)
    desc_c = role_centers.get("description", 198.0)
    hsn_c = role_centers.get("hsn", 286.0)
    upc_c = role_centers.get("upc", 321.0)
    mrp_c = role_centers.get("mrp", 344.0)
    qty_c = role_centers.get("qty", 408.0)
    gross_c = role_centers.get("gross", 445.0)
    discount_c = role_centers.get("discount", 550.0)
    taxable_c = role_centers.get("taxable", 588.0)
    cgst_c = role_centers.get("cgst", 650.0)
    sgst_c = role_centers.get("sgst", 680.0)
    net_c = role_centers.get("net_amt", page_max_x - 32.0)

    bands = {
        "sl_no": _band_dict(max(page_min_x, pcode_c - 42), pcode_c - 22),
        "pcode": _band_dict(pcode_c - 28, min(pcode_c + 28, (pcode_c + desc_c) / 2.0 - 2)),
        "description": _band_dict(max(pcode_c + 22, (pcode_c + desc_c) / 2.0 - 18), (desc_c + hsn_c) / 2.0 + 4),
        "hsn": _band_dict((desc_c + hsn_c) / 2.0 + 5, (hsn_c + upc_c) / 2.0 + 5),
        "upc": _band_dict((hsn_c + upc_c) / 2.0 + 5, (upc_c + mrp_c) / 2.0 + 5),
        "mrp": _band_dict((upc_c + mrp_c) / 2.0 + 5, mrp_c + 38),
        "qty": _band_dict(qty_c - 18, qty_c + 22),
        "gross": _band_dict(gross_c - 22, gross_c + 24),
        "discount": _band_dict(discount_c - 22, discount_c + 22),
        "taxable": _band_dict(taxable_c - 22, taxable_c + 24),
        "cgst": _band_dict(cgst_c - 24, cgst_c + 24),
        "sgst": _band_dict(sgst_c - 24, sgst_c + 24),
        "net_amt": _band_dict(max(net_c - 30, sgst_c + 16), min(page_max_x + 8, net_c + 44)),
    }
    debug["inferred_item_column_bands"] = {
        "header_y": round(float(header_y), 2),
        "header_tokens": [
            {"text": t["text"], "role": t["role"], "center_x": round(t["cx"], 2), "center_y": round(t["cy"], 2)}
            for t in sorted(header_tokens, key=lambda t: (t["cy"], t["cx"]))
        ],
        "role_centers": {k: round(v, 2) for k, v in role_centers.items()},
        "bands": bands,
    }

    pcode_re = re.compile(r"^\d{7,9}$")
    hsn_re = re.compile(r"^\d{6,8}$")
    raw_candidates: List[Dict[str, Any]] = []
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for token in sorted(tokens, key=lambda t: (t["cy"], t["cx"])):
        numeric = re.sub(r"\D", "", token["text"])
        if not numeric or not (2 <= len(numeric) <= 9):
            continue
        candidate = {
            "text": token["text"],
            "numeric": numeric,
            "token_id": token["id"],
            "center_x": round(token["cx"], 2),
            "center_y": round(token["cy"], 2),
            "geometry": token["geometry"],
        }
        if pcode_re.match(numeric):
            raw_candidates.append(candidate)
            reasons = []
            if token["cy"] <= header_y:
                reasons.append("above_or_in_header")
            if not _in_band(token["cx"], bands["pcode"], pad=2.0):
                reasons.append("outside_pcode_band")
            if _in_band(token["cx"], bands["hsn"], pad=2.0):
                reasons.append("inside_hsn_band")
            if len(numeric) < 7:
                reasons.append("serial_or_too_short")
            if reasons:
                rejected.append({**candidate, "reason": ";".join(reasons)})
            else:
                accepted.append({**candidate, "pcode": numeric, "token": token})
        elif len(numeric) <= 2:
            rejected.append({**candidate, "reason": "serial_or_too_short"})
        elif hsn_re.match(numeric) and _in_band(token["cx"], bands["hsn"], pad=2.0):
            rejected.append({**candidate, "reason": "hsn_token_in_hsn_band"})

    deduped: List[Dict[str, Any]] = []
    seen_pcodes = set()
    for anchor in accepted:
        if anchor["pcode"] in seen_pcodes:
            rejected.append({k: v for k, v in anchor.items() if k != "token"} | {"reason": "duplicate_pcode_anchor"})
            continue
        seen_pcodes.add(anchor["pcode"])
        deduped.append(anchor)

    debug["raw_pcode_anchor_candidates"] = raw_candidates
    debug["accepted_pcode_anchors"] = [{k: v for k, v in a.items() if k != "token"} for a in deduped]
    debug["rejected_pcode_anchors"] = rejected
    if not deduped:
        debug["clean_item_row_validation_errors"].append({"reason": "no_accepted_pcode_anchors"})
        return []

    stop_keywords = (
        "TOTAL", "PRODUCT NAME", "INITIATIVE", "FREE PRODUCT", "CREDIT NOTE",
        "NET PAYABLE", "AMOUNT IN WORDS", "AUTHORISED SIGNATURE",
    )
    last_anchor_y = deduped[-1]["token"]["cy"]
    stop_y_candidates = [
        t["cy"] for t in tokens
        if t["cy"] > last_anchor_y + 5 and any(keyword in t["upper"] for keyword in stop_keywords)
    ]
    stop_y = min(stop_y_candidates) if stop_y_candidates else max(t["cy"] for t in tokens) + 1

    y_ranges: List[Dict[str, Any]] = []
    for idx, anchor in enumerate(deduped):
        start_y = anchor["token"]["cy"] - (5.0 if idx == 0 else 2.0)
        if idx + 1 < len(deduped):
            end_y = deduped[idx + 1]["token"]["cy"] - 2.0
        else:
            end_y = min(stop_y - 2.0, anchor["token"]["cy"] + 36.0)
        y_ranges.append({
            "row_index": idx + 1,
            "pcode": anchor["pcode"],
            "start_y": round(start_y, 2),
            "end_y": round(end_y, 2),
            "anchor_y": round(anchor["token"]["cy"], 2),
        })
    debug["item_row_y_ranges"] = y_ranges

    item_rows: List[Dict[str, Any]] = []
    assigned_debug: List[Dict[str, Any]] = []
    rejected_column_tokens: List[Dict[str, Any]] = []
    terminal_keywords = ("TOTAL", "PRODUCT NAME", "INITIATIVE", "CREDIT NOTE", "NET PAYABLE")

    for row_range in y_ranges:
        row_tokens = [
            t for t in tokens
            if row_range["start_y"] <= t["cy"] < row_range["end_y"]
            and not any(keyword in t["upper"] for keyword in terminal_keywords)
        ]
        columns: Dict[str, List[Dict[str, Any]]] = {name: [] for name in bands}
        rejected_for_row: List[Dict[str, Any]] = []
        for token in row_tokens:
            matched = [name for name, band in bands.items() if _in_band(token["cx"], band, pad=1.5)]
            if matched:
                name = matched[0]
                columns[name].append(token)
                assigned_debug.append({
                    "row_index": row_range["row_index"],
                    "pcode_anchor": row_range["pcode"],
                    "column": name,
                    "text": token["text"],
                    "token_id": token["id"],
                    "center_x": round(token["cx"], 2),
                    "center_y": round(token["cy"], 2),
                })
            else:
                entry = {
                    "row_index": row_range["row_index"],
                    "pcode_anchor": row_range["pcode"],
                    "text": token["text"],
                    "token_id": token["id"],
                    "center_x": round(token["cx"], 2),
                    "center_y": round(token["cy"], 2),
                    "reason": "outside_inferred_item_column_bands",
                }
                rejected_for_row.append(entry)
                rejected_column_tokens.append(entry)

        pcode_tokens = [
            re.sub(r"\D", "", t["text"])
            for t in columns["pcode"]
            if pcode_re.match(re.sub(r"\D", "", t["text"]))
        ]
        pcode = pcode_tokens[0] if pcode_tokens else row_range["pcode"]

        desc = _join_tokens(columns["description"])
        hsn_tokens = [
            re.sub(r"\D", "", t["text"])
            for t in columns["hsn"]
            if hsn_re.match(re.sub(r"\D", "", t["text"]))
        ]
        hsn = next((value for value in hsn_tokens if value != pcode), "")

        net_candidates = []
        for token in columns["net_amt"]:
            value = _money_value(token["text"])
            if value is not None:
                net_candidates.append((token["cx"], token["cy"], value, token))
        net_amt = ""
        if net_candidates:
            net_amt = sorted(net_candidates, key=lambda item: (item[0], item[1]))[-1][2]

        validation_errors = []
        if not pcode:
            validation_errors.append("missing_pcode")
        if not desc:
            validation_errors.append("empty_description")
        if desc and re.sub(r"\D", "", desc) == pcode:
            validation_errors.append("description_equals_pcode")
        if not hsn:
            validation_errors.append("missing_hsn")
        if hsn and hsn == pcode:
            validation_errors.append("hsn_equals_pcode")
        if not net_amt:
            validation_errors.append("missing_net_amt")

        row = {
            "pcode": pcode,
            "item_description": desc,
            "hsn": hsn,
            "mrp": _join_tokens(columns["mrp"]),
            "qty": _join_tokens(columns["qty"]),
            "rate": "",
            "net_amt": net_amt,
            "low_confidence": bool(validation_errors),
            "confidence_reasons": validation_errors,
            "visual_row_id": f"ocr_item_row_{row_range['row_index']}",
            "source": "raw_ocr_coordinate_reconstruction",
        }
        if validation_errors:
            debug["clean_item_row_validation_errors"].append({
                "row_index": row_range["row_index"],
                "pcode": pcode,
                "reason": ";".join(validation_errors),
                "row": row,
            })
            if "description_equals_pcode" in validation_errors or "hsn_equals_pcode" in validation_errors:
                debug["rejected_item_rows_with_reason"].append({
                    "row_index": row_range["row_index"],
                    "pcode": pcode,
                    "reason": ";".join(validation_errors),
                    "row": row,
                })
                continue

        item_rows.append(row)

    debug["tokens_assigned_by_row_and_column"] = assigned_debug
    debug["tokens_rejected_by_column_rule"] = rejected_column_tokens
    return item_rows

class TableSegmenter:
    """
    Handles robust segmentation of invoice tables and anchor-based medicine item reconstruction.
    """
    def __init__(self, table_regions: List[TableRegion], ocr_blocks: List[OCRBlock]):
        self.table_regions = table_regions
        self.ocr_blocks = ocr_blocks
        self.blocks_map = {b.id: b for b in ocr_blocks if b.id}
        
        # Categorized table regions
        self.tax_summary_table = None
        self.main_item_table = None
        self.scheme_table = None
        self.credit_note_table = None
        self.other_tables = []
        
        # Diagnostics and debug outputs
        self.debug_output = {
            "table_region_debug": [],
            "detected_region_boundaries": {},
            "rejected_item_rows_with_reason": [],
            "item_row_anchor_debug": []
        }
        
    def classify_all_regions(self):
        """
        Classifies each TableRegion based on the presence of explicit header signature keywords.
        Fulfills Requirement 2.
        """
        for i, region in enumerate(self.table_regions):
            table_id = region.table_id or f"table_{i}"
            
            # Map geometry boundaries for debug reporting
            geom = region.geometry
            boundary = {
                "min_x": float(geom.min_x) if geom else 0.0,
                "max_x": float(geom.max_x) if geom else 0.0,
                "min_y": float(geom.min_y) if geom else 0.0,
                "max_y": float(geom.max_y) if geom else 0.0
            }
            self.debug_output["detected_region_boundaries"][table_id] = boundary
            
            # Group cells by visual row IDs for row-by-row header text evaluation
            cells_by_row = {}
            for cell in region.cells:
                cells_by_row.setdefault(cell.row_id, []).append(cell)
                
            region_score = {
                "tax_summary_table": 0,
                "main_item_table": 0,
                "scheme_table": 0,
                "credit_note_table": 0
            }
            
            # Evaluate every visual row in the table to capture headers anywhere in the grid
            for row in region.rows:
                row_cells = cells_by_row.get(row.row_id, [])
                row_text = " ".join(c.text for c in row_cells if c.text).upper()
                
                # 1. tax_summary_table: Particulars, Gross Amt, Sch Amt, Taxable Amt, Tax Amt
                tax_sigs = ["PARTICULARS", "GROSS AMT", "SCH AMT", "TAXABLE AMT", "TAX AMT", "CGST", "SGST"]
                tax_hits = sum(1 for sig in tax_sigs if sig in row_text)
                if tax_hits >= 2:
                    region_score["tax_summary_table"] += tax_hits * 10
                    
                # 2. main_item_table: PCode, Item Description, HSN, UPC, MRP, Net Amt
                main_sigs = ["PCODE", "P CODE", "ITEM DESCRIPTION", "DESCRIPTION", "HSN", "UPC", "MRP", "NET AMT", "NET AMOUNT", "NET PAYABLE"]
                main_hits = sum(1 for sig in main_sigs if sig in row_text)
                if main_hits >= 2:
                    region_score["main_item_table"] += main_hits * 10
                    
                # 3. scheme_table: Initiative Name, Free Product, Qty, Amount
                scheme_sigs = ["INITIATIVE NAME", "INITIATIVE", "FREE PRODUCT", "FREE PROD", "QTY", "AMOUNT", "SCHEME"]
                scheme_hits = 0
                if "INITIATIVE NAME" in row_text or "INITIATIVE" in row_text:
                    scheme_hits += 2
                if "FREE PRODUCT" in row_text or "FREE PROD" in row_text:
                    scheme_hits += 2
                if "QTY" in row_text and any(kw in row_text for kw in ("FREE", "INITIATIVE", "SCHEME", "DISC")):
                    scheme_hits += 1
                if "AMOUNT" in row_text and any(kw in row_text for kw in ("FREE", "INITIATIVE", "SCHEME", "DISC")):
                    scheme_hits += 1
                if scheme_hits >= 2:
                    region_score["scheme_table"] += scheme_hits * 10
                    
                # 4. credit_note_table: Credit Note Number, Date, Particulars, Amount
                credit_hits = 0
                if any(kw in row_text for kw in ("CREDIT NOTE NUMBER", "CREDIT NOTE", "CR NOTE", "CR/DR NOTE")):
                    credit_hits += 3
                if "RETURNED GOODS" in row_text or "RETURN GOODS" in row_text or "RETURNS" in row_text:
                    credit_hits += 3
                if "DATE" in row_text and any(kw in row_text for kw in ("CREDIT", "CR", "RETURN")):
                    credit_hits += 1
                if credit_hits >= 2:
                    region_score["credit_note_table"] += credit_hits * 10
            
            # Select classification with the highest cumulative overlap score
            best_class = "unknown"
            max_score = 0
            for cls, score in region_score.items():
                if score > max_score:
                    max_score = score
                    best_class = cls
                    
            # Fallback overall heuristics if header labels weren't explicitly matched
            if max_score == 0:
                full_text = " ".join(c.text for c in region.cells if c.text).upper()
                if any(kw in full_text for kw in ("CREDIT NOTE", "CR NOTE", "RETURNED GOODS", "RETURNS")):
                    best_class = "credit_note_table"
                elif any(kw in full_text for kw in ("INITIATIVE NAME", "FREE PRODUCT", "SCHEME DISCOUNT", "FREE GOOD")):
                    best_class = "scheme_table"
                elif any(kw in full_text for kw in ("CGST", "SGST", "IGST", "TAXABLE VALUE")):
                    if "TAB" in full_text and len(region.rows) > 4:
                        best_class = "main_item_table"
                    else:
                        best_class = "tax_summary_table"
                else:
                    if len(region.rows) >= 4 and len(region.columns) >= 4:
                        best_class = "main_item_table"
                    else:
                        best_class = "unknown"
            
            log.info("table_region_classified", table_id=table_id, classification=best_class, score_profile=region_score)
            
            self.debug_output["table_region_debug"].append({
                "table_id": table_id,
                "classification": best_class,
                "scores": region_score,
                "row_count": len(region.rows),
                "cell_count": len(region.cells)
            })
            
            # Route classified region to its respective target field
            if best_class == "tax_summary_table":
                self.tax_summary_table = region
            elif best_class == "main_item_table":
                # Handle edge case where multiple tables score as main_item_table; select the one with most rows
                if self.main_item_table is None or len(region.rows) > len(self.main_item_table.rows):
                    if self.main_item_table:
                        self.other_tables.append(self.main_item_table)
                    self.main_item_table = region
                else:
                    self.other_tables.append(region)
            elif best_class == "scheme_table":
                self.scheme_table = region
            elif best_class == "credit_note_table":
                self.credit_note_table = region
            else:
                self.other_tables.append(region)

    def reconstruct_generic_table(self, region: TableRegion) -> List[Dict[str, Any]]:
        """
        Parses auxiliary tables (tax summaries, schemes, credit notes) row by row.
        Maps cells to closest visual headers.
        """
        if not region or not region.rows:
            return []
            
        cells_by_row = {}
        for cell in region.cells:
            cells_by_row.setdefault(cell.row_id, []).append(cell)
            
        sorted_rows = sorted(region.rows, key=lambda r: r.geometry.min_y if r.geometry else 0)
        
        # Assume first row represents the table header
        header_row = sorted_rows[0]
        header_cells = cells_by_row.get(header_row.row_id, [])
        header_cells.sort(key=lambda c: c.geometry.min_x if c.geometry else 0)
        
        col_mapping = {}
        for c in header_cells:
            col_mapping[c.col_id] = c.text.strip() if c.text else f"col_{c.col_id}"
            
        rows_out = []
        for row in sorted_rows[1:]:
            row_cells = cells_by_row.get(row.row_id, [])
            row_dict = {}
            for c in row_cells:
                col_name = col_mapping.get(c.col_id, f"col_{c.col_id}")
                row_dict[col_name] = c.text.strip() if c.text else ""
            if row_dict:
                row_dict["row_id"] = row.row_id
                rows_out.append(row_dict)
                
        return rows_out

    def reconstruct_main_item_table(self) -> List[Dict[str, Any]]:
        """
        Applies conservative anchor-based reconstruction strictly on main_item_table.
        Implements PCodes, HSN, Net Amt right-hand anchoring, multiline description merging,
        and flags low-confidence values. Fulfills Requirement 5.
        """
        if not self.main_item_table:
            return []
            
        region = self.main_item_table
        cells_by_row = {}
        for cell in region.cells:
            cells_by_row.setdefault(cell.row_id, []).append(cell)
            
        # Sort visual rows sequentially top-to-bottom
        sorted_rows = sorted(region.rows, key=lambda r: r.geometry.min_y if r.geometry else 0)
        
        # 1. Identify visual header row
        header_row = None
        for r in sorted_rows:
            r_cells = cells_by_row.get(r.row_id, [])
            r_text = " ".join(c.text for c in r_cells if c.text).upper()
            if any(kw in r_text for kw in ("PCODE", "P CODE", "DESCRIPTION", "HSN", "MRP", "NET AMT", "NET AMOUNT")):
                header_row = r
                break
                
        if not header_row:
            header_row = sorted_rows[0]
            
        header_cells = cells_by_row.get(header_row.row_id, [])
        header_cells.sort(key=lambda c: c.geometry.min_x if c.geometry else 0)
        
        col_mapping = {}
        for c in header_cells:
            col_mapping[c.col_id] = c.text.strip() if c.text else f"col_{c.col_id}"
            
        log.info("main_item_table_headers", col_mapping=col_mapping)
        
        # Identify specific column semantic roles based on headers
        pcode_col_id = None
        desc_col_id = None
        hsn_col_id = None
        mrp_col_id = None
        qty_col_id = None
        rate_col_id = None
        net_amt_col_id = None
        
        for col_id, col_name in col_mapping.items():
            name_upper = col_name.upper()
            if any(term in name_upper for term in ("PCODE", "P CODE", "PRODUCT CODE", "CODE")):
                pcode_col_id = col_id
            elif any(term in name_upper for term in ("DESCRIPTION", "PRODUCT", "PARTICULARS", "ITEM")):
                desc_col_id = col_id
            elif "HSN" in name_upper:
                hsn_col_id = col_id
            elif "MRP" in name_upper:
                mrp_col_id = col_id
            elif any(term in name_upper for term in ("QTY", "QUANTITY", "PCS", "PACK")):
                qty_col_id = col_id
            elif any(term in name_upper for term in ("RATE", "PRICE", "UNIT RATE")):
                rate_col_id = col_id
            elif any(term in name_upper for term in ("NET AMT", "NET AMOUNT", "NET PAYABLE", "AMOUNT", "VALUE")):
                if "NET" in name_upper:
                    net_amt_col_id = col_id
                elif not net_amt_col_id:
                    net_amt_col_id = col_id
                    
        # Apply visual sorting fallback for indices if some headers were undersegmented or omitted
        cols_sorted = sorted(col_mapping.keys())
        if not pcode_col_id and len(cols_sorted) > 0:
            pcode_col_id = cols_sorted[0]
        if not desc_col_id and len(cols_sorted) > 1:
            desc_col_id = cols_sorted[1]
        if not hsn_col_id and len(cols_sorted) > 2:
            hsn_col_id = cols_sorted[2]
            
        item_rows_clean = []
        current_item = None
        
        # Exact regex compile for numeric/structural anchors
        pcode_pattern = re.compile(r"\b\d{7,9}\b")  # PCode 7-9 digit numeric
        hsn_pattern = re.compile(r"\b\d{6,8}\b")    # HSN 6-8 digit numeric
        price_pattern = re.compile(r"\b\d+[\.,]\d{2}\b")  # Decimal money anchors
        
        header_idx = sorted_rows.index(header_row)
        for r in sorted_rows[header_idx + 1:]:
            r_cells = cells_by_row.get(r.row_id, [])
            r_text = " ".join(c.text for c in r_cells if c.text).strip()
            if not r_text:
                continue
                
            # Perform anchor scan in cells
            has_pcode = False
            has_hsn = False
            has_net_amt = False
            
            pcode_val = ""
            hsn_val = ""
            net_amt_val = ""
            desc_val = ""
            qty_val = ""
            mrp_val = ""
            rate_val = ""
            
            cells_dict = {c.col_id: (c.text.strip() if c.text else "") for c in r_cells}
            
            for col_id, val in cells_dict.items():
                if pcode_pattern.search(val) and not has_pcode:
                    has_pcode = True
                    pcode_val = pcode_pattern.search(val).group(0)
                if hsn_pattern.search(val) and not has_hsn:
                    # Prevent matching the exact same token for PCode and HSN
                    if not (has_pcode and pcode_val == val):
                        has_hsn = True
                        hsn_val = hsn_pattern.search(val).group(0)
                if price_pattern.search(val) and col_id == net_amt_col_id:
                    has_net_amt = True
                    net_amt_val = price_pattern.search(val).group(0)
                    
            # Gather other cell columns
            desc_val = cells_dict.get(desc_col_id, "")
            qty_val = cells_dict.get(qty_col_id, "")
            mrp_val = cells_dict.get(mrp_col_id, "")
            rate_val = cells_dict.get(rate_col_id, "")
            
            if not net_amt_val:
                net_amt_val = cells_dict.get(net_amt_col_id, "")
                if price_pattern.search(net_amt_val):
                    has_net_amt = True
                    net_amt_val = price_pattern.search(net_amt_val).group(0)
                    
            # Define if this visual row represents a new Item Row Anchor
            is_anchor = False
            anchor_type = []
            
            if has_pcode:
                is_anchor = True
                anchor_type.append(f"pcode:{pcode_val}")
            if has_hsn:
                is_anchor = True
                anchor_type.append(f"hsn:{hsn_val}")
            if has_net_amt and desc_val and len(desc_val) > 3:
                is_anchor = True
                anchor_type.append(f"net_amt:{net_amt_val}")
            if getattr(r, "row_role", "") == "item_row" and desc_val and (qty_val or net_amt_val):
                is_anchor = True
                anchor_type.append("row_role_item")
                
            if is_anchor:
                # Perform strict validation of required fields
                low_confidence = False
                reasons = []
                
                # Attempt to extract missing values from unmapped parts of row text
                if not pcode_val:
                    pcode_search = pcode_pattern.search(r_text)
                    if pcode_search:
                        pcode_val = pcode_search.group(0)
                    else:
                        low_confidence = True
                        reasons.append("missing_pcode")
                if not hsn_val:
                    hsn_search = hsn_pattern.search(r_text)
                    if hsn_search:
                        hsn_val = hsn_search.group(0)
                    else:
                        low_confidence = True
                        reasons.append("missing_hsn")
                if not desc_val or len(desc_val) < 3:
                    low_confidence = True
                    reasons.append("empty_description")
                if not qty_val:
                    low_confidence = True
                    reasons.append("missing_qty")
                if not net_amt_val:
                    low_confidence = True
                    reasons.append("missing_net_amt")
                    
                current_item = {
                    "pcode": pcode_val,
                    "item_description": desc_val,
                    "hsn": hsn_val,
                    "mrp": mrp_val,
                    "qty": qty_val,
                    "rate": rate_val,
                    "net_amt": net_amt_val,
                    "low_confidence": low_confidence,
                    "confidence_reasons": reasons,
                    "visual_row_id": r.row_id
                }
                
                item_rows_clean.append(current_item)
                
                self.debug_output["item_row_anchor_debug"].append({
                    "row_id": r.row_id,
                    "is_anchor": True,
                    "anchors": anchor_type,
                    "item": current_item
                })
            else:
                # If not a new anchor, check if we can merge it as a multiline description continuation
                if current_item and desc_val and len(desc_val) > 0:
                    upper_desc = desc_val.upper()
                    # Prevent tax calculation/subtotals from leaking into descriptions
                    is_noise = any(term in upper_desc for term in ("TOTAL", "CGST", "SGST", "IGST", "ROUND OFF", "SUBTOTAL", "GRAND TOTAL"))
                    if not is_noise:
                        prev_desc = current_item["item_description"]
                        current_item["item_description"] = f"{prev_desc} {desc_val}".strip()
                        self.debug_output["item_row_anchor_debug"].append({
                            "row_id": r.row_id,
                            "is_anchor": False,
                            "action": f"merged into {current_item['visual_row_id']}",
                            "merged_text": desc_val
                        })
                    else:
                        self.debug_output["rejected_item_rows_with_reason"].append({
                            "row_id": r.row_id,
                            "text": r_text,
                            "reason": "contained noise/totals keyword"
                        })
                else:
                    self.debug_output["rejected_item_rows_with_reason"].append({
                        "row_id": r.row_id,
                        "text": r_text,
                        "reason": "no preceding parent item row anchor found to merge continuation"
                    })
                    
        return item_rows_clean

    def process(self) -> Dict[str, Any]:
        """
        Executes classification, routing, reconstruction, and dumps diagnostic verification files.
        """
        # 1. Classify table regions
        self.classify_all_regions()
        
        # 2. Extract tax summaries, scheme rows, and credit note rows
        tax_summary = self.reconstruct_generic_table(self.tax_summary_table) if self.tax_summary_table else []
        scheme_rows = self.reconstruct_generic_table(self.scheme_table) if self.scheme_table else []
        credit_note_rows = self.reconstruct_generic_table(self.credit_note_table) if self.credit_note_table else []
        
        # 3. Reconstruct item rows directly from raw OCR token coordinates.
        item_rows_clean = extract_item_rows_from_ocr_blocks(self.ocr_blocks, self.debug_output)
        
        # 4. Save item_rows_clean.json to file system for manual audit/verification (Requirement 8)
        debug_dir = "datasets/debug"
        os.makedirs(debug_dir, exist_ok=True)
        item_rows_path = os.path.join(debug_dir, "item_rows_clean.json")
        try:
            with open(item_rows_path, "w", encoding="utf-8") as f:
                json.dump(item_rows_clean, f, indent=2)
            log.info("saved_item_rows_clean_debug", path=item_rows_path)
            
            # Save a secondary copy directly to the workspace root for verification
            with open("item_rows_clean.json", "w", encoding="utf-8") as f:
                json.dump(item_rows_clean, f, indent=2)
            log.info("saved_item_rows_clean_root")
        except Exception as e:
            log.error("failed_saving_item_rows_clean", error=str(e))
            
        return {
            "tax_summary": tax_summary,
            "item_rows_clean": item_rows_clean,
            "scheme_rows": scheme_rows,
            "credit_note_rows": credit_note_rows,
            "debug": self.debug_output
        }
