import json

import pytest

from app import ai
from app.ai import chunks, html_blocks
from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace

CALLS: list[dict] = []


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    CALLS.clear()

    def complete(system, user, max_tokens=4000, temperature=0.3):
        CALLS.append({"system": system, "user": user})
        if "korektorem" in system:
            return json.dumps({"suggestions": [
                {"original": "Ala ma kota ktory", "suggestion": "Ala ma kota, który", "reason": "przecinek i ogonek"},
                {"original": "zdanie którego nie ma", "suggestion": "x", "reason": "zmyślone"},
            ]}), "test/model", 100, 20
        if "tłumaczem" in system:
            return user.replace("Ala ma kota", "Alice has a cat").replace("Rozdział", "Chapter"), "test/model", 50, 50
        return "## Pierwsze wrażenie\nDobre.", "test/model", 10, 10

    monkeypatch.setattr(ai, "complete", complete)
    monkeypatch.setattr(ai, "configured", lambda: True)


def _setup(client, enable=True):
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    if enable:
        client.patch(base, headers=h, json={"ai_enabled": True})
    book = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy"}).json()["id"]
    c = f"{base}/books/{book}/chapters"
    ch = client.post(c, headers=h, json={"title": "Rozdział 1"}).json()["id"]
    client.put(f"{c}/{ch}/content", headers=h, json={"body": "<p>Ala ma kota ktory mruczy.</p><ul><li><p>punkt</p></li></ul>"})
    return ws, h, base, book, ch


def test_blocks_keep_lists_whole_and_chunk():
    body = "<p>a</p><ul><li><p>x</p></li><li><p>y</p></li></ul><hr><h2>t</h2>"
    assert html_blocks(body) == ["<p>a</p>", "<ul><li><p>x</p></li><li><p>y</p></li></ul>", "<hr>", "<h2>t</h2>"]
    assert chunks("<p>aaaa</p><p>bbbb</p><p>cccc</p>", size=22) == ["<p>aaaa</p><p>bbbb</p>", "<p>cccc</p>"]


def test_ai_disabled_by_default(client):
    ws, h, base, book, ch = _setup(client, enable=False)
    r = client.post(f"{base}/books/{book}/ai/proofread", headers=h, json={"chapter_id": ch})
    assert r.status_code == 403 and "wyłączony" in r.json()["detail"]
    assert CALLS == []


def test_proofread_suggestions_then_apply_creates_ai_version(client):
    ws, h, base, book, ch = _setup(client)
    a = f"{base}/books/{book}/ai"
    job = client.post(f"{a}/proofread", headers=h, json={"chapter_id": ch}).json()
    job = client.get(f"{a}/jobs/{job['id']}", headers=h).json()
    assert job["status"] == "done" and job["tokens_in"] == 100
    assert [s["original"] for s in job["result"]["suggestions"]] == ["Ala ma kota ktory"]  # invented fragment dropped
    r = client.post(f"{a}/jobs/{job['id']}/apply", headers=h, json={"accept": [0]}).json()
    assert r == {"applied": 1, "skipped": 0}
    c = client.get(f"{base}/books/{book}/chapters/{ch}", headers=h).json()
    assert c["body"].startswith("<p>Ala ma kota, który mruczy.</p>")
    vs = client.get(f"{base}/books/{book}/chapters/{ch}/versions", headers=h).json()
    assert vs[0]["origin"] == "ai" and len(vs) == 3
    assert client.post(f"{a}/jobs/{job['id']}/apply", headers=h, json={"accept": [0]}).status_code == 409


def test_translate_creates_new_chapter_never_overwrites(client):
    ws, h, base, book, ch = _setup(client)
    job = client.post(f"{base}/books/{book}/ai/translate", headers=h, json={"chapter_id": ch, "target": "en"}).json()
    job = client.get(f"{base}/books/{book}/ai/jobs/{job['id']}", headers=h).json()
    assert job["status"] == "done"
    titles = [c["title"] for c in client.get(f"{base}/books/{book}/chapters", headers=h).json()["chapters"]]
    assert titles == ["Rozdział 1", "Chapter 1 [EN]"]
    new = client.get(f"{base}/books/{book}/chapters/{job['result']['new_chapter_id']}", headers=h).json()
    assert "Alice has a cat" in new["body"] and "<ul><li><p>punkt</p></li></ul>" in new["body"]
    orig = client.get(f"{base}/books/{book}/chapters/{ch}", headers=h).json()
    assert "Ala ma kota" in orig["body"]
    assert client.get(f"{base}/books/{book}/metadata", headers=h).json()["ai_disclosure"]["translation"] is True


def test_beta_read_marketing_limit_and_log(client):
    ws, h, base, book, ch = _setup(client)
    a = f"{base}/books/{book}/ai"
    client.post(f"{a}/beta-read", headers=h, json={})
    client.post(f"{a}/marketing", headers=h, json={"kind": "blurb", "lang": "pl"})
    st = client.get(a, headers=h).json()
    assert st["used_today"] == 2 and [j["kind"] for j in st["jobs"]] == ["marketing", "beta_read"]
    assert st["jobs"][1]["result"]["report"].startswith("## Pierwsze")
    assert "Rodzic bez poczucia winy" in CALLS[-1]["user"] and "Ala ma kota" in CALLS[-1]["user"]
    from app.db import get_db
    from app.models import Workspace
    db = next(get_db())
    w = db.get(Workspace, ws)
    w.limits = {**w.limits, "ai_jobs_per_day": 2}
    db.commit()
    db.close()
    assert client.post(f"{a}/marketing", headers=h, json={"kind": "social"}).status_code == 429


def test_ai_permissions_and_isolation(client):
    ws, h, base, book, ch = _setup(client)
    client.post(f"{base}/invitations", headers=h, json={"email": "rec@example.com", "role": "reviewer"})
    rev = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.post(f"{base}/books/{book}/ai/proofread", headers=rev, json={"chapter_id": ch}).status_code == 403
    ws_b, owner_b = make_workspace(client, "inne", "b@example.com")
    hb = auth(owner_b["access_token"])
    client.patch(f"/api/v1/workspaces/{ws_b}", headers=hb, json={"ai_enabled": True})
    assert client.post(f"/api/v1/workspaces/{ws_b}/books/{book}/ai/proofread", headers=hb, json={"chapter_id": ch}).status_code == 404
