"""Stock-on-hand composition, with Cypher stubbed.

What is under test is the reading the page depends on: which rows count as
low or expiring, how the totals are formed, and that the status filter means
what the route says it means.
"""

from datetime import date, timedelta
from unittest.mock import patch

from api.routers.inventory import stock as stock_route
from db.repositories import inventory_repository
from db.repositories.inventory_repository import _parse_expiry, stock_on_hand


def row(**overrides) -> dict:
    base = {
        "group_key": "p1",
        "batch_number": "B1",
        "product": "MONTICOPE SUSPENSION 60 ML",
        "product_id": "p1",
        "expiry": "2030-06-30",
        "mrp": 120.5,
        "gst": 12.0,
        "latest_invoice": "INV-1",
        "quantity": 40.0,
        "free_quantity": 0.0,
        "deliveries": 1,
    }
    base.update(overrides)
    return base


def run_with(rows):
    return patch.object(inventory_repository, "_run", return_value=rows)


class TestExpiryParsing:
    def test_reads_the_iso_form_written_today(self):
        assert _parse_expiry("2026-08-31") == date(2026, 8, 31)

    def test_reads_the_legacy_mm_yy_form(self):
        # Month precision runs to the end of the month, so August is the 31st.
        assert _parse_expiry("08/26") == date(2026, 8, 31)

    def test_december_rolls_into_the_next_year(self):
        assert _parse_expiry("12/25") == date(2025, 12, 31)

    def test_unreadable_expiry_is_unknown_not_expired(self):
        # The distinction matters: defaulting to "expired" would write good
        # stock off, and defaulting to a date would invent one.
        assert _parse_expiry("n/a") is None
        assert _parse_expiry("") is None
        assert _parse_expiry(None) is None


class TestFlags:
    def test_low_stock_is_at_or_below_the_threshold(self):
        rows = [row(group_key="a", quantity=10.0), row(group_key="b", quantity=11.0)]
        with run_with(rows):
            result = stock_on_hand()
        assert [i["is_low_stock"] for i in result["items"]] == [True, False]
        assert result["stats"]["low_stock"] == 1

    def test_expiring_soon_moves_with_the_calendar(self):
        soon = (date.today() + timedelta(days=30)).isoformat()
        later = (date.today() + timedelta(days=400)).isoformat()
        with run_with([row(group_key="a", expiry=soon), row(group_key="b", expiry=later)]):
            result = stock_on_hand()
        assert [i["is_expiring_soon"] for i in result["items"]] == [True, False]

    def test_already_expired_is_not_counted_as_expiring_soon(self):
        gone = (date.today() - timedelta(days=1)).isoformat()
        with run_with([row(expiry=gone)]):
            result = stock_on_hand()
        item = result["items"][0]
        assert item["is_expired"] is True
        assert item["is_expiring_soon"] is False
        assert result["stats"]["expired"] == 1

    def test_unknown_expiry_is_neither(self):
        with run_with([row(expiry=None)]):
            item = stock_on_hand()["items"][0]
        assert item["is_expired"] is False
        assert item["is_expiring_soon"] is False


class TestTotals:
    def test_counts_holdings_not_deliveries(self):
        # Two batches of one product are two holdings; the Cypher has already
        # collapsed repeat deliveries of the same batch into one row.
        rows = [row(batch_number="B1", quantity=10.0), row(batch_number="B2", quantity=5.0)]
        with run_with(rows):
            stats = stock_on_hand()["stats"]
        assert stats["total_skus"] == 2
        assert stats["total_quantity"] == 15.0

    def test_id_is_stable_and_distinguishes_batches(self):
        rows = [row(batch_number="B1"), row(batch_number="B2")]
        with run_with(rows):
            ids = [i["id"] for i in stock_on_hand()["items"]]
        assert ids == ["p1::B1", "p1::B2"]
        assert len(set(ids)) == 2

    def test_a_batchless_holding_still_gets_an_id(self):
        with run_with([row(batch_number=None)]):
            assert stock_on_hand()["items"][0]["id"] == "p1::-"

    def test_empty_graph_reports_zeroes_rather_than_failing(self):
        with run_with([]):
            result = stock_on_hand()
        assert result["items"] == []
        assert result["stats"]["total_skus"] == 0
        assert result["stats"]["total_quantity"] == 0


class TestRouteScoping:
    def test_defaults_to_verified_only(self):
        with patch.object(inventory_repository, "stock_on_hand", return_value={}) as call:
            stock_route(statuses=None)
        assert call.call_args.kwargs["statuses"] == ["verified"]

    def test_all_widens_to_every_status(self):
        with patch.object(inventory_repository, "stock_on_hand", return_value={}) as call:
            stock_route(statuses="all")
        assert call.call_args.kwargs["statuses"] is None

    def test_an_explicit_list_is_passed_through(self):
        with patch.object(inventory_repository, "stock_on_hand", return_value={}) as call:
            stock_route(statuses="verified, needs_review")
        assert call.call_args.kwargs["statuses"] == ["verified", "needs_review"]
