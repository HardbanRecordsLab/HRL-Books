import io
import zipfile

from app.text import docx_to_chapters, sanitize_html, text_to_chapters
from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace


def _setup(client):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    book = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy"}).json()["id"]
    return ws, h, base, book


def _docx(paragraphs: list[tuple[str, str]]) -> bytes:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>' if style else
        f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{text}</w:t></w:r></w:p>'
        for style, text in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {ns}><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def test_sanitizer_strips_scripts_and_bad_links():
    dirty = '<p onclick="x()">Hi<script>alert(1)</script> <a href="javascript:evil()">x</a> <a href="https://ok.pl">ok</a></p><img src=x onerror=y>'
    clean = sanitize_html(dirty)
    assert "script" not in clean and "onclick" not in clean and "javascript" not in clean and "<img" not in clean
    assert '<a href="https://ok.pl" rel="noopener noreferrer">ok</a>' in clean


def test_docx_and_text_split():
    parts = docx_to_chapters(_docx([("Heading1", "Rozdział 1"), ("", "Akapit pierwszy"), ("Heading1", "Rozdział 2"), ("", "Drugi")]))
    assert [t for t, _ in parts] == ["Rozdział 1", "Rozdział 2"]
    assert parts[0][1] == "<p><strong>Akapit pierwszy</strong></p>"
    parts = text_to_chapters("Wstęp tekstu\n\n# Jeden\nAla ma\nkota\n\n## Sekcja\nDalej\n# Dwa\nKoniec")
    assert [t for t, _ in parts] == ["Wstęp", "Jeden", "Dwa"]
    assert "<p>Ala ma kota</p><h2>Sekcja</h2>" in parts[1][1]


def test_research_sources_notes_search_and_quote_rule(client):
    ws, h, base, book = _setup(client)
    r = f"{base}/books/{book}/research"
    src = client.post(f"{r}/sources", headers=h, json={"title": "Raport o rodzicielstwie", "url": "https://example.org/r"}).json()
    assert client.post(f"{r}/notes", headers=h, json={"body": "Cytat bez źródła", "is_quote": True}).status_code == 422
    assert client.post(f"{r}/notes", headers=h, json={"body": "„Dzieci potrzebują…”", "is_quote": True,
                                                       "source_id": src["id"], "page_ref": "s. 12", "tags": ["wina", " "]}).status_code == 201
    client.post(f"{r}/notes", headers=h, json={"body": "Pomysł na rozdział o złości"})
    found = client.get(f"{r}?q=złości", headers=h).json()
    assert [n["body"] for n in found["notes"]] == ["Pomysł na rozdział o złości"] and found["sources"] == []
    assert client.get(f"{r}?q=rodzicielstwie", headers=h).json()["sources"][0]["id"] == src["id"]


def test_research_gate_soft_and_hard(client):
    ws, h, base, book = _setup(client)
    url = f"{base}/books/{book}"
    assert client.patch(url, headers=h, json={"status": "writing"}).status_code == 409
    r = client.patch(url, headers=h, json={"status": "writing", "gate_override_reason": "Mam materiał z poprzedniej książki"})
    assert r.status_code == 200 and r.json()["status"] == "writing"
    book2 = client.post(f"{base}/books", headers=h, json={"title": "Druga"}).json()["id"]
    client.patch(base, headers=h, json={"research_gate_mode": "hard"})
    assert client.patch(f"{base}/books/{book2}", headers=h, json={"status": "writing", "gate_override_reason": "x"}).status_code == 409
    assert client.post(f"{base}/books/{book2}/research/gate", headers=h, json={"note": "Wszystko zebrane"}).json()["closed"] is True
    assert client.patch(f"{base}/books/{book2}", headers=h, json={"status": "writing"}).status_code == 200


def test_chapters_versions_restore_and_import(client):
    ws, h, base, book = _setup(client)
    c = f"{base}/books/{book}/chapters"
    ch = client.post(c, headers=h, json={"title": "Wstęp"}).json()
    client.put(f"{c}/{ch['id']}/content", headers=h, json={"body": "<p>Pierwsza wersja tekstu</p>"})
    saved = client.put(f"{c}/{ch['id']}/content", headers=h, json={"body": "<p>Druga wersja, dłuższa niż pierwsza</p><script>x</script>"}).json()
    assert "script" not in saved["body"] and saved["words"] == 5
    client.put(f"{c}/{ch['id']}/content", headers=h, json={"body": saved["body"]})  # unchanged -> no new version
    vs = client.get(f"{c}/{ch['id']}/versions", headers=h).json()
    assert len(vs) == 3 and vs[1]["body"] == "<p>Pierwsza wersja tekstu</p>"
    restored = client.post(f"{c}/{ch['id']}/versions/{vs[1]['id']}/restore", headers=h).json()
    assert restored["body"] == "<p>Pierwsza wersja tekstu</p>"
    r = client.post(f"{base}/books/{book}/manuscript/import", headers=h,
                    files={"file": ("ksiazka.docx", _docx([("Heading1", "Rozdział A"), ("", "Tekst A"), ("Heading1", "Rozdział B"), ("", "Tekst B")]),
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.json() == {"chapters": 2}
    listing = client.get(c, headers=h).json()
    assert [x["title"] for x in listing["chapters"]] == ["Wstęp", "Rozdział A", "Rozdział B"] and listing["words"] > 0
    ids = [x["id"] for x in listing["chapters"]][::-1]
    client.put(f"{c}/order", headers=h, json={"chapter_ids": ids})
    assert [x["title"] for x in client.get(c, headers=h).json()["chapters"]] == ["Rozdział B", "Rozdział A", "Wstęp"]


def test_manuscript_and_research_permissions(client):
    ws, h, base, book = _setup(client)
    client.post(f"{base}/invitations", headers=h, json={"email": "rec@example.com", "role": "reviewer"})
    rev = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.get(f"{base}/books/{book}/research", headers=rev).status_code == 403
    assert client.post(f"{base}/books/{book}/chapters", headers=rev, json={"title": "x"}).status_code == 403
    client.post(f"{base}/invitations", headers=h, json={"email": "red@example.com", "role": "editor"})
    ed = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.get(f"{base}/books/{book}/research", headers=ed).status_code == 200
    assert client.post(f"{base}/books/{book}/research/notes", headers=ed, json={"body": "x"}).status_code == 403
    assert client.post(f"{base}/books/{book}/chapters", headers=ed, json={"title": "Od redaktora"}).status_code == 201
    ws_b, owner_b = make_workspace(client, "inne", "b@example.com")
    hb = auth(owner_b["access_token"])
    assert client.get(f"/api/v1/workspaces/{ws_b}/books/{book}/chapters", headers=hb).status_code == 404
    assert client.get(f"/api/v1/workspaces/{ws_b}/books/{book}/research", headers=hb).status_code == 404
