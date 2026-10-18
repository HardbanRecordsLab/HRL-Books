"""Publishing centre (module PUB): the publisher's ISBN pool, readiness of every title for every store, one-click
preparation and bulk packages, and automatic verification of listing URLs. Goal: type nothing twice."""
import io
import json
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.channels import CHANNELS, channel_from_url
from app.checks import run_checks
from app.db import get_db
from app.deps import require
from app.http import attachment
from app.isbn import hyphenate_pl, parse_isbn_list
from app.models import Asset, Book, Edition, IsbnPool, Listing, Membership, Workspace, utcnow
from app.routers import distribution as dist

router = APIRouter(prefix="/api/v1/workspaces/{ws}", tags=["publishing"])

# one ISBN per format: an e-book and a paperback of the same title never share a number
ISBN_FORMATS = ("ebook_epub", "ebook_pdf", "paperback", "hardcover", "audiobook")


class IsbnImportIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    note: str = Field(default="", max_length=200)


class AssignIn(BaseModel):
    edition_id: str | None = None      # one edition; omitted = every edition of the title that has no ISBN


def _pool_counts(db: Session, ws_id: str) -> dict:
    total = db.scalar(select(func.count()).select_from(IsbnPool).where(IsbnPool.workspace_id == ws_id)) or 0
    used = db.scalar(select(func.count()).select_from(IsbnPool).where(IsbnPool.workspace_id == ws_id, IsbnPool.edition_id.is_not(None))) or 0
    return {"total": total, "used": used, "free": total - used}


def _next_free(db: Session, ws_id: str) -> IsbnPool | None:
    return db.scalar(select(IsbnPool).where(IsbnPool.workspace_id == ws_id, IsbnPool.edition_id.is_(None))
                     .order_by(IsbnPool.isbn).limit(1))


@router.get("/isbn-pool")
def isbn_pool(m: Membership = Depends(require("read_distribution")), db: Session = Depends(get_db)):
    rows = db.execute(select(IsbnPool, Edition, Book).outerjoin(Edition, Edition.id == IsbnPool.edition_id)
                      .outerjoin(Book, Book.id == Edition.book_id)
                      .where(IsbnPool.workspace_id == m.workspace_id).order_by(IsbnPool.isbn)).all()
    return {**_pool_counts(db, m.workspace_id), "items": [
        {"isbn": p.isbn, "display": hyphenate_pl(p.isbn), "note": p.note, "edition_id": p.edition_id,
         "format": e.format if e else "", "title": b.title if b else ""} for p, e, b in rows]}


@router.post("/isbn-pool/import")
def isbn_import(body: IsbnImportIn, m: Membership = Depends(require("manage_distribution")), db: Session = Depends(get_db)):
    valid, bad = parse_isbn_list(body.text)
    existing = set(db.scalars(select(IsbnPool.isbn).where(IsbnPool.workspace_id == m.workspace_id)))
    # a number already written on an edition counts as taken, even if it never went through the pool
    on_editions = set(db.scalars(select(Edition.isbn).where(Edition.workspace_id == m.workspace_id, Edition.isbn != "")))
    added = 0
    for n in valid:
        if n in existing:
            continue
        ed = db.scalar(select(Edition).where(Edition.workspace_id == m.workspace_id, Edition.isbn.in_([n, hyphenate_pl(n)])))
        db.add(IsbnPool(workspace_id=m.workspace_id, isbn=n, note=body.note.strip(), edition_id=ed.id if ed else None))
        added += 1
    audit(db, "isbn.imported", m.user_id, m.workspace_id, added=added, rejected=len(bad))
    db.commit()
    return {"added": added, "duplicates": len(valid) - added, "rejected": bad, **_pool_counts(db, m.workspace_id),
            "already_on_editions": len([n for n in valid if n in on_editions])}


@router.post("/books/{book_id}/isbn/assign")
def assign_isbn(book_id: str, body: AssignIn | None = None, m: Membership = Depends(require("manage_distribution")),
                db: Session = Depends(get_db)):
    book = dist._book(db, m.workspace_id, book_id)
    editions = list(db.scalars(select(Edition).where(Edition.book_id == book.id).order_by(Edition.created_at)))
    if body and body.edition_id:
        editions = [e for e in editions if e.id == body.edition_id]
        if not editions:
            raise HTTPException(404, "Nie znaleziono wydania")
    assigned, skipped = [], []
    for e in editions:
        if e.isbn or e.format not in ISBN_FORMATS:
            continue
        nxt = _next_free(db, m.workspace_id)
        if nxt is None:
            skipped.append(e.format)
            continue
        nxt.edition_id = e.id
        e.isbn = hyphenate_pl(nxt.isbn)
        db.flush()                       # sessions here do not autoflush: the next lookup must see this row as taken
        assigned.append({"format": e.format, "isbn": e.isbn})
    audit(db, "isbn.assigned", m.user_id, m.workspace_id, target=book.id, count=len(assigned))
    db.commit()
    return {"assigned": assigned, "pool_empty_for": skipped, **_pool_counts(db, m.workspace_id)}


