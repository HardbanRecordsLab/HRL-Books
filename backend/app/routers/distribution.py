"""Distribution (module DIST): channel profiles, board title x channel, listing status, checklist, package ZIP."""
import csv
import io
import json
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.channels import CHANNELS, STATUS_LABELS, channel_from_url, public_profile
from app.checks import run_checks
from app.db import get_db
from app.deps import require
from app.models import Book, BookContributor, Edition, Listing, Membership, Person, Workspace, utcnow
from app.schemas import ListingIn, ListingOut

router = APIRouter(prefix="/api/v1/workspaces/{ws}", tags=["distribution"])
CONTRIB_PL = {"author": "autor", "editor": "redaktor", "translator": "tłumacz", "cover_designer": "projekt okładki",
              "illustrator": "ilustrator", "narrator": "lektor"}


def _book(db: Session, ws_id: str, book_id: str) -> Book:
    b = db.scalar(select(Book).where(Book.id == book_id, Book.workspace_id == ws_id, Book.deleted_at.is_(None)))
    if b is None:
        raise HTTPException(404, "Nie znaleziono")
    return b


def _channel(key: str) -> dict:
    if key not in CHANNELS:
        raise HTTPException(404, "Nieznany kanał")
    return CHANNELS[key]


def _contributors(db: Session, book: Book):
    return list(db.execute(select(BookContributor, Person).join(Person, Person.id == BookContributor.person_id)
                           .where(BookContributor.book_id == book.id).order_by(BookContributor.position)).all())


def _implicit_status(book: Book, channel: str) -> str:
    """A store link imported for a title counts as a published listing until someone edits the listing."""
    for link in book.store_links or []:
        if channel_from_url(link.get("url", "")) == channel:
            return "published"
    return "not_ready"


def channel_issues(book: Book, editions: list[Edition], key: str) -> list[str]:
    ch = CHANNELS[key]
    issues = []
    limits = ch.get("limits", {})
    if limits.get("keywords_max") and len(book.keywords or []) > limits["keywords_max"]:
        issues.append(f"{ch['name']}: maksymalnie {limits['keywords_max']} słów kluczowych (jest {len(book.keywords)}).")
    if limits.get("desc_long_max") and len(book.desc_long or "") > limits["desc_long_max"]:
        issues.append(f"{ch['name']}: opis może mieć najwyżej {limits['desc_long_max']} znaków (ma {len(book.desc_long)}).")
    if not any(e.format in ch["formats"] for e in editions):
        names = ", ".join(ch["formats"])
        issues.append(f"{ch['name']}: brak wydania w obsługiwanym formacie ({names}).")
    return issues


@router.get("/channels")
def channels(m: Membership = Depends(require("read_books"))):
    return {"channels": [public_profile(k) for k in CHANNELS], "statuses": STATUS_LABELS}


@router.get("/distribution")
def board(m: Membership = Depends(require("read_distribution")), db: Session = Depends(get_db)):
    books = list(db.scalars(select(Book).where(Book.workspace_id == m.workspace_id, Book.deleted_at.is_(None))
                            .order_by(Book.title)))
    listings = {(l.book_id, l.channel): l for l in db.scalars(select(Listing).where(Listing.workspace_id == m.workspace_id))}
    rows = []
    for b in books:
        cells = {}
        for key in CHANNELS:
            lst = listings.get((b.id, key))
            cells[key] = {"status": lst.status if lst else _implicit_status(b, key), "url": lst.url if lst else ""}
        rows.append({"book_id": b.id, "title": b.title, "book_status": b.status, "cells": cells})
    return {"channels": [{"key": k, "name": v["name"]} for k, v in CHANNELS.items()], "statuses": STATUS_LABELS,
            "rows": rows}


@router.get("/books/{book_id}/listings")
def book_listings(book_id: str, m: Membership = Depends(require("read_distribution")), db: Session = Depends(get_db)):
    book = _book(db, m.workspace_id, book_id)
    editions = list(db.scalars(select(Edition).where(Edition.book_id == book.id)))
    existing = {l.channel: l for l in db.scalars(select(Listing).where(Listing.book_id == book.id))}
    base = run_checks(db.get(Workspace, m.workspace_id), book, _contributors(db, book), editions)
    out = []
    for key in CHANNELS:
        lst = existing.get(key)
        data = ListingOut.model_validate(lst).model_dump() if lst else {
            "channel": key, "market": "all", "status": _implicit_status(book, key), "url": "", "notes": "",
            "rejection_reason": "", "checklist": [], "edition_id": None, "sent_at": None, "published_at": None}
        issues = channel_issues(book, editions, key)
        if base["missing"]:
            issues.insert(0, "Uzupełnij w karcie: " + ", ".join(x["label"] for x in base["missing"]) + ".")
        out.append({**data, "profile": public_profile(key), "issues": issues})
    return out


