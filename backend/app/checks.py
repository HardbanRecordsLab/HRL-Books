"""Completeness and consistency checks for a title's metadata (FR-BOOK-03, FR-META-06, FR-META-08)."""
import re

from app.models import Book, BookContributor, Edition, Person, Workspace

FIELD_LABELS = {
    "desc_short": "krótki opis",
    "desc_long": "długi opis",
    "keywords": "słowa kluczowe",
    "categories": "kategorie",
    "author": "autor",
    "edition": "co najmniej jedno wydanie",
    "price": "cena wydania",
    "copyright_holder": "właściciel praw autorskich",
    "copyright_year": "rok praw autorskich",
}


def isbn_valid(raw: str) -> bool:
    s = re.sub(r"[\s-]", "", raw or "").upper()
    if re.fullmatch(r"\d{13}", s):
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(s[:12]))
        return (10 - total % 10) % 10 == int(s[12])
    if re.fullmatch(r"\d{9}[\dX]", s):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s))
        return total % 11 == 0
    return False


def run_checks(ws: Workspace, book: Book, contributors: list[tuple[BookContributor, Person]],
               editions: list[Edition]) -> dict:
    missing: list[str] = []
    if not book.desc_short.strip():
        missing.append("desc_short")
    if not book.desc_long.strip():
        missing.append("desc_long")
    if len(book.keywords or []) < 3:
        missing.append("keywords")
    if not book.categories:
        missing.append("categories")
    if not any(c.role == "author" for c, _ in contributors):
        missing.append("author")
    if not book.copyright_holder.strip():
        missing.append("copyright_holder")
    if not book.copyright_year:
        missing.append("copyright_year")
    if not editions:
        missing.append("edition")
    elif not any(e.prices for e in editions):
        missing.append("price")

    warnings: list[str] = []
    for e in editions:
        if e.isbn and not isbn_valid(e.isbn):
            warnings.append(f"Wydanie {e.format}: numer ISBN {e.isbn} ma błędną sumę kontrolną.")

    # Author identity rules: forbidden name variants anywhere in public-facing text.
    texts = {
        "tytuł": book.title, "podtytuł": book.subtitle, "krótki opis": book.desc_short, "długi opis": book.desc_long,
        "właściciel praw": book.copyright_holder,
    }
    for c, p in contributors:
        texts[f"osoba „{p.display_name}”"] = p.display_name
        texts[f"biogram {p.display_name}"] = f"{p.bio_short}\n{p.bio_long}"
    for rule in ws.identity_rules or []:
        canonical = rule.get("canonical", "")
        for variant in rule.get("forbidden", []):
            if not variant.strip():
                continue
            pat = re.compile(rf"(?<!\w){re.escape(variant)}(?!\w)", re.IGNORECASE)
            for where, text in texts.items():
                if text and pat.search(text):
                    warnings.append(f"Niedozwolona forma „{variant}” w polu: {where} (użyj „{canonical}”).")

    return {
        "complete": not missing and not warnings,
        "missing": [{"field": f, "label": FIELD_LABELS[f]} for f in missing],
        "warnings": warnings,
    }
