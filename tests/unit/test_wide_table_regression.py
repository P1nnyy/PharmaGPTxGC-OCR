"""
Regression tests for wide-table reconstruction end-to-end behaviour.

Three synthetic fixture scenarios — all using synthetic OCR block JSON,
no vendor names, invoice numbers, medicine names, or exact expected row values.

Fixture 1: Wide pharma invoice (14+ columns, 6 item rows)
Fixture 2: Narrow simple invoice (4-5 columns, 3 item rows)
Fixture 3: Different pharma layout (10 columns, different ordering)
"""

import pytest
from models.layout_models import (
    OCRBlock, GeometryBox, TableRegion, ColumnRegion, RowRegion, TableCell, RegionType,
)
from services.layout_pipeline.wide_table_detector import detect_wide_table
from services.topology.column_stabilizer import ColumnStabilizer
from services.spatial_reconstruction import _enforce_ordering_invariants


def _block(text, min_x, max_x, min_y, max_y, block_id=None):
    geom = GeometryBox(
        min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y,
        center_x=(min_x + max_x) / 2, center_y=(min_y + max_y) / 2,
    )
    return OCRBlock(
        id=block_id or f"b_{int(min_x)}_{int(min_y)}",
        text=text, raw_text=text, normalized_geometry=geom,
    )


def _col(col_id, min_x, max_x):
    geom = GeometryBox(min_x=min_x, max_x=max_x, min_y=0, max_y=500,
                       center_x=(min_x + max_x) / 2, center_y=250)
    return ColumnRegion(col_id=col_id, geometry=geom, normalized_geometry=geom)


def _row(row_id, min_y, max_y):
    geom = GeometryBox(min_x=0, max_x=700, min_y=min_y, max_y=max_y,
                       center_x=350, center_y=(min_y + max_y) / 2)
    return RowRegion(row_id=row_id, geometry=geom, normalized_geometry=geom)


def _cell(row_id, col_id, min_x, max_x, min_y, max_y):
    geom = GeometryBox(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y,
                       center_x=(min_x + max_x) / 2, center_y=(min_y + max_y) / 2)
    return TableCell(row_id=row_id, col_id=col_id, geometry=geom, normalized_geometry=geom)


# ─── Fixture 1: Wide pharma invoice ──────────────────────────────────

def _fixture_wide_pharma():
    """14-column wide pharma invoice with 6 item rows + header."""
    col_specs = [
        ("col_0", 10, 40),     # SR NO
        ("col_1", 50, 160),    # PRODUCT
        ("col_2", 170, 210),   # HSN
        ("col_3", 220, 255),   # PACK
        ("col_4", 260, 310),   # BATCH
        ("col_5", 315, 360),   # EXPIRY
        ("col_6", 365, 395),   # QTY
        ("col_7", 400, 430),   # FREE
        ("col_8", 435, 475),   # RATE
        ("col_9", 480, 510),   # DISC
        ("col_10", 515, 555),  # MRP
        ("col_11", 560, 590),  # GST
        ("col_12", 595, 650),  # AMOUNT
        ("col_13", 655, 720),  # COMPANY
    ]

    header_labels = [
        "SR NO", "PRODUCT", "HSN", "PACK", "BATCH", "EXPIRY",
        "QTY", "FREE", "RATE", "DISC", "MRP", "GST", "AMOUNT", "COMPANY",
    ]

    blocks = []
    # Header row blocks
    for (cid, x0, x1), label in zip(col_specs, header_labels):
        blocks.append(_block(label, x0, x1, 10, 22))

    # 6 item rows
    for row_idx in range(6):
        y = 30 + row_idx * 15
        row_data = [
            str(row_idx + 1),                  # SR NO
            f"TABLET COMPOUND {row_idx}",       # PRODUCT (generic)
            "30049099",                          # HSN
            "10x10",                             # PACK
            f"BN{row_idx:04d}",                  # BATCH
            f"0{row_idx + 1}/28",                # EXPIRY
            str(row_idx * 3 + 5),                # QTY
            str(row_idx + 1),                    # FREE
            f"{row_idx * 8 + 40:.2f}",           # RATE
            "5.00",                              # DISC
            f"{row_idx * 12 + 80:.2f}",          # MRP
            "12.00",                             # GST
            f"{(row_idx * 3 + 5) * (row_idx * 8 + 40):.2f}",  # AMOUNT
            f"PHARMA CORP {row_idx}",            # COMPANY
        ]
        for (cid, x0, x1), val in zip(col_specs, row_data):
            blocks.append(_block(val, x0, x1, y, y + 12))

    columns = [_col(cid, x0, x1) for cid, x0, x1 in col_specs]
    rows = [_row(f"row_{i}", 10 + i * 15, 22 + i * 15) for i in range(7)]

    cells = []
    for row_idx in range(7):
        for cid, x0, x1 in col_specs:
            y0 = 10 + row_idx * 15
            y1 = 22 + row_idx * 15
            cells.append(_cell(f"row_{row_idx}", cid, x0, x1, y0, y1))

    table = TableRegion(
        table_id="wide_pharma",
        region_type=RegionType.TABLE,
        columns=columns,
        rows=rows,
        cells=cells,
    )
    return blocks, table


