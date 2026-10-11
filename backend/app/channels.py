"""Distribution channel profiles (spec 6.7, 17.1). Profiles are data: rules change, so values that were not
verified at the source are marked as such and shown to the user, never presented as fact."""

STATUSES = ["not_ready", "ready", "sent", "in_review", "published", "rejected", "withdrawn"]
STATUS_LABELS = {
    "not_ready": "Nieprzygotowane", "ready": "Gotowe do wysyłki", "sent": "Wysłane", "in_review": "W weryfikacji",
    "published": "Opublikowane", "rejected": "Odrzucone", "withdrawn": "Wycofane",
}

CHANNELS: dict[str, dict] = {
    "kdp": {
        "name": "Amazon KDP",
        "panel_url": "https://kdp.amazon.com",
        "formats": ["ebook_epub", "paperback", "hardcover"],
        "limits": {"keywords_max": 7, "desc_long_max": 4000},
        "ai_disclosure_required": True,
        "url_hosts": ["amazon."],
        "steps": [
            "Zaloguj się do KDP i utwórz nowy tytuł (Kindle eBook albo Paperback).",
            "Wklej tytuł, podtytuł, serię, autora i twórców z pakietu.",
            "Wklej opis (do 4000 znaków) i maksymalnie 7 słów kluczowych.",
            "Wybierz kategorie i odbiorców.",
            "Odpowiedz na pytanie o treści wygenerowane przez AI zgodnie z deklaracją w karcie.",
            "Wgraj plik wydania i okładkę, sprawdź podgląd.",
            "Ustaw terytoria, tantiemy i ceny.",
            "Opublikuj i zmień status wpisu na „Wysłane”.",
        ],
    },
    "google_play": {
        "name": "Google Play Książki",
        "panel_url": "https://play.google.com/books/publish",
        "formats": ["ebook_epub", "ebook_pdf"],
        "limits": {},
        "url_hosts": ["play.google."],
        "steps": [
            "Zaloguj się do Google Play Books Partner Center i dodaj książkę.",
            "Uzupełnij metadane z pakietu (tytuł, autorzy, opis, język, kategorie).",
            "Wgraj EPUB (lub PDF) i okładkę.",
            "Ustaw ceny na rynkach i terytoria.",
            "Wyślij do publikacji i zmień status wpisu na „Wysłane”.",
        ],
    },
    "kobo": {
        "name": "Kobo Writing Life",
        "panel_url": "https://www.kobo.com/writinglife",
        "formats": ["ebook_epub"],
        "limits": {},
        "url_hosts": ["kobo."],
        "steps": [
            "Zaloguj się do Kobo Writing Life i utwórz nowy e-book.",
            "Wklej metadane z pakietu.",
            "Wgraj EPUB i okładkę.",
            "Ustaw ceny i rynki; zdecyduj o udziale w Kobo Plus.",
            "Opublikuj i zmień status wpisu na „Wysłane”.",
        ],
    },
    "d2d": {
        "name": "Draft2Digital",
        "panel_url": "https://www.draft2digital.com",
        "formats": ["ebook_epub", "paperback"],
        "limits": {},
        "url_hosts": ["draft2digital.", "books2read."],
        "note": "Agregator: Apple Books, Barnes & Noble, Scribd, biblioteki i inne.",
        "steps": [
            "Zaloguj się do Draft2Digital i dodaj nową książkę.",
            "Wklej metadane z pakietu i wgraj plik (EPUB lub DOCX) oraz okładkę.",
            "Wybierz sklepy docelowe (Apple Books, B&N, Scribd, biblioteki…).",
            "Ustaw ceny.",
            "Opublikuj i zmień status wpisu na „Wysłane”.",
        ],
    },
    "virtualo": {
        "name": "Virtualo",
        "panel_url": "https://virtualo.pl",
        "formats": ["ebook_epub", "ebook_pdf"],
        "limits": {},
        "url_hosts": ["virtualo.", "empik.", "legimi.", "woblink.", "allegro."],
        "note": "Polski dystrybutor: Empik, Empik Go, Legimi, Woblink, Allegro i inne.",
        "steps": [
            "Prześlij Virtualo plik wydania, okładkę i metadane z pakietu (zgodnie z umową z dystrybutorem).",
            "Potwierdź ceny i sklepy docelowe.",
            "Po przyjęciu zmień status wpisu na „Wysłane”.",
        ],
    },
}


def channel_from_url(url: str) -> str | None:
    low = url.lower()
    for key, ch in CHANNELS.items():
        if any(h in low for h in ch.get("url_hosts", [])):
            return key
    return None


def public_profile(key: str) -> dict:
    ch = CHANNELS[key]
    return {"key": key, "name": ch["name"], "panel_url": ch["panel_url"], "formats": ch["formats"],
            "limits": ch["limits"], "note": ch.get("note", ""), "steps": ch["steps"],
            "ai_disclosure_required": ch.get("ai_disclosure_required", False)}
