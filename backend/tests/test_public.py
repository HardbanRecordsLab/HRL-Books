from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_public_page_lifecycle(client):
    ws, owner = make_workspace(client, "wydawnictwo", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    book = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy", "desc_short": "Krótko"}).json()["id"]
    assert client.get("/api/v1/public/w/wydawnictwo/rodzic-bez-poczucia-winy").status_code == 404  # private by default
    assert client.get("/api/v1/public/w/wydawnictwo").json()["books"] == []

    client.patch(f"{base}/books/{book}", headers=h, json={"store_links": [{"url": "https://www.amazon.pl/dp/B0TEST"}]})
    r = client.patch(f"{base}/books/{book}", headers=h, json={"public": True}).json()
    assert r["public"] is True and r["slug"] == "rodzic-bez-poczucia-winy"
    person = client.post(f"{base}/people", headers=h, json={"display_name": "Kamil Skomra", "bio_short": "Autor."}).json()["id"]
    client.put(f"{base}/books/{book}/metadata", headers=h, json={"contributors": [{"person_id": person, "role": "author"}]})
    client.post(f"{base}/assets", headers=h, data={"kind": "cover", "book_id": book}, files={"file": ("c.png", PNG, "image/png")})
    client.post(f"{base}/books/{book}/editions", headers=h, json={"format": "ebook_epub", "release_date": "2026-11-01"})

    page = client.get("/api/v1/public/w/wydawnictwo/rodzic-bez-poczucia-winy").json()
    assert page["title"] == "Rodzic bez poczucia winy" and page["authors"] == ["Kamil Skomra"]
    assert page["stores"] == [{"url": "https://www.amazon.pl/dp/B0TEST", "label": "Amazon"}]
    assert page["cover_url"].startswith("https://") and page["editions"][0]["format"] == "E-book (EPUB)"
    assert [b["slug"] for b in client.get("/api/v1/public/w/wydawnictwo").json()["books"]] == ["rodzic-bez-poczucia-winy"]

    other = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy"}).json()["id"]
    assert client.patch(f"{base}/books/{other}", headers=h, json={"public": True}).json()["slug"] == "rodzic-bez-poczucia-winy-2"
    assert client.patch(f"{base}/books/{other}", headers=h, json={"slug": "rodzic-bez-poczucia-winy"}).status_code == 409

    client.patch(f"{base}/books/{book}", headers=h, json={"public": False})
    assert client.get("/api/v1/public/w/wydawnictwo/rodzic-bez-poczucia-winy").status_code == 404
    client.delete(f"{base}/books/{other}", headers=h)
    assert client.get("/api/v1/public/w/wydawnictwo/rodzic-bez-poczucia-winy-2").status_code == 404
    third = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy"}).json()["id"]
    client.delete(f"{base}/books/{book}", headers=h)  # a deleted title no longer reserves its address
    assert client.patch(f"{base}/books/{third}", headers=h, json={"public": True}).json()["slug"] == "rodzic-bez-poczucia-winy"


def test_only_owner_publishes(client):
    ws, owner = make_workspace(client, "wydawnictwo", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    book = client.post(f"{base}/books", headers=h, json={"title": "X"}).json()["id"]
    client.post(f"{base}/invitations", headers=h, json={"email": "ed@example.com", "role": "editor"})
    ed = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.patch(f"{base}/books/{book}", headers=ed, json={"public": True}).status_code == 403
    assert client.patch(f"{base}/books/{book}", headers=ed, json={"title": "Y"}).status_code == 200
