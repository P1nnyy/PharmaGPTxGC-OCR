"""The workspace the current request belongs to.

Every account owns a Pharmacy, and effectively every query is scoped to one.
Threading that through thirty route signatures would work, but the failure
mode is bad in a specific way: the one handler that forgets does not error, it
quietly reads another tenant's data. So the tenant is carried in a
request-scoped ContextVar, set once when the caller is authenticated, and read
by the repositories as their default.

`current_tenant()` **raises when nothing is set** rather than falling back.
That is the whole point. The previous behaviour - defaulting to
`settings.DEFAULT_PHARMACY_ID` - meant an unauthenticated or mis-wired code
path silently read the shared pile, which is exactly the bug this design has
to make impossible. Failing loudly in development beats leaking quietly in
production.

Code outside a request (scripts, migrations, tests) passes `pharmacy_id`
explicitly or uses `tenant_scope()`.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_current_pharmacy: ContextVar[Optional[str]] = ContextVar("current_pharmacy", default=None)


class TenantUnavailableError(RuntimeError):
    """Raised when tenant-scoped data is requested with no workspace in scope."""


def set_current_tenant(pharmacy_id: Optional[str]) -> None:
    _current_pharmacy.set(pharmacy_id)


def get_current_tenant() -> Optional[str]:
    """The workspace in scope, or None. For callers that can cope with neither."""
    return _current_pharmacy.get()


def current_tenant() -> str:
    """The workspace in scope, or a loud failure."""
    pharmacy_id = _current_pharmacy.get()
    if not pharmacy_id:
        raise TenantUnavailableError(
            "No workspace in scope. Tenant-scoped data requires an authenticated "
            "request, or an explicit pharmacy_id."
        )
    return pharmacy_id


@contextmanager
def tenant_scope(pharmacy_id: str) -> Iterator[None]:
    """Runs a block as one workspace. For scripts and tests."""
    token = _current_pharmacy.set(pharmacy_id)
    try:
        yield
    finally:
        _current_pharmacy.reset(token)
