"""Request-scoped authentication.

Every protected endpoint depends on `current_user`, and `current_user` is the
only thing that reads the Authorization header. Swapping this project's own
tokens for a hosted identity provider later means changing this file and
`core.security` - no endpoint signature changes.
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from core.security import decode_token
from core.tenancy import set_current_tenant
from db.repositories import pharmacy_repository, scan_repository, user_repository

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


async def current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Resolves the caller, or raises 401.

    The account is re-read from the graph on every request rather than trusted
    from the token's claims. That is one extra lookup, and it is what makes
    deactivating an account take effect immediately instead of whenever the
    holder's token happens to expire - the difference between revoking access
    and asking politely.

    This is `async def` for a reason that is not stylistic. A sync dependency
    is run by FastAPI in a worker thread, via `anyio.to_thread.run_sync`, which
    executes it inside a *copy* of the request's context. Values copy inwards
    but not back out, so `set_current_tenant` below took effect only for the
    duration of this function and was discarded before the endpoint ran - every
    tenant-scoped query then raised TenantUnavailableError. Awaiting from the
    request's own context is what makes the tenant stick.

    The graph lookup is the one blocking call here, so it goes to a worker
    thread explicitly rather than stalling the event loop.
    """
    token = _bearer(authorization)
    if not token:
        raise _UNAUTHENTICATED

    claims = decode_token(token)
    if not claims or not claims.get("sub"):
        raise _UNAUTHENTICATED

    user = await run_in_threadpool(user_repository.get_user, claims["sub"])
    if user is None or not user.get("is_active"):
        raise _UNAUTHENTICATED

    # From here on every repository call is scoped to this account's
    # workspace. Set once, at the only point where identity is established,
    # so no individual query has to remember.
    set_current_tenant(user.get("pharmacy_id"))
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


# Scanning costs money - every upload is a paid Azure Document Intelligence
# call - and registration is open to anyone. A small free allowance lets a
# real pharmacy try the product before filling in paperwork, while making an
# open registration page useless as a way to spend someone else's OCR budget.
FREE_SCANS_WITHOUT_SHOP = 2


def scan_quota(user: dict = Depends(current_user)) -> dict:
    """Allows the scan, or explains what would lift the limit.

    The gate is a completed shop profile rather than a payment or an approval
    step: it requires a valid GSTIN, which is checked including its check
    digit, so it is evidence of a real registered business rather than a form
    someone clicked through. It is also work the pharmacy has to do anyway -
    the same details are what let a scan tell its own invoices apart.
    """
    profile = pharmacy_repository.get_profile(user["pharmacy_id"])
    if not pharmacy_repository.missing_fields(profile):
        return user

    used = scan_repository.count_scans(user["pharmacy_id"])
    if used >= FREE_SCANS_WITHOUT_SHOP:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"You have used your {FREE_SCANS_WITHOUT_SHOP} trial scans. "
                "Add your shop's details in Settings > Shop to keep scanning."
            ),
        )
    return user


def scan_quota_state(pharmacy_id: str) -> dict:
    """What the UI needs to warn before the limit is hit rather than after."""
    profile = pharmacy_repository.get_profile(pharmacy_id)
    unlocked = not pharmacy_repository.missing_fields(profile)
    used = scan_repository.count_scans(pharmacy_id)
    return {
        "scans_used": used,
        "scan_limit": None if unlocked else FREE_SCANS_WITHOUT_SHOP,
        "scans_remaining": None if unlocked else max(0, FREE_SCANS_WITHOUT_SHOP - used),
        "unlocked": unlocked,
    }
