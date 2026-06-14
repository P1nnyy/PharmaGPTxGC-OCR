import re
from typing import Any, Dict, List, Optional
from extraction.normalizers.canonical_invoice import CanonicalInvoice, CanonicalLineItem

def is_numeric(s: str) -> bool:
    """Checks if a stripped string is a valid integer or float."""
    # Remove a single decimal point and check if the remainder is digits
    return s.replace(".", "", 1).isdigit()

def clean_decimal_string(val: str) -> str:
    """
    Cleans up numeric strings from OCR and formatting variations:
    - Removes currency symbols ($, ₹).
    - Converts spaces between numbers (e.g. "52 53") to a dot (e.g. "52.53").
    - Handles commas: if a comma is followed by exactly two digits at the end of the string
      (e.g., "126,99"), treats the last comma as a decimal separator and replaces it with a dot,
      while removing any other commas. Otherwise, removes all commas as thousands separators.
    """
    s = val.strip()
    # Strip leading noise characters: |, :, ;, space
    while s and s[0] in ['|', ':', ';', ' ']:
        s = s[1:].strip()
    # Remove common currency symbols
    s = s.replace("$", "").replace("₹", "")
    
    # Check for space as dot separator (e.g., "52 53" -> "52.53")
    if re.match(r'^\d+ +\d+$', s):
        s = re.sub(r' +', '.', s)
        return s
        
    # Remove all other whitespace
    s = s.replace(" ", "")

    if "," in s:
        # Check if the last comma is followed by exactly two digits at the end
        if re.search(r',\d{2}$', s):
            r_idx = s.rfind(",")
            # Replace the last comma with a dot and remove all other commas
            s = s[:r_idx].replace(",", "") + "." + s[r_idx+1:]
        else:
            # Just remove commas as thousands separators (e.g., "1,269.90" -> "1269.90")
            s = s.replace(",", "")
            
    return s

