"""Workspace invitations.

An invitation is a claim on a seat, not an email. The token is what grants
access, so the person who holds it joins - which is why the link must be sent
over a channel the admin trusts, and why the invitation is bound to the email
it was issued for and checked on acceptance.

Nothing here sends mail. The admin gets a link and passes it on however they
like; adding an email provider later means sending this same link, not
reworking the model.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.tenancy import current_tenant
from db.graph_db import get_driver
from db.repositories.user_repository import ROLES, normalize_email, normalize_role

# Long enough that guessing is hopeless, short enough to paste into a message.
_TOKEN_BYTES = 32

# An invitation that is never accepted should not stay valid forever - a link
# leaked from an old chat a year later should not still open a workspace.
INVITE_TTL_DAYS = 14


class InviteError(RuntimeError):
    """Raised when an invitation cannot be issued or accepted."""


def _run_write(query: str, **params):
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: tx.run(query, **params).single())


def _run_read(query: str, **params):
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r for r in tx.run(query, **params)])


def _serialize(node) -> dict:
    data = dict(node)
    out = {}
    for key in ("id", "email", "role", "status", "invited_by_email", "pharmacy_id"):
        out[key] = data.get(key)
    for key in ("created_at", "expires_at", "accepted_at"):
        v = data.get(key)
        out[key] = v.isoformat() if hasattr(v, "isoformat") else v
    # The token is deliberately absent. It is returned once, by create(), as
    # part of the link; listing invitations must not hand it out again.
    return out


def create(email: str, role: str, invited_by: dict, pharmacy_id: Optional[str] = None) -> dict:
    """Issues an invitation and returns it together with its one-time token."""
    email = normalize_email(email)
    if not email or "@" not in email:
        raise InviteError("A valid email address is required.")

    role = normalize_role(role)
    if role == "super_admin":
        # Deliberate: a workspace gets more administrators by promoting someone
        # already in it, not by emailing admin rights to an unverified address.
        raise InviteError("Super Admins are promoted from existing members, not invited.")

    workspace = pharmacy_id or current_tenant()
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)

    existing = _run_read(
        "MATCH (u:User {email: $email})-[:MEMBER_OF]->(:Pharmacy {id: $pharmacy_id}) RETURN u",
        email=email, pharmacy_id=workspace,
    )
    if existing:
        raise InviteError(f"{email} is already a member of this workspace.")

    record = _run_write(
        """
        MATCH (ph:Pharmacy {id: $pharmacy_id})
        // One live invitation per address per workspace: re-inviting replaces
        // the previous link rather than leaving two valid ones in the wild.
        OPTIONAL MATCH (old:Invitation {email: $email, pharmacy_id: $pharmacy_id, status: 'pending'})
        SET old.status = 'superseded'
        CREATE (i:Invitation {
            id: $id, pharmacy_id: $pharmacy_id, email: $email, role: $role,
            token: $token, status: 'pending',
            invited_by_id: $invited_by_id, invited_by_email: $invited_by_email,
            created_at: datetime(), expires_at: datetime($expires), accepted_at: null
        })
        MERGE (i)-[:INVITED_TO]->(ph)
        RETURN i, ph.name AS pharmacy_name
        """,
        pharmacy_id=workspace, id=str(uuid.uuid4()), email=email, role=role,
        token=token, expires=expires.isoformat(),
        invited_by_id=invited_by.get("id"), invited_by_email=invited_by.get("email"),
    )
    if record is None:
        raise InviteError("That workspace no longer exists.")

    out = _serialize(record["i"])
    out["pharmacy_name"] = record["pharmacy_name"]
    out["token"] = token
    return out


def for_token(token: str) -> Optional[dict]:
    """Looks up a pending invitation by its token, for the acceptance screen."""
    rows = _run_read(
        """
        MATCH (i:Invitation {token: $token})-[:INVITED_TO]->(ph:Pharmacy)
        RETURN i, ph.name AS pharmacy_name
        """,
        token=token,
    )
    if not rows:
        return None
    out = _serialize(rows[0]["i"])
    out["pharmacy_name"] = rows[0]["pharmacy_name"]
    out["valid"] = _is_open(rows[0]["i"])
    return out


def _is_open(node) -> bool:
    data = dict(node)
    if data.get("status") != "pending":
        return False
    expires = data.get("expires_at")
    if expires is None:
        return True
    try:
        return expires.to_native() > datetime.now(timezone.utc)
    except AttributeError:
        return True


def accept(token: str, email: str) -> dict:
    """Consumes an invitation, returning the workspace and role it grants.

    The email is checked against the invitation: a link forwarded to someone
    else does not let them in under the invited address. Marking it accepted
    in the same write is what stops one link seating two people.
    """
    rows = _run_read(
        "MATCH (i:Invitation {token: $token}) RETURN i", token=token,
    )
    if not rows:
        raise InviteError("That invitation link is not valid.")
    node = rows[0]["i"]
    if not _is_open(node):
        raise InviteError("That invitation has expired or has already been used.")
    if normalize_email(email) != dict(node).get("email"):
        raise InviteError("This invitation was issued for a different email address.")

    record = _run_write(
        """
        MATCH (i:Invitation {token: $token, status: 'pending'})
        SET i.status = 'accepted', i.accepted_at = datetime()
        RETURN i
        """,
        token=token,
    )
    if record is None:
        raise InviteError("That invitation has already been used.")
    return _serialize(record["i"])


def revoke(invite_id: str, pharmacy_id: Optional[str] = None) -> dict:
    workspace = pharmacy_id or current_tenant()
    record = _run_write(
        """
        MATCH (i:Invitation {id: $id, pharmacy_id: $pharmacy_id})
        WHERE i.status = 'pending'
        SET i.status = 'revoked'
        RETURN i
        """,
        id=invite_id, pharmacy_id=workspace,
    )
    if record is None:
        raise InviteError("No pending invitation with that id.")
    return _serialize(record["i"])


def list_invites(pharmacy_id: Optional[str] = None) -> list[dict]:
    workspace = pharmacy_id or current_tenant()
    rows = _run_read(
        "MATCH (i:Invitation {pharmacy_id: $pharmacy_id}) RETURN i ORDER BY i.created_at DESC",
        pharmacy_id=workspace,
    )
    return [_serialize(r["i"]) for r in rows]
