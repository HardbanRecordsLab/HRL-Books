from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.deps import require
from app.http import slugify
from app.models import Book, Membership, ResearchGate, Workspace, utcnow
from app.security import role_can
from app.schemas import BookImportIn, BookIn, BookOut, BookPatchIn

router = APIRouter(prefix="/api/v1/workspaces/{ws}/books", tags=["books"])


def _book(db: Session, ws_id: str, book_id: str) -> Book:
    # Always filter by workspace: a book id from another workspace is simply "not found" (spec 8.4).
    b = db.scalar(select(Book).where(Book.id == book_id, Book.workspace_id == ws_id, Book.deleted_at.is_(None)))
    if b is None:
        raise HTTPException(404, "Nie znaleziono")
    return b


@router.get("", response_model=list[BookOut])
def list_books(m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    return db.scalars(select(Book).where(Book.workspace_id == m.workspace_id, Book.deleted_at.is_(None))
                      .order_by(Book.created_at.desc())).all()


@router.post("", response_model=BookOut, status_code=201)
def create_book(body: BookIn, m: Membership = Depends(require("create_book")), db: Session = Depends(get_db)):
    ws = db.get(Workspace, m.workspace_id)
    count = db.scalar(select(func.count()).select_from(Book)
                      .where(Book.workspace_id == ws.id, Book.deleted_at.is_(None)))
    if count >= int(ws.limits.get("max_titles", 50)):
        raise HTTPException(403, "Osiągnięto limit tytułów w tym workspace'ie")
    b = Book(workspace_id=ws.id, created_by=m.user_id, **body.model_dump())
    db.add(b)
    db.flush()
    audit(db, "book.created", m.user_id, ws.id, target=b.id)
    db.commit()
    return b


@router.post("/import", status_code=201)
def import_books(body: BookImportIn, m: Membership = Depends(require("create_book")), db: Session = Depends(get_db)):
    """Bring already-published titles into the platform, with their store links."""
    ws = db.get(Workspace, m.workspace_id)
    count = db.scalar(select(func.count()).select_from(Book)
                      .where(Book.workspace_id == ws.id, Book.deleted_at.is_(None)))
    if count + len(body.books) > int(ws.limits.get("max_titles", 50)):
        raise HTTPException(403, "Import przekroczyłby limit tytułów w tym workspace'ie")
    for item in body.books:
        data = item.model_dump(mode="json")
        db.add(Book(workspace_id=ws.id, created_by=m.user_id, **data))
    audit(db, "book.imported", m.user_id, ws.id, count=len(body.books))
    db.commit()
    return {"imported": len(body.books)}


@router.patch("/{book_id}", response_model=BookOut)
def patch_book(book_id: str, body: BookPatchIn, m: Membership = Depends(require("edit_book")),
               db: Session = Depends(get_db)):
    b = _book(db, m.workspace_id, book_id)
    changes = body.model_dump(mode="json", exclude_none=True)
    reason = changes.pop("gate_override_reason", "").strip()
    if changes.get("status") == "writing" and b.status in ("idea", "research"):
        gate = db.get(ResearchGate, b.id)
        if not (gate and gate.closed_at):
            mode = db.get(Workspace, m.workspace_id).research_gate_mode
            if mode == "hard":
                raise HTTPException(409, "Najpierw zamknij research (bramka twarda).")
            if not reason:
                raise HTTPException(409, "Research nie jest zamknięty — podaj powód, aby przejść do pisania.")
            gate = gate or ResearchGate(book_id=b.id, workspace_id=m.workspace_id)
            gate.override_reason = reason
            db.add(gate)
            audit(db, "research.gate_overridden", m.user_id, m.workspace_id, target=b.id, reason=reason)
    if "public" in changes and not role_can(m.role, "manage_distribution"):
        raise HTTPException(403, "Stronę publiczną włącza właściciel")
    if "slug" in changes or changes.get("public"):
        slug = changes.get("slug") or b.slug or slugify(b.title)
        base, n = slug, 2
        while db.scalar(select(Book.id).where(Book.workspace_id == m.workspace_id, Book.slug == slug, Book.id != b.id)):
            if "slug" in changes:
                raise HTTPException(409, "Ten adres jest już zajęty przez inny tytuł")
            slug, n = f"{base}-{n}", n + 1
        changes["slug"] = slug
    for k, v in changes.items():
        setattr(b, k, v)
    audit(db, "book.updated", m.user_id, m.workspace_id, target=b.id, fields=sorted(changes))
    db.commit()
    return b


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    return _book(db, m.workspace_id, book_id)


@router.delete("/{book_id}", status_code=204)
def delete_book(book_id: str, m: Membership = Depends(require("delete_book")), db: Session = Depends(get_db)):
    b = _book(db, m.workspace_id, book_id)
    b.deleted_at = utcnow()  # soft delete; purge after 30 days (spec 10.2)
    audit(db, "book.deleted", m.user_id, m.workspace_id, target=b.id)
    db.commit()
