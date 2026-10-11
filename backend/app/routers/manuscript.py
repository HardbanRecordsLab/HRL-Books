"""Manuscript (module MS): chapters, versioned content, restore, import from DOCX/TXT/MD."""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.deps import require
from app.epub import build_epub
from app.http import attachment
from app.models import Book, Chapter, ChapterVersion, Membership
from app.text import docx_to_chapters, sanitize_html, stats, text_to_chapters

router = APIRouter(prefix="/api/v1/workspaces/{ws}/books/{book_id}/chapters", tags=["manuscript"])
STATUS_PL = {"draft": "szkic", "to_edit": "do redakcji", "edited": "zredagowany", "approved": "zatwierdzony"}


class ChapterIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class ChapterPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    status: str | None = Field(default=None, pattern="^(draft|to_edit|edited|approved)$")


class ContentIn(BaseModel):
    body: str = Field(max_length=2_000_000)
    note: str = Field(default="", max_length=300)


class OrderIn(BaseModel):
    chapter_ids: list[str] = Field(max_length=500)


def _book(db: Session, ws_id: str, book_id: str) -> Book:
    b = db.scalar(select(Book).where(Book.id == book_id, Book.workspace_id == ws_id, Book.deleted_at.is_(None)))
    if b is None:
        raise HTTPException(404, "Nie znaleziono")
    return b


def _chapter(db: Session, ws_id: str, book_id: str, chapter_id: str) -> Chapter:
    c = db.scalar(select(Chapter).where(Chapter.id == chapter_id, Chapter.book_id == book_id, Chapter.workspace_id == ws_id))
    if c is None:
        raise HTTPException(404, "Nie znaleziono rozdziału")
    return c


def latest(db: Session, chapter_id: str) -> ChapterVersion | None:
    return db.scalar(select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id)
                     .order_by(ChapterVersion.created_at.desc(), ChapterVersion.id.desc()).limit(1))


def add_version(db: Session, ch: Chapter, body: str, origin: str, user_id: str | None, note: str = "") -> ChapterVersion:
    clean = sanitize_html(body)
    words, chars = stats(clean)
    v = ChapterVersion(workspace_id=ch.workspace_id, chapter_id=ch.id, body=clean, words=words, chars=chars,
                       origin=origin, note=note, created_by=user_id)
    db.add(v)
    db.flush()
    return v


def chapter_out(db: Session, c: Chapter, with_body: bool = False) -> dict:
    v = latest(db, c.id)
    out = {"id": c.id, "title": c.title, "position": c.position, "status": c.status, "status_label": STATUS_PL[c.status],
           "language": c.language, "words": v.words if v else 0, "chars": v.chars if v else 0,
           "updated_at": v.created_at if v else c.created_at}
    if with_body:
        out["body"] = v.body if v else ""
        out["version_id"] = v.id if v else None
    return out


@router.get("")
def list_chapters(book_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    chapters = [chapter_out(db, c) for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.position))]
    return {"chapters": chapters, "words": sum(c["words"] for c in chapters), "chars": sum(c["chars"] for c in chapters)}


