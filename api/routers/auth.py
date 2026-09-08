"""Sign-in and account management.

Lives under `/auth/` for the same reason reports do: `/auth` may one day be a
page route in the SPA, and a bare prefix would let the edge swallow it.

Account creation is deliberately admin-only - there is no self-serve signup.
A pharmacy's staff list is not something a stranger should be able to add
themselves to, and every account here is someone the owner hired.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.deps import current_user, require_super_admin
from core import google_oauth
from core.config import settings
from core.security import AuthConfigError, create_access_token, verify_password
from db.repositories import (audit_repository, invite_repository,
                             pharmacy_repository, user_repository)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    name: str = ""
    password: str = Field(min_length=12)
    confirm_password: str
    pharmacy_name: str = ""
    # Present when arriving from an invitation link: joins that workspace
    # instead of creating one.
    invite_token: Optional[str] = None


class ShopProfileRequest(BaseModel):
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    gstin: Optional[str] = None
    drug_licence_number: Optional[str] = None
    fssai_number: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    phone: Optional[str] = None
    contact_email: Optional[str] = None


class InviteRequest(BaseModel):
    email: str
    role: str = user_repository.DEFAULT_ROLE


class CreateUserRequest(BaseModel):
    email: str
    name: str = ""
    password: str = Field(min_length=12)
    role: str = user_repository.DEFAULT_ROLE


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordRequest(BaseModel):
    password: str = Field(min_length=12)


# One message for every failure mode. "No such account" and "wrong password"
# are the same sentence on purpose: telling them apart hands an attacker a
# free check for which addresses are registered.
_REJECTED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Email or password is incorrect.",
)


@router.post("/login")
def login(payload: LoginRequest):
    """Exchanges credentials for a session token."""
    record = user_repository.credentials_for(payload.email)

    # Always verify, even with no record: `verify_password` burns the same
    # bcrypt time against a dummy hash, so a request for an unknown address
    # takes as long as one for a real account.
    matched = verify_password(payload.password, (record or {}).get("password_hash"))
    if not record or not matched or not record.get("is_active"):
        # Recorded without an actor when the address is unknown: a run of
        # these against one address is what a guessing attempt looks like.
        audit_repository.record(
            "auth.sign_in_failed",
            actor={"email": user_repository.normalize_email(payload.email)} if record is None else record,
            pharmacy_id=(record or {}).get("pharmacy_id"),
            summary=f"Failed sign-in for {user_repository.normalize_email(payload.email)}",
            reason="inactive" if (record and matched) else "bad_credentials",
        )
        raise _REJECTED

    try:
        token = create_access_token(record["id"], record["email"], record["role"])
    except AuthConfigError as e:
        # A missing signing key is our fault, not the caller's, and must not
        # be reported as a bad password.
        raise HTTPException(status_code=500, detail=str(e))

    user_repository.record_login(record["id"])
    full = user_repository.get_user(record["id"])
    audit_repository.record("auth.signed_in", actor=full,
                            target_type="user", target_id=full["id"],
                            summary=f"{full['email']} signed in")
    return {"access_token": token, "token_type": "bearer", "user": full}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest):
    """Self-serve sign-up. Creates an account and the empty workspace it owns.

    Public, and safe to be public only because of that second half: a new
    account lands in a pharmacy of its own with nothing attached to it. There
    is no shared pile to be dropped into, so a stranger registering sees an
    empty application rather than someone else's invoices.
    """
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="The two passwords do not match.")

    # An invitation decides both the workspace and the role. It is consumed
    # before the account is created so a link cannot seat two people, and the
    # email is checked against it inside accept().
    invited = None
    if payload.invite_token:
        try:
            invited = invite_repository.accept(payload.invite_token, payload.email)
        except invite_repository.InviteError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        user = user_repository.create_user(
            email=payload.email, name=payload.name,
            password=payload.password, pharmacy_name=payload.pharmacy_name,
            pharmacy_id=invited["pharmacy_id"] if invited else None,
            role=invited["role"] if invited else user_repository.DEFAULT_ROLE,
        )
    except user_repository.UserExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Signed in immediately: making someone register and then type the same
    # credentials again is friction with nothing behind it, since registering
    # already proved they hold the address.
    try:
        token = create_access_token(user["id"], user["email"], user["role"])
    except AuthConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    user_repository.record_login(user["id"])
    full = user_repository.get_user(user["id"])
    audit_repository.record(
        "user.invite_accepted" if invited else "auth.registered",
        actor=full, target_type="user", target_id=user["id"],
        summary=(f"{user['email']} joined the workspace by invitation"
                 if invited else f"{user['email']} registered a new workspace"),
    )
    return {"access_token": token, "token_type": "bearer", "user": full}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    """Who the current token belongs to. The SPA calls this on load to decide
    whether a stored token is still good."""
    return user


@router.get("/roles")
def roles(user: dict = Depends(current_user)):
    """The role vocabulary, so the UI does not hardcode its own copy."""
    return {"roles": list(user_repository.ROLES), "default": user_repository.DEFAULT_ROLE}


@router.get("/users")
def list_users(user: dict = Depends(require_super_admin)):
    return {"users": user_repository.list_users(user["pharmacy_id"])}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: CreateUserRequest, user: dict = Depends(require_super_admin)):
    try:
        # Staff join the admin's existing workspace rather than getting one
        # of their own - that is the difference between adding a colleague
        # and creating a separate customer.
        created = user_repository.create_user(
            email=payload.email, name=payload.name,
            password=payload.password, role=payload.role,
            pharmacy_id=user["pharmacy_id"],
        )
        audit_repository.record(
            "user.invited", actor=user, target_type="user", target_id=created["id"],
            summary=f"{user['email']} created an account for {created['email']} as {created['role']}",
        )
        return created
    except user_repository.UserExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: UpdateUserRequest, user: dict = Depends(require_super_admin)):
    """Renames, re-roles or disables an account.

    A super admin may not remove their own last privilege or disable
    themselves: doing so would leave the deployment with no one able to
    administer it, recoverable only by editing the database by hand.
    """
    if user_id == user["id"]:
        if payload.is_active is False:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
        if payload.role is not None and payload.role != "super_admin":
            raise HTTPException(status_code=400, detail="You cannot remove your own Super Admin role.")

    if payload.is_active is False or (payload.role and payload.role != "super_admin"):
        _guard_last_admin(user_id, user["pharmacy_id"])

    try:
        updated = user_repository.update_user(
            user_id, name=payload.name, role=payload.role, is_active=payload.is_active,
        )
    except user_repository.UnknownUserError:
        raise HTTPException(status_code=404, detail="No such account.")

    if payload.role is not None:
        audit_repository.record(
            "user.role_changed", actor=user, target_type="user", target_id=user_id,
            summary=f"{user['email']} set {updated['email']} to {updated['role']}",
        )
    if payload.is_active is not None:
        audit_repository.record(
            "user.deactivated" if not payload.is_active else "user.reactivated",
            actor=user, target_type="user", target_id=user_id,
            summary=f"{user['email']} {'disabled' if not payload.is_active else 're-enabled'} {updated['email']}",
        )
    return updated


@router.post("/users/{user_id}/password")
def set_password(user_id: str, payload: PasswordRequest, user: dict = Depends(require_super_admin)):
    """Admin password reset - the stand-in for reset-by-email at this scale."""
    try:
        changed = user_repository.set_password(user_id, payload.password)
        audit_repository.record(
            "user.password_reset", actor=user, target_type="user", target_id=user_id,
            summary=f"{user['email']} reset the password for {changed['email']}",
        )
        return changed
    except user_repository.UnknownUserError:
        raise HTTPException(status_code=404, detail="No such account.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _guard_last_admin(user_id: str, pharmacy_id: str) -> None:
    """Refuses a change that would leave no active super admin at all."""
    others = [
        u for u in user_repository.list_users(pharmacy_id)
        if u["id"] != user_id and u["role"] == "super_admin" and u["is_active"]
    ]
    if not others:
        raise HTTPException(
            status_code=400,
            detail="This is the only active Super Admin; promote someone else first.",
        )


# ---- Invitations ----------------------------------------------------------
# No email is sent. The admin receives a link and passes it on over a channel
# they trust; adding a mail provider later means sending this same link rather
# than reworking anything.


@router.post("/invites", status_code=status.HTTP_201_CREATED)
def create_invite(payload: InviteRequest, request: Request, user: dict = Depends(require_super_admin)):
    """Issues an invitation and returns the link to share.

    The token comes back exactly once, here. Listing invitations never returns
    it again, so a leaked list is not a set of working keys.
    """
    try:
        invite = invite_repository.create(
            email=payload.email, role=payload.role, invited_by=user,
            pharmacy_id=user["pharmacy_id"],
        )
    except invite_repository.InviteError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    token = invite.pop("token")
    # Built from the request so it works on localhost and the deployed domain
    # without a configured base URL to drift out of date.
    invite["invite_url"] = str(request.base_url).rstrip("/") + f"/join/{token}"
    audit_repository.record(
        "user.invited", actor=user, target_type="invitation", target_id=invite["id"],
        summary=f"{user['email']} invited {invite['email']} as {invite['role']}",
    )
    return invite


@router.get("/invites")
def list_invites(user: dict = Depends(require_super_admin)):
    return {"invites": invite_repository.list_invites(user["pharmacy_id"])}


@router.delete("/invites/{invite_id}")
def revoke_invite(invite_id: str, user: dict = Depends(require_super_admin)):
    try:
        invite = invite_repository.revoke(invite_id, user["pharmacy_id"])
    except invite_repository.InviteError as e:
        raise HTTPException(status_code=404, detail=str(e))
    audit_repository.record(
        "user.invite_revoked", actor=user, target_type="invitation", target_id=invite_id,
        summary=f"{user['email']} revoked the invitation for {invite['email']}",
    )
    return invite


@router.get("/invites/lookup/{token}")
def lookup_invite(token: str):
    """What an invitation link points at, for the acceptance screen.

    Public by necessity - the recipient has no account yet. It returns the
    workspace name, the address it was issued for and whether it is still
    open, and nothing about the workspace's contents.
    """
    invite = invite_repository.for_token(token)
    if invite is None:
        raise HTTPException(status_code=404, detail="That invitation link is not valid.")
    return invite


# ---- Audit trail ----------------------------------------------------------


@router.get("/audit")
def audit_trail(
    limit: int = 100,
    action: Optional[str] = None,
    actor_id: Optional[str] = None,
    before: Optional[str] = None,
    user: dict = Depends(require_super_admin),
):
    """Who did what, newest first. Scoped to the caller's workspace."""
    return audit_repository.list_events(
        pharmacy_id=user["pharmacy_id"], limit=limit,
        action=action, actor_id=actor_id, before=before,
    )


