"""Royalties (module ROY): import store reports, match rows to titles, revenue per title / store / month.

Amounts stay in the report currency (no FX guesses); totals are shown per currency.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.audit import audit
from app.channels import CHANNELS
from app.db import get_db
from app.deps import require
from app.models import Book, Edition, Membership, RoyaltyImport, RoyaltyLine
from app.royalties import FIELDS, ReportError, normalize, read_table

router = APIRouter(prefix="/api/v1/workspaces/{ws}/royalties", tags=["royalties"])
CHANNEL_LABELS = {k: v["name"] for k, v in CHANNELS.items()} | {
    "empik": "Empik Go", "legimi": "Legimi", "woblink": "Woblink", "apple": "Apple Books", "publio": "Publio",
    "audioteka": "Audioteka", "storytel": "Storytel", "own_shop": "Sprzedaż własna", "other": "Inne"}


class AssignIn(BaseModel):
    raw_title: str
    book_id: str | None


def _key(title: str) -> str:
    return re.sub(r"[^0-9a-ząćęłńóśźż]", "", title.casefold())


def _matcher(db: Session, ws_id: str):
    books = list(db.scalars(select(Book).where(Book.workspace_id == ws_id, Book.deleted_at.is_(None))))
    by_title = {}
    for b in books:
        by_title.setdefault(_key(b.title), b.id)
        by_title.setdefault(_key(f"{b.title}{b.subtitle}"), b.id)
        by_title.setdefault(_key(f"{b.title}: {b.subtitle}"), b.id)
    by_id = {e.isbn: e.book_id for e in db.scalars(select(Edition).where(Edition.workspace_id == ws_id)) if e.isbn}
    links = [(b.id, " ".join(link.get("url", "") for link in (b.store_links or []))) for b in books]
    learned = dict(db.execute(select(RoyaltyLine.raw_title, RoyaltyLine.book_id)
                              .where(RoyaltyLine.workspace_id == ws_id, RoyaltyLine.book_id.is_not(None))).all())

    def match(title: str, raw_id: str) -> str | None:
        if raw_id:
            if raw_id in by_id:
                return by_id[raw_id]
            if len(raw_id) >= 8:
                for book_id, urls in links:
                    if raw_id in urls:
                        return book_id
        if title in learned:
            return learned[title]
        k = _key(title)
        return by_title.get(k) or by_title.get(_key(re.split(r"[:(\[]", title)[0]))
    return match


@router.post("/import", status_code=201)
async def import_report(file: UploadFile = File(...), channel: str = Form(...), period: str = Form(""),
                        currency: str = Form("PLN"), mapping: str = Form(""),
                        m: Membership = Depends(require("royalties")), db: Session = Depends(get_db)):
    if channel not in CHANNEL_LABELS:
        raise HTTPException(422, "Nieznany sklep")
    if period and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise HTTPException(422, "Miesiąc w formacie RRRR-MM")
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "Plik większy niż 20 MB")
    try:
        cols = {k: int(v) for k, v in json.loads(mapping).items() if k in FIELDS and v not in ("", None)} if mapping else None
        rows = normalize(read_table(data, file.filename or ""), cols, period or None, currency.upper()[:3] or "PLN")
    except ReportError as e:
        raise HTTPException(422, {"message": str(e), "headers": e.headers}) from e
    except (ValueError, KeyError, OSError) as e:
        raise HTTPException(422, {"message": "Nie udało się odczytać pliku (CSV lub XLSX).", "headers": []}) from e

    imp = RoyaltyImport(workspace_id=m.workspace_id, channel=channel, filename=(file.filename or "")[:300], created_by=m.user_id)
    db.add(imp)
    db.flush()
    match = _matcher(db, m.workspace_id)
    existing = set(db.scalars(select(RoyaltyLine.row_hash).where(RoyaltyLine.workspace_id == m.workspace_id, RoyaltyLine.channel == channel)))
    seen: Counter = Counter()
    added = dupes = 0
    for r in rows:
        base = "|".join(str(r[k]) for k in ("period", "title", "id", "market", "units", "amount", "currency"))
        seen[base] += 1  # identical rows inside one report are real separate sales
        h = hashlib.sha256(f"{channel}|{base}|{seen[base]}".encode()).hexdigest()
        if h in existing:
            dupes += 1
            continue
        existing.add(h)
        db.add(RoyaltyLine(workspace_id=m.workspace_id, import_id=imp.id, book_id=match(r["title"], r["id"]), channel=channel,
                           period=r["period"], raw_title=r["title"], raw_id=r["id"], market=r["market"], units=r["units"],
                           amount=r["amount"], currency=r["currency"], row_hash=h))
        added += 1
    imp.rows, imp.duplicates = added, dupes
    audit(db, "royalties.imported", m.user_id, m.workspace_id, target=imp.id, rows=added, duplicates=dupes)
    db.commit()
    return {"import_id": imp.id, "rows": added, "duplicates": dupes}


@router.get("")
def summary(year: str = "", book_id: str = "", m: Membership = Depends(require("royalties")), db: Session = Depends(get_db)):
    q = select(RoyaltyLine).where(RoyaltyLine.workspace_id == m.workspace_id)
    if re.fullmatch(r"\d{4}", year):
        q = q.where(RoyaltyLine.period.like(f"{year}-%"))
    if book_id:
        q = q.where(RoyaltyLine.book_id == book_id)
    lines = list(db.scalars(q))
    titles = dict(db.execute(select(Book.id, Book.title).where(Book.workspace_id == m.workspace_id)).all())

    def bucket():
        return {"units": 0, "amounts": defaultdict(int)}
    totals, by_book, by_channel, by_month, unmatched = bucket(), defaultdict(bucket), defaultdict(bucket), defaultdict(bucket), defaultdict(bucket)
    for ln in lines:
        groups = [totals, by_channel[ln.channel], by_month[ln.period]]
        groups.append(by_book[ln.book_id] if ln.book_id else unmatched[ln.raw_title])
        for g in groups:
            g["units"] += ln.units
            g["amounts"][ln.currency] += ln.amount

    def money(b):
        return {"units": b["units"], "amounts": {c: round(a / 100, 2) for c, a in sorted(b["amounts"].items())}}
    imports = db.scalars(select(RoyaltyImport).where(RoyaltyImport.workspace_id == m.workspace_id)
                         .order_by(RoyaltyImport.created_at.desc()).limit(50))
    years = sorted({p[:4] for p in db.scalars(select(RoyaltyLine.period).where(RoyaltyLine.workspace_id == m.workspace_id).distinct())}, reverse=True)
    return {
        "years": years, "totals": money(totals),
        "by_book": sorted(({"book_id": k, "title": titles.get(k, "?"), **money(v)} for k, v in by_book.items()), key=lambda x: -x["units"]),
        "by_channel": [{"channel": k, "label": CHANNEL_LABELS.get(k, k), **money(v)} for k, v in sorted(by_channel.items())],
        "by_month": [{"period": k, **money(v)} for k, v in sorted(by_month.items())],
        "unmatched": sorted(({"raw_title": k, **money(v)} for k, v in unmatched.items()), key=lambda x: -x["units"]),
        "imports": [{"id": i.id, "channel": i.channel, "label": CHANNEL_LABELS.get(i.channel, i.channel), "filename": i.filename,
                     "rows": i.rows, "duplicates": i.duplicates, "created_at": i.created_at} for i in imports],
        "channels": CHANNEL_LABELS,
    }


@router.post("/assign")
def assign(body: AssignIn, m: Membership = Depends(require("royalties")), db: Session = Depends(get_db)):
    """Link every row with this report title to a book (or unlink with book_id=null); future imports reuse it."""
    if body.book_id and db.scalar(select(Book.id).where(Book.id == body.book_id, Book.workspace_id == m.workspace_id)) is None:
        raise HTTPException(404, "Nie znaleziono tytułu")
    n = db.execute(update(RoyaltyLine).where(RoyaltyLine.workspace_id == m.workspace_id, RoyaltyLine.raw_title == body.raw_title)
                   .values(book_id=body.book_id)).rowcount
    db.commit()
    return {"updated": n}


@router.delete("/imports/{import_id}", status_code=204)
def delete_import(import_id: str, m: Membership = Depends(require("royalties")), db: Session = Depends(get_db)):
    imp = db.scalar(select(RoyaltyImport).where(RoyaltyImport.id == import_id, RoyaltyImport.workspace_id == m.workspace_id))
    if imp is None:
        raise HTTPException(404, "Nie znaleziono")
    db.execute(delete(RoyaltyLine).where(RoyaltyLine.import_id == imp.id))
    db.delete(imp)
    audit(db, "royalties.import_deleted", m.user_id, m.workspace_id, target=import_id)
    db.commit()
