import sys
import os

# Ensure the workspace is on the python search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.layout_models import TableRegion, RowRegion, ColumnRegion, TableCell, GeometryBox
from services.layout_pipeline.semantic_column_classifier import SemanticColumnClassifier, ColumnSemantics

def test_classifier():
    print("Initializing SemanticColumnClassifier...")
    classifier = SemanticColumnClassifier()

    # Define mock geometries
    geom = GeometryBox(min_x=0, max_x=1000, min_y=0, max_y=500, center_x=500, center_y=250)

    # 1. MOCK TABLE 1:
    # Col 0: Serial Number (Header: "S.No", cells: ["1", "2", "3", "4"])
    # Col 1: Product Name (Header: "Particulars", cells: ["CROCIN", "DOLO", "PAN-D", "ASPIRIN"])
    # Col 2: PACK Column (Header: "PACK", cells: ["1*15", "1*15", "1*10", "1*10"])
    # Col 3: Actual Quantity Column (Header: "QTY", cells: ["10", "5", "15", "8"])
    
    rows = [
        RowRegion(row_id="row_h", row_role="header_row", stability=1.0),
        RowRegion(row_id="row_1", row_role="item_row", stability=1.0),
        RowRegion(row_id="row_2", row_role="item_row", stability=1.0),
        RowRegion(row_id="row_3", row_role="item_row", stability=1.0),
        RowRegion(row_id="row_4", row_role="item_row", stability=1.0),
    ]

    columns = [
        ColumnRegion(col_id="col_0", geometry=GeometryBox(min_x=10, max_x=50, min_y=0, max_y=500, center_x=30, center_y=250)),
        ColumnRegion(col_id="col_1", geometry=GeometryBox(min_x=60, max_x=400, min_y=0, max_y=500, center_x=230, center_y=250)),
        ColumnRegion(col_id="col_2", geometry=GeometryBox(min_x=410, max_x=480, min_y=0, max_y=500, center_x=445, center_y=250)),
        ColumnRegion(col_id="col_3", geometry=GeometryBox(min_x=490, max_x=550, min_y=0, max_y=500, center_x=520, center_y=250)),
    ]

    cells = [
        # Headers
        TableCell(row_id="row_h", col_id="col_0", text="UnknownHeader", geometry=GeometryBox(min_x=10, max_x=50, min_y=10, max_y=30, center_x=30, center_y=20)),
        TableCell(row_id="row_h", col_id="col_1", text="Particulars", geometry=GeometryBox(min_x=60, max_x=400, min_y=10, max_y=30, center_x=230, center_y=20)),
        TableCell(row_id="row_h", col_id="col_2", text="PACK", geometry=GeometryBox(min_x=410, max_x=480, min_y=10, max_y=30, center_x=445, center_y=20)),
        TableCell(row_id="row_h", col_id="col_3", text="QTY", geometry=GeometryBox(min_x=490, max_x=550, min_y=10, max_y=30, center_x=520, center_y=20)),

        # Row 1
        TableCell(row_id="row_1", col_id="col_0", text="1", geometry=GeometryBox(min_x=10, max_x=50, min_y=40, max_y=60, center_x=30, center_y=50)),
        TableCell(row_id="row_1", col_id="col_1", text="CROCIN TAB", geometry=GeometryBox(min_x=60, max_x=400, min_y=40, max_y=60, center_x=230, center_y=50)),
        TableCell(row_id="row_1", col_id="col_2", text="1*15", geometry=GeometryBox(min_x=410, max_x=480, min_y=40, max_y=60, center_x=445, center_y=50)),
        TableCell(row_id="row_1", col_id="col_3", text="10", geometry=GeometryBox(min_x=490, max_x=550, min_y=40, max_y=60, center_x=520, center_y=50)),

        # Row 2
        TableCell(row_id="row_2", col_id="col_0", text="2", geometry=GeometryBox(min_x=10, max_x=50, min_y=70, max_y=90, center_x=30, center_y=80)),
        TableCell(row_id="row_2", col_id="col_1", text="DOLO 650", geometry=GeometryBox(min_x=60, max_x=400, min_y=70, max_y=90, center_x=230, center_y=80)),
        TableCell(row_id="row_2", col_id="col_2", text="1*15", geometry=GeometryBox(min_x=410, max_x=480, min_y=70, max_y=90, center_x=445, center_y=80)),
        TableCell(row_id="row_2", col_id="col_3", text="5", geometry=GeometryBox(min_x=490, max_x=550, min_y=70, max_y=90, center_x=520, center_y=80)),

        # Row 3
        TableCell(row_id="row_3", col_id="col_0", text="3", geometry=GeometryBox(min_x=10, max_x=50, min_y=100, max_y=120, center_x=30, center_y=110)),
        TableCell(row_id="row_3", col_id="col_1", text="PAN-D CAP", geometry=GeometryBox(min_x=60, max_x=400, min_y=100, max_y=120, center_x=230, center_y=110)),
        TableCell(row_id="row_3", col_id="col_2", text="1*10", geometry=GeometryBox(min_x=410, max_x=480, min_y=100, max_y=120, center_x=445, center_y=110)),
        TableCell(row_id="row_3", col_id="col_3", text="15", geometry=GeometryBox(min_x=490, max_x=550, min_y=100, max_y=120, center_x=520, center_y=110)),

        # Row 4
        TableCell(row_id="row_4", col_id="col_0", text="4", geometry=GeometryBox(min_x=10, max_x=50, min_y=130, max_y=150, center_x=30, center_y=140)),
        TableCell(row_id="row_4", col_id="col_1", text="ASPIRIN 100", geometry=GeometryBox(min_x=60, max_x=400, min_y=130, max_y=150, center_x=230, center_y=140)),
        TableCell(row_id="row_4", col_id="col_2", text="1*10", geometry=GeometryBox(min_x=410, max_x=480, min_y=130, max_y=150, center_x=445, center_y=140)),
        TableCell(row_id="row_4", col_id="col_3", text="8", geometry=GeometryBox(min_x=490, max_x=550, min_y=130, max_y=150, center_x=520, center_y=140)),
    ]

    region = TableRegion(
        table_id="table_1",
        geometry=geom,
        rows=rows,
        columns=columns,
        cells=cells
    )

    print("Analyzing columns...")
    results = classifier.enrich_region_metadata(region)
    
    col_0_type = results["col_0"]["type"]
    col_1_type = results["col_1"]["type"]
    col_2_type = results["col_2"]["type"]
    col_3_type = results["col_3"]["type"]

    print("\n--- RESULTS ---")
    print(f"Col 0 (S.No) Semantic Label: {col_0_type}")
    print(f"Col 1 (Particulars) Semantic Label: {col_1_type}")
    print(f"Col 2 (PACK) Semantic Label: {col_2_type}")
    print(f"Col 3 (QTY) Semantic Label: {col_3_type}")

    assert col_0_type == ColumnSemantics.SERIAL, f"Expected {ColumnSemantics.SERIAL}, got {col_0_type}"
    assert col_1_type == ColumnSemantics.PRODUCT, f"Expected {ColumnSemantics.PRODUCT}, got {col_1_type}"
    assert col_2_type == ColumnSemantics.PACK, f"Expected {ColumnSemantics.PACK}, got {col_2_type}"
    assert col_3_type == ColumnSemantics.QUANTITY, f"Expected {ColumnSemantics.QUANTITY}, got {col_3_type}"
    
    print("\nAll assertions passed successfully!")

if __name__ == "__main__":
    test_classifier()
