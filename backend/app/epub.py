"""EPUB 3 export of the manuscript with accessibility metadata (EPUB Accessibility 1.1, schema.org).

Born-accessible by construction: text only (the sanitizer allows no images in chapters), semantic headings,
language on every document, navigation document + NCX, logical reading order; the cover has alt text.
"""
import html
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Book, BookContributor, Chapter, ChapterVersion, Edition, Person, Workspace

MARC = {"author": "aut", "editor": "edt", "translator": "trl", "cover_designer": "cov", "illustrator": "ill", "narrator": "nrt"}
CSS = """body { font-family: serif; line-height: 1.5; margin: 0 5%; }
h1 { font-size: 1.6em; margin: 2em 0 1em; text-align: center; page-break-before: always; }
h2 { font-size: 1.3em; margin: 1.5em 0 .6em; } h3 { font-size: 1.1em; } h4 { font-size: 1em; font-style: italic; }
p { margin: 0; text-indent: 1.5em; text-align: justify; } h1 + p, h2 + p, h3 + p, h4 + p, hr + p { text-indent: 0; }
blockquote { margin: 1em 2em; font-style: italic; } hr { border: 0; text-align: center; margin: 1.2em 0; }
hr::after { content: "* * *"; } .title { text-align: center; margin-top: 30%; } .title p { text-indent: 0; text-align: center; }
.small { font-size: .85em; } .copyright p { text-indent: 0; margin-bottom: .6em; }
.cover { margin: 0; padding: 0; text-align: center; } .cover img { max-width: 100%; max-height: 100vh; }
"""


def _x(s: str) -> str:
    return html.escape(s or "", quote=True)


def to_xhtml(body: str) -> str:
    """Sanitized HTML -> well-formed XHTML (void elements closed)."""
    return re.sub(r"<(br|hr)>", r"<\1/>", body or "")


def _doc(lang: str, title: str, body: str, epub_type: str = "") -> str:
    et = f' epub:type="{epub_type}"' if epub_type else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">\n'
            f'<head><meta charset="UTF-8"/><title>{_x(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
            f'<body{et}>\n{body}\n</body>\n</html>\n')


def chapters_for(db: Session, book: Book, lang: str) -> list[tuple[str, str]]:
    out = []
    for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id, Chapter.language == lang).order_by(Chapter.position)):
        v = db.scalar(select(ChapterVersion).where(ChapterVersion.chapter_id == c.id)
                      .order_by(ChapterVersion.created_at.desc(), ChapterVersion.id.desc()).limit(1))
        if v and re.sub(r"<[^>]+>", "", v.body).strip():
            out.append((re.sub(r"\s*\[(PL|EN)\]$", "", c.title), v.body))
    return out


