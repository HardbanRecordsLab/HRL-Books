"""Shop + print on demand: products (Gelato), public product page + Stripe checkout, webhook -> Gelato order."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import integrations as gi
from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.deps import require
from app.mailer import send_mail
from app.models import Asset, Book, Membership, Order, Product, User, utcnow
from app.routers.assets import asset_public_url

log = logging.getLogger(__name__)
router = APIRouter(tags=["shop"])

FINAL = {"delivered", "canceled", "failed"}
GELATO_TO_STATUS = {"created": "submitted", "uploading": "submitted", "passed": "submitted", "pending_approval": "submitted",
                    "in_production": "in_production", "printed": "in_production", "shipped": "shipped",
                    "in_transit": "shipped", "delivered": "delivered", "canceled": "canceled", "cancelled": "canceled",
                    "failed": "failed", "returned": "failed"}
STATUS_PL = {"pending_payment": "czeka na płatność", "paid": "opłacone", "submitted": "przekazane do druku",
             "in_production": "w produkcji", "shipped": "wysłane", "delivered": "dostarczone",
             "canceled": "anulowane", "failed": "błąd realizacji"}


class ProductIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str = Field(default="", max_length=5000)
    gelato_catalog: str
    gelato_product_uid: str = Field(min_length=3, max_length=300)
    design_asset_id: str
    price: float = Field(gt=0, le=100000)  # PLN, shipping included
    book_id: str | None = None
    active: bool = True


class CheckoutIn(BaseModel):
    quantity: int = Field(default=1, ge=1, le=20)


def _money(cents: int) -> float:
    return round(cents / 100, 2)


def product_out(db: Session, p: Product) -> dict:
    asset = db.get(Asset, p.design_asset_id)
    return {"id": p.id, "book_id": p.book_id, "title": p.title, "description": p.description,
            "gelato_catalog": p.gelato_catalog, "catalog_label": gi.GELATO_CATALOGS.get(p.gelato_catalog, p.gelato_catalog),
            "gelato_product_uid": p.gelato_product_uid, "design_asset_id": p.design_asset_id,
            "design_url": asset_public_url(asset) if asset else "", "price": _money(p.price_amount),
            "currency": p.currency, "active": p.active,
            "public_url": f"{get_settings().APP_URL}/sklep/{p.id}"}


def order_out(o: Order, product: Product | None) -> dict:
    return {"id": o.id, "product_id": o.product_id, "product_title": product.title if product else "",
            "quantity": o.quantity, "status": o.status, "status_label": STATUS_PL.get(o.status, o.status),
            "amount": _money(o.amount_total), "currency": o.currency, "customer_email": o.customer_email,
            "customer_name": o.customer_name, "shipping": o.shipping, "gelato_order_id": o.gelato_order_id,
            "tracking": o.tracking, "error": o.error, "created_at": o.created_at, "updated_at": o.updated_at}


def _owner_emails(db: Session, ws_id: str) -> list[str]:
    from app.models import Membership as M
    return [u.email for u in db.scalars(select(User).join(M, M.user_id == User.id)
                                        .where(M.workspace_id == ws_id, M.role == "owner"))]


# ---- catalog helpers (owner) ------------------------------------------------------------------------

@router.get("/api/v1/workspaces/{ws}/shop/catalogs")
def catalogs(m: Membership = Depends(require("manage_shop"))):
    return [{"uid": k, "label": v, "singular": gi.GELATO_SINGULAR.get(k, v)} for k, v in gi.GELATO_CATALOGS.items()]


@router.get("/api/v1/workspaces/{ws}/shop/catalogs/{catalog}/products")
def catalog_products(catalog: str, m: Membership = Depends(require("manage_shop"))):
    if catalog not in gi.GELATO_CATALOGS:
        raise HTTPException(404, "Nieznany katalog")
    try:
        return gi.gelato_products(catalog)
    except gi.IntegrationError as e:
        raise HTTPException(502, f"Gelato: {e}") from e


@router.get("/api/v1/workspaces/{ws}/shop/quote")
def quote(product_uid: str, asset_id: str, country: str = "PL", m: Membership = Depends(require("manage_shop")),
          db: Session = Depends(get_db)):
    asset = db.scalar(select(Asset).where(Asset.id == asset_id, Asset.workspace_id == m.workspace_id))
    if asset is None:
        raise HTTPException(404, "Nie znaleziono pliku")
    try:
        return gi.gelato_quote(product_uid, asset_public_url(asset), country)
    except gi.IntegrationError as e:
        raise HTTPException(502, f"Gelato: {e}") from e


# ---- products (owner) --------------------------------------------------------------------------------

def _product(db: Session, ws_id: str, product_id: str) -> Product:
    p = db.scalar(select(Product).where(Product.id == product_id, Product.workspace_id == ws_id))
    if p is None:
        raise HTTPException(404, "Nie znaleziono produktu")
    return p


def _validate(db: Session, ws_id: str, body: ProductIn) -> None:
    if body.gelato_catalog not in gi.GELATO_CATALOGS:
        raise HTTPException(422, "Nieznany katalog Gelato")
    if db.scalar(select(Asset).where(Asset.id == body.design_asset_id, Asset.workspace_id == ws_id)) is None:
        raise HTTPException(404, "Nie znaleziono pliku projektu")
    if body.book_id and db.scalar(select(Book).where(Book.id == body.book_id, Book.workspace_id == ws_id)) is None:
        raise HTTPException(404, "Nie znaleziono tytułu")


@router.get("/api/v1/workspaces/{ws}/shop/products")
def list_products(book_id: str = "", m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    q = select(Product).where(Product.workspace_id == m.workspace_id)
    if book_id:
        q = q.where(Product.book_id == book_id)
    return [product_out(db, p) for p in db.scalars(q.order_by(Product.created_at.desc()))]


@router.post("/api/v1/workspaces/{ws}/shop/products", status_code=201)
def create_product(body: ProductIn, m: Membership = Depends(require("manage_shop")), db: Session = Depends(get_db)):
    _validate(db, m.workspace_id, body)
    p = Product(workspace_id=m.workspace_id, book_id=body.book_id or None, title=body.title, description=body.description,
                gelato_catalog=body.gelato_catalog, gelato_product_uid=body.gelato_product_uid,
                design_asset_id=body.design_asset_id, price_amount=round(body.price * 100), active=body.active)
    db.add(p)
    db.flush()
    audit(db, "product.created", m.user_id, m.workspace_id, target=p.id)
    db.commit()
    return product_out(db, p)


@router.put("/api/v1/workspaces/{ws}/shop/products/{product_id}")
def update_product(product_id: str, body: ProductIn, m: Membership = Depends(require("manage_shop")),
                   db: Session = Depends(get_db)):
    p = _product(db, m.workspace_id, product_id)
    _validate(db, m.workspace_id, body)
    p.title, p.description, p.active = body.title, body.description, body.active
    p.gelato_catalog, p.gelato_product_uid, p.design_asset_id = body.gelato_catalog, body.gelato_product_uid, body.design_asset_id
    p.price_amount, p.book_id = round(body.price * 100), body.book_id or None
    db.commit()
    return product_out(db, p)


# ---- orders (owner) ----------------------------------------------------------------------------------

def refresh_from_gelato(db: Session, o: Order) -> None:
    if not o.gelato_order_id or o.status in FINAL:
        return
    try:
        g = gi.gelato_get_order(o.gelato_order_id)
    except gi.IntegrationError as e:
        log.warning("gelato refresh %s: %s", o.id, e)
        return
    o.gelato_status = str(g.get("fulfillmentStatus") or g.get("status") or "")
    o.status = GELATO_TO_STATUS.get(o.gelato_status.lower(), o.status)
    tracking = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("trackingUrl") or x.get("trackingCode"):
                tracking.append({"code": x.get("trackingCode", ""), "url": x.get("trackingUrl", "")})
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(g)
    if tracking:
        o.tracking = [dict(t) for t in {tuple(sorted(t.items())) for t in tracking}]
    o.updated_at = utcnow()


@router.get("/api/v1/workspaces/{ws}/shop/orders")
def list_orders(refresh: bool = True, m: Membership = Depends(require("manage_shop")), db: Session = Depends(get_db)):
    orders = list(db.scalars(select(Order).where(Order.workspace_id == m.workspace_id).order_by(Order.created_at.desc()).limit(200)))
    if refresh:
        for o in [o for o in orders if o.gelato_order_id and o.status not in FINAL][:20]:
            refresh_from_gelato(db, o)
        db.commit()
    products = {p.id: p for p in db.scalars(select(Product).where(Product.workspace_id == m.workspace_id))}
    return [order_out(o, products.get(o.product_id)) for o in orders]


@router.post("/api/v1/workspaces/{ws}/shop/orders/{order_id}/retry")
def retry_order(order_id: str, m: Membership = Depends(require("manage_shop")), db: Session = Depends(get_db)):
    o = db.scalar(select(Order).where(Order.id == order_id, Order.workspace_id == m.workspace_id))
    if o is None:
        raise HTTPException(404, "Nie znaleziono zamówienia")
    if o.status != "failed" or o.gelato_order_id or not o.shipping:
        raise HTTPException(409, "Ponowić można tylko opłacone zamówienie, którego nie przyjęła drukarnia")
    fulfill(db, o)
    db.commit()
    return order_out(o, db.get(Product, o.product_id))


# ---- public shop -------------------------------------------------------------------------------------

@router.get("/api/v1/public/products/{product_id}")
def public_product(product_id: str, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if p is None or not p.active:
        raise HTTPException(404, "Produkt niedostępny")
    out = product_out(db, p)
    book = db.get(Book, p.book_id) if p.book_id else None
    return {k: out[k] for k in ("id", "title", "description", "catalog_label", "design_url", "price", "currency")} | {
        "book_title": book.title if book else ""}


@router.post("/api/v1/public/products/{product_id}/checkout")
def checkout(product_id: str, body: CheckoutIn, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if p is None or not p.active:
        raise HTTPException(404, "Produkt niedostępny")
    o = Order(workspace_id=p.workspace_id, product_id=p.id, quantity=body.quantity, amount_total=p.price_amount * body.quantity)
    db.add(o)
    db.flush()
    base = get_settings().APP_URL
    asset = db.get(Asset, p.design_asset_id)
    image = asset_public_url(asset) if asset and asset.content_type.startswith("image/") else ""
    try:
        session = gi.stripe_checkout_session(o.id, p.title, p.price_amount, body.quantity, image,
                                             f"{base}/sklep/dziekujemy?zamowienie={o.id}", f"{base}/sklep/{p.id}")
    except gi.IntegrationError as e:
        db.rollback()
        raise HTTPException(502, "Płatności są chwilowo niedostępne") from e
    o.stripe_session_id = session.get("id", "")
    db.commit()
    return {"url": session.get("url"), "order_id": o.id}


@router.get("/api/v1/public/orders/{order_id}")
def public_order(order_id: str, db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if o is None:
        raise HTTPException(404, "Nie znaleziono")
    p = db.get(Product, o.product_id)
    return {"status": o.status, "status_label": STATUS_PL.get(o.status, o.status), "product_title": p.title if p else "",
            "quantity": o.quantity, "amount": _money(o.amount_total), "currency": o.currency, "tracking": o.tracking}


def _recipient(session: dict) -> tuple[dict, str, str]:
    details = session.get("customer_details") or {}
    ship = session.get("shipping_details") or (session.get("collected_information") or {}).get("shipping_details") or {}
    addr = ship.get("address") or details.get("address") or {}
    full = (ship.get("name") or details.get("name") or "").strip()
    first, _, last = full.partition(" ")
    recipient = {"firstName": first or full or "Klient", "lastName": last or "-", "addressLine1": addr.get("line1") or "",
                 "addressLine2": addr.get("line2") or "", "city": addr.get("city") or "", "postCode": addr.get("postal_code") or "",
                 "state": addr.get("state") or "", "country": addr.get("country") or "PL",
                 "email": details.get("email") or "", "phone": details.get("phone") or ""}
    return recipient, details.get("email") or "", full


def fulfill(db: Session, o: Order) -> None:
    """Send a paid order to Gelato. On failure keep it 'failed' with the reason and tell the owners."""
    p = db.get(Product, o.product_id)
    asset = db.get(Asset, p.design_asset_id) if p else None
    try:
        g = gi.gelato_create_order(o.id, p.gelato_product_uid, asset_public_url(asset), o.quantity, o.shipping)
        o.gelato_order_id = str(g.get("id", ""))
        o.gelato_status = str(g.get("fulfillmentStatus") or "created")
        o.status = "submitted"
        o.error = ""
    except (gi.IntegrationError, AttributeError) as e:
        o.status = "failed"
        o.error = str(e)[:2000]
        for email in _owner_emails(db, o.workspace_id):
            send_mail(email, "[HRL Books] Zamówienie nie trafiło do druku",
                      f"Zamówienie {o.id} ({p.title if p else ''}) jest opłacone, ale Gelato go nie przyjęło:\n{o.error}\n\n"
                      f"Ponów je w panelu: {get_settings().APP_URL}")
    o.updated_at = utcnow()


@router.post("/api/v1/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    try:
        event = gi.stripe_verify_webhook(payload, request.headers.get("stripe-signature", ""))
    except gi.IntegrationError as e:
        raise HTTPException(400, str(e)) from e
    if event.get("type") != "checkout.session.completed":
        return {"ignored": event.get("type")}
    session = event["data"]["object"]
    order_id = (session.get("metadata") or {}).get("order_id") or session.get("client_reference_id")
    o = db.get(Order, order_id) if order_id else None
    if o is None or o.status != "pending_payment":
        return {"ok": True, "duplicate_or_unknown": True}  # idempotent: Stripe retries deliveries
    if session.get("payment_status") != "paid":
        return {"ok": True, "unpaid": True}
    recipient, email, name = _recipient(session)
    o.status, o.shipping, o.customer_email, o.customer_name = "paid", recipient, email, name
    o.stripe_payment_intent = str(session.get("payment_intent") or "")
    o.amount_total = int(session.get("amount_total") or o.amount_total)
    audit(db, "order.paid", None, o.workspace_id, target=o.id, amount=o.amount_total)
    fulfill(db, o)
    db.commit()
    p = db.get(Product, o.product_id)
    if email:
        send_mail(email, f"Dziękujemy za zamówienie — {p.title}",
                  f"Dzień dobry,\n\ndziękujemy za zakup: {p.title} × {o.quantity}.\nProdukt jest drukowany na zamówienie "
                  f"i wyślemy go na podany adres. Status sprawdzisz tutaj: {get_settings().APP_URL}/sklep/dziekujemy?zamowienie={o.id}\n\n"
                  "— HRL Books · HardbanRecords Lab")
    for owner in _owner_emails(db, o.workspace_id):
        send_mail(owner, f"[HRL Books] Nowe zamówienie: {p.title} × {o.quantity}",
                  f"Kwota: {_money(o.amount_total)} {o.currency}\nKlient: {name} <{email}>\nStatus: {STATUS_PL.get(o.status)}\n"
                  f"{('Błąd: ' + o.error) if o.error else ''}")
    return {"ok": True}
