"""Small HTTP helpers."""
import re
import unicodedata
from urllib.parse import quote


def attachment(title: str, suffix: str, ascii_suffix: str | None = None) -> str:
    """Content-Disposition for a download named after a (Polish) title.

    HTTP headers are latin-1: ASCII fallback name + RFC 5987 UTF-8 name.
    """
    folded = unicodedata.normalize("NFKD", title.lower().replace("ł", "l")).encode("ascii", "ignore").decode()
    ascii_name = (re.sub(r"-+", "-", "".join(c if c.isalnum() else "-" for c in folded))[:50].strip("-") or "ksiazka")
    return (f"attachment; filename=\"{ascii_name}{ascii_suffix or suffix}\"; "
            f"filename*=UTF-8''{quote(title[:80] + suffix)}")