def build_epub(db: Session, book: Book, lang: str | None = None) -> bytes:
    lang = lang or book.language or "pl"
    chapters = chapters_for(db, book, lang)
    if not chapters:
        raise ValueError("Brak rozdziałów z tekstem w tym języku")
    ws = db.get(Workspace, book.workspace_id)
    people = list(db.execute(select(BookContributor, Person).join(Person, Person.id == BookContributor.person_id)
                             .where(BookContributor.book_id == book.id).order_by(BookContributor.position)).all())
    authors = [p.display_name for c, p in people if c.role == "author"]
    isbn = next((e.isbn for e in db.scalars(select(Edition).where(Edition.book_id == book.id, Edition.format == "ebook_epub")) if e.isbn), "")
    cover = db.scalar(select(Asset).where(Asset.book_id == book.id, Asset.kind == "cover",
                                          Asset.content_type.in_(("image/jpeg", "image/png"))).order_by(Asset.created_at.desc()).limit(1))
    cover_bytes = Path(cover.path).read_bytes() if cover and Path(cover.path).is_file() else None
    cover_ext = ".png" if cover and cover.content_type == "image/png" else ".jpg"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ident = f"urn:isbn:{isbn}" if isbn else f"urn:uuid:{book.id}"
    title_full = book.title + (f": {book.subtitle}" if book.subtitle else "")

    files: list[tuple[str, str, str, str]] = []  # (href, id, title, xhtml)
    if cover_bytes:
        files.append(("cover.xhtml", "cover", "Okładka", _doc(lang, book.title,
                      f'<section class="cover" epub:type="cover"><img src="images/cover{cover_ext}" alt="Okładka książki: {_x(title_full)}"/></section>')))
    by = "".join(f"<p>{_x(a)}</p>" for a in authors)
    files.append(("title.xhtml", "titlepage", "Strona tytułowa", _doc(lang, book.title,
                  f'<section class="title" epub:type="titlepage">{by}<h1>{_x(book.title)}</h1>'
                  + (f"<p>{_x(book.subtitle)}</p>" if book.subtitle else "") + "</section>")))
    rights = []
    if book.copyright_holder or book.copyright_year:
        rights.append(f"Copyright © {book.copyright_year or ''} {_x(book.copyright_holder)}".strip())
    rights += [f"{_x(MARC_PL.get(c.role, c.role))}: {_x(p.display_name)}" for c, p in people if c.role != "author"]
    if isbn:
        rights.append(f"ISBN {_x(isbn)}")
    if ws:
        rights.append(f"Wydawca: {_x(ws.name)}")
    if (book.ai_disclosure or {}).get("translation"):
        rights.append("Tłumaczenie przygotowane z pomocą narzędzi AI." if lang == "pl" else "Translated with the assistance of AI tools.")
    files.append(("copyright.xhtml", "copyright", "Prawa autorskie", _doc(lang, book.title,
                  '<section class="copyright small" epub:type="copyright-page">' + "".join(f"<p>{r}</p>" for r in rights) + "</section>")))
    for i, (t, body) in enumerate(chapters, 1):
        files.append((f"chap-{i:03d}.xhtml", f"chap{i:03d}", t, _doc(lang, t,
                      f'<section epub:type="chapter" aria-labelledby="h{i}"><h1 id="h{i}">{_x(t)}</h1>\n{to_xhtml(body)}\n</section>')))

    toc_label = "Spis treści" if lang == "pl" else "Contents"
    nav_items = "".join(f'<li><a href="{h}">{_x(t)}</a></li>' for h, _, t, _ in files if h.startswith("chap-"))
    first_chap = next(h for h, *_ in files if h.startswith("chap-"))
    nav = _doc(lang, toc_label,
               f'<nav epub:type="toc" id="toc" role="doc-toc"><h1>{toc_label}</h1><ol>{nav_items}</ol></nav>\n'
               f'<nav epub:type="landmarks" hidden=""><ol>'
               + (f'<li><a epub:type="cover" href="cover.xhtml">Okładka</a></li>' if cover_bytes else "")
               + f'<li><a epub:type="titlepage" href="title.xhtml">{_x(book.title)}</a></li>'
               f'<li><a epub:type="toc" href="nav.xhtml">{toc_label}</a></li>'
               f'<li><a epub:type="bodymatter" href="{first_chap}">{_x(chapters[0][0])}</a></li></ol></nav>')
    ncx_points = "".join(f'<navPoint id="np{n}" playOrder="{n}"><navLabel><text>{_x(t)}</text></navLabel><content src="{h}"/></navPoint>'
                         for n, (h, _, t, _) in enumerate([f for f in files if f[0].startswith("chap-")], 1))
    ncx = (f'<?xml version="1.0" encoding="UTF-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{lang}">'
           f'<head><meta name="dtb:uid" content="{_x(ident)}"/></head><docTitle><text>{_x(book.title)}</text></docTitle>'
           f'<navMap>{ncx_points}</navMap></ncx>\n')

    creators = "".join(f'<dc:creator id="cr{i}">{_x(a)}</dc:creator><meta refines="#cr{i}" property="role" scheme="marc:relators">aut</meta>'
                       for i, a in enumerate(authors))
    contributors = "".join(f'<dc:contributor id="ct{i}">{_x(p.display_name)}</dc:contributor>'
                           f'<meta refines="#ct{i}" property="role" scheme="marc:relators">{MARC.get(c.role, "ctb")}</meta>'
                           for i, (c, p) in enumerate((c, p) for c, p in people if c.role != "author"))
    features = ["structuralNavigation", "tableOfContents", "readingOrder", "displayTransformability"] + (["alternativeText"] if cover_bytes else [])
    a11y = "".join(f'<meta property="schema:accessibilityFeature">{f}</meta>' for f in features)
    a11y += ('<meta property="schema:accessMode">textual</meta>'
             + ('<meta property="schema:accessMode">visual</meta>' if cover_bytes else "")
             + '<meta property="schema:accessModeSufficient">textual</meta>'
             '<meta property="schema:accessibilityHazard">none</meta>'
             '<meta property="schema:accessibilitySummary">Publikacja tekstowa z semantyczną strukturą nagłówków, spisem treści '
             'i logiczną kolejnością czytania. Tekst można powiększać i zmieniać jego krój. Okładka ma opis alternatywny. '
             'Brak treści migających, dźwięku i animacji.</meta>'
             '<meta property="dcterms:conformsTo">EPUB Accessibility 1.1 - WCAG 2.1 Level AA</meta>'
             f'<meta property="a11y:certifiedBy">{_x(ws.name if ws else "HRL Books")}</meta>')
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="css" href="style.css" media-type="text/css"/>']
    if cover_bytes:
        manifest.append(f'<item id="cover-image" href="images/cover{cover_ext}" media-type="{cover.content_type}" properties="cover-image"/>')
    manifest += [f'<item id="{i}" href="{h}" media-type="application/xhtml+xml"/>' for h, i, _, _ in files]
    spine = "".join(f'<itemref idref="{i}"/>' for h, i, _, _ in files if h != "copyright.xhtml")
    spine = spine.replace('<itemref idref="chap001"/>', '<itemref idref="nav"/><itemref idref="chap001"/>', 1)
    spine += '<itemref idref="copyright"/>'
    opf = (f'<?xml version="1.0" encoding="UTF-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang="{lang}">\n'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
           f'<dc:identifier id="pub-id">{_x(ident)}</dc:identifier><dc:title>{_x(title_full)}</dc:title><dc:language>{lang}</dc:language>'
           f'{creators}{contributors}'
           + (f"<dc:publisher>{_x(ws.name)}</dc:publisher>" if ws else "")
           + (f"<dc:description>{_x(book.desc_short)}</dc:description>" if book.desc_short else "")
           + (f"<dc:rights>Copyright © {book.copyright_year or ''} {_x(book.copyright_holder)}</dc:rights>" if book.copyright_holder else "")
           + "".join(f"<dc:subject>{_x(k)}</dc:subject>" for k in (book.keywords or [])[:20])
           + f'<meta property="dcterms:modified">{modified}</meta>{a11y}\n'
           + ('<meta name="cover" content="cover-image"/>' if cover_bytes else "")
           + f'</metadata>\n<manifest>{"".join(manifest)}</manifest>\n<spine toc="ncx">{spine}</spine>\n</package>\n')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)  # must be first, uncompressed
        z.writestr("META-INF/container.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>\n',
                   compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", CSS, compress_type=zipfile.ZIP_DEFLATED)
        if cover_bytes:
            z.writestr(f"OEBPS/images/cover{cover_ext}", cover_bytes, compress_type=zipfile.ZIP_STORED)
        for h, _, _, doc in files:
            z.writestr(f"OEBPS/{h}", doc, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


MARC_PL = {"editor": "Redakcja", "translator": "Tłumaczenie", "cover_designer": "Projekt okładki", "illustrator": "Ilustracje", "narrator": "Lektor"}
