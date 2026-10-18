import io
import zipfile

from app.isbn import hyphenate_pl, parse_isbn_list, to_isbn13
from tests.conftest import auth, make_workspace

def _fix(n12: str) -> str:
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(n12))
    return n12 + str((10 - total % 10) % 10)


# valid ISBN-13s with the Polish prefix, built with the check-digit rule
POOL = [_fix("978837541" + f"{i:03d}") for i in range(100, 106)]


def _setup(client):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    book = client.post(f"{base}/books", headers=h, json={"title": "Cyfrowy Zen", "desc_short": "Krótko."}).json()["id"]
    return ws, h, base, book


def test_isbn_parsing_accepts_pasted_lists_and_rejects_bad_checksums():
    ok, bad = parse_isbn_list(f"{POOL[0]}\n{hyphenate_pl(POOL[1])}, ISBN {POOL[2]}\n9788375411230\nzupełnie nie numer")
    assert ok == POOL[:3]
    assert len(bad) == 2
    assert to_isbn13("0306406152") == "9780306406157"          # ISBN-10 -> ISBN-13
    assert hyphenate_pl(POOL[0]) == f"{POOL[0][:3]}-83-{POOL[0][5:-1]}-{POOL[0][-1]}"
    assert hyphenate_pl("9780306406157") == "9780306406157"        # non-Polish prefixes are not guessed


def test_import_pool_dedupes_and_counts(client):
    ws, h, base, _ = _setup(client)
    r = client.post(f"{base}/isbn-pool/import", headers=h, json={"text": "\n".join(POOL[:4]) + f"\n{POOL[0]}\n1234567890123"}).json()
    assert r["added"] == 4 and r["rejected"] and r["free"] == 4
    again = client.post(f"{base}/isbn-pool/import", headers=h, json={"text": POOL[0]}).json()
    assert again["added"] == 0 and again["duplicates"] == 1


def test_assign_gives_one_number_per_format_and_never_reuses(client):
    ws, h, base, book = _setup(client)
    client.post(f"{base}/isbn-pool/import", headers=h, json={"text": "\n".join(POOL)})
    client.post(f"{base}/books/{book}/editions", headers=h, json={"format": "ebook_epub"})
    client.post(f"{base}/books/{book}/editions", headers=h, json={"format": "paperback"})
    r = client.post(f"{base}/books/{book}/isbn/assign", headers=h).json()
    assert len(r["assigned"]) == 2 and r["free"] == len(POOL) - 2
    isbns = [a["isbn"].replace("-", "") for a in r["assigned"]]
    assert len(set(isbns)) == 2
    # a second call has nothing left to do
    assert client.post(f"{base}/books/{book}/isbn/assign", headers=h).json()["assigned"] == []
    editions = client.get(f"{base}/books/{book}/editions", headers=h).json()
    assert all(e["isbn"] for e in editions)
    # release returns the number to the pool and clears the edition
    client.delete(f"{base}/isbn-pool/{isbns[0]}", headers=h)
    pool = client.get(f"{base}/isbn-pool", headers=h).json()
    assert pool["free"] == len(POOL) - 1
    assert any(not e["isbn"] for e in client.get(f"{base}/books/{book}/editions", headers=h).json())


def test_pool_empty_is_reported_not_crashed(client):
    ws, h, base, book = _setup(client)
    client.post(f"{base}/books/{book}/editions", headers=h, json={"format": "paperback"})
    r = client.post(f"{base}/books/{book}/isbn/assign", headers=h).json()
    assert r["assigned"] == [] and r["pool_empty_for"] == ["paperback"]


def test_readiness_lists_gaps_and_prepare_marks_ready_only_when_complete(client):
    ws, h, base, book = _setup(client)
    ov = client.get(f"{base}/publishing", headers=h).json()
    row = next(r for r in ov["rows"] if r["book_id"] == book)
    assert "brak okładki" in row["gaps"]
    done = client.post(f"{base}/publishing/prepare", headers=h).json()
    assert done["marked_ready"] == 0 and done["blocked"]          # nothing is complete: nothing is marked


def test_kdp_select_blocks_other_ebook_stores_until_unset(client):
    ws, h, base, book = _setup(client)
    client.post(f"{base}/books/{book}/editions", headers=h, json={"format": "ebook_epub"})
    client.patch(f"{base}/books/{book}", headers=h, json={"kdp_select": True})
    listings = client.get(f"{base}/books/{book}/listings", headers=h).json()
    play = next(x for x in listings if x["channel"] == "google_play")
    assert any("KDP Select" in i for i in play["issues"])
    kdp = next(x for x in listings if x["channel"] == "kdp")
    assert not any("KDP Select" in i for i in kdp["issues"])
    client.patch(f"{base}/books/{book}", headers=h, json={"kdp_select": False})
    play = next(x for x in client.get(f"{base}/books/{book}/listings", headers=h).json() if x["channel"] == "google_play")
    assert not any("KDP Select" in i for i in play["issues"])


def test_bulk_package_contains_one_folder_per_title_and_store_with_cover(client):
    ws, h, base, book = _setup(client)
    client.post(f"{base}/books/{book}/editions", headers=h, json={"format": "ebook_epub"})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    up = client.post(f"{base}/assets", headers=h, data={"kind": "cover", "book_id": book}, files={"file": ("c.png", png, "image/png")})
    assert up.status_code == 201
    z = client.get(f"{base}/publishing/package", headers=h)
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert any(n.startswith("Cyfrowy Zen/kdp/") and n.endswith("metadane.json") for n in names)
    assert "Cyfrowy Zen/kdp/okladka.png" in names
    assert any(n.startswith("Cyfrowy Zen/kobo/") for n in names)
    only = client.get(f"{base}/publishing/package?channel=kobo", headers=h)
    assert all("/kobo/" in n for n in zipfile.ZipFile(io.BytesIO(only.content)).namelist())


def test_verify_marks_sent_listing_published_when_store_page_is_live(client, monkeypatch):
    from app.routers import publishing
    ws, h, base, book = _setup(client)
    client.put(f"{base}/books/{book}/listings/kdp", headers=h, json={"status": "sent", "url": "https://www.amazon.com/dp/B0TEST"})
    client.put(f"{base}/books/{book}/listings/kobo", headers=h, json={"status": "sent", "url": "https://www.kobo.com/x"})
    monkeypatch.setattr(publishing, "_fetch_ok", lambda url: "amazon" in url)
    r = client.post(f"{base}/publishing/verify", headers=h).json()
    assert r["checked"] == 2 and r["published"] == 1
    status = {x["channel"]: x["status"] for x in client.get(f"{base}/books/{book}/listings", headers=h).json()}
    assert status["kdp"] == "published" and status["kobo"] == "sent"
