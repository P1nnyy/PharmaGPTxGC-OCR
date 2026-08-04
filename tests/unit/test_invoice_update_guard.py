"""Refusing a save that would delete every line item on an invoice.

Why the guard exists
--------------------
`update_invoice` replaces line items wholesale: it deletes the invoice's rows
and rewrites them from the request body. The review page always sends the full
table, so the payload is normally the 16 rows the user just checked.

An empty array is the dangerous case, because at the repository layer it is
indistinguishable from its innocent twin. "The user deleted all the rows" and
"a save fired before the fetch resolved" arrive as the same bytes, and one of
them destroys a verified invoice with no warning and no undo.

So emptiness alone is not accepted as consent. The caller must say so with
allow_empty_line_items, which is precisely the thing a payload sent by accident
will never do.
"""

import pytest
from unittest.mock import patch

from db.invoice_repository import (
    EmptyLineItemsError,
    _update_invoice_tx,
)


class FakeResult:
    def __init__(self, row):
        self._row = row

    def single(self):
        return self._row


class FakeTx:
    """Records every Cypher statement so a test can assert what was written."""

    def __init__(self, invoice_exists=True, existing_item_count=0):
        self.invoice_exists = invoice_exists
        self.existing_item_count = existing_item_count
        self.queries = []

    def run(self, query, **params):
        self.queries.append((" ".join(query.split()), params))
        if "RETURN inv.id AS id" in query:
            return FakeResult({"id": params.get("id")} if self.invoice_exists else None)
        if "count(li) AS n" in query:
            return FakeResult({"n": self.existing_item_count})
        if "MERGE (p:Product" in query:
            return FakeResult({"id": "product-1"})
        return FakeResult(None)

    # -- helpers -----------------------------------------------------------
    def ran(self, fragment):
        return any(fragment in q for q, _ in self.queries)

    @property
    def deleted_line_items(self):
        return self.ran("DETACH DELETE li")


ITEM = {"name": "STERIVON H/S (R.BOTT) 100 ML", "quantity": 4, "amount": 152.0}


# --------------------------------------------------------------------------
# The destructive case
# --------------------------------------------------------------------------

def test_empty_array_is_refused_when_the_invoice_has_items():
    tx = FakeTx(existing_item_count=16)

    with pytest.raises(EmptyLineItemsError) as exc:
        _update_invoice_tx(tx, "inv-1", {}, [], None)

    assert exc.value.existing_count == 16
    assert exc.value.invoice_id == "inv-1"


def test_nothing_is_deleted_when_the_save_is_refused():
    """The point of the guard: the rows survive."""
    tx = FakeTx(existing_item_count=16)

    with pytest.raises(EmptyLineItemsError):
        _update_invoice_tx(tx, "inv-1", {}, [], None)

    assert not tx.deleted_line_items


def test_header_is_not_written_when_the_save_is_refused():
    """Refusing must leave the invoice wholly untouched, not half-updated with
    totals that no longer match the rows still sitting under them."""
    tx = FakeTx(existing_item_count=16)

    with pytest.raises(EmptyLineItemsError):
        _update_invoice_tx(tx, "inv-1", {"grand_total": 9999.0}, [], None)

    assert not tx.ran("SET inv.grand_total")
    assert not any("SET" in q for q, _ in tx.queries)


def test_the_error_says_how_much_was_at_stake():
    tx = FakeTx(existing_item_count=16)

    with pytest.raises(EmptyLineItemsError, match="16 line item"):
        _update_invoice_tx(tx, "inv-1", {}, [], None)


# --------------------------------------------------------------------------
# Cases that must still go through
# --------------------------------------------------------------------------

def test_explicit_opt_in_clears_the_table():
    """A user who deletes all the rows themselves is allowed to save that."""
    tx = FakeTx(existing_item_count=16)

    assert _update_invoice_tx(tx, "inv-1", {}, [], None, allow_empty_line_items=True) is True
    assert tx.deleted_line_items


def test_empty_array_is_fine_when_there_is_nothing_to_lose():
    """An invoice with no rows yet: the replacement is a no-op, not a loss."""
    tx = FakeTx(existing_item_count=0)

    assert _update_invoice_tx(tx, "inv-1", {}, [], None) is True


def test_a_normal_save_is_untouched_by_the_guard():
    # How a row is written is _write_line_item's business and varies by branch;
    # stub it so this stays a test of the guard letting the save through.
    with patch("db.invoice_repository._write_line_item") as write_item:
        tx = FakeTx(existing_item_count=16)

        assert _update_invoice_tx(tx, "inv-1", {"grand_total": 2278.0}, [ITEM], None) is True

    assert tx.deleted_line_items
    assert tx.ran("SET inv.grand_total")
    assert write_item.call_count == 1


def test_omitting_line_items_still_updates_only_the_header():
    """None means "not editing the table" and must never touch the rows."""
    tx = FakeTx(existing_item_count=16)

    assert _update_invoice_tx(tx, "inv-1", {"seller_name": "ARORA BROS"}, None, None) is True
    assert not tx.deleted_line_items
    assert tx.ran("SET inv.seller_name")


def test_status_only_save_does_not_touch_the_rows():
    tx = FakeTx(existing_item_count=16)

    assert _update_invoice_tx(tx, "inv-1", {}, None, "verified") is True
    assert not tx.deleted_line_items
    assert tx.ran("SET inv.status")


def test_missing_invoice_is_reported_before_the_guard_runs():
    """A 404 must not be reported as a conflict."""
    tx = FakeTx(invoice_exists=False, existing_item_count=0)

    assert _update_invoice_tx(tx, "nope", {}, [], None) is False


# --------------------------------------------------------------------------
# The HTTP surface
# --------------------------------------------------------------------------

def test_route_turns_the_refusal_into_409():
    """409, not 500: the request is well-formed, it conflicts with the invoice's
    current state, and the client can act on it."""
    from fastapi import HTTPException
    from api.routes import update_invoice, InvoiceUpdate

    with patch(
        "api.routes.invoice_repository.update_invoice",
        side_effect=EmptyLineItemsError("inv-1", 16),
    ):
        with pytest.raises(HTTPException) as exc:
            update_invoice("inv-1", InvoiceUpdate(line_items=[]))

    assert exc.value.status_code == 409
    assert "16 line item" in exc.value.detail


def test_route_defaults_the_opt_in_to_false():
    """A client that has never heard of the flag gets the safe behaviour."""
    from api.routes import update_invoice, InvoiceUpdate

    with patch("api.routes.invoice_repository.update_invoice", return_value=True) as mock_update, \
         patch("api.routes.invoice_repository.get_invoice", return_value={}), \
         patch("api.routes._attach_image_urls"):
        update_invoice("inv-1", InvoiceUpdate(line_items=[]))

    assert mock_update.call_args.kwargs["allow_empty_line_items"] is False


def test_route_forwards_an_explicit_opt_in():
    from api.routes import update_invoice, InvoiceUpdate

    with patch("api.routes.invoice_repository.update_invoice", return_value=True) as mock_update, \
         patch("api.routes.invoice_repository.get_invoice", return_value={}), \
         patch("api.routes._attach_image_urls"):
        update_invoice("inv-1", InvoiceUpdate(line_items=[], allow_empty_line_items=True))

    assert mock_update.call_args.kwargs["allow_empty_line_items"] is True
