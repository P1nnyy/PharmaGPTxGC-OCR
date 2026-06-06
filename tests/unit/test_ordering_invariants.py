"""
Tests for universal ordering invariants (_enforce_ordering_invariants).

Verifies that columns are sorted by min_x ascending (leftmost = col_0),
rows are sorted by min_y ascending (topmost = row_0), and cell references
are correctly remapped.
"""

import pytest
from models.layout_models import (
    GeometryBox, TableRegion, ColumnRegion, RowRegion, TableCell, RegionType,
)
from services.spatial_reconstruction import _enforce_ordering_invariants


def _geom(min_x, min_y, max_x, max_y):
    return GeometryBox(
        min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y,
        center_x=(min_x + max_x) / 2, center_y=(min_y + max_y) / 2,
    )


def _make_table(columns, rows, cells):
    """Build a TableRegion from specs."""
    col_objs = [
        ColumnRegion(col_id=cid, geometry=_geom(*bounds), normalized_geometry=_geom(*bounds))
        for cid, bounds in columns
    ]
    row_objs = [
        RowRegion(row_id=rid, geometry=_geom(*bounds), normalized_geometry=_geom(*bounds))
        for rid, bounds in rows
    ]
    cell_objs = [
        TableCell(row_id=rid, col_id=cid, text=text, geometry=_geom(0, 0, 10, 10))
        for rid, cid, text in cells
    ]
    return TableRegion(
        table_id="test_table",
        region_type=RegionType.TABLE,
        columns=col_objs,
        rows=row_objs,
        cells=cell_objs,
    )


class TestOrderingInvariants:
    """Tests for _enforce_ordering_invariants."""

    def test_columns_sorted_left_to_right(self):
        """Columns in reverse x-order should be sorted to left-to-right."""
        # Columns are in reverse order: rightmost first
        table = _make_table(
            columns=[
                ("col_2", (200, 0, 300, 100)),  # rightmost
                ("col_1", (100, 0, 200, 100)),  # middle
                ("col_0", (0, 0, 100, 100)),    # leftmost
            ],
            rows=[("row_0", (0, 0, 300, 50))],
            cells=[
                ("row_0", "col_0", "left"),
                ("row_0", "col_1", "middle"),
                ("row_0", "col_2", "right"),
            ],
        )

        _enforce_ordering_invariants([table])

        # After sorting, col_0 should be the leftmost (x=0..100)
        assert table.columns[0].col_id == "col_0"
        assert table.columns[0].geometry.min_x == 0
        assert table.columns[1].col_id == "col_1"
        assert table.columns[1].geometry.min_x == 100
        assert table.columns[2].col_id == "col_2"
        assert table.columns[2].geometry.min_x == 200

    def test_rows_sorted_top_to_bottom(self):
        """Rows in reverse y-order should be sorted top-to-bottom."""
        table = _make_table(
            columns=[("col_0", (0, 0, 100, 200))],
            rows=[
                ("row_2", (0, 150, 100, 200)),  # bottom
                ("row_0", (0, 0, 100, 50)),     # top
                ("row_1", (0, 50, 100, 150)),   # middle
            ],
            cells=[
                ("row_0", "col_0", "top_cell"),
                ("row_1", "col_0", "mid_cell"),
                ("row_2", "col_0", "bot_cell"),
            ],
        )

        _enforce_ordering_invariants([table])

        assert table.rows[0].row_id == "row_0"
        assert table.rows[0].geometry.min_y == 0
        assert table.rows[1].row_id == "row_1"
        assert table.rows[1].geometry.min_y == 50
        assert table.rows[2].row_id == "row_2"
        assert table.rows[2].geometry.min_y == 150

    def test_cell_references_remapped(self):
        """Cell col_id and row_id should be remapped after sorting."""
        # Start with reversed IDs that don't match physical order
        table = _make_table(
            columns=[
                ("old_right", (200, 0, 300, 100)),
                ("old_left", (0, 0, 100, 100)),
            ],
            rows=[
                ("old_bottom", (0, 100, 300, 200)),
                ("old_top", (0, 0, 300, 100)),
            ],
            cells=[
                ("old_top", "old_left", "top_left"),
                ("old_top", "old_right", "top_right"),
                ("old_bottom", "old_left", "bot_left"),
                ("old_bottom", "old_right", "bot_right"),
            ],
        )

        _enforce_ordering_invariants([table])

        # After remapping:
        # old_left (x=0) → col_0, old_right (x=200) → col_1
        # old_top (y=0) → row_0, old_bottom (y=100) → row_1
        cell_lookup = {(c.row_id, c.col_id): c.text for c in table.cells}
        assert cell_lookup[("row_0", "col_0")] == "top_left"
        assert cell_lookup[("row_0", "col_1")] == "top_right"
        assert cell_lookup[("row_1", "col_0")] == "bot_left"
        assert cell_lookup[("row_1", "col_1")] == "bot_right"

    def test_already_sorted_is_idempotent(self):
        """Calling on already-sorted data should produce the same result."""
        table = _make_table(
            columns=[
                ("col_0", (0, 0, 100, 100)),
                ("col_1", (100, 0, 200, 100)),
            ],
            rows=[
                ("row_0", (0, 0, 200, 50)),
                ("row_1", (0, 50, 200, 100)),
            ],
            cells=[
                ("row_0", "col_0", "a"),
                ("row_0", "col_1", "b"),
                ("row_1", "col_0", "c"),
                ("row_1", "col_1", "d"),
            ],
        )

        _enforce_ordering_invariants([table])

        assert table.columns[0].col_id == "col_0"
        assert table.columns[1].col_id == "col_1"
        assert table.rows[0].row_id == "row_0"
        assert table.rows[1].row_id == "row_1"

    def test_empty_table_no_crash(self):
        """Empty table should not raise."""
        table = TableRegion(table_id="empty", region_type=RegionType.TABLE)
        _enforce_ordering_invariants([table])
        assert len(table.columns) == 0
        assert len(table.rows) == 0
