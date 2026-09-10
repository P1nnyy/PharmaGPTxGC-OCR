"""Recording what an invoice put on the shelf.

The stock ledger only ever had sales in it: `save_counter_sale` wrote negative
movements and nothing wrote positive ones, so a "running balance" could only
ever count down. Purchases are the other half, and they also carry the cost
basis every margin figure is computed against.

The generation behaviour is what these tests are really for. `update_invoice`
deletes an invoice's line items and recreates them with new ids on every edit,
so the obvious design - one movement per line item id - would leave the old
movements orphaned and still counted. Stock and cost basis would both double
on a correction, which is the duplicate-ingestion failure the house rules call
the highest-severity class of bug in this codebase.
"""

import pytest

from db.repositories.invoice_repository import (
    _generation_key,
    _purchase_rows,
    _replace_purchase_movements,
)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class FakeTx:
    """Records the statements run against it, and answers reads from fixtures."""

    def __init__(self, lines=(), live_generation=None):
        self.lines = list(lines)
        self.live_generation = live_generation
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        if "CONTAINS]->(li:LineItem)" in query and "RETURN li.id" in query:
            return FakeResult(self.lines)
        if "RETURN DISTINCT m.generation_key" in query:
            return FakeResult(
                [{"generation_key": self.live_generation}] if self.live_generation else []
            )
        return FakeResult([])

    def statements(self, fragment):
        return [c for c in self.calls if fragment in c[0]]


def line(**kwargs):
    base = {
        "line_item_id": "L1", "row_index": 0, "product_id": "P1",
        "batch_number": "B1", "expiry": "2027-03-31",
        "quantity": 10.0, "free_quantity": 2.0,
        "amount": 1000.0, "mrp": 150.0, "gst_percent": 12.0,
        "vendor_id": "V1", "occurred_on": "2026-09-03", "pharmacy_id": "ph-1",
    }
    base.update(kwargs)
    return base


class TestPurchaseRows:
    def test_received_quantity_is_billed_plus_free(self):
        # A 10+2 scheme puts twelve packs on the shelf. Costing them as ten
        # would overstate unit cost by a fifth.
        rows = _purchase_rows(FakeTx([line()]), "INV-1")
        assert rows[0]["received"] == 12.0

    def test_cost_is_carried_as_a_total_not_a_unit_price(self):
        # So the weighted average is taken once over sums, rather than
        # averaging figures that were each rounded.
        rows = _purchase_rows(FakeTx([line()]), "INV-1")
        assert rows[0]["taxable_paise"] == 100000
        assert "unit_cost_paise" not in rows[0]

    def test_input_tax_is_computed_from_the_stored_rate(self):
        # 12% of ₹1,000.00 is ₹120.00 - the credit that has to go back if this
        # stock is destroyed rather than returned.
        rows = _purchase_rows(FakeTx([line()]), "INV-1")
        assert rows[0]["gst_rate_bp"] == 1200
        assert rows[0]["input_tax_paise"] == 12000

    def test_a_line_with_no_matched_product_moves_nothing(self):
        # It cannot move a product's stock, so it is left out rather than
        # written as a movement nobody can act on.
        assert _purchase_rows(FakeTx([line(product_id=None)]), "INV-1") == []

    def test_a_line_with_no_quantity_moves_nothing(self):
        assert _purchase_rows(FakeTx([line(quantity=0.0, free_quantity=0.0)]), "INV-1") == []

    def test_free_goods_alone_still_count_as_stock(self):
        rows = _purchase_rows(FakeTx([line(quantity=0.0, free_quantity=5.0)]), "INV-1")
        assert rows and rows[0]["received"] == 5.0

    def test_money_crosses_the_float_boundary_into_paise(self):
        rows = _purchase_rows(FakeTx([line(amount=1234.5600000000001, mrp=99.99)]), "INV-1")
        assert rows[0]["taxable_paise"] == 123456
        assert rows[0]["mrp_paise"] == 9999


