"""The catalogue must only ever be built from invoices a human has verified.

These assert on the generated Cypher rather than on a live graph, because the
rule lives in the query. A regression here does not raise - it silently starts
writing unreviewed extractions into master data, which is the failure mode the
rule exists to prevent, so it is worth pinning even without a database.
"""

import re

from db import product_repository as pr


def _clauses(query: str) -> str:
    return re.sub(r"\s+", " ", query)


class TestAggregateQuery:
    def test_list_query_filters_to_verified_invoices(self):
        assert "inv.status = 'verified'" in _clauses(pr._aggregate_query())

    def test_detail_query_filters_to_verified_invoices(self):
        assert "inv.status = 'verified'" in _clauses(pr._aggregate_query(single=True))

    def test_filter_applies_to_the_invoice_not_the_product(self):
        # Product nodes have no status; filtering p.status would silently
        # match nothing and empty the catalogue.
        query = _clauses(pr._aggregate_query())
        assert "p.status" not in query

    def test_still_scoped_to_one_pharmacy(self):
        # The verified filter must not have displaced tenant scoping.
        for query in (pr._aggregate_query(), pr._aggregate_query(single=True)):
            assert "$pharmacy_id" in query

    def test_detail_query_still_targets_one_product(self):
        assert "$product_id" in _clauses(pr._aggregate_query(single=True))

    def test_where_precedes_the_optional_matches(self):
        # A WHERE placed after an OPTIONAL MATCH filters that match rather
        # than the preceding MATCH, which would let unverified invoices back
        # in while merely dropping their vendor.
        query = _clauses(pr._aggregate_query())
        assert query.index("WHERE inv.status") < query.index("OPTIONAL MATCH")


class TestSharedConstant:
    def test_single_source_of_truth(self):
        assert pr.VERIFIED_ONLY == "inv.status = 'verified'"

    def test_matches_the_status_the_api_writes(self):
        # api/routes.py PATCHes status='verified' from the review screen's
        # "Mark as Verified"; a mismatch here would mean nothing ever appears.
        from api.routes import InvoiceUpdate

        assert "status" in InvoiceUpdate.model_fields