# ---- The shop -------------------------------------------------------------


@router.get("/shop")
def get_shop(user: dict = Depends(current_user)):
    """The workspace's business details, and what is still missing.

    Readable by every member, not just admins: the shop's GSTIN and address
    appear on what they are scanning, so hiding it from staff would be
    theatre.
    """
    profile = pharmacy_repository.get_profile(user["pharmacy_id"])
    return {
        "shop": profile,
        "missing": pharmacy_repository.missing_fields(profile),
        "required": list(pharmacy_repository.REQUIRED_FIELDS),
    }


@router.patch("/shop")
def update_shop(payload: ShopProfileRequest, user: dict = Depends(require_super_admin)):
    """Records the business details. Super Admin only - it is a Settings action.

    The GSTIN is validated here rather than on first use. A wrong one would
    not fail loudly; it would quietly mis-assign buyer and seller on every
    invoice scanned afterwards, which is far harder to notice and to undo.
    """
    try:
        shop = pharmacy_repository.update_profile(
            payload.model_dump(exclude_none=True), user["pharmacy_id"]
        )
    except pharmacy_repository.ProfileError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    audit_repository.record(
        "shop.updated", actor=user, target_type="pharmacy", target_id=user["pharmacy_id"],
        summary=f"{user['email']} updated the shop profile",
        fields=",".join(sorted(payload.model_dump(exclude_none=True).keys())),
    )
    return {
        "shop": shop,
        "missing": pharmacy_repository.missing_fields(shop),
        "required": list(pharmacy_repository.REQUIRED_FIELDS),
    }


