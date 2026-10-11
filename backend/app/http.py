"""Small HTTP helpers."""
import re
import unicodedata
from urllib.parse import quote


def slugify(text: str, limit: int = 50, fallback: str = "ksiazka") -> str:
    folded = unicodedata.normalize("NFKD", text.lower().replace("ł", "l")).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", "".join(c if c.isalnum() else "-" for c in folded))[:limit].strip("-") or fallback


def attachment(title: str, suffix: str, ascii_suffix: str | None = None) -> str:
    """Content-Disposition for a download named after a (Polish) title.

    HTTP headers are latin-1: ASCII fallback name + RFC 5987 UTF-8 name.
    """
    ascii_name = slugify(title)
    return (f"attachment; filename=\"{ascii_name}{ascii_suffix or suffix}\"; "
            f"filename*=UTF-8''{quote(title[:80] + suffix)}")
