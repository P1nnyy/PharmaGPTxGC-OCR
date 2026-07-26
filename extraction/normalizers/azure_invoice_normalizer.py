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

def parse_split_quantity(value: Any) -> Optional[Dict[str, float]]:
    """
    Parses same-cell billed/free quantity expressions such as "2.75 + .25".
    Only accepts an explicit plus sign between two numeric values.
    """
    if value is None:
        return None

    text = str(value).strip()
    if not text or "+" not in text:
        return None

    normalized = re.sub(r'\s+', ' ', text)
    number_pattern = r'(?:\d+(?:[.,]\d+)?|[.,]\d+)'
    match = re.match(
        rf'^[^\d.,]*({number_pattern})\s*\+\s*({number_pattern})[^\d.,]*$',
        normalized
    )
    if not match:
        return None

    billed_qty = try_parse_float(match.group(1))
    free_qty = try_parse_float(match.group(2))
    if billed_qty is None or free_qty is None:
        return None

    return {
        "quantity": billed_qty,
        "free_quantity": free_qty,
    }

def is_discount_label(label: str) -> bool:
    """Detects footer/header discount aliases without treating unrelated text as discount."""
    normalized = re.sub(r'[^a-z0-9]+', ' ', label.lower()).strip()
    aliases = {
        "dis amt",
        "disc amt",
        "discount",
        "discount amt",
        "scheme discount",
        "sch discount",
        "oth disc amt",
    }
    if normalized in aliases:
        return True
    return "discount" in normalized or normalized.startswith("disc ") or normalized.startswith("dis ")

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
    if t in ["qty", "qty.", "quantity", "quant", "pes", "pcs", "pieces", "bill qty", "billed qty", "sale qty", "sold qty"]:
        return "quantity_pcs"
    
    # 5.5 Free Quantity column mapping
    if t in ["free", "free qty", "free quantity", "free.qty", "free.quantity", "f.qty", "f qty", "scheme qty", "sch qty", "bonus qty", "fr", "foc"]:
        return "free_quantity"
    
    # 6. Batch column mapping
    if t in ["batch", "batch no", "batch no.", "batchno", "b.no", "b.no."]:
        return "batch"
    
    # 7. Expiry column mapping
    if t in ["exp", "expiry", "exp.", "exp date", "exp.date", "expiry date", "exp dt", "exp.dt", "exp dt.", "expdt", "exp dt/mfg dt"]:
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
    if t in ["dis", "dis.", "disc", "disc.", "dise", "discount", "disc %", "discount %", "dis %", "dis amt", "disc amt", "discount amt", "scheme discount", "sch discount", "oth disc amt"]:
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
    if t in ["net amt", "net amount", "amount", "amt", "amt.", "value", "total", "total amount"]:
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
        
    # Determine if there is any free quantity column
    has_free_column = False
    for cell in header_row:
        full = re.sub(r'\s+', ' ', cell.lower().strip())
        norm = normalize_header(full)
        if norm == "free_quantity":
            has_free_column = True
            break
            
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
        
        # 1. Batch header cleanup (also matches "Hatch", a common OCR misread of "Batch")
        if "batch" in t or t.startswith("batch") or t.startswith("b.no") or "b.no" in t or t == "hatch":
            col_names.append("batch")
            continue
            
        # 1.5 Total Qty conditional mapping
        if t in ["total qty", "total qty.", "total quantity"]:
            if has_free_column:
                col_names.append("quantity_total")
            else:
                col_names.append("quantity_pcs")
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

    # 4. Positional fallback for a garbled Qty header (e.g. OCR mangles "Qty"
    # into something like "(1)"). On Indian pharma invoices the Qty column is
    # reliably immediately left of MRP; if that slot has real (non-empty) but
    # unrecognized header text and no quantity column was already found
    # elsewhere, treat it as quantity.
    qty_keys = {"quantity", "quantity_pcs", "quantity_total", "quantity_tes"}
    if not any(name in qty_keys for name in col_names):
        try:
            mrp_idx = col_names.index("mrp")
        except ValueError:
            mrp_idx = -1
        if mrp_idx > 0 and col_names[mrp_idx - 1] is None and cleaned_full[mrp_idx - 1].strip():
            col_names[mrp_idx - 1] = "quantity_pcs"

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
    footer_keys = ["sub total", "subtotal", "grand total", "discount", "disc amt", "dis amt", "sgst", "cgst", "igst", "roundoff", "round off"]
    for row in grid:
        if len(row) >= 2:
            lbl = row[0].lower().strip()
            val = row[1].strip()
            # If the first column contains a footer key and second column has content
            if (any(k in lbl for k in footer_keys) or is_discount_label(lbl)) and val:
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
    target_terms = {"particulars", "gros ami", "gross amt", "sch amt", "dis amt", "disc amt", "oth disc amt", "discount", "trashle amt", "taxable amt", "net amt", "net payable"}
    
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
        elif "sch amt" in c or "oth disc" in c or is_discount_label(c):
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
    pages = raw_result.get("pages", [])
    page_w = 1.0
    page_h = 1.0
    if pages:
        p_obj = pages[0]
        page_w = float(p_obj.get("width", 1.0) if isinstance(p_obj, dict) else getattr(p_obj, "width", 1.0)) or 1.0
        page_h = float(p_obj.get("height", 1.0) if isinstance(p_obj, dict) else getattr(p_obj, "height", 1.0)) or 1.0
    
    # 1. Parse all tables into grids
    grids = [build_grid(table) for table in tables]
    
    # 2. Select item tables (supports multi-page / multi-table split invoices)
    item_table_candidates = []
    detection_target_headers = {
        "product", "batch", "expiry", "hsn", "mrp", "rate", "amount", 
        "quantity_total", "quantity_tes", "quantity_pcs", "quantity",
        "taxable_amount", "gross_amount"
    }
    
    all_scored_tables = []
    for table_idx, grid in enumerate(grids):
        best_row_idx = None
        best_score = -1
        best_headers = []
        for row_idx, row in enumerate(grid[:3]):
            headers = normalize_header_row(row)
            score = sum(1 for norm in headers if norm in detection_target_headers)
            if score > best_score:
                best_score = score
                best_row_idx = row_idx
                best_headers = headers
                
        if best_score >= 2 and best_row_idx is not None:
            all_scored_tables.append((table_idx, best_row_idx, best_score, best_headers))
            
    if all_scored_tables:
        all_scored_tables.sort(key=lambda x: x[2], reverse=True)
        primary_idx, primary_row, primary_score, primary_headers = all_scored_tables[0]
        primary_set = set(h for h in primary_headers if h)
        item_table_candidates.append((primary_idx, primary_row, primary_score))
        
        for (tbl_idx, r_idx, score, headers) in all_scored_tables[1:]:
            col_set = set(h for h in headers if h)
            overlap = len(col_set & primary_set)
            if score >= 2 and overlap >= 2 and abs(len(headers) - len(primary_headers)) <= 2:
                item_table_candidates.append((tbl_idx, r_idx, score))
            
    selected_item_table_indices = [c[0] for c in item_table_candidates]
    selected_item_table_idx = selected_item_table_indices[0] if selected_item_table_indices else None
    
    if not item_table_candidates:
        warnings.append("No valid line item table found based on column headers classification.")
        
    # 3. Select the footer table
    selected_footer_table_idx = None
    max_footer_score = -1
    is_footer_horizontal = False
    horizontal_footer_data = None
    
    for table_idx, grid in enumerate(grids):
        # We don't want the same table to be both item and footer unless no other tables exist
        if table_idx in selected_item_table_indices and len(grids) > len(selected_item_table_indices):
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
                if any(k in lbl for k in ["sub total", "subtotal", "taxable amount", "taxable value", "taxable total", "net taxable", "gross total", "gross amount", "amount before tax", "total before tax", "basic amount", "basic value", "item total"]):
                    footer_data["subtotal"] = val
                elif is_discount_label(lbl):
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
    
    # Extended metadata fields: GST, address, phone, drug license
    seller_gstin = extract_field_value(fields, ["VendorTaxId", "VendorGSTIN"])
    buyer_gstin = extract_field_value(fields, ["CustomerTaxId", "CustomerGSTIN"])
    seller_address = extract_field_value(fields, ["VendorAddress"])
    buyer_address = extract_field_value(fields, ["CustomerAddress"])
    seller_phone = extract_field_value(fields, ["VendorPhone", "VendorTelephone"])
    drug_license = extract_field_value(fields, ["DrugLicenseNumber", "DrugLicense", "DLNumber"])
    
    # Stringify address objects (Azure may return structured dicts with city/state/etc.)
    if isinstance(seller_address, dict):
        parts = [seller_address.get(k, "") for k in ["streetAddress", "city", "state", "postalCode"] if seller_address.get(k)]
        seller_address = ", ".join(parts) if parts else str(seller_address)
    if isinstance(buyer_address, dict):
        parts = [buyer_address.get(k, "") for k in ["streetAddress", "city", "state", "postalCode"] if buyer_address.get(k)]
        buyer_address = ", ".join(parts) if parts else str(buyer_address)
    
    # Regex fallback against document content if standard Azure fields missed metadata
    raw_content = raw_result.get("content", "")
    if raw_content:
        import re
        if not seller_phone:
            phone_match = re.search(r'(?:PHONE|Phone|Ph\.?|Mob\.?|Mobile|Contact)[\s\:\.\-]*([0-9\-\,\ ]{8,})', raw_content, re.IGNORECASE)
            if phone_match:
                seller_phone = phone_match.group(1).split('\n')[0].strip()
        if not drug_license:
            dl_match = re.search(r'(?:Licence\s*No\.?|D\.?L\.?\s*No\.?|20B|21B)[\s\:\.\-]*([0-9A-Z\-\,\/ ]+)', raw_content, re.IGNORECASE)
            if dl_match:
                drug_license = dl_match.group(1).split('\n')[0].strip()
        if not seller_gstin or not buyer_gstin:
            gstin_matches = re.findall(r'\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b', raw_content)
            if gstin_matches:
                if not seller_gstin and len(gstin_matches) > 0:
                    seller_gstin = gstin_matches[0]
                if not buyer_gstin and len(gstin_matches) > 1:
                    buyer_gstin = gstin_matches[1]
        if not buyer_address and buyer_name:
            lines = [l.strip() for l in raw_content.split('\n') if l.strip()]
            for idx, l in enumerate(lines):
                if buyer_name.lower() in l.lower() and idx + 1 < len(lines):
                    addr_lines = lines[idx+1:min(idx+4, len(lines))]
                    clean_addr = [al for al in addr_lines if not any(kw in al.lower() for kw in ['gstin', 'licence', 'phone', 'ack no', 'date', 'invoice'])]
                    if clean_addr:
                        buyer_address = ", ".join(clean_addr)
                    break
    
    doc_subtotal = try_parse_float(extract_field_value(fields, ["SubTotal", "TaxableAmount", "TotalTaxableValue", "AmountBeforeTax", "NetTaxable", "GrossTotal"]))
    doc_grand_total = try_parse_float(extract_field_value(fields, ["InvoiceTotal"]))
    doc_tax = try_parse_float(extract_field_value(fields, ["TotalTax", "Tax"]))
    
    # Extracted CGST / SGST individual amount values from item table total row (e.g. Table 3 row 7)
    item_table_cgst = None
    item_table_sgst = None
    
    # 6. Parse line items from all selected item tables (multi-page/multi-table support)
    line_items = []
    for (tbl_idx, hdr_idx, _) in item_table_candidates:
        item_grid = grids[tbl_idx]
        header_row = item_grid[hdr_idx]
        col_names = normalize_header_row(header_row)
        table_items = []

        for r_idx in range(hdr_idx + 1, len(item_grid)):
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
            
            # Determine if free quantity column has value in row_data
            has_free_in_row = "free_quantity" in row_data and row_data["free_quantity"] is not None and str(row_data["free_quantity"]).strip() != ""
            
            quantity = None
            free_quantity = None
            split_qty = None
            for qty_candidate in [qty_pcs, qty_raw, qty_total, qty_tes]:
                split_qty = parse_split_quantity(qty_candidate)
                if split_qty:
                    break

            if split_qty:
                quantity = split_qty["quantity"]
                free_quantity = split_qty["free_quantity"]
            else:
                if has_free_in_row:
                    # Prioritize standard billed/pcs qty column over combined/total qty column
                    if qty_pcs is not None and qty_pcs.strip():
                        quantity = extract_corrected_qty(qty_pcs, serial_raw)
                    elif qty_raw is not None and qty_raw.strip():
                        quantity = extract_corrected_qty(qty_raw, serial_raw)
                    elif qty_total is not None and qty_total.strip():
                        quantity = extract_corrected_qty(qty_total, serial_raw)
                else:
                    # Standard prioritization
                    if qty_total is not None and qty_total.strip():
                        quantity = extract_corrected_qty(qty_total, serial_raw)
                    elif qty_tes is not None and qty_tes.strip():
                        quantity = extract_corrected_qty(qty_tes, serial_raw)
                    elif qty_pcs is not None and qty_pcs.strip():
                        quantity = extract_corrected_qty(qty_pcs, serial_raw)
                    else:
                        quantity = extract_corrected_qty(qty_raw, serial_raw)

                free_quantity = parse_decimal_safe(row_data.get("free_quantity"))
                
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
            
            # Calculate bounding box for the row from raw table cells
            row_bbox = None
            if tbl_idx < len(tables):
                t_obj = tables[tbl_idx]
                t_cells = t_obj.get("cells", []) if isinstance(t_obj, dict) else getattr(t_obj, "cells", [])
                xs, ys = [], []
                for cell in t_cells:
                    c_row = cell.get("rowIndex") if isinstance(cell, dict) else getattr(cell, "rowIndex", -1)
                    if c_row == r_idx:
                        regions = cell.get("boundingRegions", []) if isinstance(cell, dict) else getattr(cell, "boundingRegions", [])
                        for reg in regions:
                            poly = reg.get("polygon", []) if isinstance(reg, dict) else getattr(reg, "polygon", [])
                            if len(poly) >= 8:
                                xs.extend(poly[0::2])
                                ys.extend(poly[1::2])
                if xs and ys:
                    min_x, max_x = min(xs) / page_w, max(xs) / page_w
                    min_y, max_y = min(ys) / page_h, max(ys) / page_h
                    row_bbox = [round(min_x, 4), round(min_y, 4), round(max_x, 4), round(max_y, 4)]
            
            item = CanonicalLineItem(
                name=product_name,
                pack=row_data.get("pack") if row_data.get("pack") else None,
                batch=batch_val if batch_val else None,
                expiry=row_data.get("expiry") if row_data.get("expiry") else None,
                hsn=row_data.get("hsn") if row_data.get("hsn") else None,
                quantity=quantity,
                free_quantity=free_quantity,
                mrp=parse_decimal_safe(row_data.get("mrp")),
                rate=parse_decimal_safe(row_data.get("rate")),
                discount=discount_val,
                gst_percent=gst_percent,
                amount=amount,
                confidence=None,
                bounding_box=row_bbox
            )
            table_items.append(item)

        # Azure occasionally assigns a stray footnote/formula fragment a rowIndex
        # that lands it mid-table; re-sort this table's rows by actual vertical
        # position so the review screen matches the printed invoice order.
        if all(it.bounding_box for it in table_items):
            table_items.sort(key=lambda it: it.bounding_box[1])
        line_items.extend(table_items)

    # Fallback to Azure prebuilt document Items if custom table parsing returned 0 line items
    if not line_items and fields:
        items_field = fields.get("Items", {})
        items_arr = items_field.get("valueArray", []) if isinstance(items_field, dict) else []
        for it in items_arr:
            val_obj = it.get("valueObject", {}) if isinstance(it, dict) else {}
            if not val_obj:
                continue
            desc_val = extract_field_value(val_obj, ["Description", "ProductCode"])
            if desc_val:
                line_items.append(CanonicalLineItem(
                    name=str(desc_val),
                    batch=extract_field_value(val_obj, ["Batch"]),
                    hsn=extract_field_value(val_obj, ["TaxCode", "HSNCode"]),
                    quantity=try_parse_float(extract_field_value(val_obj, ["Quantity"])),
                    mrp=parse_decimal_safe(extract_field_value(val_obj, ["UnitPrice"])),
                    rate=parse_decimal_safe(extract_field_value(val_obj, ["UnitPrice"])),
                    amount=parse_decimal_safe(extract_field_value(val_obj, ["Amount"])),
                    confidence=None
                ))

    # 7. Merge header fields (footer data takes precedence for totals)
    subtotal = footer_data.get("subtotal") if footer_data.get("subtotal") is not None else doc_subtotal
    discount = footer_data.get("discount")
    cgst = footer_data.get("cgst")
    sgst = footer_data.get("sgst")
    igst = footer_data.get("igst")
    grand_total = footer_data.get("grand_total") if footer_data.get("grand_total") is not None else doc_grand_total
    
    # Smart fallback for subtotal if not explicitly extracted by OCR
    if subtotal is None:
        line_amounts = [item.amount for item in line_items if item.amount is not None]
        if line_amounts:
            subtotal = round(sum(line_amounts), 2)
        elif grand_total is not None:
            tax_sum = (cgst or 0.0) + (sgst or 0.0) + (igst or 0.0)
            subtotal = round(grand_total + (discount or 0.0) - tax_sum, 2)
    
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
        
    # 8.5 Extract page rotation angle from Azure's pages array
    # Azure returns pages[].angle in degrees (counter-clockwise from horizontal)
    page_angle = None
    if pages:
        raw_angle = pages[0].get("angle") if isinstance(pages[0], dict) else getattr(pages[0], "angle", None)
        if raw_angle is not None:
            try:
                page_angle = float(raw_angle)
            except (ValueError, TypeError):
                pass
    
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
        "doc_fields_tax": doc_tax,
        "page_angle": page_angle
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
        seller_gstin=str(seller_gstin) if seller_gstin else None,
        buyer_gstin=str(buyer_gstin) if buyer_gstin else None,
        seller_address=str(seller_address) if seller_address else None,
        buyer_address=str(buyer_address) if buyer_address else None,
        seller_phone=str(seller_phone) if seller_phone else None,
        drug_license=str(drug_license) if drug_license else None,
        subtotal=subtotal,
        discount=discount,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        grand_total=grand_total,
        line_items=line_items,
        confidence=confidence,
        extraction_engine="azure_document_intelligence",
        raw_engine_metadata=raw_engine_metadata,
        page_angle=page_angle
    )
