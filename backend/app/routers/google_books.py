"""Google Books: search already-published titles, import them, or fill gaps in an existing title's metadata."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import google_books as gb
from app.audit import audit
from app.db import get_db
from app.deps import require
from app.integrations import IntegrationError
from app.models import Asset, Book, BookContributor, Edition, Membership, Person, Workspace
from app.routers.assets import store_asset

router = APIRouter(prefix="/api/v1/workspaces/{ws}", tags=["google-books"])


class ImportIn(BaseModel):
    volume_ids: list[str] = Field(min_length=1, max_length=50)


class FillIn(BaseModel):
    volume_id: str


def _fail(e: IntegrationError):
    raise HTTPException(503 if "klucz" in str(e).lower() or "limit" in str(e).lower() else 502, str(e))


def _norm_title(t: str) -> str:
    return re.sub(r"\W+", "", (t or "").casefold())


def canonical_name(name: str, rules: list) -> str:
    """Map store spellings onto the workspace's canonical author name (Ustawienia → reguły nazwiska),
    e.g. "Kamil Skomra Skomrakus" -> "Kamil Skomra" when "Skomrakus" is a forbidden variant."""
    low = name.casefold()
    for r in rules or []:
        canon = (r.get("canonical") or "").strip()
        if not canon:
            continue
        variants = [canon] + [f for f in r.get("forbidden", []) if f]
        if canon.casefold() in low or any(f.casefold() in low for f in variants[1:]):
            return canon
    return name


def _person(db: Session, ws_id: str, name: str) -> Person:
    p = db.scalar(select(Person).where(Person.workspace_id == ws_id, func.lower(Person.display_name) == name.lower()))
    if p is None:
        p = Person(workspace_id=ws_id, display_name=name[:200])
        db.add(p)
        db.flush()
    return p


def _apply(db: Session, ws_id: str, book: Book, v: dict, only_empty: bool) -> list[str]:
    """Copy Google data onto the book. only_empty=True never overwrites what the user already filled."""
    changed = []

    def put(attr, value):
        if value and (not only_empty or not getattr(book, attr)):
            setattr(book, attr, value)
            changed.append(attr)

    put("subtitle", v["subtitle"][:500])
    put("desc_short", (v["description"][:297] + "…") if len(v["description"]) > 300 else v["description"])
    put("desc_long", v["description"][:20000])
    put("categories", v["categories"][:20])
    put("copyright_year", v["year"])
    if v["store_url"] and not any(link.get("url") == v["store_url"] for link in (book.store_links or [])):
        book.store_links = [*(book.store_links or []), {"url": v["store_url"], "channel": "Google Play" if "play.google" in v["store_url"] else "Google Books"}]
        changed.append("store_links")

    if v["authors"] and not db.scalar(select(func.count()).select_from(BookContributor).where(BookContributor.book_id == book.id)):
        rules = db.get(Workspace, ws_id).identity_rules
        names = list(dict.fromkeys(canonical_name(n, rules) for n in v["authors"][:10]))
        for i, name in enumerate(names):
            db.add(BookContributor(workspace_id=ws_id, book_id=book.id, person_id=_person(db, ws_id, name).id, role="author", position=i))
        changed.append("authors")

    isbn = v["isbn13"] or v["isbn10"]
    fmt = "ebook_epub" if v["is_ebook"] else "paperback"
    has_edition = db.scalar(select(Edition).where(Edition.book_id == book.id, Edition.format == fmt))
    if not has_edition and (isbn or v["release_date"] or v["pages"]):
        db.add(Edition(workspace_id=ws_id, book_id=book.id, format=fmt, isbn=isbn, release_date=v["release_date"],
                       pages=v["pages"], prices=[]))
        changed.append("edition")

    has_cover = db.scalar(select(Asset.id).where(Asset.book_id == book.id, Asset.kind == "cover"))
    if v["cover_url"] and not has_cover:
        img = gb.fetch_cover(v["cover_url"])
        if img:
            store_asset(db, ws_id, book.id, "cover", img[0], img[1], f"google-books-{v['id']}")
            changed.append("cover")
    return changed


@router.get("/google-books/search")
def search(q: str = Query(min_length=2, max_length=200), m: Membership = Depends(require("create_book")),
           db: Session = Depends(get_db)):
    try:
        results = gb.search(q)
    except IntegrationError as e:
        _fail(e)
    # Mark titles already in this workspace so the UI can grey them out.
    books = db.scalars(select(Book).where(Book.workspace_id == m.workspace_id, Book.deleted_at.is_(None)))
    titles = {_norm_title(b.title) for b in books}
    isbns = {e for e in db.scalars(select(Edition.isbn).where(Edition.workspace_id == m.workspace_id)) if e}
    for r in results:
        r["exists"] = _norm_title(r["title"]) in titles or bool({r["isbn13"], r["isbn10"]} & isbns)
    return {"results": results}


@router.post("/google-books/import", status_code=201)
def import_volumes(body: ImportIn, m: Membership = Depends(require("create_book")), db: Session = Depends(get_db)):
    ws = db.get(Workspace, m.workspace_id)
    count = db.scalar(select(func.count()).select_from(Book).where(Book.workspace_id == ws.id, Book.deleted_at.is_(None)))
    if count + len(body.volume_ids) > int(ws.limits.get("max_titles", 50)):
        raise HTTPException(403, "Import przekroczyłby limit tytułów w tym workspace'ie")
    titles = {_norm_title(b.title) for b in db.scalars(select(Book).where(Book.workspace_id == ws.id, Book.deleted_at.is_(None)))}
    isbns = {e for e in db.scalars(select(Edition.isbn).where(Edition.workspace_id == ws.id)) if e}
    imported, skipped = [], []
    for vid in dict.fromkeys(body.volume_ids):
        try:
            v = gb.volume(vid)
        except IntegrationError as e:
            skipped.append({"id": vid, "reason": str(e)})
            continue
        if not v["title"] or _norm_title(v["title"]) in titles or ({v["isbn13"], v["isbn10"]} - {""}) & isbns:
            skipped.append({"id": vid, "title": v["title"], "reason": "już jest w katalogu"})
            continue
        book = Book(workspace_id=ws.id, created_by=m.user_id, title=v["title"][:500], language=v["language"] or "pl",
                    status="published")
        db.add(book)
        db.flush()
        _apply(db, ws.id, book, v, only_empty=False)
        titles.add(_norm_title(v["title"]))
        isbns |= {v["isbn13"], v["isbn10"]} - {""}
        imported.append({"id": book.id, "title": book.title})
    audit(db, "google_books.imported", m.user_id, ws.id, count=len(imported))
    db.commit()
    return {"imported": imported, "skipped": skipped}


@router.post("/books/{book_id}/google-books/fill")
def fill(book_id: str, body: FillIn, m: Membership = Depends(require("edit_metadata")), db: Session = Depends(get_db)):
    book = db.scalar(select(Book).where(Book.id == book_id, Book.workspace_id == m.workspace_id, Book.deleted_at.is_(None)))
    if book is None:
        raise HTTPException(404, "Nie znaleziono")
    try:
        v = gb.volume(body.volume_id)
    except IntegrationError as e:
        _fail(e)
    changed = _apply(db, m.workspace_id, book, v, only_empty=True)
    audit(db, "google_books.filled", m.user_id, m.workspace_id, target=book.id, fields=changed)
    db.commit()
    return {"filled": changed}
