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


class MyWorkspaceOut(WorkspaceOut):
    role: Role


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9-]{2,80}$")
    owner_email: EmailStr


class WorkspacePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
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
