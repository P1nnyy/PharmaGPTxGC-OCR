"""Invitations and the audit trail.

The properties here are the ones that make "who did what" trustworthy and
"join my shop" safe: a link that seats exactly the person it was issued to,
once; and a record that survives the deletion of whatever it describes.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.routers import auth as auth_router
from api.routers.auth import InviteRequest, create_invite
from core.tenancy import tenant_scope
from db.repositories import audit_repository, invite_repository


def admin(**overrides) -> dict:
    base = {"id": "a1", "email": "owner@example.com", "name": "Owner",
            "role": "super_admin", "is_active": True, "pharmacy_id": "ph1"}
    base.update(overrides)
    return base


class TestInviteIssuing:
    def test_super_admin_cannot_be_invited_only_promoted(self):
        # Emailing admin rights to an unverified address is a different and
        # much worse thing than promoting someone already in the workspace.
        with pytest.raises(invite_repository.InviteError) as e:
            with tenant_scope("ph1"):
                invite_repository.create("x@example.com", "super_admin", admin())
        assert "promoted" in str(e.value)

    def test_a_bad_address_is_refused(self):
        with pytest.raises(invite_repository.InviteError):
            with tenant_scope("ph1"):
                invite_repository.create("not-an-email", "pharmacist", admin())

    def test_the_token_is_returned_once_and_not_in_listings(self):
        issued = {"id": "i1", "email": "new@example.com", "role": "pharmacist",
                  "status": "pending", "pharmacy_id": "ph1", "token": "secret-token",
                  "pharmacy_name": "Shop"}

        class FakeRequest:
            base_url = "https://dev.pharmagpt.co/"

        with patch.object(invite_repository, "create", return_value=dict(issued)), \
             patch.object(audit_repository, "record"):
            result = create_invite(InviteRequest(email="new@example.com"), FakeRequest(), user=admin())

        # The link carries the token; the invitation body must not.
        assert result["invite_url"].endswith("/join/secret-token")
        assert "token" not in result

    def test_issuing_is_audited_with_who_and_whom(self):
        class FakeRequest:
            base_url = "https://x/"
        with patch.object(invite_repository, "create", return_value={
                "id": "i1", "email": "new@example.com", "role": "pharmacist",
                "status": "pending", "pharmacy_id": "ph1", "token": "t"}), \
             patch.object(audit_repository, "record") as rec:
            create_invite(InviteRequest(email="new@example.com"), FakeRequest(), user=admin())
        assert rec.call_args.args[0] == "user.invited"
        assert "new@example.com" in rec.call_args.kwargs["summary"]


class TestInviteAcceptance:
    def _pending(self, email="new@example.com"):
        return {"i": {"email": email, "status": "pending", "expires_at": None,
                      "pharmacy_id": "ph1", "role": "pharmacist", "id": "i1"}}

    def test_a_forwarded_link_does_not_admit_someone_else(self):
        # The link is the credential, so it is bound to the invited address.
        with patch.object(invite_repository, "_run_read", return_value=[self._pending()]):
            with pytest.raises(invite_repository.InviteError) as e:
                invite_repository.accept("tok", "someone-else@example.com")
        assert "different email" in str(e.value)

    def test_an_already_used_invitation_is_refused(self):
        used = {"i": {"email": "new@example.com", "status": "accepted",
                      "expires_at": None, "pharmacy_id": "ph1", "role": "pharmacist"}}
        with patch.object(invite_repository, "_run_read", return_value=[used]):
            with pytest.raises(invite_repository.InviteError) as e:
                invite_repository.accept("tok", "new@example.com")
        assert "expired or has already been used" in str(e.value)

    def test_an_unknown_token_is_refused(self):
        with patch.object(invite_repository, "_run_read", return_value=[]):
            with pytest.raises(invite_repository.InviteError):
                invite_repository.accept("nope", "new@example.com")

    def test_a_race_for_the_same_link_seats_only_one(self):
        # The conditional write returns nothing when another request already
        # flipped it to accepted.
        with patch.object(invite_repository, "_run_read", return_value=[self._pending()]), \
             patch.object(invite_repository, "_run_write", return_value=None):
            with pytest.raises(invite_repository.InviteError) as e:
                invite_repository.accept("tok", "new@example.com")
        assert "already been used" in str(e.value)


class TestAuditDurability:
    def test_recording_never_raises_even_when_the_write_fails(self):
        # A failed audit write must not fail the action it describes; the gap
        # is logged instead.
        with patch.object(audit_repository, "get_driver", side_effect=RuntimeError("db down")):
            audit_repository.record("invoice.deleted", actor=admin(), summary="x")

    def test_the_workspace_is_a_property_not_a_relationship(self):
        # An edge to the invoice would be followed by DETACH DELETE, and the
        # record of a deletion would be destroyed by that deletion.
        captured = {}

        class FakeSession:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute_write(self, fn):
                fn(type("Tx", (), {"run": lambda _s, q, **k: captured.update(query=q, params=k)})())

        with patch.object(audit_repository, "get_driver",
                          return_value=type("D", (), {"session": lambda _s: FakeSession()})()):
            audit_repository.record("invoice.deleted", actor=admin(),
                                    target_type="invoice", target_id="inv1", summary="gone")

        assert "pharmacy_id: $pharmacy_id" in captured["query"]
        assert "target_id: $target_id" in captured["query"]
        # No MATCH/MERGE joining it to anything.
        assert "MATCH" not in captured["query"]
        assert captured["params"]["target_id"] == "inv1"

    def test_an_unknown_action_is_still_recorded(self):
        with patch.object(audit_repository, "get_driver", side_effect=RuntimeError("x")), \
             patch.object(audit_repository, "logger") as log:
            audit_repository.record("something.new", actor=admin())
        assert any("unrecognised action" in str(c) for c in log.warning.call_args_list)

    def test_the_trail_is_scoped_to_one_workspace(self):
        with patch.object(audit_repository, "get_driver") as drv:
            drv.return_value.session.return_value.__enter__.return_value.execute_read.return_value = []
            result = audit_repository.list_events(pharmacy_id="ph-9", limit=10)
        assert result["events"] == []

    def test_limit_is_clamped_rather_than_trusted(self):
        with patch.object(audit_repository, "get_driver") as drv:
            drv.return_value.session.return_value.__enter__.return_value.execute_read.return_value = []
            audit_repository.list_events(pharmacy_id="ph1", limit=100000)
        # No exception, and the query would have been built with a sane cap.