@router.put("/books/{book_id}/listings/{channel}", response_model=ListingOut)
def update_listing(book_id: str, channel: str, body: ListingIn, m: Membership = Depends(require("manage_distribution")),
                   db: Session = Depends(get_db)):
    _channel(channel)
    book = _book(db, m.workspace_id, book_id)
    lst = db.scalar(select(Listing).where(Listing.book_id == book.id, Listing.channel == channel, Listing.market == "all"))
    if lst is None:
        lst = Listing(workspace_id=m.workspace_id, book_id=book.id, channel=channel, market="all",
                      status=_implicit_status(book, channel))
        db.add(lst)
    changes = body.model_dump(exclude_none=True)
    if "edition_id" in changes:
        ed = db.scalar(select(Edition).where(Edition.id == changes["edition_id"], Edition.book_id == book.id))
        if ed is None:
            raise HTTPException(404, "Nie znaleziono wydania")
    if changes.get("status") == "sent" and lst.sent_at is None:
        lst.sent_at = utcnow()
    if changes.get("status") == "published" and lst.published_at is None:
        lst.published_at = utcnow()
    for k, v in changes.items():
        setattr(lst, k, v)
    lst.updated_at = utcnow()
    audit(db, "listing.updated", m.user_id, m.workspace_id, target=f"{book.id}:{channel}", fields=sorted(changes))
    db.commit()
    return lst


def _package(db: Session, ws: Workspace, book: Book, key: str) -> bytes:
    ch = CHANNELS[key]
    editions = list(db.scalars(select(Edition).where(Edition.book_id == book.id)))
    contributors = _contributors(db, book)
    meta = {
        "channel": ch["name"], "title": book.title, "subtitle": book.subtitle, "language": book.language,
        "series": book.series_name, "series_volume": book.series_volume,
        "contributors": [{"name": p.display_name, "role": c.role, "bio_short": p.bio_short} for c, p in contributors],
        "description_short": book.desc_short, "description_long": book.desc_long,
        "keywords": (book.keywords or [])[: ch["limits"].get("keywords_max", 50)],
        "categories": book.categories, "audience": book.audience,
        "copyright": {"holder": book.copyright_holder, "year": book.copyright_year}, "territories": book.territories,
        "ai_generated": book.ai_disclosure,
        "editions": [{"format": e.format, "isbn": e.isbn, "release_date": e.release_date, "pages": e.pages,
                      "drm": e.drm, "prices": e.prices} for e in editions if e.format in ch["formats"]],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadane.json", json.dumps(meta, ensure_ascii=False, indent=2))
        rows = io.StringIO()
        w = csv.writer(rows, delimiter=";")
        w.writerow(["pole", "wartość"])
        w.writerow(["tytuł", book.title])
        w.writerow(["podtytuł", book.subtitle])
        for c, p in contributors:
            w.writerow([CONTRIB_PL.get(c.role, c.role), p.display_name])
        w.writerow(["język", book.language])
        w.writerow(["słowa kluczowe", ", ".join(meta["keywords"])])
        w.writerow(["kategorie", " | ".join(book.categories or [])])
        w.writerow(["odbiorcy", book.audience])
        for e in meta["editions"]:
            prices = ", ".join(f"{p['amount']} {p['currency']} ({p['market']})" for p in e["prices"])
            w.writerow([f"wydanie {e['format']}", f"ISBN {e['isbn'] or '—'}; premiera {e['release_date'] or '—'}; {prices}"])
        z.writestr("metadane.csv", "﻿" + rows.getvalue())
        z.writestr("opis.txt", book.desc_long or book.desc_short)
        steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(ch["steps"]))
        ai = book.ai_disclosure or {}
        ai_line = ("Treści AI do zadeklarowania: " + ", ".join(k for k, v in ai.items() if v)) if any(ai.values()) else "Brak treści wygenerowanych przez AI do zadeklarowania."
        z.writestr("INSTRUKCJA.txt",
                   f"{ch['name']} — {book.title}\nPanel: {ch['panel_url']}\n\n{steps}\n\n{ai_line}\n\n"
                   f"Pliki wydania i okładkę dołącz z karty książki.\nWygenerowano w HRL Books {datetime.now():%Y-%m-%d %H:%M}.\n")
    return buf.getvalue()


@router.get("/books/{book_id}/package/{channel}")
def package(book_id: str, channel: str, m: Membership = Depends(require("manage_distribution")),
            db: Session = Depends(get_db)):
    _channel(channel)
    book = _book(db, m.workspace_id, book_id)
    data = _package(db, db.get(Workspace, m.workspace_id), book, channel)
    audit(db, "package.exported", m.user_id, m.workspace_id, target=f"{book.id}:{channel}")
    db.commit()
    safe = "".join(c if c.isalnum() else "-" for c in book.title.lower())[:50].strip("-") or "ksiazka"
    return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{safe}-{channel}.zip"'})
