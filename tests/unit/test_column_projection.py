import pytest
from typing import List
from models.layout_models import OCRBlock, GeometryBox
from services.layout_pipeline.column_projection import (
    project_column_boundaries,
    _is_dense_pharma_region
)

def make_block(text: str, min_x: float, max_x: float, min_y: float = 10.0, max_y: float = 25.0) -> OCRBlock:
    geom = GeometryBox(
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
        center_x=(min_x + max_x) / 2.0,
        center_y=(min_y + max_y) / 2.0
    )
    return OCRBlock(
        text=text,
        normalized_geometry=geom
    )

def test_dense_pharma_mode_detection():
    # Construct blocks representing the Abka Medicos dense invoice table
    row0_data = [
        ("118.00", 0.00, 43.74),
        ("5", 49.53, 64.26),
        ("90", 82.01, 102.26),
        ("84.16", 117.54, 159.30),
        ("0.16 64.13 05/27", 167.82, 283.10),
        ("1.84", 288.12, 320.86),
        ("MANKIN OUFZY045-", 358.93, 459.21),
        ("30049099 10 S", 464.50, 549.27),
        ("GLIPTAGREAT-M 500", 566.07, 682.88)
    ]
    row1_data = [
        ("270.32", 0.32, 43.56),
        ("5", 49.35, 63.56),
        ("0", 82.86, 94.07),
        ("168.95", 117.62, 164.38),
        ("135.16 07/27", 166.64, 248.42),
        ("2.00", 288.95, 320.69),
        ("LUPIN UB02123", 369.27, 457.02),
        ("CNDERO MET 2.5/1000 M 30049099 10 S", 463.84, 682.67)
    ]
    
    blocks = []
    # Row 0
    for text, xmin, xmax in row0_data:
        blocks.append(make_block(text, xmin, xmax, min_y=718.0, max_y=731.0))
    # Row 1
    for text, xmin, xmax in row1_data:
        blocks.append(make_block(text, xmin, xmax, min_y=733.0, max_y=746.0))
        
    assert _is_dense_pharma_region(blocks) is True


def test_dense_pharma_projection_resolution():
    row0_data = [
        ("118.00", 0.00, 43.74),
        ("5", 49.53, 64.26),
        ("90", 82.01, 102.26),
        ("84.16", 117.54, 159.30),
        ("0.16 64.13 05/27", 167.82, 283.10),
        ("1.84", 288.12, 320.86),
        ("MANKIN OUFZY045-", 358.93, 459.21),
        ("30049099 10 S", 464.50, 549.27),
        ("GLIPTAGREAT-M 500", 566.07, 682.88)
    ]
    row1_data = [
        ("270.32", 0.32, 43.56),
        ("5", 49.35, 63.56),
        ("0", 82.86, 94.07),
        ("168.95", 117.62, 164.38),
        ("135.16 07/27", 166.64, 248.42),
        ("2.00", 288.95, 320.69),
        ("LUPIN UB02123", 369.27, 457.02),
        ("CNDERO MET 2.5/1000 M 30049099 10 S", 463.84, 682.67)
    ]
    
    blocks = []
    for text, xmin, xmax in row0_data:
        blocks.append(make_block(text, xmin, xmax, min_y=718.0, max_y=731.0))
    for text, xmin, xmax in row1_data:
        blocks.append(make_block(text, xmin, xmax, min_y=733.0, max_y=746.0))
        
    bounds = project_column_boundaries(blocks)
    
    # Assert that dense pharma projection returns >= 4 columns, preferably >= 6
    print(f"Detected boundaries: {bounds}")
    assert len(bounds) >= 4, f"Should find >= 4 columns, found {len(bounds)}: {bounds}"
    assert len(bounds) >= 6, f"Should find >= 6 columns under optimized adaptive parameters, found {len(bounds)}: {bounds}"


def test_sparse_non_dense_backward_compatibility():
    # Simple table with 2 columns and 2 rows
    row0 = [
        ("Product Name", 10.0, 150.0),
        ("Price", 300.0, 350.0)
    ]
    row1 = [
        ("Paracetamol 650", 10.0, 140.0),
        ("15.00", 300.0, 310.0)
    ]
    blocks = []
    for text, xmin, xmax in row0:
        blocks.append(make_block(text, xmin, xmax, min_y=10.0, max_y=25.0))
    for text, xmin, xmax in row1:
        blocks.append(make_block(text, xmin, xmax, min_y=30.0, max_y=45.0))
        
    # Should detect as non-dense
    assert _is_dense_pharma_region(blocks) is False
    
    bounds = project_column_boundaries(blocks)
    # Should resolve exactly 2 columns safely (no over-splitting)
    assert len(bounds) == 2, f"Should resolve exactly 2 columns, got {len(bounds)}: {bounds}"