# ---- Sign in with Google --------------------------------------------------


def _redirect_uri() -> str:
    """Must match a URI registered at Google, character for character."""
    return settings.PUBLIC_BASE_URL.rstrip("/") + "/auth/google/callback"


@router.get("/google/status")
def google_status():
    """Whether the server can offer Google sign-in.

    The button is drawn from this rather than assumed, so a deployment with no
    credentials shows a working email form instead of a button that fails.
    """
    return {"available": google_oauth.is_configured()}


@router.get("/google/start")
def google_start(invite: Optional[str] = None, next: str = "/"):
    """Sends the browser to Google's consent screen."""
    try:
        state = google_oauth.make_state(invite_token=invite, next_path=next)
        url = google_oauth.authorization_url(_redirect_uri(), state)
    except google_oauth.GoogleAuthError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AuthConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return RedirectResponse(url, status_code=307)


@router.get("/google/callback")
def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Where Google returns. Signs the person in, creating the account if new.

    The session token goes back in the URL **fragment**, not the query string:
    a fragment is never sent to a server, so it stays out of access logs and
    out of the Referer header on the next navigation. The SPA reads it and
    clears it from the address bar immediately.
    """
    def fail(message: str) -> RedirectResponse:
        # Errors go back to the app rather than rendering a bare API page, so
        # someone who declines consent lands somewhere they can try again.
        from urllib.parse import quote
        return RedirectResponse(
            settings.PUBLIC_BASE_URL.rstrip("/") + f"/#auth_error={quote(message)}",
            status_code=303,
        )

    if error:
        return fail("Google sign-in was cancelled.")
    if not code or not state:
        return fail("That sign-in link was incomplete.")

    try:
        claims = google_oauth.read_state(state)
        tokens = google_oauth.exchange_code(code, _redirect_uri())
        identity = google_oauth.identity_from(tokens)
    except google_oauth.GoogleAuthError as e:
        return fail(str(e))

    # An invitation decides the workspace and role; without one, a first-time
    # signer-in gets a workspace of their own.
    invited = None
    if claims.get("invite"):
        try:
            invited = invite_repository.accept(claims["invite"], identity["email"])
        except invite_repository.InviteError as e:
            return fail(str(e))

    user, created = user_repository.find_or_create_google_user(
        email=identity["email"], name=identity["name"], google_sub=identity["google_sub"],
        pharmacy_id=invited["pharmacy_id"] if invited else None,
        role=invited["role"] if invited else user_repository.DEFAULT_ROLE,
    )
    if not user.get("is_active"):
        return fail("That account has been disabled.")

    try:
        token = create_access_token(user["id"], user["email"], user["role"])
    except AuthConfigError as e:
        return fail(str(e))

    user_repository.record_login(user["id"])
    audit_repository.record(
        "user.invite_accepted" if invited else ("auth.registered" if created else "auth.signed_in"),
        actor=user, target_type="user", target_id=user["id"],
        summary=f"{user['email']} signed in with Google" + (" (new account)" if created else ""),
        provider="google",
    )

    from urllib.parse import quote
    destination = claims.get("next") or "/"
    return RedirectResponse(
        settings.PUBLIC_BASE_URL.rstrip("/") + f"/#token={quote(token)}&next={quote(destination)}",
        status_code=303,
    )
