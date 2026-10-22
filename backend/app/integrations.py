"""Thin REST clients for Gelato (print on demand) and Stripe (checkout). Kept tiny and mockable in tests."""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from app.config import get_settings

UA = "HRL-Books/0.1 (+https://hrl-books.hardbanrecordslab.online)"

# Catalogs offered in the UI (Gelato has ~60; these are the ones that make sense next to a book).
GELATO_CATALOGS = {
    "t-shirts": "Koszulki", "hoodies": "Bluzy z kapturem", "sweatshirts": "Bluzy", "tote-bags": "Torby",
    "mugs": "Kubki", "posters": "Plakaty", "framed-posters": "Plakaty w ramie", "canvas": "Obrazy na płótnie",
    "notebooks": "Notesy", "calendars": "Kalendarze", "cards": "Kartki", "phone-cases": "Etui na telefon",
    "soft-cover-photobooks": "Fotoksiążki (miękka oprawa)", "hard-cover-photobooks": "Fotoksiążki (twarda oprawa)",
}


GELATO_SINGULAR = {
    "t-shirts": "Koszulka", "hoodies": "Bluza z kapturem", "sweatshirts": "Bluza", "tote-bags": "Torba",
    "mugs": "Kubek", "posters": "Plakat", "framed-posters": "Plakat w ramie", "canvas": "Obraz na płótnie",
    "notebooks": "Notes", "calendars": "Kalendarz", "cards": "Kartka", "phone-cases": "Etui na telefon",
    "soft-cover-photobooks": "Fotoksiążka", "hard-cover-photobooks": "Fotoksiążka",
}


class IntegrationError(Exception):
    pass


def _request(method: str, url: str, headers: dict, body: bytes | None = None, timeout: int = 30):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, **headers}, data=body)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read()[:500].decode(errors="replace")
        raise IntegrationError(f"{url.split('/')[2]} HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise IntegrationError(f"{url.split('/')[2]}: {e.reason}") from e


# ---- Gelato -----------------------------------------------------------------------------------------

def _gelato(method: str, url: str, body: dict | None = None):
    key = get_settings().GELATO_API_KEY
    if not key:
        raise IntegrationError("Brak klucza Gelato (GELATO_API_KEY)")
    return _request(method, url, {"X-API-KEY": key, "Accept": "application/json", "Content-Type": "application/json"},
                    json.dumps(body).encode() if body is not None else None)


def gelato_products(catalog: str, limit: int = 60) -> list[dict]:
    res = _gelato("POST", f"https://product.gelatoapis.com/v3/catalogs/{urllib.parse.quote(catalog)}/products:search",
                  {"limit": limit, "offset": 0})
    out = []
    for p in res.get("products", []):
        attrs = {k: v for k, v in (p.get("attributes") or {}).items() if k not in ("ProductStatus", "State")}
        out.append({"productUid": p["productUid"], "attributes": attrs})
    return out


def gelato_quote(product_uid: str, design_url: str, country: str = "PL", quantity: int = 1) -> dict:
    """Production price + cheapest shipping to the country, in USD."""
    res = _gelato("POST", "https://order.gelatoapis.com/v4/orders:quote", {
        "orderReferenceId": f"quote-{int(time.time())}", "customerReferenceId": "hrl-books", "currency": "USD",
        "recipient": {"country": country, "firstName": "Wycena", "lastName": "HRL", "addressLine1": "Marszałkowska 1",
                      "city": "Warszawa", "postCode": "00-001", "email": "no-reply@hardbanrecordslab.online"},
        "products": [{"itemReferenceId": "q1", "productUid": product_uid, "files": [{"type": "default", "url": design_url}],
                      "quantity": quantity}],
    })
    quote = (res.get("quotes") or [{}])[0]
    product = sum(float(p.get("price") or 0) for p in quote.get("products", []))
    methods = sorted(quote.get("shipmentMethods", []), key=lambda s: float(s.get("price") or 0))
    ship = methods[0] if methods else {}
    return {"product": round(product, 2), "shipping": round(float(ship.get("price") or 0), 2),
            "shipping_method": ship.get("name", ""), "delivery_days": [ship.get("minDeliveryDays"), ship.get("maxDeliveryDays")]}


def gelato_create_order(order_ref: str, product_uid: str, design_url: str, quantity: int, recipient: dict) -> dict:
    return _gelato("POST", "https://order.gelatoapis.com/v4/orders", {
        "orderType": "order", "orderReferenceId": order_ref, "customerReferenceId": "hrl-books", "currency": "USD",
        "items": [{"itemReferenceId": f"{order_ref}-1", "productUid": product_uid,
                   "files": [{"type": "default", "url": design_url}], "quantity": quantity}],
        "shippingAddress": recipient,
    })


def gelato_get_order(gelato_order_id: str) -> dict:
    return _gelato("GET", f"https://order.gelatoapis.com/v4/orders/{urllib.parse.quote(gelato_order_id)}")


# ---- Stripe -----------------------------------------------------------------------------------------

def _stripe(method: str, path: str, form: list[tuple[str, str]] | None = None):
    key = get_settings().STRIPE_SECRET_KEY
    if not key:
        raise IntegrationError("Brak klucza Stripe (STRIPE_SECRET_KEY)")
    return _request(method, f"https://api.stripe.com/v1/{path}",
                    {"Authorization": f"Bearer {key}", "Content-Type": "application/x-www-form-urlencoded"},
                    urllib.parse.urlencode(form).encode() if form is not None else None)


def stripe_checkout_session(order_id: str, name: str, unit_amount: int, quantity: int, image_url: str,
                            success_url: str, cancel_url: str, lang: str = "en") -> dict:
    s = get_settings()
    form = [
        ("mode", "payment"),
        ("client_reference_id", order_id),
        ("metadata[order_id]", order_id),
        ("metadata[app]", "hrl-books"),  # shared Stripe account: lets reports (and other apps' webhooks) tell sales apart
        ("payment_intent_data[metadata][app]", "hrl-books"),
        ("payment_intent_data[metadata][order_id]", order_id),
        ("line_items[0][quantity]", str(quantity)),
        ("line_items[0][price_data][currency]", "usd"),
        ("line_items[0][price_data][unit_amount]", str(unit_amount)),
        ("line_items[0][price_data][product_data][name]", name[:250]),
        ("phone_number_collection[enabled]", "true"),
        ("success_url", success_url),
        ("cancel_url", cancel_url),
        ("locale", "pl" if lang == "pl" else "en"),
    ]
    if image_url:
        form.append(("line_items[0][price_data][product_data][images][0]", image_url))
    for i, c in enumerate(x.strip() for x in s.SHOP_COUNTRIES.split(",") if x.strip()):
        form.append((f"shipping_address_collection[allowed_countries][{i}]", c))
    return _stripe("POST", "checkout/sessions", form)


def stripe_verify_webhook(payload: bytes, sig_header: str, tolerance: int = 300) -> dict:
    """Verify the Stripe-Signature header (HMAC-SHA256 over 't.payload') and return the event."""
    secret = get_settings().STRIPE_WEBHOOK_SECRET
    if not secret:
        raise IntegrationError("Brak STRIPE_WEBHOOK_SECRET")
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    ts = parts.get("t", "")
    signatures = [v for k, v in (p.split("=", 1) for p in sig_header.split(",") if "=" in p) if k == "v1"]
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not ts or not any(hmac.compare_digest(expected, s) for s in signatures):
        raise IntegrationError("Nieprawidłowy podpis webhooka")
    if abs(time.time() - int(ts)) > tolerance:
        raise IntegrationError("Webhook zbyt stary")
    return json.loads(payload)
