"""AI assistant (module AI): proofreading suggestions, translation into a new chapter, beta-read report, marketing drafts.

Rules: opt-in per workspace (ai_enabled), daily job limit, every job logged, results are suggestions —
text changes land only as a new version (origin="ai") after the user accepts them.
Jobs run in the background; the UI polls GET /jobs/{id}.
"""
import html
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ai
from app.audit import audit
from app.db import get_db
from app.deps import require
from app.models import AIJob, Book, Chapter, Membership, Workspace, utcnow
from app.routers.manuscript import _book, _chapter, add_version, latest
from app.text import html_to_text, sanitize_html

router = APIRouter(prefix="/api/v1/workspaces/{ws}/books/{book_id}/ai", tags=["ai"])
KIND_PL = {"proofread": "Korekta", "translate": "Tłumaczenie", "beta_read": "Beta-czytanie", "marketing": "Marketing"}
STALE = timedelta(minutes=20)


class ChapterJobIn(BaseModel):
    chapter_id: str


class TranslateIn(BaseModel):
    chapter_id: str
    target: str = Field(pattern="^(pl|en)$")


class BetaIn(BaseModel):
    chapter_id: str | None = None


class MarketingIn(BaseModel):
    kind: str = Field(pattern="^(blurb|social|newsletter|keywords)$")
    lang: str = Field(default="pl", pattern="^(pl|en)$")


class ApplyIn(BaseModel):
    accept: list[int] = Field(max_length=1000)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def job_out(j: AIJob) -> dict:
    status = j.status
    if status in ("queued", "running") and utcnow() - _aware(j.created_at) > STALE:
        status = "failed"
    return {"id": j.id, "kind": j.kind, "kind_label": KIND_PL.get(j.kind, j.kind), "chapter_id": j.chapter_id,
            "params": j.params, "status": status, "result": j.result, "error": j.error or ("Przekroczono czas" if status != j.status else ""),
            "model": j.model, "tokens_in": j.tokens_in, "tokens_out": j.tokens_out, "created_at": j.created_at,
            "finished_at": j.finished_at}


def _used_today(db: Session, ws_id: str) -> int:
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count(AIJob.id)).where(AIJob.workspace_id == ws_id, AIJob.created_at >= midnight)) or 0


def _new_job(db: Session, m: Membership, book: Book, kind: str, chapter_id: str | None, params: dict) -> AIJob:
    w = db.get(Workspace, m.workspace_id)
    if not w.ai_enabled:
        raise HTTPException(403, "Asystent AI jest wyłączony — właściciel może go włączyć w Ustawieniach.")
    if not ai.configured():
        raise HTTPException(503, "AI nie jest skonfigurowane na serwerze")
    limit = int((w.limits or {}).get("ai_jobs_per_day", 50))
    if _used_today(db, w.id) >= limit:
        raise HTTPException(429, f"Wykorzystano dzienny limit zadań AI ({limit}). Spróbuj jutro.")
    j = AIJob(workspace_id=w.id, book_id=book.id, chapter_id=chapter_id, kind=kind, params=params, created_by=m.user_id)
    db.add(j)
    audit(db, f"ai.{kind}", m.user_id, w.id, target=book.id)
    db.commit()
    return j


@router.get("")
def status(book_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    w = db.get(Workspace, m.workspace_id)
    jobs = db.scalars(select(AIJob).where(AIJob.book_id == book.id).order_by(AIJob.created_at.desc()).limit(30))
    return {"enabled": w.ai_enabled, "configured": ai.configured(), "used_today": _used_today(db, w.id),
            "limit": int((w.limits or {}).get("ai_jobs_per_day", 50)), "jobs": [job_out(j) for j in jobs]}


@router.get("/jobs/{job_id}")
def get_job(book_id: str, job_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    j = db.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.book_id == book_id, AIJob.workspace_id == m.workspace_id))
    if j is None:
        raise HTTPException(404, "Nie znaleziono")
    return job_out(j)