@router.delete("/isbn-pool/{isbn}", status_code=204)
def release_isbn(isbn: str, m: Membership = Depends(require("manage_distribution")), db: Session = Depends(get_db)):
    """Take the number off its edition and return it to the pool (e.g. assigned to the wrong format)."""
    p = db.scalar(select(IsbnPool).where(IsbnPool.workspace_id == m.workspace_id, IsbnPool.isbn == isbn))
    if p is None:
        raise HTTPException(404, "Nie ma takiego numeru w puli")
    if p.edition_id:
        e = db.get(Edition, p.edition_id)
        if e and e.isbn in (p.isbn, hyphenate_pl(p.isbn)):
            e.isbn = ""
        p.edition_id = None
    audit(db, "isbn.released", m.user_id, m.workspace_id, target=isbn)
    db.commit()


# ───────────────────────────── readiness ─────────────────────────────

def _cover(db: Session, book_id: str) -> Asset | None:
    return db.scalar(select(Asset).where(Asset.book_id == book_id, Asset.kind == "cover").order_by(Asset.created_at.desc()))


def _gaps(db: Session, ws: Workspace, book: Book) -> dict:
    editions = list(db.scalars(select(Edition).where(Edition.book_id == book.id)))
    base = run_checks(ws, book, dist._contributors(db, book), editions)
    per_channel = {k: dist.channel_issues(book, editions, k) for k in CHANNELS}
    gaps = []
    if _cover(db, book.id) is None:
        gaps.append("brak okładki")
    gaps += [x["label"] for x in base["missing"]]
    if any(not e.isbn and e.format in ("paperback", "hardcover") for e in editions):
        gaps.append("brak ISBN dla druku")
    return {"editions": editions, "base_missing": base["missing"], "gaps": gaps, "per_channel": per_channel}


@router.get("/publishing")
def publishing_overview(m: Membership = Depends(require("read_distribution")), db: Session = Depends(get_db)):
    ws = db.get(Workspace, m.workspace_id)
    books = list(db.scalars(select(Book).where(Book.workspace_id == m.workspace_id, Book.deleted_at.is_(None)).order_by(Book.title)))
    listings = {(l.book_id, l.channel): l for l in db.scalars(select(Listing).where(Listing.workspace_id == m.workspace_id))}
    rows = []
    for b in books:
        g = _gaps(db, ws, b)
        cells = {}
        for key in CHANNELS:
            lst = listings.get((b.id, key))
            status = lst.status if lst else dist._implicit_status(b, key)
            cells[key] = {"status": status, "issues": g["per_channel"][key], "can_prepare": not g["per_channel"][key] and status == "not_ready"}
        rows.append({"book_id": b.id, "title": b.title, "language": b.language, "public": b.public, "kdp_select": b.kdp_select,
                     "has_cover": _cover(db, b.id) is not None, "gaps": g["gaps"],
                     "isbn_missing": [e.format for e in g["editions"] if not e.isbn and e.format in ISBN_FORMATS],
                     "cells": cells})
    return {"channels": [{"key": k, "name": v["name"], "panel_url": v["panel_url"]} for k, v in CHANNELS.items()],
            "isbn": _pool_counts(db, m.workspace_id), "rows": rows}


