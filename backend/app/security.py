"""Passwords (Argon2id), access JWTs, rotating refresh tokens, permission matrix (spec 3.2, 9.2)."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RefreshToken, utcnow

_ph = PasswordHasher()  # argon2id with library defaults
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=s.ACCESS_TOKEN_MINUTES), "typ": "access"}
    return jwt.encode(payload, s.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload.get("sub") if payload.get("typ") == "access" else None


def issue_refresh_token(db: Session, user_id: str, family_id: str | None = None) -> str:
    raw = new_opaque_token()
    db.add(RefreshToken(
        token_hash=sha256(raw),
        family_id=family_id or str(uuid.uuid4()),
        user_id=user_id,
        expires_at=utcnow() + timedelta(days=get_settings().REFRESH_TOKEN_DAYS),
    ))
    return raw


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rotate_refresh_token(db: Session, raw: str) -> tuple[str, str] | None:
    """Return (user_id, new_raw) or None. Reusing an already-rotated token revokes its whole family."""
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256(raw)))
    if rt is None:
        return None
    if rt.revoked_at is not None:
        revoke_family(db, rt.family_id)
        return None
    if _aware(rt.expires_at) < utcnow():
        return None
    rt.revoked_at = utcnow()
    return rt.user_id, issue_refresh_token(db, rt.user_id, rt.family_id)


def revoke_family(db: Session, family_id: str) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def revoke_by_raw(db: Session, raw: str) -> None:
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256(raw)))
    if rt is not None:
        revoke_family(db, rt.family_id)


# Permission matrix (spec 3.2). Roles are not a ladder: the API checks the concrete permission.
PERMISSIONS: dict[str, set[str]] = {
    "invite_members": {"owner"},
    "manage_workspace": {"owner"},
    "create_book": {"owner", "author"},
    "delete_book": {"owner"},
    "read_books": {"owner", "editor", "author", "reviewer"},
    "edit_metadata": {"owner", "editor"},
    "edit_book": {"owner", "editor", "author"},
    "manage_distribution": {"owner"},
    "read_distribution": {"owner", "editor", "author"},
    "royalties": {"owner"},
    "manage_shop": {"owner"},
    "read_research": {"owner", "editor", "author"},
    "edit_research": {"owner", "author"},
    "edit_manuscript": {"owner", "editor", "author"},
    "upload_files": {"owner", "editor", "author"},
    "use_ai": {"owner", "editor", "author"},
}


def role_can(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())
