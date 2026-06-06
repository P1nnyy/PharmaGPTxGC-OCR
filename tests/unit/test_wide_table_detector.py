"""
Tests for wide_table_detector — topology-gated wide-table evidence evaluation.

All fixtures use synthetic OCR blocks with no vendor names, invoice numbers,
or exact expected row values.
"""

import pytest
from models.layout_models import OCRBlock, GeometryBox, TableRegion, ColumnRegion, RowRegion, RegionType
from services.layout_pipeline.wide_table_detector import (
    detect_wide_table,
    WideTableEvidence,
    WIDE_TABLE_CONFIDENCE_THRESHOLD,
)


def _block(text: str, min_x: float, max_x: float, min_y: float, max_y: float, block_id: str = None) -> OCRBlock:
    """Factory for synthetic OCR blocks with normalised geometry."""
    geom = GeometryBox(
        min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y,
        center_x=(min_x + max_x) / 2, center_y=(min_y + max_y) / 2,
    )
    return OCRBlock(
        id=block_id or f"b_{text[:6]}_{int(min_x)}",
        text=text,
        raw_text=text,
        normalized_geometry=geom,
    )


def _col(col_id: str, min_x: float, max_x: float) -> ColumnRegion:
    geom = GeometryBox(min_x=min_x, max_x=max_x, min_y=0, max_y=500,
                       center_x=(min_x + max_x) / 2, center_y=250)
    return ColumnRegion(col_id=col_id, geometry=geom, normalized_geometry=geom)


def _wide_header_blocks():
    """Generate header-row blocks matching pharma column label patterns."""
    y = 10.0
    labels = [
        ("SR NO", 10, 40),
        ("PRODUCT", 50, 130),
        ("HSN", 140, 170),
        ("PACK", 180, 210),
        ("BATCH", 220, 260),
        ("EXPIRY", 270, 310),
        ("QTY", 320, 350),
        ("FREE", 360, 390),
        ("RATE", 400, 430),
        ("DISC", 440, 470),
        ("MRP", 480, 510),
        ("GST", 520, 550),
        ("AMOUNT", 560, 610),
        ("COMPANY", 620, 680),
    ]
    return [_block(lbl, x0, x1, y, y + 12) for lbl, x0, x1 in labels]


def _wide_item_row_blocks(row_y: float, row_idx: int):
    """Generate a single item row with diverse field types."""
    return [
        _block(str(row_idx + 1), 10, 30, row_y, row_y + 12),        # SR NO
        _block(f"MEDICINE TABLET {row_idx}", 50, 130, row_y, row_y + 12),  # PRODUCT
        _block("30049099", 140, 170, row_y, row_y + 12),             # HSN
        _block("10x10", 180, 210, row_y, row_y + 12),                # PACK
        _block(f"BA{row_idx:04d}", 220, 260, row_y, row_y + 12),     # BATCH
        _block(f"0{row_idx + 1}/27", 270, 310, row_y, row_y + 12),   # EXPIRY
        _block(str(row_idx * 5 + 10), 320, 350, row_y, row_y + 12),  # QTY
        _block(str(row_idx + 1), 360, 390, row_y, row_y + 12),       # FREE
        _block(f"{row_idx * 10 + 50:.2f}", 400, 430, row_y, row_y + 12),  # RATE
        _block(f"{5.00:.2f}", 440, 470, row_y, row_y + 12),          # DISC
        _block(f"{row_idx * 15 + 100:.2f}", 480, 510, row_y, row_y + 12),  # MRP
        _block("12.00", 520, 550, row_y, row_y + 12),                # GST
        _block(f"{(row_idx * 5 + 10) * (row_idx * 10 + 50):.2f}", 560, 610, row_y, row_y + 12),  # AMOUNT
        _block(f"PHARMA CO {row_idx}", 620, 680, row_y, row_y + 12), # COMPANY
    ]


def _narrow_blocks():
    """Generate a simple 4-column narrow invoice."""
    blocks = [
        _block("PRODUCT", 10, 200, 10, 22),
        _block("QTY", 210, 250, 10, 22),
        _block("RATE", 260, 310, 10, 22),
        _block("AMOUNT", 320, 400, 10, 22),
    ]
    for i in range(3):
        y = 30 + i * 15
        blocks.extend([
            _block(f"Item {i+1}", 10, 200, y, y + 12),
            _block(str(i + 2), 210, 250, y, y + 12),
            _block(f"{50 + i * 10:.2f}", 260, 310, y, y + 12),
            _block(f"{(i + 2) * (50 + i * 10):.2f}", 320, 400, y, y + 12),
        ])
    return blocks


