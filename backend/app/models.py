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
    # FR-META-06: [{"canonical": "Kamil Skomra", "forbidden": ["Skomrakus", "K. Skomra"]}]
    identity_rules: Mapped[list] = mapped_column(JSON, default=list)
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
    # Links to the book in stores (also filled by the import of already-published titles).
    store_links: Mapped[list] = mapped_column(JSON, default=list)
    desc_long: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    audience: Mapped[str] = mapped_column(String(200), default="")
    series_name: Mapped[str] = mapped_column(String(300), default="")
    series_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    copyright_holder: Mapped[str] = mapped_column(String(300), default="")
    copyright_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    territories: Mapped[str] = mapped_column(String(200), default="world")
    # FR-META-07 (KDP rules): AI-generated text / images (incl. cover) / translation must be declared.
    ai_disclosure: Mapped[dict] = mapped_column(JSON, default=lambda: {"text": False, "images": False, "translation": False})
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # soft delete, 30 days


CONTRIBUTOR_ROLES = ("author", "editor", "translator", "cover_designer", "illustrator", "narrator")
EDITION_FORMATS = ("ebook_epub", "ebook_pdf", "paperback", "hardcover", "audiobook")


class Person(Base):
    """A contributor (author, editor, translator…) with reusable bios, per workspace (FR-META-02, -05)."""
    __tablename__ = "people"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200))
    bio_short: Mapped[str] = mapped_column(Text, default="")
    bio_long: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BookContributor(Base):
    __tablename__ = "book_contributors"
    __table_args__ = (UniqueConstraint("book_id", "person_id", "role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    position: Mapped[int] = mapped_column(Integer, default=0)


class Edition(Base):
    """A concrete format of a title (FR-META-03, -04). ISBN optional until the publisher gets a pool."""
    __tablename__ = "editions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    format: Mapped[str] = mapped_column(String(20))
    isbn: Mapped[str] = mapped_column(String(20), default="")
    release_date: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drm: Mapped[bool] = mapped_column(Boolean, default=False)
    # [{"market": "PL", "currency": "PLN", "amount": 39.99}]
    prices: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
