"""Google Books API (v1) — find already-published titles and pull their metadata into HRL Books.

Read-only public data (title, authors, description, ISBN, cover, store link). Needs GOOGLE_BOOKS_API_KEY:
anonymous calls share one global daily quota that is usually exhausted.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from app.config import get_settings
from app.integrations import UA, IntegrationError
from app.text import html_to_text

API = "https://www.googleapis.com/books/v1"


def configured() -> bool:
    return bool(get_settings().GOOGLE_BOOKS_API_KEY)


def _get(path: str, params: dict) -> dict:
    key = get_settings().GOOGLE_BOOKS_API_KEY
    if not key:
        raise IntegrationError("Brak klucza Google Books API (GOOGLE_BOOKS_API_KEY)")
    url = f"{API}{path}?{urllib.parse.urlencode({**params, 'key': key})}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(3):  # Google Books answers 503 now and then — retry briefly
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            _raise(e)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise IntegrationError("Google Books nie odpowiada") from e


def _raise(e: urllib.error.HTTPError):
    if e.code == 429:
        raise IntegrationError("Wyczerpany dzienny limit Google Books API") from e
    if e.code == 404:
        raise IntegrationError("Nie znaleziono w Google Books") from e
    if e.code in (500, 502, 503):
        raise IntegrationError("Google Books chwilowo nie odpowiada — spróbuj za kilka minut") from e
    raise IntegrationError(f"Google Books HTTP {e.code}") from e


def _cover(links: dict) -> str:
    for size in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
        if links.get(size):
            url = links[size].replace("http://", "https://").replace("&edge=curl", "")
            return re.sub(r"([?&])zoom=\d", r"\1zoom=0", url) if size in ("thumbnail", "smallThumbnail") else url
    return ""


def _date(d: str) -> tuple[str, int | None]:
    """'2024-05-12' -> ('2024-05-12', 2024); '2024' -> ('', 2024)."""
    m = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", d or "")
    if not m:
        return "", None
    full = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m.group(3) else ""
    return full, int(m.group(1))


def normalize(item: dict) -> dict:
    v, s = item.get("volumeInfo", {}), item.get("saleInfo", {})
    ids = {i.get("type"): i.get("identifier") for i in v.get("industryIdentifiers", [])}
    release, year = _date(v.get("publishedDate", ""))
    desc = html_to_text(v.get("description", ""))
    return {
        "id": item.get("id"),
        "title": (v.get("title") or "").strip(),
        "subtitle": (v.get("subtitle") or "").strip(),
        "authors": [a.strip() for a in v.get("authors", []) if a.strip()],
        "publisher": v.get("publisher", ""),
        "published_date": v.get("publishedDate", ""),
        "release_date": release,
        "year": year,
        "description": desc,
        "isbn13": ids.get("ISBN_13", ""),
        "isbn10": ids.get("ISBN_10", ""),
        "pages": v.get("pageCount"),
        "categories": v.get("categories", []),
        "language": (v.get("language") or "")[:10],
        "cover_url": _cover(v.get("imageLinks", {})),
        "is_ebook": bool(s.get("isEbook")),
        "for_sale": s.get("saleability") == "FOR_SALE",
        "store_url": s.get("buyLink") or v.get("infoLink") or v.get("canonicalVolumeLink") or "",
        "price": (s.get("listPrice") or {}).get("amount"),
        "currency": (s.get("listPrice") or {}).get("currencyCode"),
    }


def search(q: str, limit: int = 20) -> list[dict]:
    q = q.strip()
    digits = re.sub(r"[^0-9Xx]", "", q)
    if len(digits) in (10, 13) and len(digits) >= len(q) - 4:  # looks like an ISBN
        q = f"isbn:{digits}"
    data = _get("/volumes", {"q": q, "maxResults": max(1, min(limit, 40)), "printType": "books"})
    return [normalize(i) for i in data.get("items", [])]


def volume(volume_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,40}", volume_id or ""):
        raise IntegrationError("Nieprawidłowy identyfikator Google Books")
    return normalize(_get(f"/volumes/{volume_id}", {}))


def fetch_cover(url: str) -> tuple[bytes, str] | None:
    """Download a cover image (JPEG/PNG, max 5 MB). Only Google's book-image hosts are allowed."""
    host = urllib.parse.urlparse(url).hostname or ""
    if not url.startswith("https://") or not (host.endswith("books.google.com") or host.endswith("googleusercontent.com")):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(5 * 1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError):
        return None
    if len(data) > 5 * 1024 * 1024:
        return None
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    return None