@router.post("/publishing/prepare")
def prepare_all(book_id: str | None = None, m: Membership = Depends(require("manage_distribution")), db: Session = Depends(get_db)):
    """Everything the platform can do without a store login: give every missing edition an ISBN from the pool and move
    every listing that has no open issues from 'not ready' to 'ready to send'."""
    ws = db.get(Workspace, m.workspace_id)
    q = select(Book).where(Book.workspace_id == m.workspace_id, Book.deleted_at.is_(None))
    if book_id:
        q = q.where(Book.id == book_id)
    done = {"isbn_assigned": 0, "marked_ready": 0, "blocked": []}
    for b in db.scalars(q):
        for e in db.scalars(select(Edition).where(Edition.book_id == b.id).order_by(Edition.created_at)):
            if not e.isbn and e.format in ISBN_FORMATS:
                nxt = _next_free(db, m.workspace_id)
                if nxt is None:
                    break
                nxt.edition_id = e.id
                e.isbn = hyphenate_pl(nxt.isbn)
                db.flush()
                done["isbn_assigned"] += 1
        db.flush()
        g = _gaps(db, ws, b)
        for key in CHANNELS:
            lst = db.scalar(select(Listing).where(Listing.book_id == b.id, Listing.channel == key, Listing.market == "all"))
            status = lst.status if lst else dist._implicit_status(b, key)
            if status != "not_ready":
                continue
            issues = g["per_channel"][key] + ([f"brak: {', '.join(g['gaps'])}"] if g["gaps"] else [])
            if issues:
                done["blocked"].append({"title": b.title, "channel": CHANNELS[key]["name"], "why": issues[0]})
                continue
            if lst is None:
                lst = Listing(workspace_id=m.workspace_id, book_id=b.id, channel=key, market="all")
                db.add(lst)
            lst.status = "ready"
            lst.updated_at = utcnow()
            done["marked_ready"] += 1
    audit(db, "publishing.prepared", m.user_id, m.workspace_id, **{k: v for k, v in done.items() if k != "blocked"})
    db.commit()
    return done


# ───────────────────────────── bulk packages ─────────────────────────────

@router.get("/publishing/package")
def package_all(book_id: str | None = None, channel: str | None = None,
                m: Membership = Depends(require("manage_distribution")), db: Session = Depends(get_db)):
    """One ZIP: <title>/<store>/ with metadata, description, EPUB, cover and instructions for each store — for one title
    or for the whole catalogue, for one store or for all of them."""
    ws = db.get(Workspace, m.workspace_id)
    q = select(Book).where(Book.workspace_id == m.workspace_id, Book.deleted_at.is_(None)).order_by(Book.title)
    if book_id:
        q = q.where(Book.id == book_id)
    if channel and channel not in CHANNELS:
        raise HTTPException(404, "Nieznany kanał")
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for b in db.scalars(q):
            editions = list(db.scalars(select(Edition).where(Edition.book_id == b.id)))
            safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in b.title).strip()[:80] or b.id
            for key in ([channel] if channel else list(CHANNELS)):
                if not any(e.format in CHANNELS[key]["formats"] for e in editions):
                    continue
                data = dist._package(db, ws, b, key)
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    for name in inner.namelist():
                        z.writestr(f"{safe}/{key}/{name}", inner.read(name))
                count += 1
        if count == 0:
            z.writestr("PUSTO.txt", "Żaden tytuł nie ma jeszcze wydania w formacie obsługiwanym przez wybrany sklep. "
                                    "Dodaj wydanie (EPUB / druk) w karcie książki.")
    audit(db, "package.bulk_exported", m.user_id, m.workspace_id, packages=count)
    db.commit()
    name = "HRL Books - paczki publikacyjne"
    return StreamingResponse(io.BytesIO(buf.getvalue()), media_type="application/zip", headers={
        "Content-Disposition": attachment(name, f" ({count}).zip", f"-{count}.zip")})


# ───────────────────────────── verification ─────────────────────────────

def _fetch_ok(url: str) -> bool:
    """True when the store page answers 200. Stores that block bots (403/429/503) are 'unknown', not 'missing'."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (HRL Books link check)"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        if e.code in (403, 429, 503):
            raise
        return False
    except Exception:
        return False


@router.post("/publishing/verify")
def verify_listings(m: Membership = Depends(require("manage_distribution")), db: Session = Depends(get_db)):
    """Open the URLs of listings that were sent / are in review and mark them published when the store page is live.
    Also reconciles the status of titles whose store links were imported."""
    checked = published = unknown = 0
    changed = []
    for lst in db.scalars(select(Listing).where(Listing.workspace_id == m.workspace_id, Listing.status.in_(["sent", "in_review"]),
                                                Listing.url != "")):
        checked += 1
        try:
            if _fetch_ok(lst.url):
                lst.status = "published"
                lst.published_at = lst.published_at or utcnow()
                lst.updated_at = utcnow()
                published += 1
                changed.append({"book_id": lst.book_id, "channel": lst.channel})
        except urllib.error.HTTPError:
            unknown += 1
    audit(db, "publishing.verified", m.user_id, m.workspace_id, checked=checked, published=published)
    db.commit()
    return {"checked": checked, "published": published, "unknown": unknown, "changed": changed}
