import io
import json
import zipfile

from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace


def _setup(client):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    book = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy", "desc_short": "Krótko."}).json()["id"]
    return ws, h, base, book


def test_board_shows_imported_store_links_as_published(client):
    ws, h, base, _ = _setup(client)
    client.post(f"{base}/books/import", headers=h, json={"books": [
        {"title": "Cyfrowy Zen", "store_links": [{"url": "https://www.amazon.pl/dp/B0TEST"}, {"url": "https://www.empik.com/x"}]}]})
    board = client.get(f"{base}/distribution", headers=h).json()
    zen = next(r for r in board["rows"] if r["title"] == "Cyfrowy Zen")
    assert zen["cells"]["kdp"]["status"] == "published"
    assert zen["cells"]["virtualo"]["status"] == "published"
    assert zen["cells"]["kobo"]["status"] == "not_ready"
    assert [c["key"] for c in board["channels"]] == ["kdp", "google_play", "kobo", "d2d", "virtualo"]


def test_listing_status_flow_and_checklist(client):
    ws, h, base, book = _setup(client)
    r = client.put(f"{base}/books/{book}/listings/kdp", headers=h, json={"status": "sent", "checklist": [0, 1, 2]})
    assert r.status_code == 200 and r.json()["sent_at"] is not None and r.json()["checklist"] == [0, 1, 2]
    r = client.put(f"{base}/books/{book}/listings/kdp", headers=h, json={"status": "published", "url": "https://www.amazon.pl/dp/X"})
    assert r.json()["published_at"] is not None
    assert client.put(f"{base}/books/{book}/listings/kdp", headers=h, json={"status": "bogus"}).status_code == 422
    assert client.put(f"{base}/books/{book}/listings/nope", headers=h, json={"status": "sent"}).status_code == 404
    listings = client.get(f"{base}/books/{book}/listings", headers=h).json()
    kdp = next(x for x in listings if x["channel"] == "kdp")
    assert kdp["status"] == "published" and kdp["profile"]["name"] == "Amazon KDP"
    assert any("brak wydania" in i for i in kdp["issues"])


def test_kdp_keyword_limit_reported(client):
    ws, h, base, book = _setup(client)
    client.put(f"{base}/books/{book}/metadata", headers=h, json={"keywords": [f"k{i}" for i in range(9)]})
    kdp = next(x for x in client.get(f"{base}/books/{book}/listings", headers=h).json() if x["channel"] == "kdp")
    assert any("maksymalnie 7 słów kluczowych" in i for i in kdp["issues"])


def test_package_zip_contents(client):
    ws, h, base, book = _setup(client)
    client.put(f"{base}/books/{book}/metadata", headers=h, json={"keywords": [f"k{i}" for i in range(9)], "desc_long": "Opis."})
    client.post(f"{base}/books/{book}/editions", headers=h, json={"format": "ebook_epub", "prices": [{"market": "PL", "currency": "PLN", "amount": 39.99}]})
    r = client.get(f"{base}/books/{book}/package/kdp", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(z.namelist()) == {"metadane.json", "metadane.csv", "opis.txt", "INSTRUKCJA.txt"}
    meta = json.loads(z.read("metadane.json"))
    assert len(meta["keywords"]) == 7 and meta["editions"][0]["prices"][0]["amount"] == 39.99
    assert "kdp.amazon.com" in z.read("INSTRUKCJA.txt").decode()


def test_distribution_permissions_and_isolation(client):
    ws, h, base, book = _setup(client)
    client.post(f"{base}/invitations", headers=h, json={"email": "aut@example.com", "role": "author"})
    author = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.get(f"{base}/distribution", headers=author).status_code == 200
    assert client.put(f"{base}/books/{book}/listings/kdp", headers=author, json={"status": "sent"}).status_code == 403
    assert client.get(f"{base}/books/{book}/package/kdp", headers=author).status_code == 403
    client.post(f"{base}/invitations", headers=h, json={"email": "rec@example.com", "role": "reviewer"})
    reviewer = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.get(f"{base}/distribution", headers=reviewer).status_code == 403
    ws_b, owner_b = make_workspace(client, "inne", "b@example.com")
    hb = auth(owner_b["access_token"])
    assert client.put(f"/api/v1/workspaces/{ws_b}/books/{book}/listings/kdp", headers=hb, json={"status": "sent"}).status_code == 404
    assert client.get(f"/api/v1/workspaces/{ws_b}/books/{book}/package/kdp", headers=hb).status_code == 404
