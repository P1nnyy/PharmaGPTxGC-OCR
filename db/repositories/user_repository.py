"""User accounts.

Users were already modelled - `ensure_bootstrap_tenant` has been creating a
`User`-[:MEMBER_OF {role}]->`Pharmacy` since the first migration, with a
comment saying it stood in "until real multi-user auth exists". This module is
that, built on the same shape rather than beside it.

`password_hash` is written by `create_user`/`set_password` and read by exactly
one function, `credentials_for`, which the login path uses. Every other read
goes through `_public`, which cannot return it: the field is dropped by
construction rather than by remembering to exclude it at each call site.
"""

import uuid
from typing import Any, Optional

from core.config import settings
from core.security import hash_password
from db.graph_db import get_driver

# The vocabulary RBAC will enforce. Defined now, while accounts are being
# created, so that roles are recorded from the first user rather than
# backfilled onto accounts that already exist.
#
# Only `super_admin` currently grants anything beyond signing in - user
# management. The rest are recorded and shown but not yet enforced at the
# endpoint level; see the roles/permissions phase.
ROLES = ("super_admin", "pharmacist", "inventory_manager", "auditor")

# The bootstrap node predates these names and carries role 'owner'. It has no
# password and so can never log in, but treating it as a super admin keeps a
# hand-migrated account working if someone sets a password on it directly.
_LEGACY_ROLES = {"owner": "super_admin"}

DEFAULT_ROLE = "pharmacist"

# Everything safe to send to a browser. password_hash is absent by design -
# adding a field here is a deliberate act, and no wildcard can leak one.
_PUBLIC_FIELDS = (
    "id", "email", "name", "role", "is_active", "created_at", "last_login_at",
)


class UserExistsError(RuntimeError):
    """Raised when an email is already registered."""


class UnknownUserError(RuntimeError):
    """Raised when an id does not resolve to an account."""


def normalize_role(role: Optional[str]) -> str:
    role = (role or "").strip().lower()
    role = _LEGACY_ROLES.get(role, role)
    return role if role in ROLES else DEFAULT_ROLE


def normalize_email(email: str) -> str:
    """Emails are matched case-insensitively; storing them folded is what makes
    the uniqueness constraint mean what people assume it means."""
    return (email or "").strip().lower()


def _public(node: Any) -> Optional[dict]:
    if node is None:
        return None
    data = dict(node)
    out = {}
    for key in _PUBLIC_FIELDS:
        value = data.get(key)
        # Neo4j temporals do not survive JSON encoding.
        out[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def _write(query: str, **params):
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: tx.run(query, **params).single())


def _read(query: str, **params):
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r for r in tx.run(query, **params)])


def create_user(email: str, name: str, password: str, role: str = DEFAULT_ROLE,
                pharmacy_id: Optional[str] = None, pharmacy_name: Optional[str] = None) -> dict:
    """Creates an account, and by default the workspace it owns.

    Registration provisions a new Pharmacy per account. That is what "a clean
    slate" means concretely: invoices, products and vendors all hang off a
    pharmacy, so a new tenant starts empty because there is nothing attached
    to it yet - not because anything is filtered out of a shared pile.

    Passing an existing `pharmacy_id` instead adds someone to a workspace that
    already exists, which is how a Super Admin adds staff to their own.

    The uniqueness constraint on User.email is the authority on duplicates,
    not a prior lookup: checking first and inserting second leaves a window
    where two concurrent requests both pass the check.
    """
    email = normalize_email(email)
    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")
    if password is not None and (not password or len(password) < 12):
        # Length beats composition rules: a 12-character passphrase resists
        # guessing better than "P@ss1" and people do not write it on a note.
        raise ValueError("Password must be at least 12 characters.")

    display = (name or "").strip() or email.split("@")[0]
    joining = pharmacy_id is not None
    # Someone creating their own workspace administers it; someone being added
    # to an existing one gets whatever role the admin chose.
    effective_role = normalize_role(role) if joining else "super_admin"

    params = dict(
        id=str(uuid.uuid4()),
        email=email,
        name=display,
        password_hash=hash_password(password) if password else None,
        role=effective_role,
        pharmacy_id=pharmacy_id or str(uuid.uuid4()),
        pharmacy_name=(pharmacy_name or "").strip() or f"{display}'s pharmacy",
    )

    query = ("MATCH (ph:Pharmacy {id: $pharmacy_id})" if joining else
             "MERGE (ph:Pharmacy {id: $pharmacy_id}) "
             "ON CREATE SET ph.name = $pharmacy_name, ph.created_at = datetime()")
    try:
        record = _write(
            query + """
            CREATE (u:User {
                id: $id, email: $email, name: $name,
                password_hash: $password_hash, role: $role,
                is_active: true, created_at: datetime(), last_login_at: null
            })
            MERGE (u)-[:MEMBER_OF {role: $role}]->(ph)
            RETURN u, ph.id AS pharmacy_id
            """,
            **params,
        )
    except Exception as e:
        if "already exists" in str(e) or "ConstraintValidationFailed" in type(e).__name__:
            raise UserExistsError(f"An account already exists for {email}.")
        raise
    if record is None:
        raise UnknownUserError("That workspace no longer exists.")
    out = _public(record["u"])
    out["pharmacy_id"] = record["pharmacy_id"]
    return out