@router.post("", status_code=201)
def create_chapter(book_id: str, body: ChapterIn, m: Membership = Depends(require("edit_manuscript")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    pos = (db.scalar(select(func.max(Chapter.position)).where(Chapter.book_id == book.id)) or 0) + 1
    c = Chapter(workspace_id=m.workspace_id, book_id=book.id, title=body.title, position=pos, language=book.language)
    db.add(c)
    db.flush()
    add_version(db, c, "", "human", m.user_id, "utworzono")
    db.commit()
    return chapter_out(db, c, True)


@router.put("/order")
def reorder(book_id: str, body: OrderIn, m: Membership = Depends(require("edit_manuscript")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    chapters = {c.id: c for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id))}
    if set(body.chapter_ids) != set(chapters):
        raise HTTPException(422, "Lista musi zawierać wszystkie rozdziały książki")
    for i, cid in enumerate(body.chapter_ids):
        chapters[cid].position = i + 1
    db.commit()
    return {"ok": True}


@router.get("/{chapter_id}")
def get_chapter(book_id: str, chapter_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    return chapter_out(db, _chapter(db, m.workspace_id, book_id, chapter_id), True)


@router.patch("/{chapter_id}")
def patch_chapter(book_id: str, chapter_id: str, body: ChapterPatch, m: Membership = Depends(require("edit_manuscript")),
                  db: Session = Depends(get_db)):
    c = _chapter(db, m.workspace_id, book_id, chapter_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    db.commit()
    return chapter_out(db, c)


@router.put("/{chapter_id}/content")
def save_content(book_id: str, chapter_id: str, body: ContentIn, m: Membership = Depends(require("edit_manuscript")),
                 db: Session = Depends(get_db)):
    c = _chapter(db, m.workspace_id, book_id, chapter_id)
    prev = latest(db, c.id)
    if prev and prev.body == sanitize_html(body.body):
        return chapter_out(db, c, True)  # nothing changed: no new version
    add_version(db, c, body.body, "human", m.user_id, body.note)
    db.commit()
    return chapter_out(db, c, True)


@router.delete("/{chapter_id}", status_code=204)
def delete_chapter(book_id: str, chapter_id: str, m: Membership = Depends(require("edit_manuscript")), db: Session = Depends(get_db)):
    c = _chapter(db, m.workspace_id, book_id, chapter_id)
    db.delete(c)
    audit(db, "chapter.deleted", m.user_id, m.workspace_id, target=chapter_id)
    db.commit()


@router.get("/{chapter_id}/versions")
def versions(book_id: str, chapter_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    c = _chapter(db, m.workspace_id, book_id, chapter_id)
    rows = db.scalars(select(ChapterVersion).where(ChapterVersion.chapter_id == c.id)
                      .order_by(ChapterVersion.created_at.desc(), ChapterVersion.id.desc()).limit(200))
    return [{"id": v.id, "words": v.words, "origin": v.origin, "note": v.note, "created_at": v.created_at, "body": v.body}
            for v in rows]


@router.post("/{chapter_id}/versions/{version_id}/restore")
def restore(book_id: str, chapter_id: str, version_id: str, m: Membership = Depends(require("edit_manuscript")),
            db: Session = Depends(get_db)):
    c = _chapter(db, m.workspace_id, book_id, chapter_id)
    v = db.scalar(select(ChapterVersion).where(ChapterVersion.id == version_id, ChapterVersion.chapter_id == c.id))
    if v is None:
        raise HTTPException(404, "Nie znaleziono wersji")
    add_version(db, c, v.body, "human", m.user_id, f"przywrócono wersję z {v.created_at:%Y-%m-%d %H:%M}")
    db.commit()
    return chapter_out(db, c, True)


import_router = APIRouter(prefix="/api/v1/workspaces/{ws}/books/{book_id}", tags=["manuscript"])


@import_router.post("/manuscript/import", status_code=201)
async def import_manuscript(book_id: str, file: UploadFile = File(...), m: Membership = Depends(require("edit_manuscript")),
                            db: Session = Depends(get_db)):
    """FR-MS-01: DOCX (split on Heading 1) or TXT/Markdown (split on '# ')."""
    book = _book(db, m.workspace_id, book_id)
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Plik większy niż 25 MB")
    name = (file.filename or "").lower()
    try:
        if name.endswith(".docx") or data[:2] == b"PK":
            parts = docx_to_chapters(data)
        elif name.endswith((".txt", ".md", ".markdown")):
            parts = text_to_chapters(data.decode("utf-8", errors="replace"))
        else:
            raise HTTPException(415, "Obsługiwane pliki: DOCX, TXT, MD")
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"Nie udało się odczytać pliku: {e}") from e
    if not parts:
        raise HTTPException(422, "Plik nie zawiera tekstu")
    pos = db.scalar(select(func.max(Chapter.position)).where(Chapter.book_id == book.id)) or 0
    for i, (title, body) in enumerate(parts):
        c = Chapter(workspace_id=m.workspace_id, book_id=book.id, title=title[:500], position=pos + i + 1, language=book.language)
        db.add(c)
        db.flush()
        add_version(db, c, body, "import", m.user_id, f"import z {file.filename}"[:300])
    audit(db, "manuscript.imported", m.user_id, m.workspace_id, target=book.id, chapters=len(parts))
    db.commit()
    return {"chapters": len(parts)}


@import_router.get("/export/epub")
def export_epub(book_id: str, lang: str | None = Query(default=None, pattern="^[a-z]{2}$"),
                m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    """EPUB 3 with accessibility metadata; chapters in the chosen language (default: the book's)."""
    book = _book(db, m.workspace_id, book_id)
    try:
        data = build_epub(db, book, lang)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    audit(db, "epub.exported", m.user_id, m.workspace_id, target=book.id)
    db.commit()
    other = lang and lang != book.language
    disposition = attachment(book.title, f" ({lang.upper()}).epub" if other else ".epub", f"-{lang}.epub" if other else ".epub")
    return Response(data, media_type="application/epub+zip", headers={"Content-Disposition": disposition})
