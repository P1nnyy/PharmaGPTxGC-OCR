"""
Graph fallback TableRegion builder.

Deterministically assembles a TableRegion from spatial graph candidate rows
and columns produced by document_graph.build_document_graph(). Used when
standard TSR reconstruction is collapsed, missing, or low-confidence.
"""

import re
from typing import Any, Dict, List, Optional
from core.logger import logger
from models.layout_models import (
    ColumnRegion,
    GeometryBox,
    RegionType,
    RowRegion,
    TableCell,
    TableRegion,
    OCRBlock,
)
from services.layout_pipeline.ioa_mapping import is_numeric_like


def build_graph_fallback_table_region(
    graph_rows: List[Dict[str, Any]],
    graph_cols: List[Dict[str, Any]],
    graph_confidence: float,
) -> TableRegion:
    """Deterministic assembly of TableRegion from spatial graph candidates."""

    # 1. Build ColumnRegions
    col_regions = []
    for c in graph_cols:
        col_regions.append(ColumnRegion(
            col_id=c["col_id"],
            geometry=GeometryBox(
                min_x=c["min_x"],
                max_x=c["max_x"],
                min_y=0.0,
                max_y=10000.0,
                center_x=c["center_x"],
                center_y=5000.0
            ),
            confidence=c["confidence"]
        ))

    # 2. Build RowRegions
    table_rows = []
    for r in graph_rows:
        table_rows.append(RowRegion(
            row_id=r["row_id"],
            geometry=GeometryBox(
                min_x=r["min_x"],
                max_x=r["max_x"],
                min_y=r["min_y"],
                max_y=r["max_y"],
                center_x=(r["min_x"] + r["max_x"]) / 2.0,
                center_y=r["center_y"]
            ),
            confidence=r["confidence"],
            stability=1.0,
            row_role="item_row" if r["row_type_hint"] == "item_candidate" else "unknown_row"
        ))

    # 3. Build TableCells at intersections
    table_cells = []
    for row in table_rows:
        for col in col_regions:
            cell_geom = GeometryBox(
                min_x=max(row.geometry.min_x, col.geometry.min_x),
                max_x=min(row.geometry.max_x, col.geometry.max_x),
                min_y=row.geometry.min_y,
                max_y=row.geometry.max_y,
                center_x=(max(row.geometry.min_x, col.geometry.min_x) + min(row.geometry.max_x, col.geometry.max_x)) / 2.0,
                center_y=row.geometry.center_y
            )
            table_cells.append(TableCell(
                row_id=row.row_id,
                col_id=col.col_id,
                geometry=cell_geom,
                confidence=min(row.confidence, col.confidence)
            ))

    # 4. Compute composite TableRegion geometry
    reg_min_x = min(r.geometry.min_x for r in table_rows) if table_rows else 0.0
    reg_max_x = max(r.geometry.max_x for r in table_rows) if table_rows else 1000.0
    reg_min_y = min(r.geometry.min_y for r in table_rows) if table_rows else 0.0
    reg_max_y = max(r.geometry.max_y for r in table_rows) if table_rows else 1000.0
    reg_geom = GeometryBox(
        min_x=reg_min_x,
        max_x=reg_max_x,
        min_y=reg_min_y,
        max_y=reg_max_y,
        center_x=(reg_min_x + reg_max_x) / 2.0,
        center_y=(reg_min_y + reg_max_y) / 2.0
    )

    return TableRegion(
        table_id="graph_fallback_region",
        region_type=RegionType.MEDICINE_TABLE,
        geometry=reg_geom,
        rows=table_rows,
        columns=col_regions,
        cells=table_cells,
        confidence=graph_confidence,
        source_engine="document_graph_fallback",
        topology_confidence=graph_confidence
    )


def _compute_y_overlap(b_geom: Optional[GeometryBox], r_geom: Optional[GeometryBox]) -> float:
    """Computes normalized vertical overlap between a block and a row region."""
    if not b_geom or not r_geom:
        return 0.0
    overlap = min(b_geom.max_y, r_geom.max_y) - max(b_geom.min_y, r_geom.min_y)
    if overlap <= 0:
        return 0.0
    b_height = max(1.0, b_geom.max_y - b_geom.min_y)
    return overlap / b_height


def is_gst_percent_token(text: str) -> bool:
    """Detects if a numeric token is a GST percentage value, matching common Indian slabs."""
    if not text:
        return False
    if "%" in text:
        return True
    cleaned = re.sub(r'[^\d.]', '', text)
    try:
        val = float(cleaned)
        # 0%, 2.5%, 5%, 6%, 9%, 12%, 14%, 18%, 28% half/full rates
        if val in {0.0, 2.5, 5.0, 6.0, 9.0, 12.0, 14.0, 18.0, 28.0}:
            return True
    except ValueError:
        pass
    return False