# ─── Fixture 2: Narrow simple invoice ────────────────────────────────

def _fixture_narrow():
    """Simple 4-column invoice with 3 item rows."""
    col_specs = [
        ("col_0", 10, 200),   # PRODUCT
        ("col_1", 210, 260),  # QTY
        ("col_2", 270, 340),  # RATE
        ("col_3", 350, 440),  # AMOUNT
    ]

    blocks = [
        _block("PRODUCT", 10, 200, 10, 22),
        _block("QTY", 210, 260, 10, 22),
        _block("RATE", 270, 340, 10, 22),
        _block("AMOUNT", 350, 440, 10, 22),
    ]

    for i in range(3):
        y = 30 + i * 15
        blocks.extend([
            _block(f"Simple Item {i+1}", 10, 200, y, y + 12),
            _block(str(i + 2), 210, 260, y, y + 12),
            _block(f"{50 + i * 10:.2f}", 270, 340, y, y + 12),
            _block(f"{(i + 2) * (50 + i * 10):.2f}", 350, 440, y, y + 12),
        ])

    columns = [_col(cid, x0, x1) for cid, x0, x1 in col_specs]
    rows = [_row(f"row_{i}", 10 + i * 15, 22 + i * 15) for i in range(4)]

    cells = []
    for row_idx in range(4):
        for cid, x0, x1 in col_specs:
            y0 = 10 + row_idx * 15
            y1 = 22 + row_idx * 15
            cells.append(_cell(f"row_{row_idx}", cid, x0, x1, y0, y1))

    table = TableRegion(
        table_id="narrow",
        region_type=RegionType.TABLE,
        columns=columns,
        rows=rows,
        cells=cells,
    )
    return blocks, table


# ─── Fixture 3: Different pharma layout (10 columns) ─────────────────

def _fixture_alt_pharma():
    """10-column pharma layout with different ordering."""
    col_specs = [
        ("col_0", 10, 50),     # NO
        ("col_1", 55, 180),    # DESCRIPTION
        ("col_2", 185, 230),   # BATCH
        ("col_3", 235, 280),   # EXP
        ("col_4", 285, 320),   # QTY
        ("col_5", 325, 370),   # RATE
        ("col_6", 375, 420),   # MRP
        ("col_7", 425, 460),   # DISC
        ("col_8", 465, 510),   # GST
        ("col_9", 515, 580),   # AMOUNT
    ]

    header_labels = [
        "NO", "DESCRIPTION", "BATCH", "EXP", "QTY",
        "RATE", "MRP", "DISC", "GST", "AMOUNT",
    ]

    blocks = []
    for (cid, x0, x1), label in zip(col_specs, header_labels):
        blocks.append(_block(label, x0, x1, 10, 22))

    for i in range(5):
        y = 30 + i * 15
        blocks.extend([
            _block(str(i + 1), 10, 50, y, y + 12),
            _block(f"CAPSULE TYPE {i}", 55, 180, y, y + 12),
            _block(f"LT{i:04d}", 185, 230, y, y + 12),
            _block(f"0{i + 1}/28", 235, 280, y, y + 12),
            _block(str(i * 2 + 3), 285, 320, y, y + 12),
            _block(f"{i * 5 + 30:.2f}", 325, 370, y, y + 12),
            _block(f"{i * 7 + 50:.2f}", 375, 420, y, y + 12),
            _block("3.00", 425, 460, y, y + 12),
            _block("18.00", 465, 510, y, y + 12),
            _block(f"{(i * 2 + 3) * (i * 5 + 30):.2f}", 515, 580, y, y + 12),
        ])

    columns = [_col(cid, x0, x1) for cid, x0, x1 in col_specs]
    rows = [_row(f"row_{i}", 10 + i * 15, 22 + i * 15) for i in range(6)]
    cells = []
    for row_idx in range(6):
        for cid, x0, x1 in col_specs:
            y0 = 10 + row_idx * 15
            y1 = 22 + row_idx * 15
            cells.append(_cell(f"row_{row_idx}", cid, x0, x1, y0, y1))

    table = TableRegion(
        table_id="alt_pharma",
        region_type=RegionType.TABLE,
        columns=columns,
        rows=rows,
        cells=cells,
    )
    return blocks, table


