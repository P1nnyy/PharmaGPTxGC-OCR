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
from typing import List, Dict, Any, Tuple
from models.layout_models import TableRegion, TableCell, RowRegion, OCRBlock

log = structlog.get_logger()

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
        
        # 3. Only run anchor-based item row reconstruction on main_item_table
        item_rows_clean = self.reconstruct_main_item_table()
        
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
