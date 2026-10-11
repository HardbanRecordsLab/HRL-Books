from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.deps import current_user
from app.models import Invitation, Membership, User, utcnow
from app.schemas import LoginIn, RefreshIn, RegisterIn, TokensOut, UserOut
from app.security import (create_access_token, hash_password, issue_refresh_token, revoke_by_raw,
                          rotate_refresh_token, sha256, verify_password)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tokens(db: Session, user: User) -> TokensOut:
    return TokensOut(access_token=create_access_token(user.id), refresh_token=issue_refresh_token(db, user.id))


def _valid_invitation(db: Session, token: str) -> Invitation:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == sha256(token)))
    if inv is None or inv.used_at is not None or _aware(inv.expires_at) < utcnow():
        raise HTTPException(400, "Zaproszenie jest nieważne lub wygasło")
    return inv


@router.get("/invitation/{token}")
def invitation_info(token: str, db: Session = Depends(get_db)):
    inv = _valid_invitation(db, token)
    return {"email": inv.email, "role": inv.role, "workspace_id": inv.workspace_id}


@router.post("/register", response_model=TokensOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """FR-ACC-01/06: an account is created only from a valid, one-time invitation."""
    inv = _valid_invitation(db, body.token)
    user = db.scalar(select(User).where(User.email == inv.email))
    if user is None:
        user = User(email=inv.email, password_hash=hash_password(body.password),
                    display_name=body.display_name, email_verified=True)  # the invitation link proves the address
        db.add(user)
        db.flush()
    elif not verify_password(user.password_hash, body.password):
        raise HTTPException(400, "Konto z tym adresem już istnieje — podaj jego hasło, aby przyjąć zaproszenie")
    exists = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == inv.workspace_id))
    if exists is None:
        db.add(Membership(user_id=user.id, workspace_id=inv.workspace_id, role=inv.role))
    inv.used_at = utcnow()
    audit(db, "invitation.accepted", user.id, inv.workspace_id, target=inv.email, role=inv.role)
    tokens = _tokens(db, user)
    db.commit()
    return tokens


@router.post("/login", response_model=TokensOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    s = get_settings()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is not None and user.locked_until and _aware(user.locked_until) > utcnow():
        raise HTTPException(429, "Zbyt wiele nieudanych prób — spróbuj później")
    if user is None or not verify_password(user.password_hash, body.password):
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= s.LOGIN_MAX_FAILURES:
                user.locked_until = utcnow() + timedelta(minutes=s.LOGIN_LOCK_MINUTES)
                user.failed_logins = 0
                audit(db, "login.locked", user.id)
            db.commit()
        raise HTTPException(401, "Nieprawidłowy e-mail lub hasło")
    user.failed_logins = 0
    user.locked_until = None
    audit(db, "login.success", user.id)
    tokens = _tokens(db, user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokensOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    result = rotate_refresh_token(db, body.refresh_token)
    db.commit()
    if result is None:
        raise HTTPException(401, "Sesja wygasła — zaloguj się ponownie")
    user_id, new_raw = result
    return TokensOut(access_token=create_access_token(user_id), refresh_token=new_raw)


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    revoke_by_raw(db, body.refresh_token)
    audit(db, "logout", user.id)
    db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