def credentials_for(email: str) -> Optional[dict]:
    """The only read that returns a hash. Login uses it; nothing else may.

    Returns the hash alongside `is_active` rather than filtering inactive
    accounts out in Cypher, so the caller can still spend the verification
    time on a disabled account and keep the response indistinguishable.
    """
    rows = _read(
        "MATCH (u:User {email: $email}) RETURN u.id AS id, u.email AS email, "
        "u.role AS role, u.is_active AS is_active, u.password_hash AS password_hash",
        email=normalize_email(email),
    )
    return dict(rows[0]) if rows else None


def get_user(user_id: str) -> Optional[dict]:
    """The account plus the workspace it belongs to.

    `pharmacy_id` rides along on every request because it scopes every query
    the caller will make; fetching it separately would mean each router
    remembering to, and the one that forgot would read another tenant's data.
    """
    rows = _read(
        "MATCH (u:User {id: $id}) OPTIONAL MATCH (u)-[:MEMBER_OF]->(ph:Pharmacy) "
        "RETURN u, ph.id AS pharmacy_id, ph.name AS pharmacy_name",
        id=user_id,
    )
    if not rows:
        return None
    out = _public(rows[0]["u"])
    out["pharmacy_id"] = rows[0]["pharmacy_id"]
    out["pharmacy_name"] = rows[0]["pharmacy_name"]
    return out


def list_users(pharmacy_id: str) -> list[dict]:
    """Everyone in one workspace, newest last.

    Scoped rather than global: an admin manages their own staff, and the
    account list is exactly the kind of query where a missing tenant filter
    quietly leaks every customer's team to every other customer.
    """
    rows = _read(
        "MATCH (u:User)-[:MEMBER_OF]->(:Pharmacy {id: $pharmacy_id}) "
        "RETURN u ORDER BY u.created_at ASC",
        pharmacy_id=pharmacy_id,
    )
    return [_public(r["u"]) for r in rows]


def count_users(pharmacy_id: Optional[str] = None) -> int:
    if pharmacy_id:
        rows = _read("MATCH (u:User)-[:MEMBER_OF]->(:Pharmacy {id: $pharmacy_id}) "
                     "RETURN count(u) AS c", pharmacy_id=pharmacy_id)
    else:
        rows = _read("MATCH (u:User) RETURN count(u) AS c")
    return int(rows[0]["c"]) if rows else 0


def record_login(user_id: str) -> None:
    _write("MATCH (u:User {id: $id}) SET u.last_login_at = datetime() RETURN u", id=user_id)


def set_password(user_id: str, password: str) -> dict:
    if not password or len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    record = _write(
        "MATCH (u:User {id: $id}) SET u.password_hash = $h RETURN u",
        id=user_id, h=hash_password(password),
    )
    if record is None:
        raise UnknownUserError(user_id)
    return _public(record["u"])


def update_user(user_id: str, name: Optional[str] = None,
                role: Optional[str] = None, is_active: Optional[bool] = None) -> dict:
    """Applies only the fields given. Role changes update the MEMBER_OF edge
    too, so the graph does not disagree with the node about who someone is."""
    sets, params = [], {"id": user_id}
    if name is not None:
        sets.append("u.name = $name")
        params["name"] = name.strip()
    if role is not None:
        sets.append("u.role = $role")
        params["role"] = normalize_role(role)
    if is_active is not None:
        sets.append("u.is_active = $is_active")
        params["is_active"] = bool(is_active)
    if not sets:
        existing = get_user(user_id)
        if existing is None:
            raise UnknownUserError(user_id)
        return existing

    record = _write(
        f"MATCH (u:User {{id: $id}}) SET {', '.join(sets)} "
        "WITH u OPTIONAL MATCH (u)-[m:MEMBER_OF]->(:Pharmacy) "
        "SET m.role = u.role RETURN u",
        **params,
    )
    if record is None:
        raise UnknownUserError(user_id)
    return _public(record["u"])
