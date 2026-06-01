import pytest
import json
from decimal import Decimal
from models.layout_models import TableRegion, TableCell, RowRegion, GeometryBox
from services.financial_reconciler import reconcile_invoice_financials

def _geom(x=0, y=0):
    """Utility to construct a mock GeometryBox."""
    return GeometryBox(min_x=float(x), max_x=float(x + 10), min_y=float(y), max_y=float(y + 10), center_x=float(x + 5), center_y=float(y + 5))

def _row(row_id="row_1", role="footer_summary_row", y=0):
    """Utility to construct a mock RowRegion."""
    return RowRegion(row_id=row_id, row_role=role, geometry=_geom(y=y))

def _cell(row_id, col_id, text, x=0, y=0):
    """Utility to construct a mock TableCell."""
    return TableCell(row_id=row_id, col_id=col_id, text=text, geometry=_geom(x=x, y=y))

def test_subtotal_discount_sharing_conflict():
    # Test that "SUB TOTAL Discount 2229.34" sharing a single cell/value
    # avoids assigning 2229.34 to discount (which belongs to subtotal).
    table = TableRegion(
        table_id="heuristic_region_7",
        rows=[_row("row_14", y=10)],
        cells=[
            _cell("row_14", "col_0", "SUB TOTAL Discount", x=0, y=10),
            _cell("row_14", "col_1", "2229.34", x=100, y=10)
        ],
        geometry=_geom()
    )
    main_recon = {"derived_subtotal": "2229.34"}
    res = reconcile_invoice_financials(main_recon, [table])
    
    assert res["parsed_subtotal"] == 2229.34
    assert res["discount"] == 0.0 or res["discount"] is None

def test_discount_separate_value():
    # Test that "Discount 133.75" extracts discount correctly.
    table = TableRegion(
        table_id="heuristic_region_6",
        rows=[_row("row_13", y=20)],
        cells=[
            _cell("row_13", "col_0", "Discount", x=0, y=20),
            _cell("row_13", "col_1", "133.75", x=100, y=20)
        ],
        geometry=_geom()
    )
    main_recon = {"derived_subtotal": "2229.34"}
    res = reconcile_invoice_financials(main_recon, [table])
    assert res["discount"] == 133.75

def test_sgst_cgst_extraction():
    # Test that SGST and CGST values are extracted correctly from adjacent text and cells.
    table = TableRegion(
        table_id="heuristic_region_6",
        rows=[
            _row("row_11", y=30),
            _row("row_12", y=40)
        ],
        cells=[
            _cell("row_11", "col_0", "SGST 2.5", x=0, y=30),
            _cell("row_11", "col_1", "52.38", x=100, y=30),
            _cell("row_12", "col_0", "CGST 2.5", x=0, y=40),
            _cell("row_12", "col_1", "52.38", x=100, y=40)
        ],
        geometry=_geom()
    )
    main_recon = {"derived_subtotal": "2229.34"}
    res = reconcile_invoice_financials(main_recon, [table])
    assert res["sgst"] == 52.38
    assert res["cgst"] == 52.38

def test_roundoff_extraction():
    # Test that Roundoff is extracted correctly.
    table = TableRegion(
        table_id="heuristic_region_6",
        rows=[_row("row_10", y=50)],
        cells=[
            _cell("row_10", "col_0", "Roundoff", x=0, y=50),
            _cell("row_10", "col_1", "0.35", x=100, y=50)
        ],
        geometry=_geom()
    )
    main_recon = {"derived_subtotal": "2229.34"}
    res = reconcile_invoice_financials(main_recon, [table])
    assert res["roundoff"] == 0.35

def test_grand_total_extraction():
    # Test that GRAND TOTAL is extracted correctly.
    table = TableRegion(
        table_id="heuristic_region_5",
        rows=[_row("row_8", y=60)],
        cells=[
            _cell("row_8", "col_0", "GRAND TOTAL", x=0, y=60),
            _cell("row_8", "col_1", "2200.00", x=100, y=60)
        ],
        geometry=_geom()
    )
    main_recon = {"derived_subtotal": "2229.34"}
    res = reconcile_invoice_financials(main_recon, [table])
    assert res["parsed_grand_total"] == 2200.00

def test_diagnostics_serializability():
    # Test that the returned diagnostics structure is JSON serializable.
    table = TableRegion(
        table_id="heuristic_region_5",
        rows=[_row("row_8", y=60)],
        cells=[
            _cell("row_8", "col_0", "GRAND TOTAL", x=0, y=60),
            _cell("row_8", "col_1", "2200.00", x=100, y=60)
        ],
        geometry=_geom()
    )
    main_recon = {"derived_subtotal": "2229.34"}
    res = reconcile_invoice_financials(main_recon, [table])
    
    assert "footer_label_value_diagnostics" in res
    diag = res["footer_label_value_diagnostics"]
    assert "candidates" in diag
    assert "selected" in diag
    assert "warnings" in diag
    
    # Try serializing
    serialized = json.dumps(diag)
    assert len(serialized) > 0
