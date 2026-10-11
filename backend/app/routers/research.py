"""Research vault (module RES): sources, notes and quotes, search, research gate."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.deps import require
from app.models import Asset, Book, Chapter, Membership, ResearchGate, ResearchNote, ResearchSource, utcnow

router = APIRouter(prefix="/api/v1/workspaces/{ws}/books/{book_id}/research", tags=["research"])


class SourceIn(BaseModel):
    kind: str = Field(default="url", pattern="^(url|file|book|article|interview|other)$")
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(default="", max_length=2000)
    citation: str = Field(default="", max_length=3000)
    accessed_on: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    asset_id: str | None = None


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    source_id: str | None = None
    chapter_id: str | None = None
    is_quote: bool = False
    page_ref: str = Field(default="", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)


class GateIn(BaseModel):
    note: str = Field(default="", max_length=2000)


def _book(db: Session, ws_id: str, book_id: str) -> Book:
    b = db.scalar(select(Book).where(Book.id == book_id, Book.workspace_id == ws_id, Book.deleted_at.is_(None)))
    if b is None:
        raise HTTPException(404, "Nie znaleziono")
    return b


def _source_out(s: ResearchSource) -> dict:
    return {"id": s.id, "kind": s.kind, "title": s.title, "url": s.url, "citation": s.citation,
            "accessed_on": s.accessed_on, "asset_id": s.asset_id, "created_at": s.created_at}


def _note_out(n: ResearchNote) -> dict:
    return {"id": n.id, "body": n.body, "source_id": n.source_id, "chapter_id": n.chapter_id, "is_quote": n.is_quote,
            "page_ref": n.page_ref, "tags": n.tags or [], "created_at": n.created_at}


def gate_out(g: ResearchGate | None, mode: str) -> dict:
    return {"closed": bool(g and g.closed_at), "closed_at": g.closed_at if g else None, "note": g.note if g else "",
            "override_reason": g.override_reason if g else "", "mode": mode}


@router.get("")
def overview(book_id: str, q: str = "", m: Membership = Depends(require("read_research")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    sources = select(ResearchSource).where(ResearchSource.book_id == book.id)
    notes = select(ResearchNote).where(ResearchNote.book_id == book.id)
    if q.strip():  # FR-RES-04: search across the whole vault of the title
        like = f"%{q.strip()}%"
        sources = sources.where(or_(ResearchSource.title.ilike(like), ResearchSource.citation.ilike(like), ResearchSource.url.ilike(like)))
        notes = notes.where(or_(ResearchNote.body.ilike(like), ResearchNote.page_ref.ilike(like)))
    from app.models import Workspace
    mode = db.get(Workspace, m.workspace_id).research_gate_mode
    return {"sources": [_source_out(s) for s in db.scalars(sources.order_by(ResearchSource.created_at.desc()))],
            "notes": [_note_out(n) for n in db.scalars(notes.order_by(ResearchNote.created_at.desc()))],
            "gate": gate_out(db.get(ResearchGate, book.id), mode)}


@router.post("/sources", status_code=201)
def add_source(book_id: str, body: SourceIn, m: Membership = Depends(require("edit_research")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    if body.asset_id and db.scalar(select(Asset).where(Asset.id == body.asset_id, Asset.workspace_id == m.workspace_id)) is None:
        raise HTTPException(404, "Nie znaleziono pliku")
    s = ResearchSource(workspace_id=m.workspace_id, book_id=book.id, created_by=m.user_id, **body.model_dump())
    db.add(s)
    db.commit()
    return _source_out(s)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(book_id: str, source_id: str, m: Membership = Depends(require("edit_research")), db: Session = Depends(get_db)):
    s = db.scalar(select(ResearchSource).where(ResearchSource.id == source_id, ResearchSource.book_id == book_id,
                                               ResearchSource.workspace_id == m.workspace_id))
    if s is None:
        raise HTTPException(404, "Nie znaleziono")
    db.delete(s)
    db.commit()


@router.post("/notes", status_code=201)
def add_note(book_id: str, body: NoteIn, m: Membership = Depends(require("edit_research")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    if body.is_quote and not body.source_id:
        raise HTTPException(422, "Cytat musi mieć źródło (FR-RES-03)")
    if body.source_id and db.scalar(select(ResearchSource).where(ResearchSource.id == body.source_id,
                                                                 ResearchSource.book_id == book.id)) is None:
        raise HTTPException(404, "Nie znaleziono źródła")
    if body.chapter_id and db.scalar(select(Chapter).where(Chapter.id == body.chapter_id, Chapter.book_id == book.id)) is None:
        raise HTTPException(404, "Nie znaleziono rozdziału")
    data = body.model_dump()
    data["tags"] = [t.strip() for t in data["tags"] if t.strip()]
    n = ResearchNote(workspace_id=m.workspace_id, book_id=book.id, created_by=m.user_id, **data)
    db.add(n)
    db.commit()
    return _note_out(n)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(book_id: str, note_id: str, m: Membership = Depends(require("edit_research")), db: Session = Depends(get_db)):
    n = db.scalar(select(ResearchNote).where(ResearchNote.id == note_id, ResearchNote.book_id == book_id,
                                             ResearchNote.workspace_id == m.workspace_id))
    if n is None:
        raise HTTPException(404, "Nie znaleziono")
    db.delete(n)
    db.commit()


@router.post("/gate")
def close_gate(book_id: str, body: GateIn, m: Membership = Depends(require("edit_research")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    g = db.get(ResearchGate, book.id) or ResearchGate(book_id=book.id, workspace_id=m.workspace_id)
    g.closed_at, g.closed_by, g.note = utcnow(), m.user_id, body.note
    db.add(g)
    audit(db, "research.closed", m.user_id, m.workspace_id, target=book.id)
    db.commit()
    from app.models import Workspace
    return gate_out(g, db.get(Workspace, m.workspace_id).research_gate_mode)


@router.delete("/gate")
def reopen_gate(book_id: str, m: Membership = Depends(require("edit_research")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    g = db.get(ResearchGate, book.id)
    if g:
        g.closed_at = None
        audit(db, "research.reopened", m.user_id, m.workspace_id, target=book.id)
        db.commit()
    from app.models import Workspace
    return gate_out(g, db.get(Workspace, m.workspace_id).research_gate_mode)