def is_alphabetic_product_token(text: str) -> bool:
    """Detects if a token is a medicine-like alphabetical product name."""
    if not text:
        return False
    # Check if contains letters (a-z, A-Z)
    has_alpha = any(c.isalpha() for c in text)
    if not has_alpha:
        return False
    # Exclude typical units or codes like "PCS", "TAB", "CAP", "BOX", "STR", "ML", "GM", "NO"
    upper = text.upper()
    if upper in {"PCS", "TAB", "TABS", "CAP", "CAPS", "BOX", "STR", "STRIP", "ML", "GM", "NOS", "NO", "KG", "LTR"}:
        return False
    # Exclude common short patterns like "10TAB", "2CAP" (often these are compound units or quantity fluff)
    if re.match(r'^\d+[A-Z]+$', upper):
        return False
    return True


def detect_column_semantics(
    tr: TableRegion,
    ocr_blocks: List[OCRBlock],
    graph_rows: List[Dict[str, Any]]
) -> Dict[str, str]:
    """Identifies semantic roles for all columns using header text alignment and positional layout."""
    col_semantics = {}
    for col in tr.columns:
        col_semantics[col.col_id] = "other"
        
    # Find all header rows from graph_rows
    header_rows = [r for r in graph_rows if r.get("row_type_hint") == "header_candidate"]
    if not header_rows and graph_rows:
        # fallback: take the row with minimum center_y (top of table)
        sorted_grows = sorted(graph_rows, key=lambda x: x.get("center_y", 0.0))
        if sorted_grows:
            header_rows = [sorted_grows[0]]
            
    header_block_ids = []
    for hr in header_rows:
        header_block_ids.extend(hr.get("token_ids", []))
        
    header_blocks = [b for b in ocr_blocks if b.id in header_block_ids]
    
    # Check proximity of header blocks to columns
    for col in tr.columns:
        c_x = col.geometry.center_x if col.geometry else 500.0
        closest_block = None
        min_dist = float('inf')
        for b in header_blocks:
            if b.normalized_geometry:
                b_cx = (b.normalized_geometry.min_x + b.normalized_geometry.max_x) / 2.0
                dist = abs(b_cx - c_x)
                if dist < min_dist:
                    min_dist = dist
                    closest_block = b
                    
        if closest_block and min_dist < 120.0:
            txt = (closest_block.text or "").upper()
            if any(kw in txt for kw in ["PRODUCT", "ITEM", "DESC", "NAME", "MEDICINE", "PARTICULAR", "DRUG"]):
                col_semantics[col.col_id] = "product"
            elif any(kw in txt for kw in ["QTY", "QUANTITY", "QNTY", "UNIT", "PCS", "NOS"]):
                col_semantics[col.col_id] = "quantity"
            elif any(kw in txt for kw in ["RATE", "PRICE", "UNITPRICE", "PRC", "MRP", "RTE"]):
                col_semantics[col.col_id] = "rate"
            elif any(kw in txt for kw in ["AMOUNT", "AMT", "NETAMT", "VALUE", "NET"]):
                col_semantics[col.col_id] = "amount"
            elif any(kw in txt for kw in ["GST", "SGST", "CGST", "IGST", "TAX", "VAT"]):
                col_semantics[col.col_id] = "gst"
            elif any(kw in txt for kw in ["DISCOUNT", "DISC", "DIS", "CD%", "TD%"]):
                col_semantics[col.col_id] = "discount"

    # Positional heuristics backup
    cols_sorted = sorted(tr.columns, key=lambda c: c.geometry.center_x if c.geometry else 0.0)
    num_cols = len(cols_sorted)
    
    if num_cols >= 3:
        # Rightmost column is amount by default if not classified
        amount_cols = [cid for cid, sem in col_semantics.items() if sem == "amount"]
        if not amount_cols:
            col_semantics[cols_sorted[-1].col_id] = "amount"
            
        # Leftmost column is product by default if not classified
        product_cols = [cid for cid, sem in col_semantics.items() if sem == "product"]
        if not product_cols:
            col_semantics[cols_sorted[0].col_id] = "product"
            
    return col_semantics


