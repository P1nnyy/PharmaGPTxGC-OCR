"""
Graph fallback TableRegion builder.

Deterministically assembles a TableRegion from spatial graph candidate rows
and columns produced by document_graph.build_document_graph(). Used when
standard TSR reconstruction is collapsed, missing, or low-confidence.
"""

from typing import Any, Dict, List

from models.layout_models import (
    ColumnRegion,
    GeometryBox,
    RegionType,
    RowRegion,
    TableCell,
    TableRegion,
)


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
