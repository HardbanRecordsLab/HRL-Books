"""Manuscript text helpers: allow-list HTML sanitizer, plain-text stats, DOCX/TXT import split into chapters."""
import html
import io
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

ALLOWED_TAGS = {"p", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "s", "ul", "ol", "li", "blockquote", "br", "hr",
                "a", "sup", "sub", "code", "pre"}
VOID = {"br", "hr"}


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip = 0  # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "iframe", "object"):
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if not re.match(r"^(https?://|mailto:)", href, re.I):
                return
            self.out.append(f'<a href="{html.escape(href, quote=True)}" rel="noopener noreferrer">')
        else:
            self.out.append(f"<{tag}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "iframe", "object"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_html(raw: str) -> str:
    s = _Sanitizer()
    s.feed(raw or "")
    s.close()
    return s.result()


def html_to_text(body: str) -> str:
    text = re.sub(r"<(br|/p|/h[2-4]|/li|/blockquote)>", "\n", body or "")
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def stats(body: str) -> tuple[int, int]:
    text = html_to_text(body)
    return len(re.findall(r"\w+", text)), len(text)


# ---- import -----------------------------------------------------------------------------------------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING1 = re.compile(r"^(heading1|nag[łl]?wek1|titre1|title)$", re.I)
HEADING2 = re.compile(r"^(heading[23]|nag[łl]?wek[23])$", re.I)


def _runs(p) -> str:
    parts = []
    for r in p.iter(f"{W}r"):
        text = "".join(t.text or "" for t in r.iter(f"{W}t"))
        if not text:
            if r.find(f"{W}br") is not None:
                parts.append("<br>")
            continue
        text = html.escape(text, quote=False)
        rpr = r.find(f"{W}rPr")
        if rpr is not None and rpr.find(f"{W}b") is not None:
            text = f"<strong>{text}</strong>"
        if rpr is not None and rpr.find(f"{W}i") is not None:
            text = f"<em>{text}</em>"
        parts.append(text)
    return "".join(parts)


def docx_to_chapters(data: bytes) -> list[tuple[str, str]]:
    """Split a .docx on Heading 1 into (title, html). Text before the first heading becomes 'Wstęp'."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo("word/document.xml")
        if info.file_size > 60 * 1024 * 1024:  # zip-bomb guard
            raise ValueError("Dokument jest zbyt duży po rozpakowaniu")
        xml = z.read(info)
    if b"<!DOCTYPE" in xml[:4096].upper() or b"<!ENTITY" in xml.upper():  # no DTDs/entities in Word XML
        raise ValueError("Niedozwolona struktura dokumentu")
    root = ET.fromstring(xml)
    chapters: list[tuple[str, list[str]]] = []
    current_title: str = "Wstęp"
    current: list[str] = []
    body = root.find(f"{W}body")
    for p in body.iter(f"{W}p") if body is not None else []:
        style_el = p.find(f"{W}pPr/{W}pStyle")
        style = style_el.get(f"{W}val", "") if style_el is not None else ""
        content = _runs(p).strip()
        if HEADING1.match(style):
            if current or chapters or current_title != "Wstęp":
                chapters.append((current_title, current))
            current_title, current = html.unescape(re.sub(r"<[^>]+>", "", content)) or "Rozdział", []
            continue
        if not content:
            continue
        current.append(f"<h2>{content}</h2>" if HEADING2.match(style) else f"<p>{content}</p>")
    chapters.append((current_title, current))
    return [(t, sanitize_html("".join(ps))) for t, ps in chapters if ps or t != "Wstęp"]


def text_to_chapters(text: str) -> list[tuple[str, str]]:
    """Plain text / Markdown: '# ' starts a chapter, blank lines separate paragraphs."""
    chapters, title, paras, buf = [], "Wstęp", [], []

    def flush_para():
        if buf:
            paras.append("<p>" + html.escape(" ".join(buf), quote=False) + "</p>")
            buf.clear()
    for line in text.splitlines():
        if line.startswith("# "):
            flush_para()
            if paras or chapters or title != "Wstęp":
                chapters.append((title, "".join(paras)))
            title, paras = line[2:].strip() or "Rozdział", []
        elif line.startswith("## "):
            flush_para()
            paras.append("<h2>" + html.escape(line[3:].strip(), quote=False) + "</h2>")
        elif not line.strip():
            flush_para()
        else:
            buf.append(line.strip())
    flush_para()
    chapters.append((title, "".join(paras)))
    return [(t, b) for t, b in chapters if b or t != "Wstęp"]
