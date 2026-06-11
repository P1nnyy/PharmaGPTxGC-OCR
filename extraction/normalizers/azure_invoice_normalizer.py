import re
from typing import Any, Dict, List, Optional
from extraction.normalizers.canonical_invoice import CanonicalInvoice, CanonicalLineItem

def is_numeric(s: str) -> bool:
    """Checks if a stripped string is a valid integer or float."""
    # Remove a single decimal point and check if the remainder is digits
    return s.replace(".", "", 1).isdigit()

def parse_decimal_safe(value: Any) -> Any:
    """
    Safely parses input to float or int.
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
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s

def try_parse_float(val: Any) -> Optional[float]:
    """Attempts to parse a float value, returning None if parsing fails."""
    if val is None:
        return None
    try:
        # Strip common currency symbols, commas, and whitespace
        clean = str(val).replace(",", "").replace("$", "").replace("₹", "").strip()
        return float(clean)
    except ValueError:
        return None

def normalize_header(header_text: str) -> Optional[str]:
    """
    Normalizes Azure table header text to canonical column keys.
    Maps variations of common columns used in pharma invoices.
    """
    t = header_text.lower().strip()
    
    # 1. Serial column mapping
    if t in ["s", "s.", "sr", "sr.", "sl", "sl."]:
        return "serial"
    
    # 2. Quantity column mapping
    if t in ["qty", "qty.", "quantity", "quant"]:
        return "quantity"
    
    # 3. Pack column mapping
    if t in ["pack", "packing", "pkg"]:
        return "pack"
    
    # 4. Product column mapping
    if t in ["product", "particulars", "item", "description", "product name", "item name"]:
        return "product"
    
    # 5. Batch column mapping
    if t in ["batch", "batch no", "batch no.", "batchno", "b.no", "b.no."]:
        return "batch"
    
    # 6. Expiry column mapping
    if t in ["exp", "expiry", "exp.", "exp date", "exp.date", "expiry date"]:
        return "expiry"
    
    # 7. HSN column mapping
    if t in ["hsn", "hsn code", "hsncode", "hsn/sac"]:
        return "hsn"
    
    # 8. MRP column mapping
    if t in ["mrp", "m.r.p.", "m.r.p"]:
        return "mrp"
    
    # 9. Rate column mapping
    if t in ["rate", "unit rate", "price", "unit price"]:
        return "rate"
    
    # 10. Discount column mapping
    if t in ["dis", "dis.", "disc", "disc.", "discount", "disc %", "discount %", "dis %"]:
        return "discount"
    
    # 11. GST column mappings (SGST, CGST, IGST)
    if "sgst" in t:
        return "sgst_percent"
    if "cgst" in t:
        return "cgst_percent"
    if "igst" in t:
        return "igst_percent"
    
    # 12. Amount column mapping
    if t in ["amount", "amt", "amt.", "value", "net amount", "total amount"]:
        return "amount"
        
    return None

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
    """
    Combines SGST and CGST percentages, or falls back to IGST percent.
    """
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
            # Clean up text by stripping whitespace
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
    
    detection_target_headers = {"product", "batch", "expiry", "hsn", "mrp", "rate", "amount", "quantity"}
    
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
    
    for table_idx, grid in enumerate(grids):
        # We don't want the same table to be both item and footer unless it's the only table
        if table_idx == selected_item_table_idx and len(grids) > 1:
            continue
        score = score_footer_table(grid)
        if score > max_footer_score:
            max_footer_score = score
            selected_footer_table_idx = table_idx
            
    if selected_footer_table_idx is None or max_footer_score < 1:
        selected_footer_table_idx = None
        warnings.append("No separate footer table identified.")
        
    # 4. Extract footer data
    footer_data = {}
    if selected_footer_table_idx is not None:
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
    
    # 6. Merge header fields (footer data takes precedence for totals)
    subtotal = footer_data.get("subtotal") if footer_data.get("subtotal") is not None else doc_subtotal
    discount = footer_data.get("discount")
    cgst = footer_data.get("cgst")
    sgst = footer_data.get("sgst")
    igst = footer_data.get("igst")
    grand_total = footer_data.get("grand_total") if footer_data.get("grand_total") is not None else doc_grand_total
    
    # 7. Parse line items from selected item table
    line_items = []
    if selected_item_table_idx is not None:
        item_grid = grids[selected_item_table_idx]
        header_row = item_grid[selected_header_row_idx]
        col_names = [normalize_header(cell) for cell in header_row]
        
        for r_idx in range(selected_header_row_idx + 1, len(item_grid)):
            row = item_grid[r_idx]
            # Skip rows containing footer content
            if is_footer_row(row):
                continue
                
            row_data = {}
            for c_idx, val in enumerate(row):
                if c_idx < len(col_names):
                    col_name = col_names[c_idx]
                    if col_name:
                        # Store cell value (use first non-empty value if duplicate column mappings exist)
                        if col_name not in row_data or not row_data[col_name]:
                            row_data[col_name] = val
                            
            # Filtering criteria: require product name OR batch OR amount to treat as an item row
            product_val = row_data.get("product", "").strip()
            batch_val = row_data.get("batch", "").strip()
            amount_val = row_data.get("amount", "").strip()
            
            if not (product_val or batch_val or amount_val):
                continue
                
            # Quantity extraction
            qty_raw = row_data.get("quantity")
            serial_raw = row_data.get("serial")
            quantity = extract_corrected_qty(qty_raw, serial_raw)
            
            # GST percent
            gst_percent = extract_gst_percent(
                row_data.get("sgst_percent"),
                row_data.get("cgst_percent"),
                row_data.get("igst_percent")
            )
            
            item = CanonicalLineItem(
                name=product_val if product_val else None,
                pack=row_data.get("pack") if row_data.get("pack") else None,
                batch=batch_val if batch_val else None,
                expiry=row_data.get("expiry") if row_data.get("expiry") else None,
                hsn=row_data.get("hsn") if row_data.get("hsn") else None,
                quantity=quantity,
                free_quantity=parse_decimal_safe(row_data.get("free_quantity")),
                mrp=parse_decimal_safe(row_data.get("mrp")),
                rate=parse_decimal_safe(row_data.get("rate")),
                discount=parse_decimal_safe(row_data.get("discount")),
                gst_percent=gst_percent,
                amount=parse_decimal_safe(row_data.get("amount")),
                confidence=None
            )
            line_items.append(item)
            
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
    
    # Store roundoff in metadata
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
