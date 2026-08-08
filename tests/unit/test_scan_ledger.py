"""Counting scans in a way that deleting an invoice cannot change.

The question being answered
---------------------------
"How many scans have I run?" is a measure of work done. Counting invoices
answers a different question - "how many invoices do I currently have" - and
the two diverge the moment anyone deletes a misfire, a duplicate or a test.
Worse, they diverge silently and in the wrong direction: the number of scans
you have run cannot go down, but a count of invoices does.

So the ledger row is written when the scan happens and never deleted, and it
holds the invoice id as a plain property rather than a relationship. That is
the load-bearing detail: DETACH DELETE follows edges, so an invoice with no
edge to its ledger row cannot take the row with it.
"""

import pytest

from db.repositories import scan_repository
from db.repositories.scan_repository import (
    GRANULARITIES,
    _TRUNCATE,
    _activity_tx,
    _record_tx,
)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeTx:
    def __init__(self, totals=None, surviving=0, series=None):
        self.totals = totals or {"scans": 0, "pages": 0, "without_invoice": 0,
                                 "first_scan": None, "last_scan": None}
        self.surviving = surviving
        self.series = series or []
        self.queries = []

    def run(self, query, **params):
        flat = " ".join(query.split())
        self.queries.append((flat, params))
        # Order matters: the series query also selects count(e) AS scans, so
        # the bucket check has to come before the totals check.
        if "AS bucket" in flat:
            return FakeResult(self.series)
        if "EXISTS { MATCH (inv:Invoice" in flat:
            return FakeResult([{"n": self.surviving}])
        if "count(e) AS scans" in flat:
            return FakeResult([self.totals])
        if "CREATE (e:ScanEvent" in flat:
            return FakeResult([{"id": "scan-1"}])
        return FakeResult([])

    def ran(self, fragment):
        return any(fragment in q for q, _ in self.queries)


# --------------------------------------------------------------------------
# The property that makes the whole thing work
# --------------------------------------------------------------------------

def test_the_invoice_link_is_a_property_not_a_relationship():
    """A relationship would be followed by the invoice's DETACH DELETE, taking
    the ledger row with it and reintroducing exactly the bug this prevents."""
    tx = FakeTx()
    _record_tx(tx, "ph-1", 2, "inv-9", "extracted", "azure", "bill.jpg")

    create = next(q for q, _ in tx.queries if "CREATE (e:ScanEvent" in q)
    assert "invoice_id: $invoice_id" in create
    assert "-[:" not in create, "the ledger must not be joined to the invoice by an edge"


def test_a_scan_whose_invoice_is_gone_still_counts():
    """The reason the ledger exists: 5 scans run, 3 invoices still present."""
    tx = FakeTx(totals={"scans": 5, "pages": 7, "without_invoice": 0,
                        "first_scan": None, "last_scan": None},
                surviving=3)

    result = _activity_tx(tx, "month", 24, "ph-1")

    assert result["total_scans"] == 5
    assert result["scans_with_invoice"] == 3
    assert result["scans_without_invoice"] == 2


# --------------------------------------------------------------------------
# Buckets
# --------------------------------------------------------------------------

@pytest.mark.parametrize("granularity", ["day", "month", "year"])
def test_each_granularity_truncates_to_its_own_bucket(granularity):
    tx = FakeTx(series=[{"bucket": "2026-08-01", "scans": 2, "pages": 3}])
    _activity_tx(tx, granularity, 24, "ph-1")
    assert tx.ran(f"date.truncate('{granularity}', e.created_at)")


def test_all_time_asks_for_no_series():
    """'all' is the absence of a bucket, so there is no series to draw."""
    tx = FakeTx(totals={"scans": 9, "pages": 12, "without_invoice": 1,
                        "first_scan": None, "last_scan": None})
    result = _activity_tx(tx, "all", 24, "ph-1")

    assert result["series"] == []
    assert result["total_scans"] == 9
    assert not tx.ran("date.truncate")


def test_the_series_comes_back_oldest_first():
    """A chart reads left to right; the query sorts DESC to apply LIMIT to the
    most recent buckets, so the order is restored before it leaves."""
    tx = FakeTx(series=[
        {"bucket": "2026-08-01", "scans": 3, "pages": 4},
        {"bucket": "2026-07-01", "scans": 1, "pages": 1},
    ])
    result = _activity_tx(tx, "month", 24, "ph-1")

    assert [row["bucket"] for row in result["series"]] == ["2026-07-01", "2026-08-01"]


def test_every_offered_granularity_can_actually_be_computed():
    """Guards the two lists drifting apart - an offered bucket with no
    truncation rule would raise KeyError at query time."""
    for granularity in GRANULARITIES:
        assert granularity == "all" or granularity in _TRUNCATE


def test_an_unknown_granularity_falls_back_rather_than_failing():
    tx = FakeTx()
    assert _activity_tx(tx, "month", 24, "ph-1")["granularity"] == "month"


# --------------------------------------------------------------------------
# The ledger must never break an upload
# --------------------------------------------------------------------------

def test_a_ledger_failure_does_not_propagate(monkeypatch):
    """The caller is midway through returning a good invoice. Losing the count
    is a smaller harm than turning a successful upload into a 500."""
    def boom():
        raise RuntimeError("neo4j unavailable")

    monkeypatch.setattr(scan_repository, "get_driver", boom)
    assert scan_repository.record_scan("ph-1", 1) is None


def test_linking_without_a_scan_id_is_a_no_op(monkeypatch):
    monkeypatch.setattr(scan_repository, "get_driver",
                        lambda: pytest.fail("should not touch the database"))
    scan_repository.link_invoice(None, "inv-1")
    scan_repository.mark_failed(None, "err")


def test_page_count_defaults_when_missing():
    tx = FakeTx()
    _record_tx(tx, "ph-1", 1, None, "extracted", None, None)
    _, params = next((q, p) for q, p in tx.queries if "CREATE (e:ScanEvent" in q)
    assert params["page_count"] == 1
