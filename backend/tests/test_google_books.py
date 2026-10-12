import pytest

from app import google_books as gb
from app.integrations import IntegrationError
from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200

VOLUME = {
    "id": "AbC123xyz",
    "volumeInfo": {
        "title": "Rodzic bez poczucia winy", "subtitle": "Poradnik dla zmęczonych", "authors": ["Kamil Skomra"],
        "publisher": "HardbanRecords Lab", "publishedDate": "2025-03-14",
        "description": "<p>Książka o <b>złości</b> i winie.</p><p>Drugi akapit.</p>",
        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9788396123459"}],
        "pageCount": 212, "categories": ["Family & Relationships / Parenting"], "language": "pl",
        "imageLinks": {"thumbnail": "http://books.google.com/books/content?id=AbC123xyz&printsec=frontcover&img=1&zoom=1&edge=curl"},
        "infoLink": "https://books.google.com/books?id=AbC123xyz",
    },
    "saleInfo": {"saleability": "FOR_SALE", "isEbook": True, "buyLink": "https://play.google.com/store/books/details?id=AbC123xyz",
                 "listPrice": {"amount": 39.99, "currencyCode": "PLN"}},
}
CALLS = []


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    CALLS.clear()

    def get(path, params):
        CALLS.append((path, params))
        if path == "/volumes":
            return {"items": [VOLUME]}
        if path == "/volumes/AbC123xyz":
            return VOLUME
        raise IntegrationError("Nie znaleziono w Google Books")

    monkeypatch.setattr(gb, "_get", get)
    monkeypatch.setattr(gb, "fetch_cover", lambda url: (JPEG, "image/jpeg") if url.startswith("https://books.google.com") else None)


def _setup(client):
    ws, owner = make_workspace(client, "wydawnictwo", "owner@example.com")
    return ws, auth(owner["access_token"]), f"/api/v1/workspaces/{ws}"


def test_normalize_and_isbn_query():
    v = gb.normalize(VOLUME)
    assert v["release_date"] == "2025-03-14" and v["year"] == 2025 and v["isbn13"] == "9788396123459"
    assert v["description"].startswith("Książka o złości i winie.") and "<" not in v["description"]
    assert v["cover_url"].startswith("https://books.google.com") and "zoom=0" in v["cover_url"] and "edge=curl" not in v["cover_url"]
    assert gb._date("2024") == ("", 2024)
    gb.search("978-83-961234-5-9")
    assert CALLS[-1][1]["q"] == "isbn:9788396123459"


def test_search_import_and_dedupe(client):
    ws, h, base = _setup(client)
    r = client.get(f"{base}/google-books/search?q=Skomra", headers=h).json()["results"]
    assert r[0]["title"] == "Rodzic bez poczucia winy" and r[0]["exists"] is False

    out = client.post(f"{base}/google-books/import", headers=h, json={"volume_ids": ["AbC123xyz"]}).json()
    assert len(out["imported"]) == 1 and out["skipped"] == []
    book_id = out["imported"][0]["id"]
    meta = client.get(f"{base}/books/{book_id}/metadata", headers=h).json()
    assert meta["categories"] == ["Family & Relationships / Parenting"] and meta["desc_long"].startswith("Książka o złości")
    assert [c["display_name"] for c in meta["contributors"]] == ["Kamil Skomra"]
    book = client.get(f"{base}/books/{book_id}", headers=h).json()
    assert book["status"] == "published" and book["subtitle"] == "Poradnik dla zmęczonych"
    assert book["store_links"][0]["url"].startswith("https://play.google.com")
    eds = client.get(f"{base}/books/{book_id}/editions", headers=h).json()
    assert eds[0]["format"] == "ebook_epub" and eds[0]["isbn"] == "9788396123459" and eds[0]["pages"] == 212
    assets = client.get(f"{base}/assets?book_id={book_id}", headers=h).json()
    assert [a["kind"] for a in assets] == ["cover"]

    again = client.post(f"{base}/google-books/import", headers=h, json={"volume_ids": ["AbC123xyz", "missing99"]}).json()
    assert again["imported"] == [] and len(again["skipped"]) == 2
    assert client.get(f"{base}/google-books/search?q=Skomra", headers=h).json()["results"][0]["exists"] is True


def test_fill_only_empty_fields(client):
    ws, h, base = _setup(client)
    book = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy", "desc_short": "Mój własny opis"}).json()["id"]
    out = client.post(f"{base}/books/{book}/google-books/fill", headers=h, json={"volume_id": "AbC123xyz"}).json()
    assert "desc_short" not in out["filled"] and {"subtitle", "desc_long", "authors", "edition", "cover"} <= set(out["filled"])
    assert client.get(f"{base}/books/{book}", headers=h).json()["desc_short"] == "Mój własny opis"
    second = client.post(f"{base}/books/{book}/google-books/fill", headers=h, json={"volume_id": "AbC123xyz"}).json()
    assert second["filled"] == []


def test_no_key_is_a_clear_503_and_permissions(client, monkeypatch):
    ws, h, base = _setup(client)
    monkeypatch.setattr(gb, "_get", lambda p, q: (_ for _ in ()).throw(IntegrationError("Brak klucza Google Books API (GOOGLE_BOOKS_API_KEY)")))
    r = client.get(f"{base}/google-books/search?q=abc", headers=h)
    assert r.status_code == 503 and "klucza" in r.json()["detail"]
    client.post(f"{base}/invitations", headers=h, json={"email": "rev@example.com", "role": "reviewer"})
    rev = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.get(f"{base}/google-books/search?q=abc", headers=rev).status_code == 403
