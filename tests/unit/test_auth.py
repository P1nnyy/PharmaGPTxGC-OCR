"""Authentication behaviour, with the graph stubbed.

The properties under test are the ones a login is judged on: that a hash never
escapes, that failures are indistinguishable, that a token cannot be forged or
outlive its expiry, and that the deployment cannot be left with no
administrator.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException

from api import deps
from api.routers import auth as auth_router
from api.routers.auth import LoginRequest, UpdateUserRequest, login, update_user
from core import security
from core.security import (
    AuthConfigError, create_access_token, decode_token, hash_password, verify_password,
)
from db.repositories import user_repository


@pytest.fixture(autouse=True)
def signing_key():
    """A test key, so nothing here depends on the deployment's real secret."""
    with patch.object(security.settings, "JWT_SECRET", "test-secret-not-a-real-key"):
        yield


def account(**overrides) -> dict:
    base = {
        "id": "u1", "email": "pharmacist@example.com", "name": "Test",
        "role": "pharmacist", "is_active": True,
        "created_at": "2026-09-08T00:00:00Z", "last_login_at": None,
        "pharmacy_id": "ph1",
    }
    base.update(overrides)
    return base


class TestPasswordStorage:
    def test_hash_is_salted_so_equal_passwords_differ(self):
        assert hash_password("the same passphrase") != hash_password("the same passphrase")

    def test_plaintext_never_appears_in_the_hash(self):
        assert "hunter2" not in hash_password("hunter2-and-then-some")

    def test_verifies_correct_and_rejects_wrong(self):
        h = hash_password("correct horse battery")
        assert verify_password("correct horse battery", h) is True
        assert verify_password("Correct horse battery", h) is False

    def test_a_missing_account_still_returns_false_not_an_error(self):
        # The login path calls this with None when no row was found.
        assert verify_password("anything", None) is False

    def test_a_corrupt_stored_hash_is_a_failed_login_not_a_crash(self):
        assert verify_password("anything", "not-a-bcrypt-hash") is False


