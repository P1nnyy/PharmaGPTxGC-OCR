"""Request-scoped authentication.

Every protected endpoint depends on `current_user`, and `current_user` is the
only thing that reads the Authorization header. Swapping this project's own
tokens for a hosted identity provider later means changing this file and
`core.security` - no endpoint signature changes.
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from core.security import decode_token
from db.repositories import user_repository

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in to continue.",
    # Without this header a browser cannot tell an expired session from a
    # forbidden one, and the SPA needs that distinction to redirect to login.
    headers={"WWW-Authenticate": "Bearer"},
)


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Resolves the caller, or raises 401.

    The account is re-read from the graph on every request rather than trusted
    from the token's claims. That is one extra lookup, and it is what makes
    deactivating an account take effect immediately instead of whenever the
    holder's token happens to expire - the difference between revoking access
    and asking politely.
    """
    token = _bearer(authorization)
    if not token:
        raise _UNAUTHENTICATED

    claims = decode_token(token)
    if not claims or not claims.get("sub"):
        raise _UNAUTHENTICATED

    user = user_repository.get_user(claims["sub"])
    if user is None or not user.get("is_active"):
        raise _UNAUTHENTICATED
    return user


def require_super_admin(user: dict = Depends(current_user)) -> dict:
    """Guards account management.

    Reads the role from the freshly-loaded user, not from the token, so a
    demotion applies to the demoted user's next request rather than to their
    next login.
    """
    if user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires a Super Admin account.",
        )
    return user