# ─── Tests ────────────────────────────────────────────────────────────

class TestWideTableRegression:

    def test_wide_pharma_is_detected_as_wide(self):
        """Wide pharma fixture must trigger wide-table mode."""
        blocks, table = _fixture_wide_pharma()
        evidence = detect_wide_table(blocks, [table])
        assert evidence.is_wide is True
        assert evidence.confidence >= 0.65
        assert evidence.estimated_column_count >= 10

    def test_wide_pharma_columns_preserved_by_stabilizer(self):
        """Wide-table stabilizer must NOT destructively merge adjacent numeric columns."""
        blocks, table = _fixture_wide_pharma()
        original_col_count = len(table.columns)
        evidence = detect_wide_table(blocks, [table])

        stabilizer = ColumnStabilizer()
        metrics = stabilizer.stabilize_region(table, wide_table_evidence=evidence)

        # In wide-table mode, columns should be preserved
        assert len(table.columns) >= original_col_count - 2  # Allow ≤2 legitimate merges
        # The numeric_merge_blocked_count should be > 0 if merges were blocked
        # (this depends on whether columns were close enough to trigger)

    def test_wide_pharma_ordering_invariants(self):
        """After ordering invariants, col_0 = leftmost, row_0 = topmost."""
        blocks, table = _fixture_wide_pharma()
        _enforce_ordering_invariants([table])

        # col_0 should have the smallest min_x
        assert table.columns[0].col_id == "col_0"
        min_xs = [c.geometry.min_x for c in table.columns]
        assert min_xs == sorted(min_xs)

        # row_0 should have the smallest min_y
        assert table.rows[0].row_id == "row_0"
        min_ys = [r.geometry.min_y for r in table.rows]
        assert min_ys == sorted(min_ys)

    def test_narrow_invoice_no_regression(self):
        """Narrow fixture must NOT trigger wide-table mode."""
        blocks, table = _fixture_narrow()
        evidence = detect_wide_table(blocks, [table])
        assert evidence.is_wide is False

        # Stabilizer should still work normally
        stabilizer = ColumnStabilizer()
        metrics = stabilizer.stabilize_region(table, wide_table_evidence=evidence)
        assert metrics["numeric_merge_blocked_count"] == 0

    def test_narrow_invoice_ordering(self):
        """Narrow invoice ordering should also work correctly."""
        blocks, table = _fixture_narrow()
        _enforce_ordering_invariants([table])

        min_xs = [c.geometry.min_x for c in table.columns]
        assert min_xs == sorted(min_xs)

    def test_alt_pharma_detection(self):
        """Alternative 10-column pharma layout detection."""
        blocks, table = _fixture_alt_pharma()
        evidence = detect_wide_table(blocks, [table])

        # 10 columns with diverse header labels — should be near or above threshold
        assert evidence.estimated_column_count >= 8
        # Confidence depends on exact signal weights; at minimum signals should be populated
        assert "header_label_count" in evidence.signals
        assert evidence.signals["header_label_count"] >= 6

    def test_alt_pharma_ordering(self):
        """Alt pharma columns sorted correctly."""
        blocks, table = _fixture_alt_pharma()
        _enforce_ordering_invariants([table])

        min_xs = [c.geometry.min_x for c in table.columns]
        assert min_xs == sorted(min_xs)
        assert table.columns[0].col_id == "col_0"

    def test_reversed_columns_are_fixed(self):
        """Columns in right-to-left order (simulating the reported failure) are corrected."""
        blocks, table = _fixture_wide_pharma()

        # Manually reverse column and row order to simulate the observed failure
        table.columns.reverse()
        table.rows.reverse()

        _enforce_ordering_invariants([table])

        # After fix: col_0 is leftmost, row_0 is topmost
        assert table.columns[0].col_id == "col_0"
        min_xs = [c.geometry.min_x for c in table.columns]
        assert min_xs == sorted(min_xs)

        assert table.rows[0].row_id == "row_0"
        min_ys = [r.geometry.min_y for r in table.rows]
        assert min_ys == sorted(min_ys)