@router.post("/proofread", status_code=202)
def proofread(book_id: str, body: ChapterJobIn, bg: BackgroundTasks, m: Membership = Depends(require("use_ai")),
              db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    ch = _chapter(db, m.workspace_id, book.id, body.chapter_id)
    j = _new_job(db, m, book, "proofread", ch.id, {"chapter_title": ch.title})
    bg.add_task(run_job, j.id)
    return job_out(j)


@router.post("/translate", status_code=202)
def translate(book_id: str, body: TranslateIn, bg: BackgroundTasks, m: Membership = Depends(require("use_ai")),
              db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    ch = _chapter(db, m.workspace_id, book.id, body.chapter_id)
    source = ch.language if ch.language in ai.LANGS else "pl"
    if source == body.target:
        source = "en" if body.target == "pl" else "pl"
    j = _new_job(db, m, book, "translate", ch.id, {"chapter_title": ch.title, "source": source, "target": body.target})
    bg.add_task(run_job, j.id)
    return job_out(j)


@router.post("/beta-read", status_code=202)
def beta_read(book_id: str, body: BetaIn, bg: BackgroundTasks, m: Membership = Depends(require("use_ai")),
              db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    title = _chapter(db, m.workspace_id, book.id, body.chapter_id).title if body.chapter_id else "cała książka"
    j = _new_job(db, m, book, "beta_read", body.chapter_id, {"chapter_title": title})
    bg.add_task(run_job, j.id)
    return job_out(j)


@router.post("/marketing", status_code=202)
def marketing(book_id: str, body: MarketingIn, bg: BackgroundTasks, m: Membership = Depends(require("use_ai")),
              db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    j = _new_job(db, m, book, "marketing", None, {"what": body.kind, "label": ai.MARKETING[body.kind][0], "lang": body.lang})
    bg.add_task(run_job, j.id)
    return job_out(j)


@router.post("/jobs/{job_id}/apply")
def apply(book_id: str, job_id: str, body: ApplyIn, m: Membership = Depends(require("edit_manuscript")),
          db: Session = Depends(get_db)):
    """Accept chosen proofreading suggestions -> one new chapter version (origin=ai)."""
    j = db.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.book_id == book_id, AIJob.workspace_id == m.workspace_id))
    if j is None or j.kind != "proofread":
        raise HTTPException(404, "Nie znaleziono")
    if j.status != "done":
        raise HTTPException(409, "Te poprawki zostały już zastosowane albo zadanie się nie zakończyło")
    ch = _chapter(db, m.workspace_id, book_id, j.chapter_id)
    v = latest(db, ch.id)
    text = v.body if v else ""
    suggestions = j.result.get("suggestions", [])
    applied, skipped = [], []
    for i in sorted(set(body.accept)):
        if not 0 <= i < len(suggestions):
            continue
        orig = html.escape(suggestions[i]["original"], quote=False)
        new = html.escape(suggestions[i]["suggestion"], quote=False)
        if orig in text:
            text = text.replace(orig, new, 1)
            applied.append(i)
        else:
            skipped.append(i)
    if applied:
        add_version(db, ch, text, "ai", m.user_id, f"korekta AI: {len(applied)} poprawek")
    j.status = "applied"
    j.result = {**j.result, "applied": applied, "skipped": skipped}
    db.commit()
    return {"applied": len(applied), "skipped": len(skipped)}


# ---- background worker ------------------------------------------------------------------------------

def run_job(job_id: str) -> None:
    db = next(get_db())
    try:
        j = db.get(AIJob, job_id)
        if j is None:
            return
        j.status = "running"
        db.commit()
        try:
            result, model, tin, tout = _execute(db, j)
            j.result, j.model, j.tokens_in, j.tokens_out, j.status = result, model, tin, tout, "done"
        except ai.AIError as e:
            j.status, j.error = "failed", str(e)
        except Exception:  # noqa: BLE001 - a job must never stay "running"
            j.status, j.error = "failed", "Nieoczekiwany błąd zadania AI"
        j.finished_at = utcnow()
        db.commit()
    finally:
        db.close()


def _book_html(db: Session, book_id: str) -> str:
    out = []
    for c in db.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.position)):
        v = latest(db, c.id)
        out.append(f"<h2>{html.escape(c.title, quote=False)}</h2>{v.body if v else ''}")
    return "".join(out)


