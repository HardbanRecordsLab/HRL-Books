"""Spec 7 / 8.4 / stage-1 exit criterion: workspace A sees nothing from workspace B (404, not 403)."""
from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace


def _book(client, ws, tokens, title="Rodzic bez poczucia winy"):
    r = client.post(f"/api/v1/workspaces/{ws}/books", headers=auth(tokens["access_token"]), json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_workspace_a_cannot_see_workspace_b(client):
    ws_a, owner_a = make_workspace(client, "hrl-books", "a@example.com")
    ws_b, owner_b = make_workspace(client, "inne-wydawnictwo", "b@example.com")
    book_b = _book(client, ws_b, owner_b)
    h = auth(owner_a["access_token"])

    assert client.get(f"/api/v1/workspaces/{ws_b}", headers=h).status_code == 404
    assert client.get(f"/api/v1/workspaces/{ws_b}/books", headers=h).status_code == 404
    assert client.get(f"/api/v1/workspaces/{ws_b}/books/{book_b}", headers=h).status_code == 404
    assert client.delete(f"/api/v1/workspaces/{ws_b}/books/{book_b}", headers=h).status_code == 404
    assert client.post(f"/api/v1/workspaces/{ws_b}/invitations", headers=h,
                       json={"email": "x@example.com", "role": "author"}).status_code == 404
    # A book id from B used under A's own workspace path is also not found.
    assert client.get(f"/api/v1/workspaces/{ws_a}/books/{book_b}", headers=h).status_code == 404
    assert [w["id"] for w in client.get("/api/v1/workspaces", headers=h).json()] == [ws_a]


def test_roles_follow_permission_matrix(client):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h_owner = auth(owner["access_token"])
    for email, role in [("red@example.com", "editor"), ("aut@example.com", "author"), ("rec@example.com", "reviewer")]:
        assert client.post(f"/api/v1/workspaces/{ws}/invitations", headers=h_owner,
                           json={"email": email, "role": role}).status_code == 201
        tokens = client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()
        h = auth(tokens["access_token"])
        can_create = client.post(f"/api/v1/workspaces/{ws}/books", headers=h, json={"title": "T"}).status_code
        assert can_create == (201 if role == "author" else 403), role
        assert client.get(f"/api/v1/workspaces/{ws}/books", headers=h).status_code == 200
        assert client.post(f"/api/v1/workspaces/{ws}/invitations", headers=h,
                           json={"email": "z@example.com", "role": "author"}).status_code == 403
        assert client.patch(f"/api/v1/workspaces/{ws}", headers=h, json={"ai_enabled": True}).status_code == 403


def test_ai_is_off_by_default_and_owner_can_enable(client):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    assert client.get(f"/api/v1/workspaces/{ws}", headers=h).json()["ai_enabled"] is False
    assert client.patch(f"/api/v1/workspaces/{ws}", headers=h, json={"ai_enabled": True}).json()["ai_enabled"] is True


def test_soft_delete_hides_book(client):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    book = _book(client, ws, owner)
    assert client.delete(f"/api/v1/workspaces/{ws}/books/{book}", headers=h).status_code == 204
    assert client.get(f"/api/v1/workspaces/{ws}/books/{book}", headers=h).status_code == 404
    assert client.get(f"/api/v1/workspaces/{ws}/books", headers=h).json() == []
