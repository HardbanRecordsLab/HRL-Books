from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

Role = Literal["owner", "editor", "author", "reviewer"]


class RegisterIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    display_name: str
    is_platform_admin: bool


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    slug: str
    ai_enabled: bool
    research_gate_mode: str
    status: str
    identity_rules: list[dict] = []


class MyWorkspaceOut(WorkspaceOut):
    role: Role


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9-]{2,80}$")
    owner_email: EmailStr


class IdentityRule(BaseModel):
    canonical: str = Field(min_length=2, max_length=200)
    forbidden: list[str] = Field(default_factory=list, max_length=20)


class WorkspacePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    identity_rules: list[IdentityRule] | None = Field(default=None, max_length=20)
    ai_enabled: bool | None = None
    research_gate_mode: Literal["soft", "hard"] | None = None


class InviteIn(BaseModel):
    email: EmailStr
    role: Role


class BookIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    subtitle: str = Field(default="", max_length=500)
    language: str = Field(default="pl", max_length=10)
    desc_short: str = Field(default="", max_length=2000)


BookStatus = Literal["idea", "research", "writing", "editing", "preparation", "distribution", "published", "archived"]


class StoreLink(BaseModel):
    url: HttpUrl
    channel: str = Field(default="", max_length=80)


class BookPatchIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    subtitle: str | None = Field(default=None, max_length=500)
    language: str | None = Field(default=None, max_length=10)
    status: BookStatus | None = None
    desc_short: str | None = Field(default=None, max_length=2000)
    store_links: list[StoreLink] | None = Field(default=None, max_length=50)


class BookImportItem(BookIn):
    status: BookStatus = "published"
    store_links: list[StoreLink] = Field(default_factory=list, max_length=50)


class BookImportIn(BaseModel):
    books: list[BookImportItem] = Field(min_length=1, max_length=500)


class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    title: str
    subtitle: str
    language: str
    status: str
    desc_short: str
    store_links: list[dict]
    created_at: datetime


class MemberOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: Role


ContributorRole = Literal["author", "editor", "translator", "cover_designer", "illustrator", "narrator"]
EditionFormat = Literal["ebook_epub", "ebook_pdf", "paperback", "hardcover", "audiobook"]


class PersonIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=200)
    bio_short: str = Field(default="", max_length=1000)
    bio_long: str = Field(default="", max_length=5000)


class PersonOut(PersonIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


class ContributorIn(BaseModel):
    person_id: str
    role: ContributorRole


class ContributorOut(BaseModel):
    person_id: str
    display_name: str
    role: str
    position: int


class AiDisclosure(BaseModel):
    text: bool = False
    images: bool = False
    translation: bool = False


class MetadataIn(BaseModel):
    desc_long: str | None = Field(default=None, max_length=20000)
    keywords: list[str] | None = Field(default=None, max_length=50)
    categories: list[str] | None = Field(default=None, max_length=20)
    audience: str | None = Field(default=None, max_length=200)
    series_name: str | None = Field(default=None, max_length=300)
    series_volume: int | None = Field(default=None, ge=1, le=999)
    copyright_holder: str | None = Field(default=None, max_length=300)
    copyright_year: int | None = Field(default=None, ge=1900, le=2100)
    territories: str | None = Field(default=None, max_length=200)
    ai_disclosure: AiDisclosure | None = None
    contributors: list[ContributorIn] | None = Field(default=None, max_length=30)


class MetadataOut(BaseModel):
    desc_long: str
    keywords: list[str]
    categories: list[str]
    audience: str
    series_name: str
    series_volume: int | None
    copyright_holder: str
    copyright_year: int | None
    territories: str
    ai_disclosure: dict
    contributors: list[ContributorOut]


class Price(BaseModel):
    market: str = Field(min_length=2, max_length=5)
    currency: str = Field(min_length=3, max_length=3)
    amount: float = Field(ge=0, le=100000)


class EditionIn(BaseModel):
    format: EditionFormat
    isbn: str = Field(default="", max_length=20)
    release_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    pages: int | None = Field(default=None, ge=1, le=10000)
    drm: bool = False
    prices: list[Price] = Field(default_factory=list, max_length=30)


class EditionOut(EditionIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    book_id: str
