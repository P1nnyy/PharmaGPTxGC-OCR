"""Sign-in and account management.

Lives under `/auth/` for the same reason reports do: `/auth` may one day be a
page route in the SPA, and a bare prefix would let the edge swallow it.

Account creation is deliberately admin-only - there is no self-serve signup.
A pharmacy's staff list is not something a stranger should be able to add
themselves to, and every account here is someone the owner hired.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import current_user, require_super_admin
from core.security import AuthConfigError, create_access_token, verify_password
from db.repositories import user_repository

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
        raise _REJECTED

    try:
        token = create_access_token(record["id"], record["email"], record["role"])
    except AuthConfigError as e:
        # A missing signing key is our fault, not the caller's, and must not
        # be reported as a bad password.
        raise HTTPException(status_code=500, detail=str(e))

    user_repository.record_login(record["id"])
    return {"access_token": token, "token_type": "bearer", "user": user_repository.get_user(record["id"])}


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
    try:
        user = user_repository.create_user(
            email=payload.email, name=payload.name,
            password=payload.password, pharmacy_name=payload.pharmacy_name,
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
    return {"access_token": token, "token_type": "bearer", "user": user_repository.get_user(user["id"])}


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
        return user_repository.create_user(
            email=payload.email, name=payload.name,
            password=payload.password, role=payload.role,
            pharmacy_id=user["pharmacy_id"],
        )
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
        return user_repository.update_user(
            user_id, name=payload.name, role=payload.role, is_active=payload.is_active,
        )
    except user_repository.UnknownUserError:
        raise HTTPException(status_code=404, detail="No such account.")


@router.post("/users/{user_id}/password")
def set_password(user_id: str, payload: PasswordRequest, user: dict = Depends(require_super_admin)):
    """Admin password reset - the stand-in for reset-by-email at this scale."""
    try:
        return user_repository.set_password(user_id, payload.password)
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
