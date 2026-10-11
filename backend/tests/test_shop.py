import hashlib
import hmac
import json
import time

import pytest

from app import integrations as gi
from app import mailer
from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def _sign(payload: bytes, secret="whsec_test_secret") -> str:
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


@pytest.fixture
def shop(client, monkeypatch):
    calls = {"gelato": [], "stripe": []}
    monkeypatch.setattr(gi, "stripe_checkout_session",
                        lambda order_id, *a, **k: calls["stripe"].append(order_id) or {"id": f"cs_{order_id}", "url": "https://checkout.stripe.com/pay/x"})
    monkeypatch.setattr(gi, "gelato_create_order",
                        lambda ref, uid, url, qty, rcpt: calls["gelato"].append((ref, uid, url, qty, rcpt)) or {"id": "g-123", "fulfillmentStatus": "created"})
    monkeypatch.setattr(gi, "gelato_get_order", lambda gid: {"id": gid, "fulfillmentStatus": "shipped",
                                                               "shipment": {"trackingCode": "TR1", "trackingUrl": "https://track/TR1"}})
    ws, owner = make_workspace(client, "hrl-books", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    asset = client.post(f"{base}/assets", headers=h, files={"file": ("projekt.png", PNG, "image/png")}).json()
    product = client.post(f"{base}/shop/products", headers=h, json={
        "title": "Kubek Cyfrowy Zen", "gelato_catalog": "mugs", "gelato_product_uid": "mug_product_x",
        "design_asset_id": asset["id"], "price": 89.0}).json()
    return {"ws": ws, "h": h, "base": base, "asset": asset, "product": product, "calls": calls}


def _paid_event(order_id: str) -> bytes:
    return json.dumps({"type": "checkout.session.completed", "data": {"object": {
        "id": f"cs_{order_id}", "metadata": {"order_id": order_id}, "payment_status": "paid", "amount_total": 17800,
        "payment_intent": "pi_1", "customer_details": {"email": "klient@example.com", "name": "Anna Nowak", "phone": "+48500"},
        "shipping_details": {"name": "Anna Nowak", "address": {"line1": "Polna 1", "city": "Kraków", "postal_code": "30-001", "country": "PL"}},
    }}}).encode()


def test_upload_rejects_wrong_type_and_spoofed_content(client, shop):
    base, h = shop["base"], shop["h"]
    assert client.post(f"{base}/assets", headers=h, files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.post(f"{base}/assets", headers=h, files={"file": ("x.png", b"not a png", "image/png")}).status_code == 415
    assert client.get(shop["asset"]["url"].split("hardbanrecordslab.online")[1]).content == PNG


def test_public_product_checkout_webhook_fulfillment(client, shop):
    p = shop["product"]
    pub = client.get(f"/api/v1/public/products/{p['id']}").json()
    assert pub["price"] == 89.0 and pub["title"] == "Kubek Cyfrowy Zen"
    r = client.post(f"/api/v1/public/products/{p['id']}/checkout", json={"quantity": 2})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com")
    order_id = r.json()["order_id"]
    assert client.get(f"/api/v1/public/orders/{order_id}").json()["status"] == "pending_payment"

    payload = _paid_event(order_id)
    assert client.post("/api/v1/stripe/webhook", content=payload, headers={"stripe-signature": "t=1,v1=bad"}).status_code == 400
    mailer.SENT.clear()
    r = client.post("/api/v1/stripe/webhook", content=payload, headers={"stripe-signature": _sign(payload)})
    assert r.status_code == 200, r.text
    ref, uid, url, qty, rcpt = shop["calls"]["gelato"][0]
    assert (ref, uid, qty) == (order_id, "mug_product_x", 2) and url == shop["asset"]["url"]
    assert rcpt["city"] == "Kraków" and rcpt["firstName"] == "Anna" and rcpt["email"] == "klient@example.com"
    assert {m["To"] for m in mailer.SENT} == {"klient@example.com", "owner@example.com"}
    # Stripe retries the same event: no second print order.
    client.post("/api/v1/stripe/webhook", content=payload, headers={"stripe-signature": _sign(payload)})
    assert len(shop["calls"]["gelato"]) == 1

    orders = client.get(f"{shop['base']}/shop/orders", headers=shop["h"]).json()
    assert orders[0]["status"] == "shipped" and orders[0]["tracking"] == [{"code": "TR1", "url": "https://track/TR1"}]
    assert orders[0]["amount"] == 178.0


def test_gelato_failure_marks_failed_and_retry_works(client, shop, monkeypatch):
    def boom(*a, **k):
        raise gi.IntegrationError("Gelato HTTP 400: bad file")
    monkeypatch.setattr(gi, "gelato_create_order", boom)
    order_id = client.post(f"/api/v1/public/products/{shop['product']['id']}/checkout", json={}).json()["order_id"]
    payload = _paid_event(order_id)
    client.post("/api/v1/stripe/webhook", content=payload, headers={"stripe-signature": _sign(payload)})
    orders = client.get(f"{shop['base']}/shop/orders?refresh=false", headers=shop["h"]).json()
    assert orders[0]["status"] == "failed" and "bad file" in orders[0]["error"]
    monkeypatch.setattr(gi, "gelato_create_order", lambda *a, **k: {"id": "g-2", "fulfillmentStatus": "created"})
    r = client.post(f"{shop['base']}/shop/orders/{order_id}/retry", headers=shop["h"])
    assert r.status_code == 200 and r.json()["status"] == "submitted"


def test_shop_permissions_and_isolation(client, shop):
    base, h = shop["base"], shop["h"]
    client.post(f"{base}/invitations", headers=h, json={"email": "red@example.com", "role": "editor"})
    editor = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.get(f"{base}/shop/orders", headers=editor).status_code == 403
    assert client.post(f"{base}/shop/products", headers=editor, json={}).status_code in (403, 422)
    ws_b, owner_b = make_workspace(client, "inne", "b@example.com")
    hb = auth(owner_b["access_token"])
    r = client.post(f"/api/v1/workspaces/{ws_b}/shop/products", headers=hb, json={
        "title": "Kradzież", "gelato_catalog": "mugs", "gelato_product_uid": "mug_product_x", "design_asset_id": shop["asset"]["id"], "price": 10})
    assert r.status_code == 404
    client.put(f"{base}/shop/products/{shop['product']['id']}", headers=h, json={
        "title": "Kubek", "gelato_catalog": "mugs", "gelato_product_uid": "mug_product_x",
        "design_asset_id": shop["asset"]["id"], "price": 89.0, "active": False})
    assert client.get(f"/api/v1/public/products/{shop['product']['id']}").status_code == 404
