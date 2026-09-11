"""Binding a scanned code to a product, with Cypher stubbed.

The learning loop: a pack whose code we have never seen is unrecognisable once
and instant every time after. What is worth pinning by test is the part that
makes that safe — bindings do not leak between workspaces, and one code never
ends up pointing at two products.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.routers.products import bind_product_code, resolve_product_code, unbind_product_code, CodeBinding
from core.tenancy import tenant_scope
from db.repositories import product_code_repository as repo

USER = {"id": "u-1", "email": "owner@example.com", "name": "Owner",
        "role": "super_admin", "pharmacy_id": "ph-1", "is_active": True}


@pytest.fixture(autouse=True)
def workspace():
    with tenant_scope("ph-1"):
        yield


@pytest.fixture(autouse=True)
def no_audit():
    with patch("api.routers.products.audit_repository.record"):
        yield


class TestScoping:
    def test_a_binding_is_keyed_to_its_workspace(self):
        # The property that stops one shop's mistake resolving on another's
        # counter.
        assert repo._key("ph-1", "8901234567890") != repo._key("ph-2", "8901234567890")

    def test_lookups_are_scoped_to_the_workspace_in_context(self):
        with patch.object(repo, "_run_read", return_value=[]) as read:
            repo.resolve("8901234567890")
        assert read.call_args.kwargs["key"].startswith("ph-1::")


class TestNormalisation:
    def test_strips_surrounding_whitespace(self):
        assert repo.normalise("  8901234567890 \n") == "8901234567890"

    def test_does_not_fold_case(self):
        # A GS1 payload carries a case-sensitive batch; two codes differing
        # only in case are two codes.
        assert repo.normalise("ab1234") != repo.normalise("AB1234")

    def test_an_empty_code_resolves_to_nothing_without_a_query(self):
        with patch.object(repo, "_run_read") as read:
            assert repo.resolve("   ") is None
        read.assert_not_called()


class TestResolve:
    def test_returns_the_product_behind_a_known_code(self):
        with patch.object(repo, "_run_read", return_value=[
            {"product": {"id": "p1", "canonical_name": "CALPOL 650"}, "code": {"value": "890"}}
        ]):
            match = repo.resolve("890")
        assert match["product"]["id"] == "p1"

    def test_returns_none_for_a_code_never_seen(self):
        with patch.object(repo, "_run_read", return_value=[]):
            assert repo.resolve("nope") is None


class TestBind:
    def test_refuses_an_empty_code(self):
        with pytest.raises(ValueError):
            repo.bind("p1", "   ", "ean_13")

    def test_removes_an_edge_to_a_different_product(self):
        # One code, one product. Leaving both edges would make the next scan
        # ambiguous, which is worse than the original mis-binding.
        with patch.object(repo, "_run_write", return_value=[{"code": {}, "product": {}}]) as write:
            repo.bind("p2", "890", "ean_13")
        query = write.call_args[0][0]
        assert "DELETE old" in query
        assert "other.id <> p.id" in query

    def test_keeps_the_original_first_seen_at_on_a_rebind(self):
        with patch.object(repo, "_run_write", return_value=[{"code": {}, "product": {}}]) as write:
            repo.bind("p1", "890", "ean_13")
        query = write.call_args[0][0]
        # first_seen_at is set only ON CREATE: when we first saw a code is a
        # fact, not something a second scan should move.
        assert "ON CREATE SET" in query and "first_seen_at" in query
        assert "ON MATCH SET" in query
        assert "c.first_seen_at = $now" in query.split("ON MATCH SET")[0]


class TestRoutes:
    def test_an_unknown_code_is_a_404_not_an_error(self):
        # The expected case for a pack we have never seen. It is what makes
        # the counter offer to bind rather than showing a failure.
        with patch("db.repositories.product_code_repository.resolve", return_value=None):
            with pytest.raises(HTTPException) as caught:
                resolve_product_code(value="never-seen")
        assert caught.value.status_code == 404

    def test_binding_returns_the_product_it_bound_to(self):
        with patch(
            "db.repositories.product_code_repository.bind",
            return_value={"code": {"value": "890"}, "product": {"id": "p1", "canonical_name": "CALPOL"}},
        ):
            result = bind_product_code("p1", CodeBinding(value="890", type="ean_13"), USER)
        assert result["product"]["id"] == "p1"

    def test_binding_to_a_missing_product_is_a_404(self):
        with patch("db.repositories.product_code_repository.bind", side_effect=LookupError("No product p9.")):
            with pytest.raises(HTTPException) as caught:
                bind_product_code("p9", CodeBinding(value="890"), USER)
        assert caught.value.status_code == 404

    def test_binding_an_empty_code_is_a_400(self):
        with pytest.raises(HTTPException) as caught:
            bind_product_code("p1", CodeBinding(value="  "), USER)
        assert caught.value.status_code == 400

    def test_unbinding_something_unbound_is_a_404(self):
        with patch("db.repositories.product_code_repository.unbind", return_value=False):
            with pytest.raises(HTTPException) as caught:
                unbind_product_code(value="890", user=USER)
        assert caught.value.status_code == 404
