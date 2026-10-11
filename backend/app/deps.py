"""Request dependencies: current user, workspace membership (tenant isolation at the app layer)."""
from fastapi import Depends, Header, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Membership, User
from app.security import decode_access_token, role_can


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Brak tokenu")
    user_id = decode_access_token(authorization[7:])
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Nieprawidłowy lub wygasły token")
    return user


def platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(403, "Tylko administrator platformy")
    return user


def membership(ws: str = Path(...), user: User = Depends(current_user), db: Session = Depends(get_db)) -> Membership:
    """404 (not 403) for a workspace the user doesn't belong to — don't reveal that it exists (spec 8.4)."""
    m = db.scalar(select(Membership).where(Membership.workspace_id == ws, Membership.user_id == user.id))
    if m is None:
        raise HTTPException(404, "Nie znaleziono")
    return m


def require(permission: str):
    def _check(m: Membership = Depends(membership)) -> Membership:
        if not role_can(m.role, permission):
            raise HTTPException(403, "Brak uprawnień")
        return m
    return _check