class TestTokens:
    def test_round_trips_the_identity(self):
        claims = decode_token(create_access_token("u1", "a@b.com", "pharmacist"))
        assert claims["sub"] == "u1"
        assert claims["role"] == "pharmacist"

    def test_a_token_signed_with_another_key_is_rejected(self):
        forged = jwt.encode({"sub": "u1", "role": "super_admin"}, "other-key", algorithm="HS256")
        assert decode_token(forged) is None

    def test_an_expired_token_is_rejected(self):
        stale = jwt.encode(
            {"sub": "u1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            "test-secret-not-a-real-key", algorithm="HS256",
        )
        assert decode_token(stale) is None

    def test_the_none_algorithm_is_rejected(self):
        # The classic JWT bypass: an unsigned token claiming alg=none.
        unsigned = jwt.encode({"sub": "u1"}, key="", algorithm="none")
        assert decode_token(unsigned) is None

    def test_garbage_is_rejected_rather_than_raising(self):
        assert decode_token("not.a.token") is None

    def test_signing_without_a_secret_is_a_loud_failure(self):
        with patch.object(security.settings, "JWT_SECRET", ""):
            with pytest.raises(AuthConfigError):
                create_access_token("u1", "a@b.com", "pharmacist")


class TestLogin:
    def test_returns_a_token_and_a_user_without_a_hash(self):
        record = {**account(), "password_hash": hash_password("a-real-passphrase")}
        with patch.object(user_repository, "credentials_for", return_value=record), \
             patch.object(user_repository, "record_login"), \
             patch.object(user_repository, "get_user", return_value=account()):
            result = login(LoginRequest(email="pharmacist@example.com", password="a-real-passphrase"))
        assert result["access_token"]
        assert "password_hash" not in result["user"]

    def test_wrong_password_and_unknown_email_give_the_same_error(self):
        record = {**account(), "password_hash": hash_password("a-real-passphrase")}
        with patch.object(user_repository, "credentials_for", return_value=record):
            with pytest.raises(HTTPException) as wrong:
                login(LoginRequest(email="pharmacist@example.com", password="wrong-password"))
        with patch.object(user_repository, "credentials_for", return_value=None):
            with pytest.raises(HTTPException) as unknown:
                login(LoginRequest(email="nobody@example.com", password="wrong-password"))
        assert wrong.value.status_code == unknown.value.status_code == 401
        assert wrong.value.detail == unknown.value.detail

    def test_a_deactivated_account_cannot_sign_in_with_the_right_password(self):
        record = {**account(is_active=False), "password_hash": hash_password("a-real-passphrase")}
        with patch.object(user_repository, "credentials_for", return_value=record):
            with pytest.raises(HTTPException) as e:
                login(LoginRequest(email="pharmacist@example.com", password="a-real-passphrase"))
        assert e.value.status_code == 401


class TestCurrentUser:
    def test_rejects_a_missing_or_malformed_header(self):
        for header in (None, "", "Basic abc", "Bearer", "token-without-scheme"):
            with pytest.raises(HTTPException) as e:
                deps.current_user(authorization=header)
            assert e.value.status_code == 401

    def test_resolves_a_valid_token_to_the_live_account(self):
        token = create_access_token("u1", "pharmacist@example.com", "pharmacist")
        with patch.object(user_repository, "get_user", return_value=account()):
            assert deps.current_user(authorization=f"Bearer {token}")["id"] == "u1"

    def test_deactivation_takes_effect_without_waiting_for_expiry(self):
        # The token is still cryptographically valid; the account is not.
        token = create_access_token("u1", "pharmacist@example.com", "pharmacist")
        with patch.object(user_repository, "get_user", return_value=account(is_active=False)):
            with pytest.raises(HTTPException):
                deps.current_user(authorization=f"Bearer {token}")

    def test_a_deleted_account_stops_working_immediately(self):
        token = create_access_token("gone", "gone@example.com", "super_admin")
        with patch.object(user_repository, "get_user", return_value=None):
            with pytest.raises(HTTPException):
                deps.current_user(authorization=f"Bearer {token}")

    def test_role_comes_from_the_graph_not_the_token(self):
        # A token minted while the holder was an admin must not keep admin
        # rights after they are demoted.
        token = create_access_token("u1", "a@b.com", "super_admin")
        with patch.object(user_repository, "get_user", return_value=account(role="auditor")):
            user = deps.current_user(authorization=f"Bearer {token}")
            with pytest.raises(HTTPException) as e:
                deps.require_super_admin(user)
        assert e.value.status_code == 403


class TestAdminGuards:
    def test_an_admin_cannot_deactivate_themselves(self):
        admin = account(id="admin", role="super_admin")
        with pytest.raises(HTTPException) as e:
            update_user("admin", UpdateUserRequest(is_active=False), user=admin)
        assert "your own account" in e.value.detail

    def test_an_admin_cannot_demote_themselves(self):
        admin = account(id="admin", role="super_admin")
        with pytest.raises(HTTPException) as e:
            update_user("admin", UpdateUserRequest(role="auditor"), user=admin)
        assert "Super Admin role" in e.value.detail

    def test_the_last_admin_cannot_be_demoted_by_another_admin(self):
        acting = account(id="a2", role="super_admin")
        only = [account(id="a1", role="super_admin", is_active=True)]
        with patch.object(user_repository, "list_users", return_value=only):
            with pytest.raises(HTTPException) as e:
                update_user("a1", UpdateUserRequest(role="auditor"), user=acting)
        assert "only active Super Admin" in e.value.detail

    def test_demotion_is_allowed_while_another_admin_remains(self):
        acting = account(id="a2", role="super_admin")
        users = [account(id="a1", role="super_admin"), account(id="a3", role="super_admin")]
        with patch.object(user_repository, "list_users", return_value=users), \
             patch.object(user_repository, "update_user", return_value=account(id="a1", role="auditor")) as call:
            update_user("a1", UpdateUserRequest(role="auditor"), user=acting)
        assert call.called


class TestRoles:
    def test_unknown_roles_fall_back_rather_than_being_stored(self):
        assert user_repository.normalize_role("wizard") == user_repository.DEFAULT_ROLE
        assert user_repository.normalize_role(None) == user_repository.DEFAULT_ROLE

    def test_the_legacy_owner_role_maps_to_super_admin(self):
        assert user_repository.normalize_role("owner") == "super_admin"

    def test_emails_are_folded_so_uniqueness_means_what_it_looks_like(self):
        assert user_repository.normalize_email("  Admin@Example.COM ") == "admin@example.com"
