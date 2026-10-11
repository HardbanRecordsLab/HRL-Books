from app.checks import isbn_valid
from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace


def _setup(client):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    book = client.post(f"/api/v1/workspaces/{ws}/books", headers=h, json={"title": "Rodzic bez poczucia winy",
                                                                        "desc_short": "Krótko."}).json()["id"]
    return ws, h, book


def test_isbn_checksum():
    assert isbn_valid("978-83-0000-000-7") is False
    assert isbn_valid("9780306406157") is True
    assert isbn_valid("0-306-40615-2") is True
    assert isbn_valid("") is False


def test_metadata_contributors_editions_and_completeness(client):
    ws, h, book = _setup(client)
    base = f"/api/v1/workspaces/{ws}"
    checks = client.get(f"{base}/books/{book}/checks", headers=h).json()
    assert checks["complete"] is False
    assert {m["field"] for m in checks["missing"]} >= {"desc_long", "author", "edition"}

    person = client.post(f"{base}/people", headers=h, json={"display_name": "Kamil Skomra", "bio_short": "Autor."}).json()
    r = client.put(f"{base}/books/{book}/metadata", headers=h, json={
        "desc_long": "Długi opis książki.", "keywords": ["rodzicielstwo", "poczucie winy", "emocje", " "],
        "categories": ["Poradniki / Rodzicielstwo"], "copyright_holder": "Kamil Skomra", "copyright_year": 2026,
        "contributors": [{"person_id": person["id"], "role": "author"}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["keywords"] == ["rodzicielstwo", "poczucie winy", "emocje"]
    assert r.json()["contributors"][0]["display_name"] == "Kamil Skomra"

    e = client.post(f"{base}/books/{book}/editions", headers=h, json={
        "format": "ebook_epub", "prices": [{"market": "PL", "currency": "PLN", "amount": 39.99}]})
    assert e.status_code == 201, e.text
    assert client.post(f"{base}/books/{book}/editions", headers=h,
                       json={"format": "paperback", "isbn": "1234567890123"}).status_code == 422
    checks = client.get(f"{base}/books/{book}/checks", headers=h).json()
    assert checks == {"complete": True, "missing": [], "warnings": []}


def test_identity_rule_flags_forbidden_variant(client):
    ws, h, book = _setup(client)
    base = f"/api/v1/workspaces/{ws}"
    assert client.patch(base, headers=h, json={"identity_rules": [
        {"canonical": "Kamil Skomra", "forbidden": ["Skomrakus"]}]}).status_code == 200
    client.put(f"{base}/books/{book}/metadata", headers=h, json={"desc_long": "Nowa książka od Skomrakus!"})
    warnings = client.get(f"{base}/books/{book}/checks", headers=h).json()["warnings"]
    assert any("Skomrakus" in w and "długi opis" in w for w in warnings)


def test_metadata_permissions_and_isolation(client):
    ws, h, book = _setup(client)
    base = f"/api/v1/workspaces/{ws}"
    client.post(f"{base}/invitations", headers=h, json={"email": "aut@example.com", "role": "author"})
    author = client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()
    ha = auth(author["access_token"])
    assert client.get(f"{base}/books/{book}/metadata", headers=ha).status_code == 200
    assert client.put(f"{base}/books/{book}/metadata", headers=ha, json={"desc_long": "x"}).status_code == 403
    assert client.post(f"{base}/books/{book}/editions", headers=ha, json={"format": "ebook_epub"}).status_code == 403

    ws_b, owner_b = make_workspace(client, "inne", "b@example.com")
    hb = auth(owner_b["access_token"])
    foreign = client.post(f"/api/v1/workspaces/{ws_b}/people", headers=hb, json={"display_name": "Obca Osoba"}).json()
    r = client.put(f"{base}/books/{book}/metadata", headers=h,
                   json={"contributors": [{"person_id": foreign["id"], "role": "author"}]})
    assert r.status_code == 404
    assert client.get(f"/api/v1/workspaces/{ws_b}/books/{book}/editions", headers=hb).status_code == 404
