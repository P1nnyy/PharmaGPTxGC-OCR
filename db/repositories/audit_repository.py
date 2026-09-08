"""The record of who did what, and when.

Append-only. Events are written once and never updated or deleted, because an
audit trail that can be edited answers a different and much weaker question
than the one it exists to answer.

Two structural decisions follow from that:

  * The workspace and the target are stored as **plain properties, not
    relationships**. `DETACH DELETE` follows relationships, so an audit event
    joined by an edge to the invoice it describes would be destroyed by the
    very deletion it is supposed to record. This is the same lesson the scan
    ledger learned.
  * `actor_email` and `actor_name` are copied onto the event rather than
    looked up through the actor's account. People get renamed and accounts get
    removed; the trail has to keep saying who it was at the time.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from core.logger import logger
from core.tenancy import current_tenant
from db.graph_db import get_driver

# The vocabulary, kept closed so the log stays queryable. An action not listed
# here is still recorded - refusing to log something because its name is
# unfamiliar would lose the very event most worth having - but it is flagged
# so the omission gets noticed.
ACTIONS = {
    "auth.registered", "auth.signed_in", "auth.sign_in_failed", "auth.signed_out",
    "user.invited", "user.invite_accepted", "user.invite_revoked",
    "user.role_changed", "user.deactivated", "user.reactivated", "user.password_reset",
    "invoice.created", "invoice.updated", "invoice.deleted", "invoice.verified",
    "product.updated", "product.merged", "product.confirmed", "product.alias_split",
    "item_type.created", "item_type.updated", "item_type.deleted",
    "shop.updated",
    "cache.cleared",
}


def record(
    action: str,
    actor: Optional[dict] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    summary: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
    **details: Any,
) -> None:
    """Writes one event.

    Never raises. A failure to record must not fail the action being recorded:
    refusing to delete an invoice because the audit write timed out would be a
    worse outcome than a gap in the log, and the gap is logged loudly either
    way. This is the one place where swallowing an exception is correct.
    """
    if action not in ACTIONS:
        logger.warning(f"[AUDIT] unrecognised action '{action}' - recorded anyway")

    try:
        workspace = pharmacy_id or (actor or {}).get("pharmacy_id") or current_tenant()
    except Exception:
        # An event with no workspace is still worth keeping - a failed sign-in
        # happens before any workspace is known.
        workspace = None

    try:
        driver = get_driver()
        with driver.session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    """
                    CREATE (e:AuditEvent {
                        id: $id, pharmacy_id: $pharmacy_id,
                        actor_id: $actor_id, actor_email: $actor_email, actor_name: $actor_name,
                        action: $action, target_type: $target_type, target_id: $target_id,
                        summary: $summary, details: $details, at: datetime()
                    })
                    """,
                    id=str(uuid.uuid4()),
                    pharmacy_id=workspace,
                    actor_id=(actor or {}).get("id"),
                    actor_email=(actor or {}).get("email"),
                    actor_name=(actor or {}).get("name"),
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    summary=summary,
                    # Flattened to strings: Neo4j cannot store a map on a node,
                    # and a stringified detail still reads fine in the trail.
                    details=[f"{k}={v}" for k, v in sorted(details.items()) if v is not None],
                )
            )
    except Exception as e:
        logger.error(f"[AUDIT] failed to record {action}: {e}")


def _serialize(row: dict) -> dict:
    at = row.get("at")
    return {
        "id": row.get("id"),
        "at": at.isoformat() if hasattr(at, "isoformat") else at,
        "actor_id": row.get("actor_id"),
        "actor_email": row.get("actor_email"),
        "actor_name": row.get("actor_name"),
        "action": row.get("action"),
        "target_type": row.get("target_type"),
        "target_id": row.get("target_id"),
        "summary": row.get("summary"),
        "details": row.get("details") or [],
    }


def list_events(
    pharmacy_id: Optional[str] = None,
    limit: int = 100,
    action: Optional[str] = None,
    actor_id: Optional[str] = None,
    before: Optional[str] = None,
) -> dict:
    """One workspace's trail, newest first.

    Scoped like everything else - an unscoped audit view would show every
    customer's activity to every other customer, which is a worse leak than
    the data itself.
    """
    workspace = pharmacy_id or current_tenant()
    limit = max(1, min(int(limit), 500))

    driver = get_driver()
    with driver.session() as session:
        rows = session.execute_read(
            lambda tx: [
                r.data()
                for r in tx.run(
                    """
                    MATCH (e:AuditEvent {pharmacy_id: $pharmacy_id})
                    WHERE ($action IS NULL OR e.action = $action)
                      AND ($actor_id IS NULL OR e.actor_id = $actor_id)
                      AND ($before IS NULL OR toString(e.at) < $before)
                    RETURN e.id AS id, e.at AS at, e.actor_id AS actor_id,
                           e.actor_email AS actor_email, e.actor_name AS actor_name,
                           e.action AS action, e.target_type AS target_type,
                           e.target_id AS target_id, e.summary AS summary,
                           e.details AS details
                    ORDER BY e.at DESC
                    LIMIT $limit
                    """,
                    pharmacy_id=workspace, action=action, actor_id=actor_id,
                    before=before, limit=limit,
                )
            ]
        )

    events = [_serialize(r) for r in rows]
    return {
        "events": events,
        # The caller pages by passing the oldest timestamp it has seen back as
        # `before`, rather than an offset, so a new event arriving mid-scroll
        # cannot shift the page under them.
        "next_before": events[-1]["at"] if len(events) == limit else None,
        "actions": sorted(ACTIONS),
    }
