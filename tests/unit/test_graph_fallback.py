import pytest
from services.layout_pipeline.graph_fallback import (
    build_graph_fallback_table_region,
    assign_tokens_to_graph_cells
)
from models.layout_models import RowRegion, ColumnRegion, GeometryBox, OCRBlock, TableRegion

def test_build_graph_fallback_table_region_success():
    # Setup mock graph rows and columns
    mock_rows = [
        {
            "row_id": "row_0",
            "geometry": {"min_x": 0.0, "max_x": 1000.0, "min_y": 10.0, "max_y": 30.0},
            "confidence": 0.9,
            "stability": 0.95,
            "row_type_hint": "item_candidate"
        },
        {
            "row_id": "row_1",
            "geometry": {"min_x": 0.0, "max_x": 1000.0, "min_y": 40.0, "max_y": 60.0},
            "confidence": 0.85,
            "stability": 0.9,
            "row_type_hint": "item_candidate"
        }
    ]
    
    mock_cols = [
        {
            "col_id": "col_0",
            "geometry": {"min_x": 10.0, "max_x": 200.0, "min_y": 0.0, "max_y": 1000.0},
            "confidence": 0.95
        },
        {
            "col_id": "col_1",
            "geometry": {"min_x": 210.0, "max_x": 500.0, "min_y": 0.0, "max_y": 1000.0},
            "confidence": 0.9
        }
    ]
    
    tr = build_graph_fallback_table_region(
        graph_rows=mock_rows,
        graph_cols=mock_cols,
        graph_confidence=0.8
    )
    
    assert tr is not None
    assert isinstance(tr, TableRegion)
    assert tr.table_id == "graph_fallback_table"
    assert tr.confidence == 0.8
    assert len(tr.rows) == 2
    assert len(tr.columns) == 2
    assert len(tr.cells) == 4  # 2x2 grid
    
    # Check cells are properly initialized and match rows/cols
    cell_0 = tr.cells[0]
    assert cell_0.row_id == "row_0"
    assert cell_0.col_id == "col_0"
    assert cell_0.geometry.min_x == 10.0
    assert cell_0.geometry.max_x == 200.0
    assert cell_0.geometry.min_y == 10.0
    assert cell_0.geometry.max_y == 30.0

def test_build_graph_fallback_table_region_empty():
    assert build_graph_fallback_table_region([], []) is None
    assert build_graph_fallback_table_region(None, None) is None

def test_assign_tokens_to_graph_cells():
    # Build a simple TableRegion using our fallback function
    mock_rows = [
        {
            "row_id": "row_0",
            "geometry": {"min_x": 0.0, "max_x": 100.0, "min_y": 10.0, "max_y": 30.0}
        }
    ]
    mock_cols = [
        {
            "col_id": "col_0",
            "geometry": {"min_x": 10.0, "max_x": 50.0, "min_y": 0.0, "max_y": 100.0}
        }
    ]
    tr = build_graph_fallback_table_region(mock_rows, mock_cols)
    
    # Create a mock OCR block matching the cell location
    ocr_blocks = [
        OCRBlock(
            id="block_0",
            text="PARACETAMOL",
            normalized_geometry=GeometryBox(min_x=12.0, max_x=45.0, min_y=15.0, max_y=25.0, center_x=28.5, center_y=20.0),
            original_geometry=GeometryBox(min_x=12.0, max_x=45.0, min_y=15.0, max_y=25.0, center_x=28.5, center_y=20.0),
            confidence=0.99
        )
    ]
    
    rep_counts = assign_tokens_to_graph_cells(tr, ocr_blocks, mock_rows, mock_cols)
    
    assert isinstance(rep_counts, dict)
    assert rep_counts["product_repair_count"] == 0
    
    # Verify mapping worked (token assigned to col_0, row_0 cell)
    cell = tr.cells[0]
    assert cell.row_id == "row_0"
    assert cell.col_id == "col_0"
    assert "block_0" in cell.mapped_block_ids
    assert cell.text == "PARACETAMOL"
