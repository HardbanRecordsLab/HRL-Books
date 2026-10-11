"""Metadata master (module META): people, contributors, extended book metadata, editions, checks."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.checks import isbn_valid, run_checks
from app.db import get_db
from app.deps import require
from app.models import Book, BookContributor, Edition, Membership, Person, Workspace
from app.schemas import (ContributorOut, EditionIn, EditionOut, MetadataIn, MetadataOut, PersonIn, PersonOut)

router = APIRouter(prefix="/api/v1/workspaces/{ws}", tags=["metadata"])


def _book(db: Session, ws_id: str, book_id: str) -> Book:
    b = db.scalar(select(Book).where(Book.id == book_id, Book.workspace_id == ws_id, Book.deleted_at.is_(None)))
    if b is None:
        raise HTTPException(404, "Nie znaleziono")
    return b


def _person(db: Session, ws_id: str, person_id: str) -> Person:
    p = db.scalar(select(Person).where(Person.id == person_id, Person.workspace_id == ws_id))
    if p is None:
        raise HTTPException(404, "Nie znaleziono osoby")
    return p


def _contributors(db: Session, book: Book) -> list[tuple[BookContributor, Person]]:
    return list(db.execute(select(BookContributor, Person).join(Person, Person.id == BookContributor.person_id)
                           .where(BookContributor.book_id == book.id).order_by(BookContributor.position)).all())


def _metadata_out(db: Session, book: Book) -> MetadataOut:
    return MetadataOut(
        desc_long=book.desc_long, keywords=book.keywords or [], categories=book.categories or [],
        audience=book.audience, series_name=book.series_name, series_volume=book.series_volume,
        copyright_holder=book.copyright_holder, copyright_year=book.copyright_year, territories=book.territories,
        ai_disclosure=book.ai_disclosure or {},
        contributors=[ContributorOut(person_id=p.id, display_name=p.display_name, role=c.role, position=c.position)
                      for c, p in _contributors(db, book)],
    )


# ---- people ---------------------------------------------------------------------------------------

@router.get("/people", response_model=list[PersonOut])
def list_people(m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    return db.scalars(select(Person).where(Person.workspace_id == m.workspace_id).order_by(Person.display_name)).all()


@router.post("/people", response_model=PersonOut, status_code=201)
def create_person(body: PersonIn, m: Membership = Depends(require("edit_metadata")), db: Session = Depends(get_db)):
    p = Person(workspace_id=m.workspace_id, **body.model_dump())
    db.add(p)
    db.flush()
    audit(db, "person.created", m.user_id, m.workspace_id, target=p.id)
    db.commit()
    return p


@router.put("/people/{person_id}", response_model=PersonOut)
def update_person(person_id: str, body: PersonIn, m: Membership = Depends(require("edit_metadata")),
                  db: Session = Depends(get_db)):
    p = _person(db, m.workspace_id, person_id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return p


@router.delete("/people/{person_id}", status_code=204)
def delete_person(person_id: str, m: Membership = Depends(require("edit_metadata")), db: Session = Depends(get_db)):
    p = _person(db, m.workspace_id, person_id)
    db.delete(p)
    audit(db, "person.deleted", m.user_id, m.workspace_id, target=person_id)
    db.commit()


# ---- book metadata ---------------------------------------------------------------------------------

@router.get("/books/{book_id}/metadata", response_model=MetadataOut)
def get_metadata(book_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    return _metadata_out(db, _book(db, m.workspace_id, book_id))


@router.put("/books/{book_id}/metadata", response_model=MetadataOut)
def put_metadata(book_id: str, body: MetadataIn, m: Membership = Depends(require("edit_metadata")),
                 db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    data = body.model_dump(exclude_none=True, exclude={"contributors"})
    if "keywords" in data:
        data["keywords"] = [k.strip() for k in data["keywords"] if k.strip()]
    if "categories" in data:
        data["categories"] = [c.strip() for c in data["categories"] if c.strip()]
    for k, v in data.items():
        setattr(book, k, v)
    if body.contributors is not None:
        db.execute(delete(BookContributor).where(BookContributor.book_id == book.id))
        seen = set()
        for i, c in enumerate(body.contributors):
            _person(db, m.workspace_id, c.person_id)  # must belong to this workspace
            if (c.person_id, c.role) in seen:
                continue
            seen.add((c.person_id, c.role))
            db.add(BookContributor(workspace_id=m.workspace_id, book_id=book.id, person_id=c.person_id,
                                   role=c.role, position=i))
    audit(db, "book.metadata_updated", m.user_id, m.workspace_id, target=book.id, fields=sorted(data))
    db.commit()
    return _metadata_out(db, book)


@router.get("/books/{book_id}/checks")
def checks(book_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    editions = list(db.scalars(select(Edition).where(Edition.book_id == book.id)))
    return run_checks(db.get(Workspace, m.workspace_id), book, _contributors(db, book), editions)


# ---- editions --------------------------------------------------------------------------------------

def _edition(db: Session, ws_id: str, book_id: str, edition_id: str) -> Edition:
    e = db.scalar(select(Edition).where(Edition.id == edition_id, Edition.book_id == book_id, Edition.workspace_id == ws_id))
    if e is None:
        raise HTTPException(404, "Nie znaleziono wydania")
    return e


def _check_isbn(isbn: str) -> str:
    isbn = isbn.strip()
    if isbn and not isbn_valid(isbn):
        raise HTTPException(422, "Numer ISBN jest niepoprawny (zła suma kontrolna)")
    return isbn


@router.get("/books/{book_id}/editions", response_model=list[EditionOut])
def list_editions(book_id: str, m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    return db.scalars(select(Edition).where(Edition.book_id == book.id).order_by(Edition.created_at)).all()


@router.post("/books/{book_id}/editions", response_model=EditionOut, status_code=201)
def create_edition(book_id: str, body: EditionIn, m: Membership = Depends(require("edit_metadata")),
                   db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    data = body.model_dump(mode="json")
    data["isbn"] = _check_isbn(data["isbn"])
    e = Edition(workspace_id=m.workspace_id, book_id=book.id, **data)
    db.add(e)
    db.flush()
    audit(db, "edition.created", m.user_id, m.workspace_id, target=e.id, format=e.format)
    db.commit()
    return e


@router.put("/books/{book_id}/editions/{edition_id}", response_model=EditionOut)
def update_edition(book_id: str, edition_id: str, body: EditionIn, m: Membership = Depends(require("edit_metadata")),
                   db: Session = Depends(get_db)):
    e = _edition(db, m.workspace_id, book_id, edition_id)
    data = body.model_dump(mode="json")
    data["isbn"] = _check_isbn(data["isbn"])
    for k, v in data.items():
        setattr(e, k, v)
    db.commit()
    return e


@router.delete("/books/{book_id}/editions/{edition_id}", status_code=204)
def delete_edition(book_id: str, edition_id: str, m: Membership = Depends(require("edit_metadata")),
                   db: Session = Depends(get_db)):
    e = _edition(db, m.workspace_id, book_id, edition_id)
    db.delete(e)
    audit(db, "edition.deleted", m.user_id, m.workspace_id, target=edition_id)
    db.commit()
