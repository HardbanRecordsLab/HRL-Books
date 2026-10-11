"""LLM access (OpenRouter, OpenAI-compatible) + the prompts behind the AI assistant.

Privacy: every request asks OpenRouter to route only to providers that do not store or train on the
data (provider.data_collection = "deny"), the same rule as Dropify and MasteringPro.
"""
import json
import re
import urllib.error
import urllib.request

from app.config import get_settings
from app.integrations import UA
from app.text import html_to_text

CHUNK_CHARS = 6000
LANGS = {"pl": "polski", "en": "angielski"}
FROM = {"pl": "polskiego", "en": "angielskiego"}


class AIError(Exception):
    pass


def configured() -> bool:
    return bool(get_settings().OPENROUTER_API_KEY)


def complete(system: str, user: str, max_tokens: int = 4000, temperature: float = 0.3) -> tuple[str, str, int, int]:
    """Return (text, model, tokens_in, tokens_out). Tries LLM_MODEL, then LLM_MODEL_FALLBACK."""
    s = get_settings()
    if not s.OPENROUTER_API_KEY:
        raise AIError("AI nie jest skonfigurowane na serwerze")
    models = [s.LLM_MODEL] + ([s.LLM_MODEL_FALLBACK] if s.LLM_MODEL_FALLBACK and s.LLM_MODEL_FALLBACK != s.LLM_MODEL else [])
    last = ""
    for model in models:
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if "openrouter.ai" in s.LLM_BASE_URL:
            body["provider"] = {"data_collection": "deny"}
        req = urllib.request.Request(
            f"{s.LLM_BASE_URL.rstrip('/')}/chat/completions", method="POST", data=json.dumps(body).encode(),
            headers={"User-Agent": UA, "Content-Type": "application/json", "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                     "HTTP-Referer": s.APP_URL, "X-Title": "HRL Books"})
        try:
            with urllib.request.urlopen(req, timeout=s.LLM_TIMEOUT) as r:
                data = json.loads(r.read())
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            if not text.strip():
                last = "pusta odpowiedź modelu"
                continue
            usage = data.get("usage") or {}
            return text, data.get("model", model), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = str(e)[:200]
    raise AIError(f"Model AI nie odpowiedział ({last})")


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise AIError("Model zwrócił odpowiedź w złym formacie")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise AIError("Model zwrócił odpowiedź w złym formacie") from e


BLOCK = {"p", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "pre"}
TAG = re.compile(r"<(/?)([a-z0-9]+)[^>]*>")


def html_blocks(body: str) -> list[str]:
    """Split sanitized HTML into top-level blocks (a whole list stays one block)."""
    blocks, depth, start = [], 0, 0
    for m in TAG.finditer(body):
        closing, tag = m.group(1) == "/", m.group(2)
        if tag == "hr" and depth == 0:
            blocks.append(body[start:m.end()])
            start = m.end()
        if tag not in BLOCK:
            continue
        depth += -1 if closing else 1
        if closing and depth == 0:
            blocks.append(body[start:m.end()])
            start = m.end()
    if body[start:].strip():
        blocks.append(body[start:])
    return [b for b in blocks if b.strip()]


def chunks(body: str, size: int = CHUNK_CHARS) -> list[str]:
    out, cur = [], ""
    for b in html_blocks(body):
        if cur and len(cur) + len(b) > size:
            out.append(cur)
            cur = ""
        cur += b
    if cur:
        out.append(cur)
    return out


# ---- prompts ----------------------------------------------------------------------------------------

PROOFREAD_SYSTEM = (
    "Jesteś doświadczonym korektorem i redaktorem językowym. Poprawiasz wyłącznie błędy: ortografię, interpunkcję, "
    "gramatykę, literówki, powtórzenia i ewidentnie niezręczne sformułowania. Nie zmieniasz stylu autora, treści ani sensu. "
    "Odpowiadasz WYŁĄCZNIE obiektem JSON: {\"suggestions\": [{\"original\": \"...\", \"suggestion\": \"...\", \"reason\": \"...\"}]}. "
    "\"original\" to DOKŁADNY, dosłowny fragment tekstu (kilka słów wokół błędu, bez skracania), \"suggestion\" to ten sam fragment "
    "po poprawce, \"reason\" to krótkie wyjaśnienie po polsku. Gdy nie ma błędów, zwróć pustą listę."
)


def proofread_prompt(text: str, lang: str) -> str:
    return f"Język tekstu: {LANGS.get(lang, lang)}.\n\nTekst do korekty:\n\n{text}"


def translate_system(source: str, target: str) -> str:
    return (
        f"Jesteś literackim tłumaczem książek z języka {FROM.get(source, source)} na język {LANGS.get(target, target)}. "
        "Tłumaczysz wiernie i naturalnie, zachowując styl, ton i rejestr autora. Wejście to fragment HTML: zachowaj "
        "dokładnie te same znaczniki i ich kolejność, tłumacz tylko tekst. Nie dodawaj komentarzy ani wyjaśnień. "
        "Odpowiedz wyłącznie przetłumaczonym HTML."
    )


BETA_SYSTEM = (
    "Jesteś wnikliwym, życzliwym, ale szczerym beta-czytelnikiem i redaktorem prowadzącym. Piszesz po polsku raport "
    "dla autora. Struktura (nagłówki zaczynaj od '## '):\n"
    "## Pierwsze wrażenie\n## Mocne strony\n## Co osłabia tekst\n## Tempo i konstrukcja\n## Jasność i język\n"
    "## Dla kogo jest ten tekst\n## 5 najważniejszych poprawek (lista numerowana, konkretnie, z odwołaniem do fragmentów)\n"
    "Nie przepisuj tekstu za autora. Bądź konkretny."
)

MARKETING = {
    "blurb": ("Opis książki", "Napisz 3 warianty opisu książki do sklepu (ok. 150–200 słów każdy) i jeden krótki opis (2 zdania) "
              "na okładkę. Oddziel warianty nagłówkami '## Wariant 1' itd."),
    "social": ("Posty do social media", "Napisz 6 postów: 2 na Facebooka, 2 na Instagram (z propozycją grafiki i hashtagami), "
               "2 na LinkedIn. Oddziel je nagłówkami '## '."),
    "newsletter": ("Newsletter", "Napisz e-mail zapowiadający premierę książki do listy subskrybentów: 3 propozycje tematu, "
                   "preheader, treść (ok. 250 słów) z jednym wezwaniem do działania."),
    "keywords": ("Słowa kluczowe i kategorie", "Zaproponuj: 7 fraz kluczowych do Amazon KDP (każda do 50 znaków, tak jak szukają "
                 "czytelnicy, bez powtarzania słów z tytułu), 3 kategorie BISAC z kodami, 3 kategorie Thema z kodami oraz "
                 "15 słów kluczowych dla innych sklepów. Użyj nagłówków '## '."),
}


def marketing_system(lang: str) -> str:
    return (f"Jesteś copywriterem wydawniczym. Piszesz w języku: {LANGS.get(lang, lang)}. Bez przesadnych superlatyw i "
            "obietnic, których książka nie spełnia. Nie wymyślaj faktów (nagród, recenzji, liczb sprzedaży). "
            "Formatuj prostym tekstem z nagłówkami '## '.")


def book_brief(book, manuscript_html: str, limit: int = 8000) -> str:
    parts = [f"Tytuł: {book.title}"]
    for label, val in (("Podtytuł", book.subtitle), ("Seria", getattr(book, "series_name", "")),
                       ("Krótki opis", book.desc_short), ("Opis", getattr(book, "desc_long", "")),
                       ("Odbiorcy", getattr(book, "audience", "")), ("Język", book.language)):
        if val:
            parts.append(f"{label}: {val}")
    excerpt = html_to_text(manuscript_html)[:limit]
    if excerpt:
        parts.append(f"\nFragment tekstu:\n{excerpt}")
    return "\n".join(parts)
