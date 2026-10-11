from tests.conftest import ADMIN_EMAIL, PASSWORD, auth, last_invite_token, login, make_workspace


def test_health(client):
    assert client.get("/api/v1/health").json() == {"status": "ok", "database": "ok"}


def test_public_registration_is_closed(client):
    assert client.get("/api/v1/auth/registration").json() == {"public_registration": False}


def test_register_requires_valid_invitation(client):
    r = client.post("/api/v1/auth/register", json={"token": "made-up", "password": PASSWORD})
    assert r.status_code == 400


def test_invitation_is_single_use(client):
    make_workspace(client, "hrl-books", "kamil@example.com")
    token = last_invite_token()
    r = client.post("/api/v1/auth/register", json={"token": token, "password": PASSWORD})
    assert r.status_code == 400


def test_short_password_rejected(client):
    admin = login(client)
    client.post("/api/v1/admin/workspaces", headers=auth(admin["access_token"]),
                json={"name": "Wydawnictwo X", "slug": "xx", "owner_email": "o@example.com"})
    r = client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": "short"})
    assert r.status_code == 422


def test_login_wrong_password_and_lockout(client):
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    assert r.status_code == 429


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    tokens = login(client)
    assert client.get("/api/v1/auth/me", headers=auth(tokens["access_token"])).json()["email"] == ADMIN_EMAIL


def test_refresh_rotation_and_reuse_revokes_family(client):
    tokens = login(client)
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]
    # Replaying the already-rotated token is treated as theft: the whole family dies.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


def test_logout_revokes_refresh(client):
    tokens = login(client)
    r = client.post("/api/v1/auth/logout", headers=auth(tokens["access_token"]), json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_admin_endpoints_need_platform_admin(client):
    _, owner = make_workspace(client, "hrl-books", "kamil@example.com")
    assert client.get("/api/v1/admin/workspaces", headers=auth(owner["access_token"])).status_code == 403