def assign_tokens_to_graph_cells(
    tr: TableRegion,
    ocr_blocks: List[OCRBlock],
    graph_rows: List[Dict[str, Any]],
    graph_cols: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Hardened custom token-to-cell assignment for graph candidate and fallback tables.
    Maps tokens using row memberships first, prevents product token swallowing, and respects X-bands for numbers.
    """
    repair_telemetry = {
        "product_repair_count": 0,
        "amount_repair_count": 0,
        "numeric_reassignment_count": 0,
        "suspicious_qty_count": 0,
    }

    if not graph_rows or not graph_cols or not tr.rows or not tr.cells:
        logger.warning("[GRAPH ASSIGNMENT] Aborted assignment: empty graph or table structure.")
        return repair_telemetry

    # Initialize all cells in TableRegion to prevent garbage leftovers
    for cell in tr.cells:
        cell.mapped_block_ids = []
        cell.text = ""
        cell.assignment_strategy = "unassigned"
        cell.assignment_confidence = 1.0

    # Index OCR blocks by ID for immediate lookup
    blocks_by_id = {b.id: b for b in ocr_blocks if b.id}
    claimed_block_ids = set()

    # Step 1: Associate blocks with TableRegion rows using graph row token memberships first
    row_blocks_map = {row.row_id: [] for row in tr.rows}
    grow_map = {grow["row_id"]: grow for grow in graph_rows}

    # Pass 1: exact graph token memberships
    for row in tr.rows:
        grow = grow_map.get(row.row_id)
        if grow:
            for tid in grow.get("token_ids", []):
                if tid in blocks_by_id and tid not in claimed_block_ids:
                    row_blocks_map[row.row_id].append(blocks_by_id[tid])
                    claimed_block_ids.add(tid)

    # Pass 2: vertical Y-overlap for remaining unassigned blocks
    for block in ocr_blocks:
        if not block.id or block.id in claimed_block_ids or not block.normalized_geometry:
            continue
        # Find best row vertically
        best_row = None
        best_y_overlap = 0.0
        for row in tr.rows:
            overlap = _compute_y_overlap(block.normalized_geometry, row.geometry)
            if overlap > best_y_overlap:
                best_y_overlap = overlap
                best_row = row
        if best_row and best_y_overlap > 0.45:
            row_blocks_map[best_row.row_id].append(block)
            claimed_block_ids.add(block.id)

    # Step 2: Determine semantic roles for all columns globally
    col_semantics = detect_column_semantics(tr, ocr_blocks, graph_rows)
    has_rate_header_evidence = any(sem == "rate" for sem in col_semantics.values())

    rate_cols = [c for c in tr.columns if col_semantics[c.col_id] == "rate"]
    amount_cols = [c for c in tr.columns if col_semantics[c.col_id] == "amount"]
    rate_col = rate_cols[0] if rate_cols else None
    amount_col = amount_cols[0] if amount_cols else None

    # Step 3: Map row blocks to correct column cells horizontally
    for row in tr.rows:
        blocks = row_blocks_map[row.row_id]
        if not blocks:
            continue

        # Map each block of the row to a column
        for block in blocks:
            if not block.normalized_geometry:
                continue

            b_cx = (block.normalized_geometry.min_x + block.normalized_geometry.max_x) / 2.0
            is_num = is_numeric_like(block.text)

            # Filtering and target choices based on block text type
            if is_num:
                # GST percent do not merge into quantity
                is_gst = is_gst_percent_token(block.text)
                valid_cols = []
                for col in tr.columns:
                    # Shield quantity from GST slabs
                    if is_gst and col_semantics[col.col_id] == "quantity":
                        continue
                    valid_cols.append(col)

                # Assign numeric by nearest x-band center
                best_col = None
                min_dist = float('inf')
                for col in valid_cols:
                    col_cx = col.geometry.center_x if col.geometry else 500.0
                    dist = abs(b_cx - col_cx)
                    if dist < min_dist:
                        min_dist = dist
                        best_col = col

                # Prefer rightmost numeric band for amount, check rate/amount override
                if rate_col and amount_col and best_col in [rate_col, amount_col]:
                    rate_cx = rate_col.geometry.center_x if rate_col.geometry else 400.0
                    amount_cx = amount_col.geometry.center_x if amount_col.geometry else 600.0

                    if not has_rate_header_evidence:
                        # Reassign to amount if in zone and no explicit RATE header
                        if b_cx > (rate_cx - 20.0):
                            if best_col != amount_col:
                                best_col = amount_col
                                repair_telemetry["numeric_reassignment_count"] += 1
                    else:
                        # Prefer RATE band before AMOUNT only when header says RATE
                        dist_rate = abs(b_cx - rate_cx)
                        dist_amount = abs(b_cx - amount_cx)
                        if dist_rate < dist_amount:
                            best_col = rate_col
                        else:
                            best_col = amount_col
            else:
                # Alphabetic / product name tokens
                is_product_token = is_alphabetic_product_token(block.text)
                valid_cols = []
                for col in tr.columns:
                    sem = col_semantics[col.col_id]
                    # Prevent alphabetic product tokens from entering quantity, rate, or amount
                    if is_product_token and sem in ["quantity", "rate", "amount"]:
                        continue
                    valid_cols.append(col)

                best_col = None
                min_dist = float('inf')
                for col in valid_cols:
                    col_cx = col.geometry.center_x if col.geometry else 500.0
                    dist = abs(b_cx - col_cx)
                    if dist < min_dist:
                        min_dist = dist
                        best_col = col

            # Map the block ID to the selected cell
            if best_col:
                # Find matching TableCell
                for cell in tr.cells:
                    if cell.row_id == row.row_id and cell.col_id == best_col.col_id:
                        cell.mapped_block_ids.append(block.id)
                        cell.assignment_strategy = "row_scoped"
                        cell.assignment_confidence = 1.0
                        break

    # Step 4: Perform Fallback Repair Pass
    for row in tr.rows:
        row_cells = [c for c in tr.cells if c.row_id == row.row_id]
        cell_by_sem = {}
        for c in row_cells:
            cell_by_sem[col_semantics[c.col_id]] = c

        product_cell = cell_by_sem.get("product")
        quantity_cell = cell_by_sem.get("quantity")
        amount_cell = cell_by_sem.get("amount")

        # 1. Product cell repair: fill empty product cell using alphabetical tokens in row
        if product_cell and not product_cell.mapped_block_ids:
            alpha_block_ids = []
            for c in row_cells:
                if c.col_id == product_cell.col_id:
                    continue
                # Extract alphabetic product blocks
                for bid in list(c.mapped_block_ids):
                    b = blocks_by_id.get(bid)
                    if b and is_alphabetic_product_token(b.text):
                        alpha_block_ids.append(bid)
                        c.mapped_block_ids.remove(bid)
            if alpha_block_ids:
                product_cell.mapped_block_ids.extend(alpha_block_ids)
                product_cell.assignment_strategy = "row_scoped"
                repair_telemetry["product_repair_count"] += 1

        # Rebuild texts for initial check
        for c in row_cells:
            c_blocks = [blocks_by_id[bid] for bid in c.mapped_block_ids if bid in blocks_by_id]
            c_blocks.sort(key=lambda b: (round((b.normalized_geometry.min_y or 0) / 6), b.normalized_geometry.min_x or 0))
            c.text = " ".join([b.text for b in c_blocks if b.text]).strip()

        # 2. Quantity cell repair: invalidate decimal price-like quantity if no product text
        if quantity_cell and quantity_cell.text:
            # Check for price-like decimal (e.g. 12.50 or 12.00)
            has_price_decimal = bool(re.search(r'\d+\.\d{2}', quantity_cell.text))
            has_product_text = bool(product_cell and product_cell.text.strip())
            if has_price_decimal and not has_product_text:
                quantity_cell.mapped_block_ids = []
                quantity_cell.text = ""
                quantity_cell.assignment_strategy = "unassigned"
                repair_telemetry["suspicious_qty_count"] += 1

        # 3. Amount cell repair: fill empty amount cell using rightmost numeric token in row
        if amount_cell and not amount_cell.text:
            rightmost_block = None
            max_x = -1.0
            source_cell = None
            
            # Find the rightmost numeric block across all other cells in the row
            for c in row_cells:
                if c.col_id == amount_cell.col_id:
                    continue
                for bid in c.mapped_block_ids:
                    b = blocks_by_id.get(bid)
                    if b and is_numeric_like(b.text) and b.normalized_geometry:
                        b_max_x = b.normalized_geometry.max_x
                        if b_max_x > max_x:
                            max_x = b_max_x
                            rightmost_block = b
                            source_cell = c
                            
            if rightmost_block and source_cell:
                source_cell.mapped_block_ids.remove(rightmost_block.id)
                amount_cell.mapped_block_ids.append(rightmost_block.id)
                amount_cell.assignment_strategy = "row_scoped"
                repair_telemetry["amount_repair_count"] += 1

        # Re-populate final text for all cells after repair pass
        for c in row_cells:
            c_blocks = [blocks_by_id[bid] for bid in c.mapped_block_ids if bid in blocks_by_id]
            c_blocks.sort(key=lambda b: (round((b.normalized_geometry.min_y or 0) / 6), b.normalized_geometry.min_x or 0))
            c.text = " ".join([b.text for b in c_blocks if b.text]).strip()

    logger.info(
        f"[GRAPH HARDENING] Done. Product repaired: {repair_telemetry['product_repair_count']} | "
        f"Amount repaired: {repair_telemetry['amount_repair_count']} | "
        f"Numeric reassigned: {repair_telemetry['numeric_reassignment_count']} | "
        f"Suspicious Qty removed: {repair_telemetry['suspicious_qty_count']}"
    )

    return repair_telemetry