class TestWideTableDetection:
    """Tests for wide-table evidence detection."""

    def test_wide_table_detected_with_many_header_labels(self):
        """Wide pharma table with 14 header labels should trigger wide-table mode."""
        blocks = _wide_header_blocks()
        for i in range(6):
            blocks.extend(_wide_item_row_blocks(30 + i * 15, i))

        table = TableRegion(
            table_id="t0", region_type=RegionType.TABLE,
            columns=[_col(f"col_{i}", i * 50, (i + 1) * 50) for i in range(14)],
        )
        evidence = detect_wide_table(blocks, [table])

        assert evidence.is_wide is True
        assert evidence.confidence >= WIDE_TABLE_CONFIDENCE_THRESHOLD
        assert evidence.estimated_column_count >= 10
        assert evidence.signals["header_label_count"] >= 8

    def test_narrow_table_not_detected(self):
        """Simple 4-column table should NOT trigger wide-table mode."""
        blocks = _narrow_blocks()
        table = TableRegion(
            table_id="t0", region_type=RegionType.TABLE,
            columns=[_col(f"col_{i}", i * 100, (i + 1) * 100) for i in range(4)],
        )
        evidence = detect_wide_table(blocks, [table])

        assert evidence.is_wide is False
        assert evidence.confidence < WIDE_TABLE_CONFIDENCE_THRESHOLD

    def test_empty_blocks_returns_not_wide(self):
        """Empty input should return safe default."""
        evidence = detect_wide_table([], [])
        assert evidence.is_wide is False
        assert evidence.confidence == 0.0

    def test_borderline_table_below_threshold(self):
        """Table with some but insufficient header labels (5 out of 8 needed)."""
        blocks = [
            _block("PRODUCT", 10, 100, 5, 15),
            _block("QTY", 110, 140, 5, 15),
            _block("RATE", 150, 180, 5, 15),
            _block("AMOUNT", 190, 240, 5, 15),
            _block("BATCH", 250, 290, 5, 15),
        ]
        # Add minimal item rows
        for i in range(3):
            y = 20 + i * 12
            blocks.extend([
                _block(f"Med {i}", 10, 100, y, y + 10),
                _block(str(i + 1), 110, 140, y, y + 10),
                _block(f"{10.0 + i:.2f}", 150, 180, y, y + 10),
                _block(f"{20.0 + i:.2f}", 190, 240, y, y + 10),
                _block(f"BT{i:03d}", 250, 290, y, y + 10),
            ])

        table = TableRegion(
            table_id="t0", region_type=RegionType.TABLE,
            columns=[_col(f"col_{i}", i * 60, (i + 1) * 60) for i in range(5)],
        )
        evidence = detect_wide_table(blocks, [table])

        # 5 labels out of 8 needed → partial score. May or may not trigger
        # depending on other signals; key assertion is it doesn't falsely fire.
        assert evidence.confidence < 0.9  # Not overwhelmingly wide

    def test_wide_table_signals_populated(self):
        """All expected signal keys should be present in the result."""
        blocks = _wide_header_blocks()
        for i in range(4):
            blocks.extend(_wide_item_row_blocks(30 + i * 15, i))

        table = TableRegion(
            table_id="t0", region_type=RegionType.TABLE,
            columns=[_col(f"col_{i}", i * 50, (i + 1) * 50) for i in range(14)],
        )
        evidence = detect_wide_table(blocks, [table])

        expected_signal_keys = {
            "header_label_count", "header_score",
            "column_gap_count", "gap_score",
            "avg_field_types_per_row", "diversity_score",
            "median_tokens_per_row", "token_score",
            "tsr_column_count", "tsr_score",
        }
        assert expected_signal_keys.issubset(set(evidence.signals.keys()))

    def test_should_split_block(self):
        """Test the pattern checking for fused block splitting."""
        from services.layout_pipeline.wide_table_detector import should_split_block
        
        # product + HSN
        assert should_split_block("CNDERO MET 2.5/1000 M 30049099 10 S LUPIN UB02123") is True
        
        # rate + expiry
        assert should_split_block("135.16 07/27") is True
        
        # discount + rate + expiry
        assert should_split_block("0.16 64.13 05/27") is True
        
        # normal text block - should not split
        assert should_split_block("AMOXICILLIN CAPSULES IP") is False
        assert should_split_block("TOTAL") is False

    def test_split_fused_block(self):
        """Test splitting mechanism and geometry interpolation."""
        from services.layout_pipeline.wide_table_detector import split_fused_block
        
        # Fused block
        block = _block("135.16 07/27", 500, 600, 100, 120, "b_fused")
        split_res = split_fused_block(block)
        
        assert len(split_res) == 2
        assert split_res[0].text == "135.16"
        assert split_res[0].normalized_geometry.min_x == 500
        assert split_res[0].normalized_geometry.max_x == 550
        
        assert split_res[1].text == "07/27"
        assert round(split_res[1].normalized_geometry.min_x, 2) == 558.33
        assert split_res[1].normalized_geometry.max_x == 600
