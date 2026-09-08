"""Sign in with Google.

The checks here are the ones standing between "Google said so" and "this
person is who the token claims". Each corresponds to a way the flow is
attacked when the check is missing.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

from core import google_oauth
from core.google_oauth import GoogleAuthError, identity_from, make_state, read_state

CLIENT_ID = "test-client-id.apps.googleusercontent.com"


@pytest.fixture(autouse=True)
def configured():
    with patch.object(google_oauth.settings, "JWT_SECRET", "test-secret-key"), \
         patch.object(google_oauth.settings, "GOOGLE_CLIENT_ID", CLIENT_ID), \
         patch.object(google_oauth.settings, "GOOGLE_CLIENT_SECRET", "test-secret"):
        yield


def id_token(**overrides) -> dict:
    claims = {
        "aud": CLIENT_ID, "iss": "https://accounts.google.com",
        "sub": "google-user-1", "email": "someone@example.com",
        "email_verified": True, "name": "Someone",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    claims.update(overrides)
    return {"id_token": jwt.encode(claims, "irrelevant-google-key", algorithm="HS256")}


class TestState:
    def test_round_trips_the_invitation_across_the_redirect(self):
        # Google will not carry an invite token for us, so state does.
        assert read_state(make_state(invite_token="inv-1"))["invite"] == "inv-1"

    def test_a_state_we_did_not_sign_is_rejected(self):
        forged = jwt.encode({"purpose": "google_oauth_state"}, "other-key", algorithm="HS256")
        with pytest.raises(GoogleAuthError):
            read_state(forged)

    def test_an_expired_state_is_rejected(self):
        stale = jwt.encode(
            {"purpose": "google_oauth_state",
             "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
            "test-secret-key", algorithm="HS256")
        with pytest.raises(GoogleAuthError):
            read_state(stale)

    def test_a_session_token_cannot_be_used_as_state(self):
        # Same key, different purpose - without the purpose claim, a stolen
        # session token would pass as a valid state.
        session = jwt.encode({"sub": "u1", "role": "super_admin"},
                             "test-secret-key", algorithm="HS256")
        with pytest.raises(GoogleAuthError, match="not valid"):
            read_state(session)


class TestIdentity:
    def test_accepts_a_well_formed_token(self):
        identity = identity_from(id_token())
        assert identity["email"] == "someone@example.com"
        assert identity["google_sub"] == "google-user-1"

    def test_rejects_a_token_issued_for_another_application(self):
        # Without this, any Google app's token would sign someone in here.
        with pytest.raises(GoogleAuthError, match="another application"):
            identity_from(id_token(aud="someone-elses-client-id"))

    def test_rejects_a_token_not_issued_by_google(self):
        with pytest.raises(GoogleAuthError, match="did not come from Google"):
            identity_from(id_token(iss="https://evil.example.com"))

    def test_rejects_an_unverified_email(self):
        # An unverified address could belong to someone else entirely.
        with pytest.raises(GoogleAuthError, match="not verified"):
            identity_from(id_token(email_verified=False))

    def test_rejects_a_response_with_no_identity_token(self):
        with pytest.raises(GoogleAuthError, match="no identity token"):
            identity_from({"access_token": "x"})

    def test_email_is_folded_so_it_matches_stored_accounts(self):
        assert identity_from(id_token(email="Someone@Example.COM"))["email"] == "someone@example.com"


class TestConfiguration:
    def test_reports_unconfigured_rather_than_failing_at_use(self):
        with patch.object(google_oauth.settings, "GOOGLE_CLIENT_ID", ""):
            assert google_oauth.is_configured() is False

    def test_the_consent_screen_always_offers_the_account_chooser(self):
        url = google_oauth.authorization_url("https://x/auth/google/callback", "st")
        # On a shared machine, silently reusing the last session is how
        # someone lands in a colleague's account.
        assert "prompt=select_account" in url

    def test_only_sign_in_scopes_are_requested(self):
        url = google_oauth.authorization_url("https://x/cb", "st")
        for over_broad in ("gmail", "drive", "contacts"):
            assert over_broad not in url
