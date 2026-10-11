import io
import zipfile
from xml.etree import ElementTree as ET

from tests.conftest import auth, make_workspace

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _setup(client):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    book = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy"}).json()["id"]
    return ws, h, base, book


def _chapter(client, h, base, book, title, body):
    c = f"{base}/books/{book}/chapters"
    ch = client.post(c, headers=h, json={"title": title}).json()["id"]
    client.put(f"{c}/{ch}/content", headers=h, json={"body": body})
    return ch


def test_epub_structure_accessibility_and_language_filter(client):
    ws, h, base, book = _setup(client)
    assert client.get(f"{base}/books/{book}/export/epub", headers=h).status_code == 422
    _chapter(client, h, base, book, "Wstęp", "<p>Pierwszy &amp; akapit<br>dalej</p><hr><blockquote><p>cytat</p></blockquote>")
    _chapter(client, h, base, book, "Złość", "<h2>Skąd się bierze</h2><ul><li><p>punkt</p></li></ul>")
    _chapter(client, h, base, book, "Pusty", "")
    en = _chapter(client, h, base, book, "Anger [EN]", "<p>English text</p>")
    from app.db import get_db
    from app.models import Chapter
    db = next(get_db()); db.get(Chapter, en).language = "en"; db.commit(); db.close()
    client.post(f"{base}/assets", headers=h, data={"kind": "cover", "book_id": book}, files={"file": ("okladka.png", PNG, "image/png")})

    r = client.get(f"{base}/books/{book}/export/epub", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/epub+zip"
    assert 'filename="rodzic-bez-poczucia-winy.epub"' in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    first = z.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED and z.read("mimetype") == b"application/epub+zip"
    for name in z.namelist():  # every XML document must be well-formed
        if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            ET.fromstring(z.read(name))
    opf = z.read("OEBPS/content.opf").decode()
    for needle in ("schema:accessMode", "schema:accessModeSufficient", "schema:accessibilityFeature\">structuralNavigation",
                   "schema:accessibilityHazard\">none", "schema:accessibilitySummary", "dcterms:modified",
                   'properties="cover-image"', 'properties="nav"', f"urn:uuid:{book}", "<dc:language>pl</dc:language>"):
        assert needle in opf, needle
    nav = z.read("OEBPS/nav.xhtml").decode()
    assert "Wstęp" in nav and "Złość" in nav and "Pusty" not in nav and "Anger" not in nav
    assert "<br/>" in z.read("OEBPS/chap-001.xhtml").decode()
    assert 'alt="Okładka książki: Rodzic bez poczucia winy"' in z.read("OEBPS/cover.xhtml").decode()

    r = client.get(f"{base}/books/{book}/export/epub?lang=en", headers=h)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert 'filename="rodzic-bez-poczucia-winy-en.epub"' in r.headers["content-disposition"]
    assert "Anger" in z.read("OEBPS/nav.xhtml").decode() and "[EN]" not in z.read("OEBPS/nav.xhtml").decode()


def test_epub_isbn_and_distribution_package(client):
    ws, h, base, book = _setup(client)
    client.post(f"{base}/books/{book}/editions", headers=h, json={"format": "ebook_epub", "isbn": "9788396123459"})
    pkg = zipfile.ZipFile(io.BytesIO(client.get(f"{base}/books/{book}/package/kdp", headers=h).content))
    assert "ksiazka.epub" not in pkg.namelist()  # no text yet
    _chapter(client, h, base, book, "Wstęp", "<p>Tekst</p>")
    pkg = zipfile.ZipFile(io.BytesIO(client.get(f"{base}/books/{book}/package/kdp", headers=h).content))
    epub = zipfile.ZipFile(io.BytesIO(pkg.read("ksiazka.epub")))
    assert "urn:isbn:9788396123459" in epub.read("OEBPS/content.opf").decode()
