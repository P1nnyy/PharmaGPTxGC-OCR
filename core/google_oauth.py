"""Sign in with Google.

The server-side authorization-code flow: the browser never holds the client
secret, and the code is exchanged for tokens over a direct TLS connection
between this server and Google.

On verifying the ID token - it is decoded without checking its signature, and
that is deliberate rather than an omission. The token arrives as the response
body of our own HTTPS POST to Google's token endpoint, authenticated with the
client secret; there is no untrusted party in between who could have
substituted it. Google documents this exact exception. The claims that still
have to be checked are the ones describing *who* it is for, so `aud`, `iss`,
`exp` and `email_verified` are all asserted below. An ID token arriving by any
other route would need full JWKS signature verification.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import jwt

from core.config import settings
from core.security import ALGORITHM, _secret

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Just enough to identify someone. No Gmail, Drive or contacts scopes: asking
# for more than sign-in needs makes the consent screen alarming and the
# breach surface larger for no benefit.
SCOPES = "openid email profile"

# The round trip through Google is seconds; a state token good for longer is
# just a wider replay window.
_STATE_TTL_SECONDS = 600


class GoogleAuthError(RuntimeError):
    """Raised when a Google sign-in cannot be completed."""


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _require_config() -> None:
    if not is_configured():
        raise GoogleAuthError(
            "Google sign-in is not configured on this server "
            "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)."
        )


def make_state(invite_token: Optional[str] = None, next_path: str = "/") -> str:
    """A signed, expiring state parameter.

    This is the CSRF defence for the callback: Google hands back whatever we
    sent, so a callback carrying a state we did not sign is someone else's
    login attempt being replayed at our endpoint. It also ferries the
    invitation across the round trip, since Google will not carry it for us.
    """
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "purpose": "google_oauth_state",
            "invite": invite_token,
            "next": next_path,
            "iat": now,
            "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def read_state(state: str) -> dict:
    try:
        claims = jwt.decode(state, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise GoogleAuthError("That sign-in attempt has expired or was not started here.")
    if claims.get("purpose") != "google_oauth_state":
        # A token of ours, but minted for something else - a session token
        # must not be usable as a state parameter.
        raise GoogleAuthError("That sign-in attempt is not valid.")
    return claims


def authorization_url(redirect_uri: str, state: str) -> str:
    _require_config()
    return AUTH_ENDPOINT + "?" + urlencode({
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        # Always show the chooser: on a shared machine, silently reusing the
        # last Google session is how someone ends up in a colleague's account.
        "prompt": "select_account",
    })


def exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    """Trades the one-time code for tokens, server to server."""
    _require_config()
    try:
        response = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as e:
        raise GoogleAuthError(f"Could not reach Google to complete sign-in: {e}")

    if response.status_code != 200:
        # Google's own message names the cause - most often a redirect_uri
        # that does not match the one registered - and repeating it saves a
        # long hunt.
        raise GoogleAuthError(f"Google rejected the sign-in: {response.text[:200]}")
    return response.json()


def identity_from(token_response: dict[str, Any]) -> dict[str, Any]:
    """The verified identity carried by the token response."""
    id_token = token_response.get("id_token")
    if not id_token:
        raise GoogleAuthError("Google's response contained no identity token.")

    try:
        claims = jwt.decode(
            id_token,
            options={"verify_signature": False},   # see module docstring
            audience=settings.GOOGLE_CLIENT_ID,
            algorithms=["RS256"],
        )
    except jwt.PyJWTError as e:
        raise GoogleAuthError(f"Google's identity token could not be read: {e}")

    if claims.get("aud") != settings.GOOGLE_CLIENT_ID:
        # A token minted for a different client must not sign anyone in here.
        raise GoogleAuthError("That identity token was issued for another application.")
    if claims.get("iss") not in _ISSUERS:
        raise GoogleAuthError("That identity token did not come from Google.")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise GoogleAuthError("Google did not return an email address.")
    if not claims.get("email_verified", False):
        # Without this, an unverified address could be used to reach an
        # account belonging to whoever really owns it.
        raise GoogleAuthError("That Google account's email address is not verified.")

    return {
        "email": email,
        "name": (claims.get("name") or "").strip(),
        "google_sub": claims.get("sub"),
        "picture": claims.get("picture"),
    }
