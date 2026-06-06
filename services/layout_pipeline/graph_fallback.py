from typing import List, Dict, Any, Optional
from models.layout_models import TableRegion, RowRegion, ColumnRegion, TableCell, GeometryBox, RegionType
from services.layout_pipeline.ioa_mapping import map_tokens_to_cells
from core.logger import logger

def get_geometry_box(geom_data: Any) -> Optional[GeometryBox]:
    """
    Extracts and normalizes a GeometryBox from various formats.
    """
    if not geom_data:
        return None
    if isinstance(geom_data, GeometryBox):
        return geom_data
    if isinstance(geom_data, dict):
        min_x = float(geom_data.get("min_x", 0.0))
        max_x = float(geom_data.get("max_x", 0.0))
        min_y = float(geom_data.get("min_y", 0.0))
        max_y = float(geom_data.get("max_y", 0.0))
        center_x = float(geom_data.get("center_x", (min_x + max_x) / 2.0))
        center_y = float(geom_data.get("center_y", (min_y + max_y) / 2.0))
        return GeometryBox(
            min_x=min_x,
            max_x=max_x,
            min_y=min_y,
            max_y=max_y,
            center_x=center_x,
            center_y=center_y
        )
    if hasattr(geom_data, "min_x") and hasattr(geom_data, "min_y"):
        return GeometryBox(
            min_x=float(geom_data.min_x),
            max_x=float(geom_data.max_x),
            min_y=float(geom_data.min_y),
            max_y=float(geom_data.max_y),
            center_x=float(getattr(geom_data, "center_x", (geom_data.min_x + geom_data.max_x) / 2.0)),
            center_y=float(getattr(geom_data, "center_y", (geom_data.min_y + geom_data.max_y) / 2.0))
        )
    return None

def build_graph_fallback_table_region(
    graph_rows: List[Any],
    graph_cols: List[Any],
    graph_confidence: float = 0.5
) -> Optional[TableRegion]:
    """
    Constructs a TableRegion from layout graph rows and columns.
    """
    if not graph_rows or not graph_cols:
        return None

    try:
        rows = []
        for idx, r in enumerate(graph_rows):
            if isinstance(r, RowRegion):
                rows.append(r)
                continue
            
            row_id = r.get("row_id") or f"row_{idx}"
            geom = get_geometry_box(r.get("geometry"))
            if not geom:
                # If no geometry, construct a flat line at vertical position or 0
                y = float(r.get("center_y", 0.0))
                geom = GeometryBox(min_x=0.0, max_x=1000.0, min_y=y - 5.0, max_y=y + 5.0, center_x=500.0, center_y=y)

            row_reg = RowRegion(
                row_id=row_id,
                geometry=geom,
                original_geometry=geom,
                normalized_geometry=geom,
                confidence=float(r.get("confidence", 1.0)),
                stability=float(r.get("stability", 1.0)),
                row_role=r.get("row_role") or r.get("row_type_hint") or "unknown_row",
                provenance=r.get("provenance") or {}
            )
            rows.append(row_reg)

        cols = []
        for idx, c in enumerate(graph_cols):
            if isinstance(c, ColumnRegion):
                cols.append(c)
                continue

            col_id = c.get("col_id") or f"col_{idx}"
            geom = get_geometry_box(c.get("geometry"))
            if not geom:
                x = float(c.get("center_x", 0.0))
                geom = GeometryBox(min_x=x - 5.0, max_x=x + 5.0, min_y=0.0, max_y=1000.0, center_x=x, center_y=500.0)

            col_reg = ColumnRegion(
                col_id=col_id,
                geometry=geom,
                original_geometry=geom,
                normalized_geometry=geom,
                confidence=float(c.get("confidence", 1.0))
            )
            cols.append(col_reg)

        cells = []
        for row in rows:
            for col in cols:
                cell_geom = None
                if row.geometry and col.geometry:
                    cell_geom = GeometryBox(
                        min_x=col.geometry.min_x,
                        max_x=col.geometry.max_x,
                        min_y=row.geometry.min_y,
                        max_y=row.geometry.max_y,
                        center_x=(col.geometry.min_x + col.geometry.max_x) / 2.0,
                        center_y=(row.geometry.min_y + row.geometry.max_y) / 2.0
                    )
                cell = TableCell(
                    row_id=row.row_id,
                    col_id=col.col_id,
                    geometry=cell_geom,
                    original_geometry=cell_geom,
                    normalized_geometry=cell_geom,
                    text=""
                )
                cells.append(cell)

        # Calculate bounding box encompassing all rows/cols
        min_x = min((r.geometry.min_x for r in rows if r.geometry), default=0.0)
        max_x = max((r.geometry.max_x for r in rows if r.geometry), default=1000.0)
        min_y = min((r.geometry.min_y for r in rows if r.geometry), default=0.0)
        max_y = max((r.geometry.max_y for r in rows if r.geometry), default=1000.0)

        table_geom = GeometryBox(
            min_x=min_x,
            max_x=max_x,
            min_y=min_y,
            max_y=max_y,
            center_x=(min_x + max_x) / 2.0,
            center_y=(min_y + max_y) / 2.0
        )

        table_region = TableRegion(
            table_id="graph_fallback_table",
            region_type=RegionType.TABLE,
            geometry=table_geom,
            original_geometry=table_geom,
            normalized_geometry=table_geom,
            rows=rows,
            columns=cols,
            cells=cells,
            confidence=graph_confidence,
            topology_confidence=graph_confidence,
            source_engine="graph_fallback"
        )
        return table_region

    except Exception as e:
        logger.error(f"Failed to build graph fallback table region: {str(e)}", exc_info=True)
        return None

def assign_tokens_to_graph_cells(
    tr: TableRegion,
    ocr_blocks: List[Any],
    graph_rows: List[Any],
    graph_cols: List[Any]
) -> Dict[str, int]:
    """
    Assign OCR block tokens to the reconstructed graph fallback table cells.
    """
    try:
        map_tokens_to_cells(ocr_blocks, [tr])
    except Exception as e:
        logger.error(f"Error mapping tokens to graph cells: {str(e)}", exc_info=True)

    return {
        "product_repair_count": 0,
        "amount_repair_count": 0,
        "numeric_reassignment_count": 0,
        "suspicious_qty_count": 0
    }
