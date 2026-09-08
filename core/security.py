"""Password hashing and session tokens.

This is the single seam the rest of the application authenticates through.
`decode_token` and the `get_current_user` dependency that wraps it are the
only places that know how a caller's identity is established, so replacing
this with a hosted identity provider later means rewriting this module and
nothing else.

Two rules hold throughout:

  * A password hash never leaves this module in either direction - callers
    pass plaintext in and get a boolean back. Nothing else should ever hold
    one, and no response model may carry one.
  * Failures are indistinguishable. A wrong password, an unknown email and a
    deactivated account all take the same path and the same time, so the
    login endpoint cannot be used to enumerate who has an account.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt

from core.config import settings

ALGORITHM = "HS256"

# A bcrypt hash of a throwaway value, used to burn the same CPU on a missing
# account as on a real one. Without it, "no such user" returns in microseconds
# while a real user costs ~250ms, and that gap alone reveals which emails are
# registered.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(rounds=4))


class AuthConfigError(RuntimeError):
    """Raised when the signing key is missing - a deployment fault, not a user one."""


def _secret() -> str:
    """The signing key, or a loud failure.

    Deliberately not defaulted. A fallback secret would mean tokens signed
    with a value that is in the source tree, which is the same as no
    authentication at all - and it would fail silently, in production, looking
    like it worked.
    """
    if not settings.JWT_SECRET:
        raise AuthConfigError(
            "JWT_SECRET is not set. Generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
            "and put it in the server's .env - it must not live in the repo."
        )
    return settings.JWT_SECRET


def hash_password(plaintext: str) -> str:
    """Hashes a password for storage. The result is safe to persist; the input never is."""
    if not plaintext:
        raise ValueError("Password must not be empty.")
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, hashed: Optional[str]) -> bool:
    """Checks a password, spending the same time whether or not the account exists.

    `hashed` is Optional because callers look the user up first and may not
    have found one. Passing None still performs a real bcrypt comparison
    against a dummy hash, so the caller can branch on the result rather than
    on whether it had a row - which is what keeps the timing flat.
    """
    candidate = (hashed or "").encode("utf-8") or _DUMMY_HASH
    try:
        matched = bcrypt.checkpw(plaintext.encode("utf-8"), candidate)
    except (ValueError, TypeError):
        # A malformed or truncated stored hash is a failed login, not a 500.
        bcrypt.checkpw(plaintext.encode("utf-8"), _DUMMY_HASH)
        return False
    return bool(hashed) and matched


def create_access_token(user_id: str, email: str, role: str) -> str:
    """Mints a session token.

    The role is carried in the token so that routine permission checks cost
    nothing, but it is a snapshot: a role changed mid-session does not take
    effect until the token is reissued. Anything destructive re-reads the
    user's current role from the graph rather than trusting this claim.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """Verifies a token, returning its claims or None.

    Returns None for every invalid case - expired, tampered, wrong algorithm,
    malformed - because the caller's response is identical in all of them and
    distinguishing them in an error message tells an attacker which part of a
    forged token to fix.
    """
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
