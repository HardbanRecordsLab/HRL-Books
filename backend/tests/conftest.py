import os
import re

os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "sqlite:///./test.db"))
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789-0123456789-abcdef")
os.environ.pop("SMTP_HOST", None)
import tempfile  # noqa: E402
os.environ.setdefault("FILES_DIR", tempfile.mkdtemp(prefix="hrlb-files-"))
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import mailer  # noqa: E402
from app.db import Base, get_db, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

ADMIN_EMAIL = "admin@hardbanrecordslab.online"
PASSWORD = "Bardzo-Dlugie-Haslo-1"


@pytest.fixture(autouse=True)
def fresh_db():
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    mailer.SENT.clear()
    db = next(get_db())
    db.add(User(email=ADMIN_EMAIL, password_hash=hash_password(PASSWORD), is_platform_admin=True, email_verified=True))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(client, email=ADMIN_EMAIL, password=PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def last_invite_token() -> str:
    body = mailer.SENT[-1].get_content()
    return re.search(r"token=([\w-]+)", body).group(1)


def make_workspace(client, slug: str, owner_email: str) -> tuple[str, dict]:
    """Admin creates a workspace, the owner registers from the e-mailed invitation. Returns (ws_id, owner tokens)."""
    admin = login(client)
    r = client.post("/api/v1/admin/workspaces", headers=auth(admin["access_token"]),
                    json={"name": slug.title(), "slug": slug, "owner_email": owner_email})
    assert r.status_code == 201, r.text
    ws_id = r.json()["id"]
    r = client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD})
    assert r.status_code == 200, r.text
    return ws_id, r.json()
