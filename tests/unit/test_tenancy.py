"""Workspace isolation.

The claim being tested is the one the product makes to anyone who registers:
their workspace is theirs. These are the properties that have to hold for that
to be true, including the unglamorous one - that a code path with no workspace
in scope fails instead of guessing.
"""

from unittest.mock import patch

import pytest

from core.tenancy import (
    TenantUnavailableError, current_tenant, get_current_tenant,
    set_current_tenant, tenant_scope,
)
from db.repositories import inventory_repository, user_repository


class TestFailsClosed:
    def test_no_workspace_in_scope_raises_rather_than_defaulting(self):
        # The whole reason this design exists: the old behaviour silently read
        # a shared default tenant, which is a data leak wearing a fallback's
        # clothing.
        set_current_tenant(None)
        with pytest.raises(TenantUnavailableError):
            current_tenant()

    def test_a_tenant_scoped_read_refuses_without_a_workspace(self):
        set_current_tenant(None)
        with patch.object(inventory_repository, "_run", return_value=[]):
            with pytest.raises(TenantUnavailableError):
                inventory_repository.stock_on_hand()

    def test_the_optional_accessor_reports_absence_without_raising(self):
        set_current_tenant(None)
        assert get_current_tenant() is None


class TestScoping:
    def test_a_scope_applies_then_restores(self):
        set_current_tenant("outer")
        with tenant_scope("inner"):
            assert current_tenant() == "inner"
        assert current_tenant() == "outer"

    def test_scopes_nest_without_leaking(self):
        with tenant_scope("a"):
            with tenant_scope("b"):
                assert current_tenant() == "b"
            assert current_tenant() == "a"

    def test_a_scope_is_restored_even_when_the_block_raises(self):
        set_current_tenant("outer")
        with pytest.raises(ValueError):
            with tenant_scope("inner"):
                raise ValueError("boom")
        assert current_tenant() == "outer"

    def test_the_stock_query_is_filtered_by_the_workspace_in_scope(self):
        with patch.object(inventory_repository, "_run", return_value=[]) as run:
            with tenant_scope("pharmacy-42"):
                inventory_repository.stock_on_hand()
        assert run.call_args.kwargs["pharmacy_id"] == "pharmacy-42"

    def test_two_workspaces_issue_different_queries(self):
        seen = []
        with patch.object(inventory_repository, "_run", side_effect=lambda q, **k: seen.append(k["pharmacy_id"]) or []):
            with tenant_scope("tenant-a"):
                inventory_repository.stock_on_hand()
            with tenant_scope("tenant-b"):
                inventory_repository.stock_on_hand()
        assert seen == ["tenant-a", "tenant-b"]


class TestAccountsAreScopedToo:
    def test_listing_staff_is_filtered_by_workspace(self):
        # An unscoped account list would show every customer's team to every
        # other customer - the most direct version of the leak.
        with patch.object(user_repository, "_read", return_value=[]) as read:
            user_repository.list_users("pharmacy-7")
        assert read.call_args.kwargs["pharmacy_id"] == "pharmacy-7"

    def test_registration_provisions_a_workspace_rather_than_joining_one(self):
        # A new registration must not be dropped into an existing pharmacy.
        captured = {}

        def fake_write(query, **params):
            captured["query"] = query
            captured["params"] = params
            return None

        with patch.object(user_repository, "_write", side_effect=fake_write):
            with pytest.raises(user_repository.UnknownUserError):
                user_repository.create_user(
                    email="new@example.com", name="New", password="a-long-enough-pass",
                )
        # MERGE, not MATCH: it creates the workspace it is about to own.
        assert "MERGE (ph:Pharmacy" in captured["query"]
        assert captured["params"]["role"] == "super_admin"

    def test_adding_staff_joins_the_existing_workspace(self):
        captured = {}

        def fake_write(query, **params):
            captured["query"] = query
            captured["params"] = params
            return None

        with patch.object(user_repository, "_write", side_effect=fake_write):
            with pytest.raises(user_repository.UnknownUserError):
                user_repository.create_user(
                    email="staff@example.com", name="Staff", password="a-long-enough-pass",
                    role="pharmacist", pharmacy_id="existing-ph",
                )
        assert "MATCH (ph:Pharmacy" in captured["query"]
        assert captured["params"]["pharmacy_id"] == "existing-ph"
        assert captured["params"]["role"] == "pharmacist"