def _execute(db: Session, j: AIJob) -> tuple[dict, str, int, int]:
    book = db.get(Book, j.book_id)
    ch = db.get(Chapter, j.chapter_id) if j.chapter_id else None
    body = (latest(db, ch.id).body if ch and latest(db, ch.id) else "")
    model, tin, tout = "", 0, 0

    if j.kind == "proofread":
        if not html_to_text(body):
            raise ai.AIError("Rozdział jest pusty")
        found, seen = [], set()
        for part in ai.chunks(body):
            text, model, a, b = ai.complete(ai.PROOFREAD_SYSTEM, ai.proofread_prompt(html_to_text(part), ch.language), max_tokens=4000)
            tin, tout = tin + a, tout + b
            for s in ai.parse_json(text).get("suggestions", []):
                o, n = str(s.get("original", "")).strip(), str(s.get("suggestion", "")).strip()
                # keep only exact, real changes we can apply in the HTML
                if o and n and o != n and o not in seen and html.escape(o, quote=False) in body:
                    seen.add(o)
                    found.append({"original": o, "suggestion": n, "reason": str(s.get("reason", ""))[:300]})
        return {"suggestions": found[:300]}, model, tin, tout

    if j.kind == "translate":
        if not html_to_text(body):
            raise ai.AIError("Rozdział jest pusty")
        out = []
        for part in ai.chunks(body):
            text, model, a, b = ai.complete(ai.translate_system(j.params["source"], j.params["target"]), part,
                                            max_tokens=8000, temperature=0.2)
            tin, tout = tin + a, tout + b
            out.append(re.sub(r"^```(?:html)?\s*|\s*```$", "", text.strip()))
        title_text, model, a, b = ai.complete(ai.translate_system(j.params["source"], j.params["target"]),
                                              f"<p>{html.escape(ch.title, quote=False)}</p>", max_tokens=200)
        tin, tout = tin + a, tout + b
        new_title = html_to_text(sanitize_html(title_text)).strip()[:480] or ch.title
        pos = (db.scalar(select(func.max(Chapter.position)).where(Chapter.book_id == book.id)) or 0) + 1
        target = j.params["target"]
        new = Chapter(workspace_id=j.workspace_id, book_id=book.id, title=f"{new_title} [{target.upper()}]", position=pos, language=target)
        db.add(new)
        db.flush()
        add_version(db, new, "".join(out), "ai", j.created_by, f"tłumaczenie AI z rozdziału „{ch.title}”"[:300])
        book.ai_disclosure = {**(book.ai_disclosure or {}), "translation": True}  # KDP: AI translation must be disclosed
        return {"new_chapter_id": new.id, "new_chapter_title": new.title}, model, tin, tout

    if j.kind == "beta_read":
        source = body if ch else _book_html(db, book.id)
        text_plain = html_to_text(source)
        if not text_plain:
            raise ai.AIError("Brak tekstu do przeczytania")
        truncated = len(text_plain) > 120_000
        prompt = f"Tytuł książki: {book.title}\n" + (f"Rozdział: {ch.title}\n" if ch else "") + f"\nTekst:\n{text_plain[:120_000]}"
        text, model, tin, tout = ai.complete(ai.BETA_SYSTEM, prompt, max_tokens=3000, temperature=0.4)
        return {"report": text.strip(), "truncated": truncated}, model, tin, tout

    if j.kind == "marketing":
        label, task = ai.MARKETING[j.params["what"]]
        prompt = f"{task}\n\nDane książki:\n{ai.book_brief(book, _book_html(db, book.id))}"
        text, model, tin, tout = ai.complete(ai.marketing_system(j.params.get("lang", "pl")), prompt, max_tokens=3000, temperature=0.7)
        return {"text": text.strip()}, model, tin, tout

    raise ai.AIError("Nieznany rodzaj zadania")