def parse_decimal_safe(value: Any) -> Any:
    """
    Safely parses input to float or int after cleaning it.
    If parsing fails, returns the original stripped string.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        clean = clean_decimal_string(s)
        if "." in clean:
            return float(clean)
        return int(clean)
    except ValueError:
        return s

def try_parse_float(val: Any) -> Optional[float]:
    """Attempts to parse a float value, returning None if parsing fails."""
    if val is None:
        return None
    try:
        clean = clean_decimal_string(str(val))
        return float(clean)
    except ValueError:
        return None

def normalize_header(header_text: str) -> Optional[str]:
    """
    Normalizes Azure table header text to canonical column keys.
    Maps variations of common columns used in pharma invoices, supporting typos.
    """
    t = header_text.lower().strip()
    # Normalize multiple whitespaces to single space
    t = re.sub(r'\s+', ' ', t)
    
    # 1. Serial column mapping
    if t in ["51", "sl", "s1", "sr", "s.no", "s", "s.", "sr.", "sl."]:
        return "serial"
    
    # 2. Product code column mapping
    if t in ["pchde", "pcode", "product code", "item code"]:
        return "product_code"
    
    # 3. Product column mapping
    if t in ["product", "particulars", "item", "description", "product name", "item name", "tiem description", "product description"]:
        return "product"
    
    # 4. Pack column mapping
    if t in ["ufc", "uom", "unit", "pack", "packing", "pkg"]:
        return "pack"
    
    # 5. Quantity column mappings
    if t in ["total 0y", "total qy", "total qty"]:
        return "quantity_total"
    if t == "t'es":
        return "quantity_tes"
    if t in ["qty", "qty.", "quantity", "quant", "pes", "pcs", "pieces"]:
        return "quantity_pcs"
    
    # 5.5 Free Quantity column mapping
    if t in ["free", "free qty", "free quantity", "free.qty", "free.quantity"]:
        return "free_quantity"
    
    # 6. Batch column mapping
    if t in ["batch", "batch no", "batch no.", "batchno", "b.no", "b.no."]:
        return "batch"
    
    # 7. Expiry column mapping
    if t in ["exp", "expiry", "exp.", "exp date", "exp.date", "expiry date"]:
        return "expiry"
    
    # 8. HSN column mapping
    if t in ["hsn", "hsn code", "hsncode", "hsn/sac"]:
        return "hsn"
    
    # 9. MRP column mapping
    if t in ["mrp", "m.r.p.", "m.r.p"]:
        return "mrp"
    
    # 10. Rate column mapping
    if t in ["rate", "unit rate", "price", "unit price"]:
        return "rate"
        
    # 11. Gross amount column mapping
    if t in ["grass amt", "gross amt", "gross_amt"]:
        return "gross_amount"
        
    # 12. Discount column mappings
    if t == "sch amt":
        return "sch_amt"
    if t == "dise amt":
        return "dise_amt"
    if t in ["dis", "dis.", "disc", "disc.", "discount", "disc %", "discount %", "dis %", "disc amt", "discount amt"]:
        return "discount"
    
    # 13. GST percent column mappings
    if t in ["ott %", "gst %", "tax %"]:
        return "gst_percent"
    if "sgst" in t:
        if "amt" in t or "amount" in t:
            return "sgst_amount"
        return "sgst_percent"
    if "cgst" in t:
        if "amt" in t or "amount" in t or "ciget" in t:
            return "cgst_amount"
        return "cgst_percent"
    if "igst" in t:
        if "amt" in t or "amount" in t:
            return "igst_amount"
        return "igst_percent"
        
    # 14. CGST / SGST individual amount mappings
    if t in ["howwy ciget", "cgst amt", "ciget amt", "cgst amount"]:
        return "cgst_amount"
    if t in ["øget amt", "oget amt", "sgst amt", "sgst amount"]:
        return "sgst_amount"
    
    # 15. Amount / Net Amount mapping
    if t in ["net amt", "net amount", "amount", "amt", "amt.", "value", "total amount"]:
        return "amount"
        
    # 16. Taxable amount mapping
    if t in ["taxable amt", "trashle amt", "taxable amount"]:
        return "taxable_amount"
        
    return None

def normalize_header_row(header_row: List[str]) -> List[Optional[str]]:
    """
    Normalizes a complete row of table headers, handling duplicate columns
    like 'Value' in a context-aware way and cleaning up noise.
    """
    cleaned_full = []
    for cell in header_row:
        # Replace all whitespaces/newlines with single space
        full = re.sub(r'\s+', ' ', cell.lower().strip())
        cleaned_full.append(full)
        
    # Determine if there is any explicit amount column
    has_explicit_amount = False
    for cell in header_row:
        full = re.sub(r'\s+', ' ', cell.lower().strip())
        if full != "value":
            norm = normalize_header(full)
            if norm == "amount":
                has_explicit_amount = True
                break
                
    col_names = []
    for i, cell in enumerate(header_row):
        t = cleaned_full[i]
        
        # 1. Batch header cleanup
        if "batch" in t or t.startswith("batch") or t.startswith("b.no") or "b.no" in t:
            col_names.append("batch")
            continue
            
        # 2. Context-aware Value mapping
        if t == "value":
            mapped = None
            if i > 0:
                prev_t = cleaned_full[i-1]
                if "sgst" in prev_t:
                    mapped = "sgst_amount"
                elif "cgst" in prev_t:
                    mapped = "cgst_amount"
                elif "igst" in prev_t:
                    mapped = "igst_amount"
                elif any(term in prev_t for term in ["gst", "tax", "dis", "discount"]):
                    mapped = None
                    
            if mapped is None:
                if not has_explicit_amount:
                    mapped = "amount"
            col_names.append(mapped)
            continue
            
        # 3. Standard normalization using full cell content
        norm = normalize_header(cell)
        col_names.append(norm)
        
    return col_names

def extract_corrected_qty(qty_text: Optional[str], serial_text: Optional[str]) -> Optional[Any]:
    """
    Corrects issues where quantity and serial are merged or misaligned.
    - If qty has multiple lines, use the last numeric line.
    - If qty is empty but serial has multiple lines, use the last numeric line as qty.
    - Does not treat single-line serial numbers alone as quantity.
    """
    qty_str = qty_text.strip() if qty_text else ""
    serial_str = serial_text.strip() if serial_text else ""
    
    if qty_str:
        lines = [l.strip() for l in qty_str.split("\n") if l.strip()]
        if len(lines) > 1:
            for line in reversed(lines):
                clean = line.replace(",", "").replace(" ", "")
                if is_numeric(clean):
                    return parse_decimal_safe(clean)
            # Fallback to the whole string if no line was numeric
            return qty_str
        return parse_decimal_safe(qty_str)
        
    if serial_str:
        lines = [l.strip() for l in serial_str.split("\n") if l.strip()]
        if len(lines) > 1:
            for line in reversed(lines):
                clean = line.replace(",", "").replace(" ", "")
                if is_numeric(clean):
                    return parse_decimal_safe(clean)
                    
    return None

def extract_gst_percent(sgst_raw: Any, cgst_raw: Any, igst_raw: Any) -> Optional[float]:
    """Combines SGST and CGST percentages, or falls back to IGST percent."""
    sgst_val = try_parse_float(sgst_raw)
    cgst_val = try_parse_float(cgst_raw)
    igst_val = try_parse_float(igst_raw)
    
    if sgst_val is not None and cgst_val is not None:
        return sgst_val + cgst_val
    if igst_val is not None:
        return igst_val
    return None

def score_footer_table(grid: List[List[str]]) -> int:
    """
    Scores a grid based on matches with common invoice footer/totals labels.
    Helps locate the totals section of the invoice.
    """
    score = 0
    footer_keys = ["sub total", "subtotal", "grand total", "discount", "sgst", "cgst", "igst", "roundoff", "round off"]
    for row in grid:
        if len(row) >= 2:
            lbl = row[0].lower().strip()
            val = row[1].strip()
            # If the first column contains a footer key and second column has content
            if any(k in lbl for k in footer_keys) and val:
                score += 1
    return score

def parse_horizontal_summary_table(grid: List[List[str]]) -> Optional[Dict[str, float]]:
    """
    Parses horizontal totals summary grids (like CM Associates TABLE 2)
    where particulars, gross, discount, taxes, net are column headers.
    Locates the Total row and yields normalized totals.
    """
    if not grid or len(grid) < 2:
        return None
        
    # Scan for a header row containing at least two core totals columns
    header_idx = None
    target_terms = {"particulars", "gros ami", "gross amt", "sch amt", "trashle amt", "taxable amt", "net amt", "net payable"}
    
    for r_idx, row in enumerate(grid):
        match_count = 0
        for cell in row:
            c = cell.lower().strip()
            if any(term in c for term in target_terms):
                match_count += 1
        if match_count >= 2:
            header_idx = r_idx
            break
            
    if header_idx is None:
        return None
        
    # Locate the Total row underneath
    total_row_idx = None
    for r_idx in range(header_idx + 1, len(grid)):
        row = grid[r_idx]
        if row and row[0].lower().strip() == "total":
            total_row_idx = r_idx
            break
            
    if total_row_idx is None:
        # Fall back to the last row
        total_row_idx = len(grid) - 1
        
    header_row = grid[header_idx]
    total_row = grid[total_row_idx]
    
    res = {}
    gross_vals = []
    disc_vals = []
    taxable_vals = []
    tax_vals = []
    grand_total_vals = []
    
    for c_idx, cell in enumerate(header_row):
        if c_idx >= len(total_row):
            continue
        c = cell.lower().strip()
        val = try_parse_float(total_row[c_idx])
        if val is None:
            continue
            
        if "gros" in c or "gross" in c:
            gross_vals.append(val)
        elif "sch amt" in c or "oth disc" in c or "discount" in c or "disc amt" in c:
            disc_vals.append(val)
        elif "trashle" in c or "taxable" in c:
            taxable_vals.append(val)
        elif "the amt" in c or "tax amt" in c or "total tax" in c:
            tax_vals.append(val)
        elif "net payable" in c:
            grand_total_vals.insert(0, val) # net payable has priority over net amt
        elif "net amt" in c or "net amount" in c:
            grand_total_vals.append(val)
            
    if gross_vals:
        res["subtotal"] = gross_vals[0]
    if disc_vals:
        res["discount"] = sum(disc_vals)
    if taxable_vals:
        res["taxable_amount"] = taxable_vals[0]
    if tax_vals:
        res["total_tax"] = tax_vals[0]
    if grand_total_vals:
        res["grand_total"] = grand_total_vals[0]
        
    return res

def extract_field_value(fields: dict, keys: List[str]) -> Any:
    """
    Retrieves a field value from Azure document field definitions.
    Supports dictionary values with standard serialization keys (camelCase/snake_case)
    as well as object attributes.
    """
    for key in keys:
        field = fields.get(key)
        if not field:
            continue
        if isinstance(field, dict):
            for value_key in ["value", "valueString", "value_string", "valueDate", "value_date", "valueFloat", "value_float", "valueNumber", "value_number", "content"]:
                if value_key in field and field[value_key] is not None:
                    return field[value_key]
        else:
            for attr in ["value", "content"]:
                if hasattr(field, attr):
                    val = getattr(field, attr)
                    if val is not None:
                        return val
    return None

def build_grid(table: dict) -> List[List[str]]:
    """Converts sparse Azure table cells into a dense 2D string grid."""
    row_count = table.get("rowCount")
    col_count = table.get("columnCount")
    cells = table.get("cells", [])
    
    if not row_count or not col_count:
        if cells:
            row_count = max(cell.get("rowIndex", 0) for cell in cells) + 1
            col_count = max(cell.get("columnIndex", 0) for cell in cells) + 1
        else:
            return []
            
    grid = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in cells:
        r = cell.get("rowIndex", 0)
        c = cell.get("columnIndex", 0)
        content = cell.get("content", "")
        if 0 <= r < row_count and 0 <= c < col_count:
            grid[r][c] = content
            
    return grid

def is_footer_row(row: List[str]) -> bool:
    """Determines if a table row contains subtotal or grand total terms."""
    footer_keywords = ["sub total", "subtotal", "grand total", "net amount", "net payable", "payable amount", "total amt", "total payable", "net amt", "bill amount", "cr/dr note", "roundoff", "round off"]
    for cell in row:
        cell_lower = cell.lower().strip()
        if any(fw in cell_lower for fw in footer_keywords):
            return True
    return False

def normalize_azure_invoice(raw_result: dict) -> CanonicalInvoice:
    """
    Normalizes a raw Azure Document Intelligence analysis response into CanonicalInvoice format.
    Uses the table extraction grid to retrieve pharmaceutical line items instead of standard fields.
    """
    warnings = []
    tables = raw_result.get("tables", [])
    documents = raw_result.get("documents", [])
    
    # 1. Parse all tables into grids
    grids = [build_grid(table) for table in tables]
    
    # 2. Select the item table
    selected_item_table_idx = None
    selected_header_row_idx = None
    max_item_score = -1
    
    # Target headers criteria for item table detection (matches various typos / variations)
    detection_target_headers = {
        "product", "batch", "expiry", "hsn", "mrp", "rate", "amount", 
        "quantity_total", "quantity_tes", "quantity_pcs", "quantity",
        "taxable_amount", "gross_amount"
    }
    
    for table_idx, grid in enumerate(grids):
        # Scan each row in the grid as a candidate header row
        for row_idx, row in enumerate(grid):
            # Score this row based on matching core columns
            score = sum(1 for cell in row if normalize_header(cell) in detection_target_headers)
            if score > max_item_score:
                max_item_score = score
                selected_item_table_idx = table_idx
                selected_header_row_idx = row_idx
                
    # We require a baseline matching score of at least 3 to confirm it's an item table
    if selected_item_table_idx is None or max_item_score < 3:
        selected_item_table_idx = None
        selected_header_row_idx = None
        warnings.append("No valid line item table found based on column headers classification.")
        
    # 3. Select the footer table
    selected_footer_table_idx = None
    max_footer_score = -1
    is_footer_horizontal = False
    horizontal_footer_data = None
    
    for table_idx, grid in enumerate(grids):
        # We don't want the same table to be both item and footer unless it's the only table
        if table_idx == selected_item_table_idx and len(grids) > 1:
            continue
            
        # Try parsing as horizontal summary table first (like CM Associates TABLE 2)
        h_data = parse_horizontal_summary_table(grid)
        if h_data:
            selected_footer_table_idx = table_idx
            is_footer_horizontal = True
            horizontal_footer_data = h_data
            break
            
        score = score_footer_table(grid)
        if score > max_footer_score:
            max_footer_score = score
            selected_footer_table_idx = table_idx
            is_footer_horizontal = False
            
    if selected_footer_table_idx is None:
        warnings.append("No separate footer table identified.")
        
    # 4. Extract footer data
    footer_data = {}
    if selected_footer_table_idx is not None:
        if is_footer_horizontal and horizontal_footer_data:
            footer_data = horizontal_footer_data
        else:
            footer_grid = grids[selected_footer_table_idx]
            for row in footer_grid:
                if len(row) < 2:
                    continue
                lbl = row[0].lower().strip()
                # Find the value column (typically column 1, but check subsequent if empty)
                val_str = row[1].strip()
                if not val_str and len(row) > 2:
                    for col_val in row[2:]:
                        if col_val.strip():
                            val_str = col_val.strip()
                            break
                
                val = try_parse_float(val_str)
                if "sub total" in lbl or "subtotal" in lbl:
                    footer_data["subtotal"] = val
                elif "discount" in lbl:
                    footer_data["discount"] = val
                elif "sgst" in lbl:
                    footer_data["sgst"] = val
                elif "cgst" in lbl:
                    footer_data["cgst"] = val
                elif "igst" in lbl:
                    footer_data["igst"] = val
                elif any(x in lbl for x in ["grand total", "net total", "payable amount", "total payable", "net amt", "bill amount"]):
                    footer_data["grand_total"] = val
                elif "round" in lbl:
                    footer_data["roundoff"] = val

    # 5. Extract document header fields
    doc = documents[0] if documents else {}
    fields = doc.get("fields", {})
    
    invoice_number = extract_field_value(fields, ["InvoiceId", "InvoiceNumber"])
    invoice_date = extract_field_value(fields, ["InvoiceDate"])
    seller_name = extract_field_value(fields, ["VendorName"])
    buyer_name = extract_field_value(fields, ["CustomerName"])
    
    doc_subtotal = try_parse_float(extract_field_value(fields, ["SubTotal"]))
    doc_grand_total = try_parse_float(extract_field_value(fields, ["InvoiceTotal"]))
    doc_tax = try_parse_float(extract_field_value(fields, ["TotalTax", "Tax"]))
    
    # Extracted CGST / SGST individual amount values from item table total row (e.g. Table 3 row 7)
    item_table_cgst = None
    item_table_sgst = None
    
    # 6. Parse line items from selected item table
    line_items = []
    if selected_item_table_idx is not None:
        item_grid = grids[selected_item_table_idx]
        header_row = item_grid[selected_header_row_idx]
        col_names = normalize_header_row(header_row)
        
        for r_idx in range(selected_header_row_idx + 1, len(item_grid)):
            row = item_grid[r_idx]
            
            # Check if this row is the Total row of the item table
            is_item_total_row = (row and row[0].lower().strip() == "total") or (len(row) > 2 and row[2].lower().strip() == "total")
            
            # Skip rows containing footer content unless it is the total row we want to inspect for taxes
            if is_footer_row(row) and not is_item_total_row:
                continue
                
            row_data = {}
            for c_idx, val in enumerate(row):
                if c_idx < len(col_names):
                    col_name = col_names[c_idx]
                    if col_name:
                        # Store cell value (use first non-empty value if duplicate column mappings exist)
                        if col_name not in row_data or not row_data[col_name]:
                            row_data[col_name] = val
                            
            product_val = row_data.get("product", "").strip()
            
            # If it is the total row, extract CGST and SGST amount values and skip item conversion
            if is_item_total_row or product_val.lower().strip() == "total":
                for c_idx, val in enumerate(row):
                    if c_idx < len(col_names):
                        col_name = col_names[c_idx]
                        if col_name == "cgst_amount":
                            item_table_cgst = try_parse_float(val)
                        elif col_name == "sgst_amount":
                            item_table_sgst = try_parse_float(val)
                continue
                
            batch_val = row_data.get("batch", "").strip()
            amount_val = row_data.get("amount", "").strip()
            taxable_amount_val = row_data.get("taxable_amount", "").strip()
            
            if not (product_val or batch_val or amount_val or taxable_amount_val):
                continue
                
            # Quantity extraction prioritizes Total 0y, then t'es, then standard qty column
            qty_total = row_data.get("quantity_total")
            qty_tes = row_data.get("quantity_tes")
            qty_pcs = row_data.get("quantity_pcs")
            qty_raw = row_data.get("quantity")
            serial_raw = row_data.get("serial")
            
            quantity = None
            if qty_total is not None and qty_total.strip():
                quantity = extract_corrected_qty(qty_total, serial_raw)
            elif qty_tes is not None and qty_tes.strip():
                quantity = extract_corrected_qty(qty_tes, serial_raw)
            elif qty_pcs is not None and qty_pcs.strip():
                quantity = extract_corrected_qty(qty_pcs, serial_raw)
            else:
                quantity = extract_corrected_qty(qty_raw, serial_raw)
                
            # Discount extraction adds SCH Amt and Dise Amt if both are present
            sch_val = try_parse_float(row_data.get("sch_amt"))
            dise_val = try_parse_float(row_data.get("dise_amt"))
            discount_val = None
            if sch_val is not None and dise_val is not None:
                discount_val = sch_val + dise_val
            elif sch_val is not None:
                discount_val = sch_val
            elif dise_val is not None:
                discount_val = dise_val
            else:
                discount_val = parse_decimal_safe(row_data.get("discount"))
                
            # GST percent
            gst_percent_raw = row_data.get("gst_percent")
            gst_percent = try_parse_float(gst_percent_raw)
            if gst_percent is None:
                gst_percent = extract_gst_percent(
                    row_data.get("sgst_percent"),
                    row_data.get("cgst_percent"),
                    row_data.get("igst_percent")
                )
                
            # Amount fallback to taxable_amount if net amt (amount) is missing
            amount_raw = row_data.get("amount")
            if amount_raw is None or not str(amount_raw).strip():
                amount_raw = row_data.get("taxable_amount")
            amount = parse_decimal_safe(amount_raw)
            
            # Clean up newlines in product name to standard spaces
            product_name = product_val.replace("\n", " ").strip() if product_val else None
            
            item = CanonicalLineItem(
                name=product_name,
                pack=row_data.get("pack") if row_data.get("pack") else None,
                batch=batch_val if batch_val else None,
                expiry=row_data.get("expiry") if row_data.get("expiry") else None,
                hsn=row_data.get("hsn") if row_data.get("hsn") else None,
                quantity=quantity,
                free_quantity=parse_decimal_safe(row_data.get("free_quantity")),
                mrp=parse_decimal_safe(row_data.get("mrp")),
                rate=parse_decimal_safe(row_data.get("rate")),
                discount=discount_val,
                gst_percent=gst_percent,
                amount=amount,
                confidence=None
            )
            line_items.append(item)
            
    # 7. Merge header fields (footer data takes precedence for totals)
    subtotal = footer_data.get("subtotal") if footer_data.get("subtotal") is not None else doc_subtotal
    discount = footer_data.get("discount")
    if discount is None:
        discount = footer_data.get("discount")
        
    cgst = footer_data.get("cgst")
    sgst = footer_data.get("sgst")
    igst = footer_data.get("igst")
    grand_total = footer_data.get("grand_total") if footer_data.get("grand_total") is not None else doc_grand_total
    
    # Fallback to item table total row tax amounts if summary totals did not provide CGST/SGST explicitly
    if cgst is None and item_table_cgst is not None:
        cgst = item_table_cgst
    if sgst is None and item_table_sgst is not None:
        sgst = item_table_sgst
        
    # 8. Calculate extraction confidence
    item_table_found = (selected_item_table_idx is not None)
    has_line_items = (len(line_items) > 0)
    has_grand_total = (grand_total is not None)
    has_header_totals = (
        invoice_number is not None or 
        invoice_date is not None or 
        seller_name is not None or 
        subtotal is not None or 
        grand_total is not None
    )
    
    if item_table_found and has_line_items and has_grand_total:
        confidence = 0.85
    elif has_header_totals:
        confidence = 0.65
    else:
        confidence = 0.40
        
    # 9. Populate metadata
    raw_engine_metadata = {
        "model_id": raw_result.get("modelId"),
        "table_count": len(tables),
        "document_count": len(documents),
        "selected_item_table_index": selected_item_table_idx,
        "selected_footer_table_index": selected_footer_table_idx,
        "item_table_row_count": len(grids[selected_item_table_idx]) if selected_item_table_idx is not None else 0,
        "item_table_column_count": len(grids[selected_item_table_idx][0]) if selected_item_table_idx is not None and len(grids[selected_item_table_idx]) > 0 else 0,
        "warnings": warnings,
        "doc_fields_tax": doc_tax
    }
    
    # Add optional keys if horizontal table parsed them
    if "taxable_amount" in footer_data:
        raw_engine_metadata["taxable_amount"] = footer_data["taxable_amount"]
    if "total_tax" in footer_data:
        raw_engine_metadata["total_tax"] = footer_data["total_tax"]
    if "roundoff" in footer_data:
        raw_engine_metadata["roundoff"] = footer_data["roundoff"]
        
    return CanonicalInvoice(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        seller_name=seller_name,
        buyer_name=buyer_name,
        subtotal=subtotal,
        discount=discount,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        grand_total=grand_total,
        line_items=line_items,
        confidence=confidence,
        extraction_engine="azure_document_intelligence",
        raw_engine_metadata=raw_engine_metadata
    )