class TestGenerationKey:
    def test_the_same_lines_fingerprint_the_same(self):
        rows = _purchase_rows(FakeTx([line()]), "INV-1")
        again = _purchase_rows(FakeTx([line()]), "INV-1")
        assert _generation_key(rows) == _generation_key(again)

    def test_a_changed_quantity_changes_the_fingerprint(self):
        before = _purchase_rows(FakeTx([line()]), "INV-1")
        after = _purchase_rows(FakeTx([line(quantity=11.0)]), "INV-1")
        assert _generation_key(before) != _generation_key(after)

    def test_a_changed_cost_changes_the_fingerprint(self):
        before = _purchase_rows(FakeTx([line()]), "INV-1")
        after = _purchase_rows(FakeTx([line(amount=1100.0)]), "INV-1")
        assert _generation_key(before) != _generation_key(after)

    def test_a_new_line_item_id_alone_does_not(self):
        # This is the whole point. Editing an invoice recreates its lines with
        # fresh ids; if that alone counted as a change, every correction would
        # supersede and rewrite a generation that says exactly the same thing.
        before = _purchase_rows(FakeTx([line(line_item_id="L1")]), "INV-1")
        after = _purchase_rows(FakeTx([line(line_item_id="L-new")]), "INV-1")
        assert _generation_key(before) == _generation_key(after)


class TestReplacePurchaseMovements:
    def test_writes_movements_for_an_invoice_with_none(self):
        tx = FakeTx([line()])
        _replace_purchase_movements(tx, "INV-1")
        created = tx.statements("CREATE (m:StockMovement")
        assert len(created) == 1
        query, params = created[0]
        rows = params["rows"]
        assert rows[0]["received"] == 12.0
        assert rows[0]["taxable_paise"] == 100000
        # The statement is what turns a received quantity into a positive
        # delta; a purchase that decremented stock would be silent and fatal.
        assert "quantity_delta: row.received" in query
        assert "reason: 'PURCHASE'" in query

    def test_verifying_again_unchanged_leaves_the_ledger_alone(self):
        rows = _purchase_rows(FakeTx([line()]), "INV-1")
        tx = FakeTx([line()], live_generation=_generation_key(rows))
        _replace_purchase_movements(tx, "INV-1")
        assert tx.statements("CREATE (m:StockMovement") == []
        assert tx.statements("SET m.superseded_by") == []

    def test_a_correction_supersedes_the_live_generation_before_writing(self):
        tx = FakeTx([line(quantity=11.0)], live_generation="an-older-fingerprint")
        _replace_purchase_movements(tx, "INV-1")
        superseded = tx.statements("SET m.superseded_by")
        created = tx.statements("CREATE (m:StockMovement")
        assert len(superseded) == 1
        assert len(created) == 1
        # Order matters: superseding after writing would leave a window in
        # which both generations are live and the stock reads double.
        assert tx.calls.index(superseded[0]) < tx.calls.index(created[0])

    def test_superseding_never_deletes(self):
        tx = FakeTx([line(quantity=11.0)], live_generation="older")
        _replace_purchase_movements(tx, "INV-1")
        assert not any("DELETE" in query for query, _ in tx.calls)

    def test_an_invoice_whose_lines_all_became_unmatched_still_supersedes(self):
        # Every line lost its product match on a correction. The old movements
        # must stop counting even though there is nothing to replace them with.
        tx = FakeTx([line(product_id=None)], live_generation="older")
        _replace_purchase_movements(tx, "INV-1")
        assert len(tx.statements("SET m.superseded_by")) == 1
        assert tx.statements("CREATE (m:StockMovement") == []

    def test_movements_point_back_at_the_invoice_that_caused_them(self):
        tx = FakeTx([line()])
        _replace_purchase_movements(tx, "INV-1")
        query, params = tx.statements("CREATE (m:StockMovement")[0]
        assert "CREATE (m)-[:CAUSED_BY]->(inv)" in query
        assert params["id"] == "INV-1"
        assert params["rows"][0]["line_item_id"] == "L1"
        assert "source_line_id: row.line_item_id" in query
        assert "source_id: $id" in query
