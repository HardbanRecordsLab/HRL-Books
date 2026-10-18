"""ISBN helpers: normalisation to ISBN-13, validation and parsing of pasted lists (the publisher's ISBN pool)."""
import re

from app.checks import isbn_valid


def to_isbn13(raw: str) -> str | None:
    """'83-7541-123-X' / '978-83-...' / spaces -> 13 digits, or None when it is not a valid ISBN."""
    s = re.sub(r"[\s-]", "", raw or "").upper()
    if not isbn_valid(s):
        return None
    if len(s) == 13:
        return s
    core = "978" + s[:9]                                   # ISBN-10 -> ISBN-13: prefix 978, new check digit
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


def parse_isbn_list(text: str) -> tuple[list[str], list[str]]:
    """Pull every ISBN out of a pasted block (one per line, commas, tabs, with or without hyphens).
    Returns (valid unique ISBN-13 in order, rejected fragments that looked like an ISBN but failed the checksum)."""
    valid: list[str] = []
    bad: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[\n\r;,\t]+", text or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        digits = re.sub(r"[\s-]", "", chunk)
        if not re.fullmatch(r"(?:\d{13}|\d{9}[\dXx])", digits):
            # a line like "ISBN 978-83-..." or "e-book: 978..." — try to find the number inside it
            m = re.search(r"(?:97[89][\s-]?)?(?:\d[\s-]?){9,12}[\dXx]", chunk)
            if not m:
                bad.append(chunk[:40])
                continue
            digits = re.sub(r"[\s-]", "", m.group(0))
        n = to_isbn13(digits)
        if n is None:
            bad.append(chunk[:40])
        elif n not in seen:
            seen.add(n)
            valid.append(n)
    return valid, bad


def hyphenate_pl(isbn13: str) -> str:
    """Display form for Polish ISBNs (978-83-...); others are shown as 978-x-... without guessing registrant lengths."""
    if len(isbn13) == 13 and isbn13.startswith("97883"):
        return f"{isbn13[:3]}-{isbn13[3:5]}-{isbn13[5:-1]}-{isbn13[-1]}"
    return isbn13
