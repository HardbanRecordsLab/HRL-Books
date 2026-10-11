"""Public bookshop pages (no login): workspace catalog and a page per title with store buttons and merch."""
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Asset, Book, BookContributor, Edition, Listing, Person, Product, Workspace
from app.routers.assets import asset_public_url
from app.routers.shop import product_out

router = APIRouter(prefix="/api/v1/public/w", tags=["public"])

STORES = [("amazon", "Amazon"), ("play.google", "Google Play"), ("kobo", "Kobo"), ("empik", "Empik"), ("legimi", "Legimi"),
          ("woblink", "Woblink"), ("virtualo", "Virtualo"), ("publio", "Publio"), ("apple", "Apple Books"),
          ("barnesandnoble", "Barnes & Noble"), ("lulu", "Lulu"), ("ebookpoint", "Ebookpoint"), ("audioteka", "Audioteka"),
          ("storytel", "Storytel"), ("bookbeat", "BookBeat")]
FORMATS = {"ebook_epub": "E-book (EPUB)", "ebook_pdf": "E-book (PDF)", "paperback": "Książka w miękkiej oprawie",
           "hardcover": "Książka w twardej oprawie", "audiobook": "Audiobook"}
ROLE_PL = {"author": "Autor", "editor": "Redakcja", "translator": "Tłumaczenie", "cover_designer": "Okładka",
           "illustrator": "Ilustracje", "narrator": "Lektor"}


def store_label(url: str) -> str:
    host = (urlparse(url).hostname or "").removeprefix("www.")
    return next((label for key, label in STORES if key in host), host or "Sklep")


def _ws(db: Session, slug: str) -> Workspace:
    w = db.scalar(select(Workspace).where(Workspace.slug == slug, Workspace.status == "active"))
    if w is None:
        raise HTTPException(404, "Nie znaleziono")
    return w


def _cover(db: Session, book: Book) -> str:
    a = db.scalar(select(Asset).where(Asset.book_id == book.id, Asset.kind == "cover", Asset.content_type.like("image/%"))
                  .order_by(Asset.created_at.desc()).limit(1))
    return asset_public_url(a) if a else ""


def _people(db: Session, book: Book):
    return list(db.execute(select(BookContributor, Person).join(Person, Person.id == BookContributor.person_id)
                           .where(BookContributor.book_id == book.id).order_by(BookContributor.position)).all())


def _card(db: Session, ws: Workspace, b: Book) -> dict:
    return {"slug": b.slug, "title": b.title, "subtitle": b.subtitle, "desc_short": b.desc_short, "cover_url": _cover(db, b),
            "authors": [p.display_name for c, p in _people(db, b) if c.role == "author"], "series": b.series_name,
            "series_volume": b.series_volume}


@router.get("/{ws_slug}")
def catalog(ws_slug: str, db: Session = Depends(get_db)):
    ws = _ws(db, ws_slug)
    books = db.scalars(select(Book).where(Book.workspace_id == ws.id, Book.public.is_(True), Book.deleted_at.is_(None))
                       .order_by(Book.series_name, Book.series_volume, Book.title))
    books = list(books)
    titles = {b.id: b.title for b in books}
    products = db.scalars(select(Product).where(Product.workspace_id == ws.id, Product.active.is_(True)).order_by(Product.created_at.desc()))
    return {"name": ws.name, "slug": ws.slug, "books": [_card(db, ws, b) for b in books],
            # merch ("nie tylko książki"): standalone products and those tied to a public title
            "products": [{k: o[k] for k in ("id", "title", "catalog_label", "design_url", "price", "currency")}
                         | {"book_title": titles.get(p.book_id, ""), "url": f"{get_settings().APP_URL}/sklep/{p.id}"}
                         for p in products if not p.book_id or p.book_id in titles
                         for o in (product_out(db, p),)]}


@router.get("/{ws_slug}/{slug}")
def book_page(ws_slug: str, slug: str, db: Session = Depends(get_db)):
    ws = _ws(db, ws_slug)
    b = db.scalar(select(Book).where(Book.workspace_id == ws.id, Book.slug == slug, Book.public.is_(True), Book.deleted_at.is_(None)))
    if b is None:
        raise HTTPException(404, "Nie znaleziono")
    links, seen = [], set()
    published = db.scalars(select(Listing).where(Listing.book_id == b.id, Listing.status == "published", Listing.url != ""))
    for url in [x.get("url", "") for x in (b.store_links or [])] + [x.url for x in published]:
        if url.startswith(("https://", "http://")) and url not in seen:
            seen.add(url)
            links.append({"url": url, "label": store_label(url)})
    people = _people(db, b)
    products = db.scalars(select(Product).where(Product.book_id == b.id, Product.active.is_(True)).order_by(Product.created_at))
    return {
        **_card(db, ws, b), "publisher": ws.name, "url": f"{get_settings().APP_URL}/ksiegarnia/{ws.slug}/{b.slug}", "language": b.language, "desc_long": b.desc_long,
        "authors_bio": [{"name": p.display_name, "bio": p.bio_long or p.bio_short} for c, p in people if c.role == "author"],
        "contributors": [{"name": p.display_name, "role": ROLE_PL.get(c.role, c.role)} for c, p in people if c.role != "author"],
        "editions": [{"format": FORMATS.get(e.format, e.format), "release_date": e.release_date, "isbn": e.isbn, "pages": e.pages}
                     for e in db.scalars(select(Edition).where(Edition.book_id == b.id).order_by(Edition.created_at))],
        "stores": links,
        "products": [{k: o[k] for k in ("id", "title", "catalog_label", "design_url", "price", "currency")}
                     | {"url": f"{get_settings().APP_URL}/sklep/{o['id']}"} for o in (product_out(db, p) for p in products)],
        "ai_disclosure": b.ai_disclosure,
        "more": [_card(db, ws, x) for x in db.scalars(
            select(Book).where(Book.workspace_id == ws.id, Book.public.is_(True), Book.deleted_at.is_(None), Book.id != b.id)
            .order_by(Book.created_at.desc()).limit(4))],
    }
