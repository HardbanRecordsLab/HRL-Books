"""Data model, stage 1 slice (spec section 10). Every user-data table carries workspace_id."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


ROLES = ("owner", "editor", "author", "reviewer")
BOOK_STATUSES = ("idea", "research", "writing", "editing", "preparation", "distribution", "published", "archived")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # FR-AI-07: opt-in, off by default
    research_gate_mode: Mapped[str] = mapped_column(String(10), default="soft")  # decision 5: soft
    limits: Mapped[dict] = mapped_column(JSON, default=lambda: {"max_titles": 50, "storage_mb": 2048, "ai_jobs_per_day": 50})
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship()


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    """Opaque refresh tokens, stored hashed; rotated on use. Reuse of a rotated token revokes the family."""
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    workspace_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(200), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Book(Base):
    __tablename__ = "books"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    subtitle: Mapped[str] = mapped_column(String(500), default="")
    language: Mapped[str] = mapped_column(String(10), default="pl")
    status: Mapped[str] = mapped_column(String(20), default="idea")
    desc_short: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # soft delete, 30 days
